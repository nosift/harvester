#!/usr/bin/env python3

"""
Monitoring system for multi-provider pipeline processing.
Provides real-time statistics, alerts, and performance monitoring.
"""

import random
import threading
import time
from collections import OrderedDict, deque
from typing import Any, Callable, Dict, List, Optional, TypedDict, Union

from config.schemas import MonitoringConfig
from constant.monitoring import FIELD_MAPPINGS, MONITORING_CONFIG, MONITORING_THRESHOLDS
from constant.system import ALERT_COOLDOWN_SECONDS
from state.models import (
    Alert,
    AlertLevel,
    AlertType,
    DisplayMode,
    MonitoringSnapshot,
    MonitoringSummary,
    PipelineStatus,
    ProviderStatus,
    StatusContext,
)
from state.status import StatusManager
from tools.logger import get_logger

logger = get_logger("manager")


class ProviderStatsUpdate(TypedDict, total=False):
    """Typed structure for provider statistics updates"""

    # Key metrics
    valid_keys: int
    invalid_keys: int
    no_quota_keys: int
    wait_check_keys: int
    material_keys: int

    # Resource metrics
    total_links: int
    total_models: int

    # Task metrics
    total_tasks: int
    completed_tasks: int
    failed_tasks: int


class PipelineStatsUpdate(TypedDict, total=False):
    """Typed structure for pipeline statistics updates"""

    # Queue metrics
    search_queue: int
    gather_queue: int
    check_queue: int
    inspect_queue: int

    # Worker metrics
    active_workers: int
    total_workers: int

    # Performance metrics
    processing_rate: float
    queue_size: int


# Union type for stats data that can be objects or dicts
StatsDataSource = Union[ProviderStatsUpdate, PipelineStatsUpdate, Any]


class AlertManager:
    """Manages alerts and notifications for pipeline issues"""

    def __init__(self, config: MonitoringConfig):
        self.alert_handlers: List[Callable] = []
        self.alert_history: deque = deque(maxlen=MONITORING_THRESHOLDS.get("max_alert_history", 100))
        # TTL index for efficient deduplication: alert_key -> timestamp
        self.alert_ttl_index: OrderedDict[str, float] = OrderedDict()
        self.lock = threading.Lock()

        # Alert thresholds with fallback to constants
        self.error_threshold = getattr(config, "error_threshold", MONITORING_THRESHOLDS["error_rate"])
        self.queue_threshold = getattr(config, "queue_threshold", MONITORING_THRESHOLDS["queue_size"])
        self.memory_threshold = getattr(config, "memory_threshold", MONITORING_THRESHOLDS["memory_usage"])
        self.min_sample_size = MONITORING_THRESHOLDS["min_sample_size"]

        logger.info("Initialized alert manager")

    def add_handler(self, handler: Callable[[Alert], None]) -> None:
        """Add alert handler function"""
        self.alert_handlers.append(handler)

    def check_alerts(self, provider_stats: Dict[str, ProviderStatus], pipeline_status: PipelineStatus) -> None:
        """Check for alert conditions and trigger notifications"""

        # Check provider error rates
        for provider_name, stats in provider_stats.items():
            total_calls = stats.calls
            if total_calls > self.min_sample_size:
                error_rate = stats.errors / total_calls
                if error_rate > self.error_threshold:
                    alert = Alert(
                        type=AlertType.PERFORMANCE,
                        level=AlertLevel.WARNING,
                        message=f"Provider {provider_name} has high error rate: {error_rate:.2%}",
                        timestamp=time.time(),
                        source=provider_name,
                        context={"provider": provider_name, "error_rate": str(error_rate)},
                    )
                    self._trigger_alert(alert)

        # Check queue sizes using PipelineStatus
        total_queue_size = pipeline_status.queue_size()

        if total_queue_size > self.queue_threshold:
            alert = Alert(
                type=AlertType.SYSTEM,
                level=AlertLevel.WARNING,
                message=f"Total queue size is high: {total_queue_size}",
                timestamp=time.time(),
                source="queue_monitor",
                context={"queue_size": str(total_queue_size)},
            )
            self._trigger_alert(alert)

    def _trigger_alert(self, alert: Alert) -> None:
        """Trigger an alert with efficient TTL-based deduplication"""
        with self.lock:
            # Create alert key for deduplication
            alert_key = f"{alert.type.value}:{alert.source}"
            current_time = time.time()

            # Clean expired entries from TTL index
            self._cleanup_expired_alerts(current_time)

            # Check if we've already sent this alert recently
            if alert_key in self.alert_ttl_index:
                last_sent = self.alert_ttl_index[alert_key]
                if current_time - last_sent < ALERT_COOLDOWN_SECONDS:
                    return  # Skip duplicate alert

            # Record this alert in TTL index
            self.alert_ttl_index[alert_key] = current_time
            self.alert_history.append(alert)

            # Send to all handlers
            for handler in self.alert_handlers:
                try:
                    handler(alert)
                except Exception as e:
                    logger.error(f"Alert handler error: {e}")

    def _cleanup_expired_alerts(self, current_time: float) -> None:
        """Remove expired entries from TTL index"""
        expired_keys = [
            key for key, timestamp in self.alert_ttl_index.items() if current_time - timestamp >= ALERT_COOLDOWN_SECONDS
        ]
        for key in expired_keys:
            del self.alert_ttl_index[key]


class MultiProviderMonitoring:
    """Main monitoring system for multi-provider pipeline"""

    def __init__(self, config: MonitoringConfig):
        self.provider_stats: Dict[str, ProviderStatus] = {}
        self.pipeline_stats = PipelineStatus()
        self.alert_manager = AlertManager(config)

        # Monitoring thread
        self.monitoring_thread: Optional[threading.Thread] = None
        self.running = False
        self.update_interval = config.update_interval

        # Statistics history for trend analysis
        self.stats_history: deque = deque(maxlen=MONITORING_THRESHOLDS.get("max_stats_history", 100))
        self.lock = threading.Lock()

        # Add default console alert handler
        self.alert_manager.add_handler(self._console_alert_handler)

        # External completion tracking
        self._externally_finished = False

        logger.info("Initialized multi-provider monitoring")

    def start(self) -> None:
        """Start monitoring thread"""
        if self.running:
            return

        self.running = True
        self.pipeline_stats.is_running = True
        self.pipeline_stats.start = time.monotonic()

        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, name="monitoring-thread", daemon=True)
        self.monitoring_thread.start()

        logger.info("Started monitoring system")

    def stop(self) -> None:
        """Stop monitoring thread"""
        self.running = False
        self.pipeline_stats.is_running = False

        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=2.0)
            if self.monitoring_thread.is_alive():
                logger.warning("Monitoring thread did not stop gracefully")

        logger.info("Stopped monitoring system")

    def _on_task_completion(self) -> None:
        """Handle task manager completion event"""
        self._externally_finished = True
        logger.info("MultiProviderMonitoring marked as finished due to task completion")

    def is_finished(self) -> bool:
        """Check if monitoring system is finished"""
        return not self.running or self._externally_finished

    def update_provider_stats(
        self, provider_name: str, stats_data: Union[ProviderStatsUpdate, StatsDataSource]
    ) -> None:
        """Update statistics for a specific provider supporting both objects and dicts"""
        with self.lock:
            if provider_name not in self.provider_stats:
                self.provider_stats[provider_name] = ProviderStatus(name=provider_name)

            stats = self.provider_stats[provider_name]

            # Use configuration-driven field mapping with dict/object fallback
            mappings = FIELD_MAPPINGS["provider_stats_mappings"]
            for source_field, (target_path, target_field) in mappings.items():
                value = self._get_field_value(stats_data, source_field)
                if value is not None:
                    try:
                        if target_field is None:
                            setattr(stats, target_path, value)
                        else:
                            # Nested assignment (e.g., stats.keys.valid)
                            target_obj = getattr(stats, target_path)
                            setattr(target_obj, target_field, value)
                    except (AttributeError, TypeError) as e:
                        logger.debug(f"Failed to set provider stat {target_path}.{target_field}: {e}")

    def _get_field_value(self, source: Any, field_name: str) -> Any:
        """Get field value from source, supporting both objects and dicts"""
        if hasattr(source, field_name):
            return getattr(source, field_name)
        elif isinstance(source, dict) and field_name in source:
            return source[field_name]
        else:
            return None

    def update_pipeline_stats(self, stats_data: Union[PipelineStatsUpdate, StatsDataSource]) -> None:
        """Update overall pipeline statistics supporting both objects and dicts"""
        with self.lock:
            mappings = FIELD_MAPPINGS["pipeline_stats_mappings"]
            for source_field, (target_field, _) in mappings.items():
                value = self._get_field_value(stats_data, source_field)
                if value is not None:
                    try:
                        setattr(self.pipeline_stats, target_field, value)
                    except (AttributeError, TypeError) as e:
                        logger.debug(f"Failed to set pipeline stat {target_field}: {e}")

    def runtime(self) -> float:
        """Get current runtime in seconds using monotonic clock"""
        return time.monotonic() - self.pipeline_stats.start

    def current_stats(self) -> MonitoringSnapshot:
        """Get current statistics snapshot"""
        with self.lock:
            return MonitoringSnapshot.create_from_monitoring(self)

    def summary(self) -> "MonitoringSummary":
        """Get summarized statistics as strong-typed object"""
        with self.lock:
            total_tasks = sum(stats.calls for stats in self.provider_stats.values())
            total_completed = sum(stats.calls - stats.errors for stats in self.provider_stats.values())
            total_failed = sum(stats.errors for stats in self.provider_stats.values())
            total_valid_keys = sum(stats.keys.valid for stats in self.provider_stats.values())
            total_links = sum(stats.resources.links for stats in self.provider_stats.values())

            runtime = time.time() - self.pipeline_stats.start
            return MonitoringSummary(
                tasks=total_tasks,
                completed=total_completed,
                failed=total_failed,
                success_rate=(total_completed / max(total_tasks, 1)),
                keys=total_valid_keys,
                links=total_links,
                runtime=runtime,
                throughput=total_completed / max(runtime, 1),
            )

    def _monitoring_loop(self) -> None:
        """Main monitoring loop"""
        while self.running:
            try:
                # Collect current stats
                current_stats = self.current_stats()

                # Store in history
                with self.lock:
                    self.stats_history.append(current_stats)

                # Check for alerts
                self.alert_manager.check_alerts(self.provider_stats, self.pipeline_stats)

                # Sleep until next update
                time.sleep(self.update_interval)

            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                time.sleep(1.0)

    def _console_alert_handler(self, alert: Alert) -> None:
        """Default console alert handler"""
        timestamp = time.strftime("%H:%M:%S")
        logger.warning(f"[{timestamp}] ALERT ({alert.type.value}): {alert.message}")


def create_monitoring_system(config: MonitoringConfig) -> MultiProviderMonitoring:
    """Factory function to create monitoring system"""
    return MultiProviderMonitoring(config)


if __name__ == "__main__":
    # Test monitoring system

    config = MonitoringConfig(
        update_interval=MONITORING_CONFIG["update_interval"],
        error_threshold=MONITORING_THRESHOLDS["error_rate"],
        queue_threshold=MONITORING_THRESHOLDS["queue_size"],
        memory_threshold=MONITORING_THRESHOLDS["memory_usage"],
    )

    monitoring = create_monitoring_system(config)
    monitoring.start()

    try:
        # Simulate some statistics updates
        for i in range(10):
            # Update provider stats
            monitoring.update_provider_stats(
                "test_provider",
                {
                    "total_tasks": i * 10,
                    "completed_tasks": i * 9,
                    "failed_tasks": i,
                    "valid_keys": i * 2,
                    "total_links": i * 5,
                },
            )

            # Update pipeline stats
            monitoring.update_pipeline_stats(
                {
                    "search_queue": random.randint(0, 50),
                    "gather_queue": random.randint(0, 100),
                    "check_queue": random.randint(0, 200),
                    "inspect_queue": random.randint(0, 20),
                    "active_workers": random.randint(5, 15),
                    "total_workers": 16,
                }
            )

            try:
                status_manager = StatusManager(monitoring=monitoring)
                status_manager.show_status(StatusContext.MONITORING, DisplayMode.DETAILED)
            except Exception as e:
                logger.debug(f"Error showing status: {e}")

            time.sleep(3)

    except KeyboardInterrupt:
        logger.info("Stopping monitoring test...")

    finally:
        monitoring.stop()
        logger.info("Monitoring test completed!")
