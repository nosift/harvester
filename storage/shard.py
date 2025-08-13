"""
NDJSON shard writer with rotation and indexing.
"""

import datetime
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from state.models import PersistenceMetrics
from tools.logger import get_logger

from .atomic import AtomicFileWriter, _exclusive_file_lock

logger = get_logger("storage")


class NDJSONShardWriter:
    """Write NDJSON records to rotating shard files with sidecar indexes."""

    def __init__(self, shard_root: str, result_type: str, max_lines: int = 10000, max_age_sec: int = 3600):
        self.shard_root = shard_root
        self.result_type = result_type
        self.max_lines = max_lines
        self.max_age_sec = max_age_sec
        self._lock = threading.Lock()
        self._current_path: Optional[str] = None
        self._current_lines = 0
        self._current_start_time = time.time()

        # Ensure shard directory exists
        self.shard_dir = os.path.join(shard_root, result_type)
        os.makedirs(self.shard_dir, exist_ok=True)

    def _ensure_current(self) -> str:
        """Ensure current shard file exists and is valid for writing."""
        now = time.time()
        needs_rotation = (
            self._current_path is None
            or self._current_lines >= self.max_lines
            or (now - self._current_start_time) >= self.max_age_sec
        )

        if needs_rotation:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # milliseconds
            filename = f"{self.result_type}_{timestamp}.ndjson"
            self._current_path = os.path.join(self.shard_dir, filename)
            self._current_lines = 0
            self._current_start_time = now

        return self._current_path

    def _get_index_path(self, shard_path: str) -> str:
        base, _ = os.path.splitext(shard_path)
        return base + ".index.json"

    def _update_index(self, shard_path: str, added_lines: int, bad_lines: int = 0) -> None:
        idx_path = self._get_index_path(shard_path)
        idx: Dict[str, Any] = {}
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
        except Exception:
            idx = {}
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        if "first_ts" not in idx:
            idx["first_ts"] = now_iso
        idx["last_ts"] = now_iso

        # Update line counts
        prev_lines = int(idx.get("lines", 0))
        prev_bad = int(idx.get("bad_lines", 0))
        idx["lines"] = prev_lines + int(added_lines)
        idx["bad_lines"] = prev_bad + int(bad_lines)

        # Schema version for future compatibility
        idx["schema_version"] = "1.0"
        idx["file"] = os.path.basename(shard_path)

        # Optional: file size for quick checks
        try:
            idx["file_size"] = os.path.getsize(shard_path)
        except Exception:
            pass

        content = json.dumps(idx, indent=2, ensure_ascii=False)
        AtomicFileWriter.write_atomic(idx_path, content)

    def append_records(self, records: List[Dict[str, Any]], stats: Optional[PersistenceMetrics] = None) -> None:
        """Append a list of JSON-serializable records as NDJSON lines."""
        if not records:
            return

        t0 = time.time()
        with self._lock:
            path = self._ensure_current()
            # Write all records in one open/flush/fsync with file lock
            with open(path, "a", encoding="utf-8") as f, _exclusive_file_lock(f):
                for rec in records:
                    line = json.dumps(rec, ensure_ascii=False)
                    f.write(line)
                    f.write("\n")
                    self._current_lines += 1
                f.flush()
                os.fsync(f.fileno())
            # Update sidecar index after successful write
            try:
                self._update_index(path, len(records))
            except Exception as e:
                logger.error(f"[storage] failed to update index for {path}: {e}")

        # Update metrics if provided
        if stats:
            dt = time.time() - t0
            stats.total_append_time += dt
            stats.append_operations += 1
