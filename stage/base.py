#!/usr/bin/env python3

"""
Base classes for pipeline stages.
Hybrid architecture with dependency injection and pure functional processing.
"""

import queue
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from config.schemas import Config, StageConfig, TaskConfig
from constant.system import DEFAULT_SHUTDOWN_TIMEOUT
from core.metrics import StageMetrics
from core.tasks import ProviderTask
from core.types import AuthProvider
from tools.logger import get_logger
from tools.ratelimit import RateLimiter
from tools.retry import ExponentialBackoff, RetryPolicy

logger = get_logger("stage")


@dataclass
class StageResources:
    """Resources injected into stages for dependency inversion"""

    limiter: RateLimiter
    providers: Dict[str, Any]
    config: Config
    task_configs: Dict[str, Any]
    auth: AuthProvider

    def is_enabled(self, provider: str, stage: str) -> bool:
        """Check if stage is enabled for provider"""
        config = self.task_configs.get(provider)
        if not config:
            return False
        return getattr(config.stages, stage, False)


@dataclass
class StageOutput:
    """Pure functional output from stage processing"""

    task: ProviderTask
    new_tasks: List[Tuple[ProviderTask, str]] = field(default_factory=list)  # (task, target_stage)
    results: List[Tuple[str, str, Any]] = field(default_factory=list)  # (provider, type, data)
    links: List[Tuple[str, List[str]]] = field(default_factory=list)  # (provider, links)
    models: List[Tuple[str, str, List[str]]] = field(default_factory=list)  # (provider, key, models)

    def add_task(self, task: ProviderTask, target: str) -> None:
        """Add new task to be routed"""
        self.new_tasks.append((task, target))

    def add_result(self, provider: str, result_type: str, data: Any) -> None:
        """Add result to be saved"""
        self.results.append((provider, result_type, data))

    def add_links(self, provider: str, links: List[str]) -> None:
        """Add links to be saved"""
        self.links.append((provider, links))

    def add_models(self, provider: str, key: str, models: List[str]) -> None:
        """Add models to be saved"""
        self.models.append((provider, key, models))


# Type alias for output handler function
OutputHandler = Callable[[StageOutput], None]


class BasePipelineStage(ABC):
    """Base class for pipeline stages with hybrid architecture support"""

    def __init__(
        self,
        name: str,
        resources: StageResources,
        handler: OutputHandler,
        thread_count: int = 1,
        queue_size: int = 1000,
        max_retries: int = 0,
        dedup_max_size: int = 100_000,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        self.name = name
        self.resources = resources
        self.handler = handler
        self.thread_count = thread_count

        # Task queue
        self.queue = queue.Queue(maxsize=queue_size)

        # Task deduplication (bounded)
        self.processed: set = set()
        self.processed_order = deque()
        self.dedup_max_size = max(1000, int(dedup_max_size))
        self.dedup_lock = threading.Lock()

        # Worker threads
        self.workers: List[threading.Thread] = []
        self.running = False
        self.accepting = True

        # Maximum number of retries
        self.max_retries = max(max_retries, 0)

        # Retry policy
        self.retry_policy = retry_policy or ExponentialBackoff(max_retries=self.max_retries)

        # Statistics
        self.total_processed = 0
        self.total_errors = 0
        self.last_activity = time.time()
        self.start_time = time.time()

        # Work state tracking
        self.active_workers = 0
        self.work_lock = threading.Lock()

        # Thread safety
        self.stats_lock = threading.Lock()

        # Thread lifecycle tracking
        self.zombie_threads = []

        logger.info(f"Created stage: {name}, threads: {thread_count}, queue: {queue_size}")

    def start(self) -> None:
        """Start worker threads"""
        if self.running:
            return

        self.running = True
        self.accepting = True

        for i in range(self.thread_count):
            worker = threading.Thread(target=self._worker_loop, name=f"{self.name}-worker-{i+1}", daemon=True)
            worker.start()
            self.workers.append(worker)

        logger.info(f"[{self.name}] started {len(self.workers)} workers")

    def stop(self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
        """Stop worker threads with enhanced tracking"""
        if not self.running:
            return

        # Stop accepting new tasks
        self.accepting = False
        logger.info(f"[{self.name}] stopping, waiting for {len(self.workers)} workers")

        # Wait for queue to drain
        queue_timeout = timeout * 0.3
        start_time = time.time()
        while not self.queue.empty() and time.time() - start_time < queue_timeout:
            time.sleep(0.1)

        # Stop workers with tracking
        self.running = False
        worker_timeout = timeout * 0.6
        alive_workers = []

        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=worker_timeout / max(len(self.workers), 1))
                if worker.is_alive():
                    worker_name = getattr(worker, "name", f"worker-{id(worker)}")
                    alive_workers.append(worker_name)

        # Track zombie threads for monitoring
        if alive_workers:
            self.zombie_threads = alive_workers
            logger.warning(f"[{self.name}] {len(alive_workers)} workers did not stop gracefully")
        else:
            self.zombie_threads = []
            logger.info(f"[{self.name}] all workers stopped gracefully")

    def put_task(self, task: ProviderTask) -> bool:
        """Add task to queue with deduplication check"""
        if not self.accepting:
            logger.warning(f"[{self.name}] not accepting tasks, discard: {task}")
            return False

        # Generate task ID for deduplication
        task_id = self._generate_id(task)

        # Check if task already processed
        with self.dedup_lock:
            # Logic: attempts == 0 means new task, but same task already queued
            if task_id in self.processed and (task.attempts == 0 or task.attempts > self.max_retries):
                if task.attempts > self.max_retries:
                    logger.warning(
                        f"[{self.name}] task=[{task_id}] discarded, max retries=[{self.max_retries}] reached"
                    )
                return False

        # Try to add to queue
        try:
            self.queue.put(task, timeout=1.0)
            with self.dedup_lock:
                if task_id not in self.processed:
                    self.processed.add(task_id)
                    self.processed_order.append(task_id)
                    # Evict oldest when exceeding cap to avoid unbounded growth
                    if len(self.processed) > self.dedup_max_size and self.processed_order:
                        oldest = self.processed_order.popleft()
                        if oldest != task_id:
                            self.processed.discard(oldest)

            return True
        except queue.Full:
            logger.warning(f"[{self.name}] queue is full")
            return False

    def is_finished(self) -> bool:
        """Check if stage is finished processing"""
        # Stage is finished if:
        # 1. Queue is empty
        # 2. No workers are actively processing tasks
        return self.queue.empty() and not self._has_active_workers()

    def get_stats(self) -> "StageMetrics":
        """Get stage statistics"""

        with self.stats_lock:
            metrics = StageMetrics(
                name=self.name,
                running=self.running,
                disabled=False,  # Active stages are not disabled
                queue_size=self.queue.qsize(),
                last_activity=self.last_activity,
                workers=len(self.workers),
            )
            # Set task metrics
            metrics.tasks.completed = self.total_processed
            metrics.tasks.failed = self.total_errors

            return metrics

    def has_zombie_threads(self) -> bool:
        """Check if there are threads that failed to stop"""
        return len(self.zombie_threads) > 0

    def get_zombie_count(self) -> int:
        """Get count of zombie threads"""
        return len(self.zombie_threads)

    def get_pending_tasks(self) -> List[ProviderTask]:
        """Get all pending tasks (for persistence)"""
        tasks = []
        temp_tasks = []

        # Extract all tasks without blocking
        while not self.queue.empty():
            try:
                task = self.queue.get_nowait()
                tasks.append(task)
                temp_tasks.append(task)
            except queue.Empty:
                break

        # Put tasks back
        for task in temp_tasks:
            try:
                self.queue.put_nowait(task)
            except queue.Full:
                logger.warning(f"[{self.name}] lost task during persistence: {task.task_id}")

        return tasks

    def is_busy(self) -> bool:
        """Check if stage is currently processing tasks"""
        return not self.queue.empty() or self._has_active_workers()

    def stop_accepting(self) -> None:
        """Stop accepting new tasks"""
        self.accepting = False

    def process_task(self, task: ProviderTask) -> Optional[StageOutput]:
        """Template method for task processing with common workflow."""
        # Step 1: Validate task type
        if not self._validate_task_type(task):
            logger.error(f"[{self.name}] invalid task type: {type(task)}")
            return None

        # Step 2: Pre-processing hook
        if not self._pre_process(task):
            return None

        # Step 3: Execute core processing (implemented by subclasses)
        try:
            result = self._execute_task(task)

            # Step 4: Post-processing hook
            if result:
                result = self._post_process(task, result)

            return result

        except Exception as e:
            logger.error(f"[{self.name}] task processing failed: {e}")
            return self._handle_processing_error(task, e)

    @abstractmethod
    def _validate_task_type(self, task: ProviderTask) -> bool:
        """Validate that the task is of the correct type for this stage."""
        pass

    @abstractmethod
    def _execute_task(self, task: ProviderTask) -> Optional[StageOutput]:
        """Execute the core task processing logic."""
        pass

    def _pre_process(self, task: ProviderTask) -> bool:
        """Pre-processing hook. Return False to skip processing."""
        return True

    def _post_process(self, task: ProviderTask, result: StageOutput) -> StageOutput:
        """Post-processing hook. Can modify the result."""
        return result

    def _handle_processing_error(self, task: ProviderTask, error: Exception) -> Optional[StageOutput]:
        """Handle processing errors. Return None by default."""
        return None

    @abstractmethod
    def _generate_id(self, task: ProviderTask) -> str:
        """Generate unique task identifier for deduplication"""
        pass

    def _worker_loop(self) -> None:
        """Main worker thread loop with pure functional processing"""
        while self.running:
            try:
                # Get task with timeout
                task = self.queue.get(timeout=1.0)

                # Mark worker as active
                with self.work_lock:
                    self.active_workers += 1

                # Update activity time
                with self.stats_lock:
                    self.last_activity = time.time()

                # Process task
                try:
                    output = self.process_task(task)

                    # Handle output if returned
                    if output:
                        self.handler(output)

                    # Update success statistics
                    with self.stats_lock:
                        self.total_processed += 1

                except Exception as e:
                    logger.error(f"[{self.name}] error processing task: {e}")

                    # Check if task should be retried using policy
                    if self.retry_policy.should_retry(task.attempts, e):
                        # Get delay from policy
                        delay = self.retry_policy.get_delay(task.attempts)
                        if delay > 0:
                            time.sleep(delay)

                        task.attempts += 1
                        success = self.put_task(task)
                        status = "successfully" if success else "failed"
                        logger.warning(f"[{self.name}] requeued {status} after {delay:.1f}s delay, task: {task}")

                    # Update error statistics
                    with self.stats_lock:
                        self.total_errors += 1
                        self.total_processed += 1

                finally:
                    # Mark worker as inactive
                    with self.work_lock:
                        self.active_workers -= 1

                    # Mark task as done
                    self.queue.task_done()

            except queue.Empty:
                # Timeout waiting for task, continue loop
                continue
            except Exception as e:
                logger.error(f"[{self.name}] worker error: {e}")

    def _has_active_workers(self) -> bool:
        """Check if any workers are currently active"""
        with self.work_lock:
            return self.active_workers > 0


class StageUtils:
    """Stage configuration utility class"""

    _names_cache: Optional[List[str]] = None

    @classmethod
    def get_names(cls) -> List[str]:
        """Get all possible stage names (cached)"""
        if cls._names_cache is None:
            names = []

            # Use reflection to get all boolean attributes from StageConfig
            for name in dir(StageConfig):
                if not name.startswith("_"):
                    try:
                        attr = getattr(StageConfig, name)
                        # Check if it's a boolean attribute or annotated as bool
                        if isinstance(attr, bool) or (
                            hasattr(StageConfig, "__annotations__")
                            and name in StageConfig.__annotations__
                            and StageConfig.__annotations__[name] == bool
                        ):
                            names.append(name)
                    except (AttributeError, TypeError):
                        continue

            cls._names_cache = names

        return cls._names_cache.copy()

    @classmethod
    def get_enabled(cls, config: TaskConfig) -> List[str]:
        """Get enabled stages from task config"""
        enabled = []
        for name in cls.get_names():
            if getattr(config.stages, name, False):
                enabled.append(name)
        return enabled

    @classmethod
    def get_info(cls, config: TaskConfig) -> Dict[str, bool]:
        """Get stage status dictionary"""
        info = {}
        for name in cls.get_names():
            info[name] = getattr(config.stages, name, False)
        return info

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached stage names (for testing)"""
        cls._names_cache = None
