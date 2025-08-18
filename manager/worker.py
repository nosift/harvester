#!/usr/bin/env python3

"""
Load balancing system for dynamic worker thread management.
Automatically adjusts worker counts based on queue sizes and processing speeds.
"""

import random
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Dict, Optional, Tuple

from config.schemas import WorkerManagerConfig
from constant.system import (
    DEFAULT_ADJUSTMENT_INTERVAL,
    DEFAULT_MAX_WORKERS,
    DEFAULT_MIN_WORKERS,
    DEFAULT_SCALE_DOWN_THRESHOLD,
    DEFAULT_SCALE_UP_THRESHOLD,
    DEFAULT_TARGET_QUEUE_SIZE,
    LB_RECENT_HISTORY_SIZE,
)
from core.enums import PipelineStage
from stage.base import WorkerManageable
from state.models import StageWorkerStatus, WorkerMetrics, WorkerStatus
from tools.logger import get_logger

from .base import ConditionalTaskManager

logger = get_logger("manager")


class ScalingStrategy(ABC):
    """Abstract base class for worker scaling strategies"""

    @abstractmethod
    def calculate_target(self, metrics: WorkerMetrics) -> int:
        """Calculate target worker count based on metrics

        Args:
            metrics: Current stage metrics snapshot

        Returns:
            int: Target worker count
        """
        pass


class DefaultScaling(ScalingStrategy):
    """Default scaling strategy based on queue size and utilization"""

    def __init__(
        self,
        min_workers: int = DEFAULT_MIN_WORKERS,
        max_workers: int = DEFAULT_MAX_WORKERS,
        target_queue_size: int = DEFAULT_TARGET_QUEUE_SIZE,
        scale_up_threshold: float = DEFAULT_SCALE_UP_THRESHOLD,
        scale_down_threshold: float = DEFAULT_SCALE_DOWN_THRESHOLD,
    ):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.target_queue_size = target_queue_size
        self.scale_up_threshold = scale_up_threshold
        self.scale_down_threshold = scale_down_threshold

    def calculate_target(self, metrics: WorkerMetrics) -> int:
        """Calculate target workers using queue size and utilization"""
        # Base calculation on queue size and processing rate
        if metrics.processing_rate > 0:
            # Calculate workers needed to maintain target queue size
            target = max(1, int(metrics.queue_size / self.target_queue_size))
        else:
            # Fallback to utilization-based calculation
            if metrics.utilization > self.scale_up_threshold:
                target = min(self.max_workers, metrics.current_workers + 1)
            elif metrics.utilization < self.scale_down_threshold:
                target = max(self.min_workers, metrics.current_workers - 1)
            else:
                target = metrics.current_workers

        # Apply constraints
        return max(self.min_workers, min(self.max_workers, target))


class WorkerManager(ConditionalTaskManager):
    """Dynamic worker manager for pipeline thread management"""

    def __init__(
        self,
        config: WorkerManagerConfig,
        shutdown_timeout: float = 5.0,
        scaling_strategy: Optional[ScalingStrategy] = None,
    ):
        # Initialize base class
        super().__init__("WorkerManager", config.adjustment_interval / 2, shutdown_timeout)

        self.worker_metrics: Dict[str, WorkerMetrics] = {}
        self.stages: Dict[str, WorkerManageable] = {}

        # Load balancing parameters
        self.min_workers = config.min_workers
        self.max_workers = config.max_workers
        self.target_queue_size = config.target_queue_size
        self.scale_up_threshold = config.scale_up_threshold
        self.scale_down_threshold = config.scale_down_threshold
        self.adjustment_interval = config.adjustment_interval
        self.log_recommendations = config.log_recommendations

        # Scaling strategy
        self.scaling_strategy = scaling_strategy or DefaultScaling(
            min_workers=self.min_workers,
            max_workers=self.max_workers,
            target_queue_size=self.target_queue_size,
            scale_up_threshold=self.scale_up_threshold,
            scale_down_threshold=self.scale_down_threshold,
        )

        # Additional lock for worker metrics
        self.lock = threading.Lock()

        # History for trend analysis
        self.metrics_history: Dict[str, deque] = {}

        # Track last recommendations to avoid spam logging
        self.last_recommendations: Dict[str, Tuple[int, int, float]] = {}  # stage -> (current, target, timestamp)

        # Batch recommendation logging
        self.pending_recommendations: Dict[str, Tuple[int, int]] = {}  # stage -> (current, target)
        self.last_batch_log_time: float = 0.0

        # Cache for last known stats (used when lock timeout occurs)
        self.last_known_stats: Optional[WorkerStatus] = None
        self.last_stats_update_time: float = 0.0

        logger.info("Initialized worker manager")

    def register_stage(self, stage_name: str, stage_instance: WorkerManageable):
        """Register a pipeline stage for worker management

        Args:
            stage_name: Name of the stage
            stage_instance: Stage instance (implementing WorkerManageable interface)
        """
        with self.lock:
            self.stages[stage_name] = stage_instance
            self.worker_metrics[stage_name] = WorkerMetrics(stage=stage_name)
            self.metrics_history[stage_name] = deque(maxlen=50)

        logger.info(f"Registered stage for worker management: {stage_name}")

    def is_stage_adjustable(self, stage_name: str) -> bool:
        """Check if a stage supports worker adjustment

        Args:
            stage_name: Name of the stage to check

        Returns:
            bool: True if stage supports worker adjustment
        """
        with self.lock:
            if stage_name not in self.stages:
                return False

            stage = self.stages[stage_name]
            return isinstance(stage, WorkerManageable)

    def _on_stopped(self) -> None:
        """Flush pending recommendations when stopped"""
        self._flush_recommendation_batch()

    def _on_task_completion(self) -> None:
        """Handle task manager completion event"""
        self.mark_finished()

    def update_metrics(self, stage_name: str, metrics_data):
        """Update metrics for a specific stage"""
        with self.lock:
            if stage_name not in self.worker_metrics:
                return

            metrics = self.worker_metrics[stage_name]

            # Update metrics from data class
            metrics.queue_size = metrics_data.queue_size
            metrics.current_workers = metrics_data.current_workers
            metrics.processing_rate = metrics_data.processing_rate
            metrics.avg_processing_time = metrics_data.avg_processing_time

            # Calculate utilization
            if metrics.current_workers > 0:
                metrics.utilization = min(1.0, metrics.queue_size / (metrics.current_workers * self.target_queue_size))

            # Store in history
            self.metrics_history[stage_name].append(
                {
                    "timestamp": time.time(),
                    "queue_size": metrics.queue_size,
                    "workers": metrics.current_workers,
                    "utilization": metrics.utilization,
                    "processing_rate": metrics.processing_rate,
                }
            )

    def get_recommended_workers(self, stage_name: str) -> int:
        """Get recommended worker count for a stage"""
        with self.lock:
            if stage_name not in self.worker_metrics:
                return self.min_workers

            # Create snapshot to avoid holding lock during calculation
            metrics = self.worker_metrics[stage_name]
            snapshot = WorkerMetrics(
                stage=metrics.stage,
                current_workers=metrics.current_workers,
                queue_size=metrics.queue_size,
                processing_rate=metrics.processing_rate,
                utilization=metrics.utilization,
            )

        # Calculate outside lock using snapshot
        target_workers = self._calculate_target_workers(snapshot)

        # Update target in original metrics
        with self.lock:
            if stage_name in self.worker_metrics:
                self.worker_metrics[stage_name].target_workers = target_workers

        return target_workers

    def _calculate_target_workers(self, metrics: WorkerMetrics) -> int:
        """Calculate target workers using scaling strategy"""
        # Use strategy to calculate base target
        target_workers = self.scaling_strategy.calculate_target(metrics)

        # Apply trend analysis
        target_workers = self._apply_trend_analysis(metrics.stage, target_workers)

        return target_workers

    def should_adjust_workers(self, stage_name: str) -> bool:
        """Check if worker count should be adjusted"""
        with self.lock:
            if stage_name not in self.worker_metrics:
                return False

            metrics = self.worker_metrics[stage_name]
            current_time = time.monotonic()

            # Check if enough time has passed since last adjustment
            if current_time - metrics.last_adjustment < self.adjustment_interval:
                return False

            # Create snapshot for calculation without nested lock
            snapshot = WorkerMetrics(
                stage=metrics.stage,
                current_workers=metrics.current_workers,
                queue_size=metrics.queue_size,
                processing_rate=metrics.processing_rate,
                utilization=metrics.utilization,
            )

        # Calculate recommended workers outside lock
        recommended = self._calculate_target_workers(snapshot)
        return recommended != snapshot.current_workers

    def adjust_workers(self, stage_name: str) -> bool:
        """Adjust worker count for a stage"""
        # Get stage and current metrics under lock
        with self.lock:
            if stage_name not in self.stages:
                return False

            stage = self.stages[stage_name]
            if stage_name not in self.worker_metrics:
                return False

            metrics = self.worker_metrics[stage_name]
            current_workers = metrics.current_workers

            # Create snapshot for calculation
            snapshot = WorkerMetrics(
                stage=metrics.stage,
                current_workers=metrics.current_workers,
                queue_size=metrics.queue_size,
                processing_rate=metrics.processing_rate,
                utilization=metrics.utilization,
            )

        # Calculate target outside lock
        target_workers = self._calculate_target_workers(snapshot)

        if target_workers == current_workers:
            return False

        try:
            # Use unified worker management interface
            if isinstance(stage, WorkerManageable):
                success = stage.adjust_workers(target_workers)
            else:
                # Fallback: log recommendation with deduplication
                self._log_worker_recommendation(stage_name, current_workers, target_workers)
                success = False

            if success:
                # Update metrics under lock
                with self.lock:
                    if stage_name in self.worker_metrics:
                        self.worker_metrics[stage_name].last_adjustment = time.monotonic()
                        self.worker_metrics[stage_name].target_workers = target_workers

                logger.info(f"Adjusted {stage_name} workers: {current_workers} -> {target_workers}")
                return True

        except Exception as e:
            logger.error(f"Failed to adjust workers for {stage_name}: {e}")

        return False

    def _log_worker_recommendation(self, stage_name: str, current_workers: int, target_workers: int) -> None:
        """Log worker recommendation with batching and deduplication"""
        # Skip logging if disabled in configuration
        if not self.log_recommendations:
            return

        current_time = time.monotonic()

        # Add to pending recommendations for batch processing
        self.pending_recommendations[stage_name] = (current_workers, target_workers)

        # Check if it's time to flush batch (every adjustment interval)
        if current_time - self.last_batch_log_time >= self.adjustment_interval:
            self._flush_recommendation_batch()
            self.last_batch_log_time = current_time

    def _flush_recommendation_batch(self) -> None:
        """Flush pending recommendations as a single batch log entry"""
        if not self.pending_recommendations:
            return

        # Group recommendations by type
        adjustments = []
        for stage_name, (current, target) in self.pending_recommendations.items():
            if current != target:
                adjustments.append(f"{stage_name}: {current} -> {target}")

        if adjustments:
            if len(adjustments) == 1:
                logger.info(f"Worker adjustment recommendation: {adjustments[0]}")
            else:
                logger.info(f"Worker adjustment recommendations: {', '.join(adjustments)}")

        # Clear pending recommendations
        self.pending_recommendations.clear()

    def get_worker_stats(self) -> WorkerStatus:
        """Get current worker management statistics with timeout protection"""
        try:
            # Try to acquire lock with timeout to prevent blocking
            if self.lock.acquire(timeout=0.5):  # 500ms timeout
                try:
                    # Quickly copy the data we need
                    worker_metrics_copy = dict(self.worker_metrics)
                finally:
                    self.lock.release()
            else:
                # Return last known stats if available, otherwise basic stats
                current_time = time.time()
                if (
                    self.last_known_stats is not None and current_time - self.last_stats_update_time < 30.0
                ):  # Use cache if < 30s old
                    # Return cached stats with updated timestamp and status
                    cached_stats = self.last_known_stats
                    return WorkerStatus(
                        timestamp=current_time,
                        stages=cached_stats.stages,
                        total_workers=cached_stats.total_workers,
                        total_target_workers=cached_stats.total_target_workers,
                        total_queue_size=cached_stats.total_queue_size,
                        status="lock_timeout_cached",
                    )
                else:
                    # Return basic stats if no recent cache available
                    return WorkerStatus(
                        timestamp=current_time,
                        stages={},
                        total_workers=0,
                        total_target_workers=0,
                        total_queue_size=0,
                        status="lock_timeout_no_cache",
                    )

            # Process the copied data outside the lock
            stages = {}
            total_workers = 0
            total_target_workers = 0
            total_queue_size = 0

            for stage_name, metrics in worker_metrics_copy.items():
                stages[stage_name] = StageWorkerStatus(
                    current_workers=metrics.current_workers,
                    target_workers=metrics.target_workers,
                    queue_size=metrics.queue_size,
                    utilization=metrics.utilization,
                    processing_rate=metrics.processing_rate,
                    last_adjustment=metrics.last_adjustment,
                )

                total_workers += metrics.current_workers
                total_target_workers += metrics.target_workers
                total_queue_size += metrics.queue_size

            # Create the stats object
            current_time = time.time()
            stats = WorkerStatus(
                timestamp=current_time,
                stages=stages,
                total_workers=total_workers,
                total_target_workers=total_target_workers,
                total_queue_size=total_queue_size,
            )

            # Update cache for future lock timeout scenarios
            self.last_known_stats = stats
            self.last_stats_update_time = current_time

            return stats
        except Exception as e:
            # Return error stats instead of raising
            return WorkerStatus(
                timestamp=time.time(),
                stages={},
                total_workers=0,
                total_target_workers=0,
                total_queue_size=0,
                status="error",
                error=str(e),
            )

    def _should_execute(self) -> bool:
        """Check if any stage needs worker adjustment"""
        return any(self.should_adjust_workers(stage_name) for stage_name in list(self.worker_metrics.keys()))

    def _handle_condition(self) -> None:
        """Handle worker adjustments for stages that need it"""
        for stage_name in list(self.worker_metrics.keys()):
            if self.should_adjust_workers(stage_name):
                self.adjust_workers(stage_name)

    def _apply_trend_analysis(self, stage_name: str, target_workers: int) -> int:
        """Apply trend analysis to worker count recommendation"""
        if stage_name not in self.metrics_history:
            return target_workers

        history = self.metrics_history[stage_name]
        if len(history) < 5:
            return target_workers

        # Analyze recent trend in queue size
        recent_queue_sizes = [entry["queue_size"] for entry in list(history)[-LB_RECENT_HISTORY_SIZE:]]

        # If queue is consistently growing, be more aggressive in scaling up
        if len(recent_queue_sizes) >= 3:
            if all(recent_queue_sizes[i] <= recent_queue_sizes[i + 1] for i in range(len(recent_queue_sizes) - 1)):
                # Queue is growing - scale up more aggressively
                target_workers = min(self.max_workers, target_workers + 1)
            elif all(recent_queue_sizes[i] >= recent_queue_sizes[i + 1] for i in range(len(recent_queue_sizes) - 1)):
                # Queue is shrinking - be more conservative about scaling down
                if target_workers < self.worker_metrics[stage_name].current_workers:
                    target_workers = self.worker_metrics[stage_name].current_workers

        return target_workers


def create_worker_manager(
    config: WorkerManagerConfig, shutdown_timeout: float = 5.0, scaling_strategy: Optional[ScalingStrategy] = None
) -> WorkerManager:
    """Factory function to create worker manager"""
    return WorkerManager(config, shutdown_timeout=shutdown_timeout, scaling_strategy=scaling_strategy)


if __name__ == "__main__":
    # Test worker manager

    config = WorkerManagerConfig(
        min_workers=DEFAULT_MIN_WORKERS,
        max_workers=DEFAULT_MAX_WORKERS,
        target_queue_size=DEFAULT_TARGET_QUEUE_SIZE,
        adjustment_interval=DEFAULT_ADJUSTMENT_INTERVAL,
        scale_up_threshold=DEFAULT_SCALE_UP_THRESHOLD,
        scale_down_threshold=DEFAULT_SCALE_DOWN_THRESHOLD,
    )

    manager = create_worker_manager(config)

    # Mock stage class
    class MockStage:
        def __init__(self, name):
            self.name = name
            self.worker_count = 2

        def adjust_workers(self, count):
            logger.info(f"Adjusting {self.name} workers: {self.worker_count} -> {count}")
            self.worker_count = count
            return True

    # Register mock stages
    for stage in PipelineStage:
        manager.register_stage(stage.value, MockStage(stage.value))

    manager.start()

    try:
        # Simulate varying load
        for i in range(20):
            for stage in PipelineStage:
                # Simulate different load patterns
                if stage == PipelineStage.SEARCH:
                    queue_size = random.randint(0, 50)
                elif stage == PipelineStage.GATHER:
                    queue_size = random.randint(10, 100)
                elif stage == PipelineStage.CHECK:
                    queue_size = random.randint(50, 200)
                else:  # models
                    queue_size = random.randint(0, 20)

                # Create metrics update using WorkerMetrics structure
                metrics_update = WorkerMetrics(
                    stage=stage.value,
                    queue_size=queue_size,
                    current_workers=manager.worker_metrics[stage.value].current_workers,
                    processing_rate=random.uniform(0.5, 5.0),
                    avg_processing_time=random.uniform(0.1, 2.0),
                )

                manager.update_metrics(stage.value, metrics_update)

            # Log stats
            stats = manager.get_worker_stats()
            logger.info(f"Iteration {i+1}:")
            for stage_name, stage_stats in stats.stages.items():
                logger.info(
                    f"  {stage_name}: workers={stage_stats.current_workers}->{stage_stats.target_workers}, "
                    f"queue={stage_stats.queue_size}, util={stage_stats.utilization:.2f}"
                )

            time.sleep(2)

    except KeyboardInterrupt:
        logger.info("Stopping worker manager test...")

    finally:
        manager.stop()
        logger.info("Worker manager test completed!")
