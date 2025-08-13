#!/usr/bin/env python3

"""
Result management system with real-time persistence.
Supports batch saving for keys, links, and other results with atomic file operations.
"""

import datetime
import json
import os
import shutil
import tempfile
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

from constant.runtime import RESULT_TYPE_MAPPINGS
from core.enums import ResultType
from core.models import AllRecoveredTasks, RecoveredTasks, Service
from core.types import Provider
from state.models import PersistenceMetrics
from tools.logger import get_context_logger, get_logger

from .atomic import AtomicFileWriter
from .shard import NDJSONShardWriter
from .snapshot import SnapshotManager

logger = get_logger("storage")


class ResultBuffer:
    """Optimized buffer for batching results before writing to files"""

    def __init__(self, result_type: str, batch_size: int = 100, flush_interval: float = 30.0):
        self.result_type = result_type
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self.buffer: deque = deque()
        self.last_flush = time.time()
        self.lock = threading.Lock()
        self._total_items = 0
        self._total_flushes = 0

    def add(self, item: Any) -> bool:
        """Add item to buffer. Returns True if buffer is full after adding."""
        with self.lock:
            self.buffer.append(item)
            self._total_items += 1
            return len(self.buffer) >= self.batch_size

    def flush(self) -> List[Any]:
        """Flush buffer and return items"""
        with self.lock:
            if not self.buffer:
                return []

            # Convert deque to list efficiently
            items = list(self.buffer)
            self.buffer.clear()
            self.last_flush = time.time()
            self._total_flushes += 1
            return items

    def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics"""
        with self.lock:
            return {
                "result_type": self.result_type,
                "current_size": len(self.buffer),
                "batch_size": self.batch_size,
                "total_items": self._total_items,
                "total_flushes": self._total_flushes,
                "last_flush": self.last_flush,
            }

    def size(self) -> int:
        """Get current buffer size"""
        with self.lock:
            return len(self.buffer)

    def should_flush(self) -> bool:
        """Check if buffer should be flushed based on time interval"""
        with self.lock:
            return (time.time() - self.last_flush) >= self.flush_interval


class ResultManager:
    """Manages results for a single provider with real-time persistence"""

    def __init__(
        self,
        provider: Provider,
        workspace: str,
        batch_size: int = 50,
        save_interval: float = 30.0,
        simple: bool = False,
        shutdown_timeout: float = 5.0,
    ):
        self.name = provider.name
        self.provider = provider
        self.workspace = workspace
        self.batch_size = batch_size
        self.save_interval = save_interval
        self.simple = simple
        self.shutdown_timeout = float(max(1.0, shutdown_timeout))

        # Create structured logger with provider context
        self.logger = get_context_logger("persist", provider=self.name)

        # Create provider directory
        self.directory = os.path.join(workspace, "providers", self.provider.directory)
        os.makedirs(self.directory, exist_ok=True)

        # Build file paths from provider instance using configuration mapping
        self.files = {}
        for result_type, config in RESULT_TYPE_MAPPINGS.items():
            filename = getattr(provider, config.filename_attr)
            self.files[result_type.value] = os.path.join(self.directory, filename)

        # Result buffers
        self.buffers = {
            result_type: ResultBuffer(result_type, batch_size, save_interval)
            for result_type in self.files.keys()
            if result_type != "summary"
        }

        # Models data (not buffered, updated directly)
        self.models_data: Dict[str, Any] = {}

        # Statistics
        self.stats = PersistenceMetrics()

        # Thread safety
        self.lock = threading.Lock()

        # Start periodic flush thread
        self.running = True
        self.flush_thread = threading.Thread(target=self._periodic_flush, daemon=True)
        self.flush_thread.start()

        logger.info(f"Initialized result manager for provider: {self.name}")

    def add_result(self, result_type: str, data: Any):
        """Add result to appropriate buffer

        Args:
            result_type: Result type string (enum value)
            data: Data to add (single item or list)
        """
        if result_type not in self.buffers:
            logger.warning(f"[persist] unknown result type: {result_type}")
            return

        # Handle different data types
        items = []
        if isinstance(data, list):
            items = data
        else:
            items = [data]

        # Add to buffer and check if flush is needed
        buffer = self.buffers[result_type]
        needs_flush = False

        for item in items:
            if buffer.add(item):
                needs_flush = True

        # Update statistics using configuration mapping
        self._update_statistics(result_type, len(items))

        # Immediate flush if needed
        if needs_flush:
            self._flush_buffer(result_type)

        logger.debug(f"[persist] added {len(items)} {result_type} for {self.name}")

    def _update_statistics(self, result_type: str, count: int):
        """Update statistics for given result type using configuration mapping"""
        with self.lock:
            # Find matching result type configuration
            for rt_enum, config in RESULT_TYPE_MAPPINGS.items():
                if rt_enum.value == result_type and config.stats_attr:
                    # Update the corresponding statistics attribute
                    current_value = getattr(self.stats, config.stats_attr, 0)
                    setattr(self.stats, config.stats_attr, current_value + count)
                    break

    def add_links(self, links: List[str]):
        """Convenience method for adding links with validation"""
        if not links:
            return

        # Filter valid links
        valid_links = [link for link in links if link and isinstance(link, str) and link.startswith("http")]

        if valid_links:
            self.add_result(ResultType.LINKS.value, valid_links)
            logger.debug(f"[persist] added {len(valid_links)} links for {self.name}")

    def add_models(self, key: str, models: List[str]):
        """Add model list for a key (not buffered, saved immediately)"""
        with self.lock:
            self.models_data[key] = {"models": models, "timestamp": time.time()}
            self.stats.resources.models += 1

        # Save models data immediately
        self._save_models()
        logger.debug(f"[persist] added {len(models)} models for key in {self.name}")

    def flush_all(self):
        """Flush all buffers immediately"""
        for result_type in self.buffers.keys():
            self._flush_buffer(result_type)

        # Save models data
        self._save_models()

        logger.info(f"Flushed all buffers for {self.name}")

    def get_stats(self) -> PersistenceMetrics:
        """Get current statistics"""
        with self.lock:
            return self.stats

    def backup_existing_files(self) -> None:
        """Backup existing result files to timestamped folder"""

        # Check if any files exist
        existing_files = []
        for file_type, filepath in self.files.items():
            if os.path.exists(filepath):
                existing_files.append((file_type, filepath))

        if not existing_files:
            logger.debug(f"No existing files to backup for {self.name}")
            return

        # Create backup folder with timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = os.path.join(self.directory, f"backup-{timestamp}")
        os.makedirs(backup_dir, exist_ok=True)

        # Move existing files to backup folder
        for file_type, filepath in existing_files:
            try:
                backup_path = os.path.join(backup_dir, os.path.basename(filepath))
                os.rename(filepath, backup_path)
                logger.debug(f"Backed up {file_type} file for {self.name}")
            except Exception as e:
                logger.error(f"Failed to backup {file_type} for {self.name}: {e}")

        logger.info(f"Backed up {len(existing_files)} files for {self.name} to {backup_dir}")

    def _process_shard_file(self, filepath: str, tasks: List[str], estimated_lines: Optional[int] = None) -> int:
        """Process a single shard file and extract valid URLs.

        Args:
            filepath: Path to the shard file to process
            tasks: List to append recovered URLs to
            estimated_lines: Optional estimated line count for debug logging

        Returns:
            Number of URLs processed from this file
        """
        count = 0
        if estimated_lines:
            self.logger.debug(f"Processing shard {filepath} (estimated {estimated_lines} lines)")

        try:
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        # Accept either {"url": "..."} or {"value": "..."}
                        url = obj.get("url") or obj.get("value")
                        if isinstance(url, str) and url.startswith("http"):
                            tasks.append(url)
                            count += 1
                    except Exception:
                        continue
        except Exception as e:
            self.logger.error(f"Failed to process shard file {filepath}: {e}")

        return count

    def recover_tasks(self) -> RecoveredTasks:
        """Recover tasks from existing result files and NDJSON shards (links)."""
        recovered = RecoveredTasks()
        # Prefer shards for links if available; fallback to legacy text file
        links_shards = os.path.join(self.directory, "shards", ResultType.LINKS.value)
        if os.path.isdir(links_shards):
            total = 0
            try:
                # Use index to optimize recovery: skip empty shards, estimate work
                indexed_shards = []
                unindexed_shards = []

                for filename in sorted(os.listdir(links_shards)):
                    if not filename.endswith(".ndjson"):
                        continue
                    shard_path = os.path.join(links_shards, filename)
                    index_path = os.path.splitext(shard_path)[0] + ".index.json"

                    try:
                        with open(index_path, encoding="utf-8") as f:
                            index_data = json.load(f)
                            lines = int(index_data.get("lines", 0))
                            if lines > 0:  # Skip empty shards
                                indexed_shards.append((shard_path, index_data))
                    except Exception:
                        unindexed_shards.append(shard_path)

                # Process indexed shards first (sorted by timestamp)
                indexed_shards.sort(key=lambda x: x[1].get("first_ts", ""))

                for shard_path, index_data in indexed_shards:
                    estimated_lines = int(index_data.get("lines", 0))
                    count = self._process_shard_file(shard_path, recovered.acquisition_tasks, estimated_lines)
                    total += count

                # Process non-indexed shards
                for shard_path in unindexed_shards:
                    count = self._process_shard_file(shard_path, recovered.acquisition_tasks)
                    total += count

                if total > 0:
                    logger.info(f"[persist] recovered {total} acquisition tasks from shards for {self.name}")
                    return recovered
            except Exception as e:
                logger.error(f"[persist] failed to read link shards for {self.name}: {e}")

        # Fallback: recover from text file
        links_path = self.files[ResultType.LINKS.value]
        if os.path.exists(links_path):
            try:
                with open(links_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and line.startswith("http"):
                            recovered.acquisition_tasks.append(line)
                logger.info(f"Recovered {len(recovered.acquisition_tasks)} acquisition tasks from {self.name}")
            except Exception as e:
                logger.error(f"Failed to read links file for {self.name}: {e}")
        return recovered

    def build_snapshot(self, result_type: str) -> int:
        """Build a pretty JSON snapshot from NDJSON shards for a result type."""
        shard_root = os.path.join(self.directory, "shards", result_type)
        snapshots_dir = os.path.join(self.directory, "snapshots")
        os.makedirs(snapshots_dir, exist_ok=True)
        snapshot_path = os.path.join(snapshots_dir, f"{result_type}.json")
        manager = SnapshotManager(shard_root, snapshot_path)
        t0 = time.time()
        count = manager.build_snapshot()
        dt = time.time() - t0
        with self.lock:
            self.stats.last_snapshot = time.time()
            self.stats.snapshot_count += 1
            self.stats.total_snapshot_time += dt
            self.stats.snapshot_operations += 1
        self.logger.info(f"built snapshot for {result_type} with {count} records in {dt:.3f}s")
        return count

    def build_all_snapshots(self) -> Dict[str, int]:
        """Build snapshots for all buffered result types (excluding summary)."""
        results: Dict[str, int] = {}
        for rt in self.buffers.keys():
            try:
                results[rt] = self.build_snapshot(rt)
            except Exception as e:
                logger.error(f"[persist] failed to build snapshot for {self.name}:{rt}: {e}")
        return results

    def _get_shard_writer(self, result_type: str) -> NDJSONShardWriter:
        """Lazy-init and cache shard writers per result type."""
        if not hasattr(self, "_shard_writers"):
            self._shard_writers: Dict[str, NDJSONShardWriter] = {}
        writer = self._shard_writers.get(result_type)
        if not writer:
            # Place shards under provider directory: <dir>/shards/<result_type>/*.ndjson
            shard_root = os.path.join(self.directory, "shards")
            writer = NDJSONShardWriter(shard_root, result_type)
            self._shard_writers[result_type] = writer
        return writer

    def _load_services_from_file(self, filepath: str) -> List:
        """Load and deserialize services from file"""
        services = []
        try:
            if os.path.exists(filepath) and os.path.isfile(filepath):
                with open(filepath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                service = self._deserialize_service(line)
                                if service:
                                    services.append(service)
                            except Exception as e:
                                logger.warning(f"Failed to deserialize service from {filepath}: {e}")
        except Exception as e:
            logger.error(f"Failed to read file {filepath}: {e}")

        return services

    def _deserialize_service(self, line: str) -> Optional[Any]:
        """Deserialize service object from string"""
        try:
            return Service.deserialize(line)
        except Exception as e:
            logger.warning(f"Failed to deserialize service: {e}")
            return None

    def stop(self):
        """Stop the result manager and flush all data, then build snapshots."""
        self.running = False
        # Stop periodic snapshot thread first to avoid concurrent builds
        try:
            self.stop_periodic_snapshot()
        except Exception as e:
            logger.error(f"[persist] failed to stop periodic snapshot for {self.name}: {e}")
        if self.flush_thread.is_alive():
            self.flush_thread.join(timeout=self.shutdown_timeout)

        self.flush_all()
        try:
            self.build_all_snapshots()
        except Exception as e:
            logger.error(f"[persist] failed to build snapshots for {self.name} on stop: {e}")
        logger.info(f"Stopped result manager for {self.name}")

    def start_periodic_snapshot(self, interval_sec: int = 300) -> None:
        """Start a background thread to build snapshots periodically."""
        if hasattr(self, "_snapshot_thread") and self._snapshot_thread and self._snapshot_thread.is_alive():
            return
        self._snapshot_running = True

        def _loop():
            while self._snapshot_running:
                try:
                    time.sleep(interval_sec)
                    if not self._snapshot_running:
                        break
                    self.build_all_snapshots()
                except Exception as e:
                    logger.error(f"[persist] periodic snapshot error for {self.name}: {e}")

        self._snapshot_thread = threading.Thread(target=_loop, daemon=True)
        self._snapshot_thread.start()

    def stop_periodic_snapshot(self) -> None:
        """Stop the background snapshot thread."""
        self._snapshot_running = False
        t = getattr(self, "_snapshot_thread", None)
        if t and t.is_alive():
            t.join(timeout=self.shutdown_timeout)

    def _periodic_flush(self):
        """Periodic flush thread"""
        while self.running:
            try:
                time.sleep(self.save_interval)

                # Check each buffer for time-based flush
                for result_type, buffer in self.buffers.items():
                    if buffer.size() > 0 and time.time() - buffer.last_flush >= self.save_interval:
                        self._flush_buffer(result_type)

            except Exception as e:
                logger.error(f"[persist] error in periodic flush for {self.name}: {e}")

    def _flush_buffer(self, result_type: str):
        """Flush a specific buffer to file"""
        buffer = self.buffers.get(result_type)
        if not buffer:
            return

        items = buffer.flush()
        if not items:
            return

        try:
            filepath = self.files[result_type]

            # Convert items to simple lines or NDJSON records
            lines: List[str] = []
            records: List[Dict[str, Any]] = []
            for item in items:
                if hasattr(item, "serialize"):
                    s = item.serialize()
                    if self.simple:
                        lines.append(s)
                    else:
                        # Best effort: also try to convert to dict if possible
                        try:
                            records.append(json.loads(s))
                        except Exception:
                            # Fallback to plain string envelope
                            records.append({"value": s})
                else:
                    s = str(item)
                    if self.simple:
                        lines.append(s)
                    else:
                        records.append({"value": s})

            # Write simple text file
            if self.simple:
                AtomicFileWriter.append_atomic(filepath, lines)
            else:
                # Append to NDJSON shard for new pipeline
                self._get_shard_writer(result_type).append_records(records, self.stats)

            with self.lock:
                self.stats.last_save = time.time()

            logger.info(f"[persist] saved {len(lines)} {result_type} for {self.name}")

        except Exception as e:
            logger.error(f"[persist] failed to save {result_type} for {self.name}: {e}")

    def _save_models(self):
        """Save models data to JSON file"""
        if not self.models_data:
            return

        try:
            filepath = self.files[ResultType.SUMMARY.value]

            # Unique models
            unique_models = set()
            for data in self.models_data.values():
                unique_models.update(data.get("models", []))

            total_models = len(unique_models)
            del unique_models

            # Prepare summary data
            summary = {
                "provider": self.name,
                "updated_at": time.time(),
                "models": self.models_data,
                "stats": {
                    "total_keys": len(self.models_data),
                    "total_models": total_models,
                },
            }

            # Write atomically
            content = json.dumps(summary, indent=2, ensure_ascii=False)
            AtomicFileWriter.write_atomic(filepath, content)

            logger.debug(f"[persist] saved models summary for {self.name}")

        except Exception as e:
            logger.error(f"[persist] failed to save models for {self.name}: {e}")


class MultiResultManager:
    """Manages results for multiple providers"""

    def __init__(
        self,
        workspace: str,
        providers: Dict[str, Any] = None,
        batch_size: int = 50,
        save_interval: float = 30.0,
        simple: bool = False,
        shutdown_timeout: float = 5.0,
    ):
        self.workspace = workspace
        self.providers = providers or {}
        self.batch_size = batch_size
        self.save_interval = save_interval
        self.simple = simple
        self.shutdown_timeout = float(max(1.0, shutdown_timeout))
        self.managers: Dict[str, ResultManager] = {}
        self.lock = threading.Lock()

        # Create workspace directory
        os.makedirs(workspace, exist_ok=True)
        os.makedirs(os.path.join(workspace, "providers"), exist_ok=True)

    def get_manager(self, name: str) -> ResultManager:
        """Get or create result manager for provider"""
        with self.lock:
            if name not in self.managers:
                provider = self.providers.get(name)
                if not provider:
                    raise ValueError(f"Provider instance not found: {name}")
                self.managers[name] = ResultManager(
                    provider,
                    self.workspace,
                    self.batch_size,
                    self.save_interval,
                    simple=self.simple,
                    shutdown_timeout=self.shutdown_timeout,
                )
            return self.managers[name]

    def add_result(self, provider: str, result_type: str, data: Any):
        """Add result for a specific provider"""
        manager = self.get_manager(provider)
        manager.add_result(result_type, data)

    def add_links(self, provider: str, links: List[str]):
        """Add links for a specific provider"""
        manager = self.get_manager(provider)
        manager.add_links(links)

    def add_models(self, provider: str, key: str, models: List[str]):
        """Add models for a specific provider"""
        manager = self.get_manager(provider)
        manager.add_models(key, models)

    def flush_all(self):
        """Flush all providers"""
        with self.lock:
            for manager in self.managers.values():
                manager.flush_all()

    def get_all_stats(self) -> Dict[str, PersistenceMetrics]:
        """Get statistics for all providers"""
        stats = {}
        with self.lock:
            for provider, manager in self.managers.items():
                stats[provider] = manager.get_stats()
        return stats

    def recover_all_tasks(self) -> AllRecoveredTasks:
        """Recover tasks from all providers' result files"""
        all_recovered = AllRecoveredTasks()

        for name in self.providers.keys():
            try:
                manager = self.get_manager(name)
                recovered = manager.recover_tasks()
                all_recovered.add_provider(name, recovered)
            except Exception as e:
                logger.error(f"Failed to recover tasks for {name}: {e}")

        if all_recovered.has_providers():
            logger.info(
                f"Recovered {all_recovered.total_check_tasks()} check tasks, "
                f"{all_recovered.total_acquisition_tasks()} acquisition tasks, and "
                f"{all_recovered.total_invalid_keys()} invalid keys from all providers"
            )

        return all_recovered

    def backup_all_existing_files(self) -> None:
        """Backup existing files for all providers"""
        for name in self.providers.keys():
            try:
                manager = self.get_manager(name)
                manager.backup_existing_files()
            except Exception as e:
                logger.error(f"Failed to backup files for {name}: {e}")

    def start_periodic_snapshots(self, interval_sec: int = 300) -> None:
        """Start periodic snapshots for all providers."""
        with self.lock:
            for manager in self.managers.values():
                try:
                    manager.start_periodic_snapshot(interval_sec)
                except Exception as e:
                    logger.error(f"Failed to start periodic snapshot for {manager.name}: {e}")
        logger.info(f"Started periodic snapshots for {len(self.managers)} providers (interval: {interval_sec}s)")

    def stop_periodic_snapshots(self) -> None:
        """Stop periodic snapshots for all providers."""
        with self.lock:
            for manager in self.managers.values():
                try:
                    manager.stop_periodic_snapshot()
                except Exception as e:
                    logger.error(f"Failed to stop periodic snapshot for {manager.name}: {e}")
        logger.info("Stopped periodic snapshots for all providers")

    def build_all_snapshots_all(self) -> Dict[str, Dict[str, int]]:
        """Build snapshots for all result types across all providers."""
        results: Dict[str, Dict[str, int]] = {}
        with self.lock:
            for provider_name, manager in self.managers.items():
                try:
                    results[provider_name] = manager.build_all_snapshots()
                except Exception as e:
                    logger.error(f"Failed to build snapshots for {provider_name}: {e}")
                    results[provider_name] = {}
        total_snapshots = sum(len(provider_results) for provider_results in results.values())
        logger.info(f"Built {total_snapshots} snapshots across {len(results)} providers")
        return results

    def stop_all(self):
        """Stop all result managers"""
        with self.lock:
            for manager in self.managers.values():
                manager.stop()

        logger.info("Stopped all result managers")


if __name__ == "__main__":
    # Test result manager
    # Create temporary workspace
    workspace = tempfile.mkdtemp()
    logger.info(f"Testing in workspace: {workspace}")

    # Create mock provider for testing
    class MockProvider:
        def __init__(self):
            self.name = "test_provider"
            self.directory = "test_provider"
            self.keys_filename = "valid-keys.txt"
            self.no_quota_filename = "no-quota-keys.txt"
            self.wait_check_filename = "wait-check-keys.txt"
            self.invalid_keys_filename = "invalid-keys.txt"
            self.material_filename = "material.txt"
            self.links_filename = "links.txt"
            self.summary_filename = "summary.json"

    try:
        # Test single provider
        mock_provider = MockProvider()
        manager = ResultManager(mock_provider, workspace, batch_size=3, save_interval=1)

        # Add some results
        manager.add_result(ResultType.VALID_KEYS.value, ["key1", "key2"])
        manager.add_links(["http://example.com/1", "http://example.com/2"])
        manager.add_result(ResultType.VALID_KEYS.value, "key3")  # Should trigger flush

        # Wait for periodic flush
        time.sleep(2)

        # Check files
        links_file = os.path.join(workspace, "providers", "test_provider", "links.txt")
        if os.path.exists(links_file):
            with open(links_file) as f:
                content = f.read()
                logger.info(f"Links file content:\n{content}")

        # Get stats
        stats = manager.get_stats()
        logger.info(f"Stats: valid_keys={stats.valid_keys}, links={stats.total_links}")

        # Stop manager
        manager.stop()

        logger.info("Result manager test completed!")

    finally:
        # Cleanup
        shutil.rmtree(workspace)
