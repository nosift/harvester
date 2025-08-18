#!/usr/bin/env python3

"""
Monitoring system for multi-provider pipeline processing.
Pure data aggregation and caching without scheduling dependencies.
"""

import threading
import time
from collections import OrderedDict, deque
from types import MappingProxyType
from typing import Callable, Dict, List, Optional

from config.schemas import MonitoringConfig
from constant.monitoring import MONITORING_THRESHOLDS, AlertConfig
from constant.system import ALERT_COOLDOWN_SECONDS
from core.enums import AlertKeyType
from tools.logger import get_logger

from .enums import AlertLevel
from .models import (
    Alert,
    IMonitorProvider,
    MonitoringSnapshot,
    MonitoringSummary,
    PerformanceMetrics,
    PipelineStatus,
    ProviderStatus,
    SystemStatus,
)

logger = get_logger("state")


class AlertManager:
    """Manages alerts and notifications for pipeline issues"""

    def __init__(self, config: MonitoringConfig):
        self.alert_handlers: List[Callable[[Alert], None]] = []
        self.alert_history: deque = deque(
            maxlen=MONITORING_THRESHOLDS.get("max_alert_history", AlertConfig.DEFAULT_HISTORY_SIZE)
        )
        # TTL index for efficient deduplication: alert_key -> timestamp
        self.alert_ttl_index: OrderedDict[str, float] = OrderedDict()
        self.lock = threading.Lock()

        # Track last cleanup time for periodic maintenance
        self.last_cleanup_time = time.time()

        # Alert thresholds - direct access to config attributes
        self.error_threshold = config.error_threshold
        self.queue_threshold = config.queue_threshold
        self.memory_threshold = config.memory_threshold
        self.min_sample_size = MONITORING_THRESHOLDS["min_sample_size"]

        logger.info("Alert manager initialized")

    def add_handler(self, handler: Callable[[Alert], None]) -> None:
        """Add alert handler function"""
        self.alert_handlers.append(handler)

    def check_alerts(self, statuses: Dict[str, ProviderStatus], pipeline_status: PipelineStatus) -> None:
        """Check for alert conditions and trigger notifications"""

        # Check provider error rates
        for name, status in statuses.items():
            total_calls = status.calls
            if total_calls > self.min_sample_size:
                error_rate = status.errors / total_calls
                if error_rate > self.error_threshold:
                    alert = Alert(
                        type=AlertKeyType.PERFORMANCE,
                        level=AlertLevel.WARNING,
                        message=f"Provider {name} has high error rate: {error_rate:.2%}",
                        timestamp=time.time(),
                        source=name,
                        context={"provider": name, "error_rate": str(error_rate)},
                    )
                    self._trigger_alert(alert)

        # Check queue sizes using PipelineStatus
        total_queue_size = pipeline_status.queue_size()

        if total_queue_size > self.queue_threshold:
            alert = Alert(
                type=AlertKeyType.SYSTEM,
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

    def cleanup(self) -> None:
        """Perform cleanup of expired alerts"""
        current_time = time.time()
        with self.lock:
            self._cleanup_expired_alerts(current_time)
            self.last_cleanup_time = current_time

            # Log cleanup stats if we cleaned anything
            if len(self.alert_ttl_index) > 0:
                logger.debug(f"Alert TTL cleanup: {len(self.alert_ttl_index)} active alert keys remaining")


class ProviderMonitoring(IMonitorProvider):
    """Pure monitoring data aggregator without scheduling dependencies"""

    def __init__(self, config: MonitoringConfig):
        self.provider_status: Dict[str, ProviderStatus] = {}
        self.pipeline_status = PipelineStatus()
        self.alert_manager = AlertManager(config)

        # Statistics history for trend analysis
        self.stats_history: deque = deque(
            maxlen=MONITORING_THRESHOLDS.get("max_stats_history", AlertConfig.DEFAULT_HISTORY_SIZE)
        )
        self.lock = threading.Lock()

        # Add default console alert handler
        self.alert_manager.add_handler(self._console_alert_handler)

        logger.info("Provider monitoring initialized as pure data aggregator")

    def ingest(self, system_stats: SystemStatus) -> None:
        """Ingest task statistics for monitoring aggregation"""
        with self.lock:
            # Extract provider statistics from task stats
            if system_stats.providers:
                for name, status in system_stats.providers.items():
                    self._update_provider(name, status)

            # Extract pipeline statistics from task stats
            if system_stats.pipeline:
                self._update_pipeline(system_stats.pipeline)

            # Update runtime
            self.pipeline_status.start = time.monotonic() - system_stats.runtime

            # Check alerts after ingestion
            self.alert_manager.check_alerts(self.provider_status, self.pipeline_status)

    def _update_provider(self, name: str, status: ProviderStatus) -> None:
        """Update provider stats from task manager data"""
        if name not in self.provider_status:
            self.provider_status[name] = ProviderStatus(name=name)

        # Copy relevant fields from task manager provider status
        target = self.provider_status[name]
        target.state = status.state
        target.enabled = status.enabled
        target.resource = status.resource
        target.calls = status.calls
        target.errors = status.errors

        # Copy stage configuration flags
        target.searchable = status.searchable
        target.gatherable = status.gatherable
        target.checkable = status.checkable
        target.inspectable = status.inspectable

    def _update_pipeline(self, pipeline_status: PipelineStatus) -> None:
        """Update pipeline stats from task manager data"""
        # Copy the entire pipeline status instead of just queue sizes
        if pipeline_status:
            # Update the entire pipeline_stats object
            self.pipeline_status = pipeline_status

    def runtime(self) -> float:
        """Get current runtime in seconds using monotonic clock"""
        return time.monotonic() - self.pipeline_status.start

    def get_provider_status(self) -> Dict[str, ProviderStatus]:
        """Get provider statistics"""
        with self.lock:
            return self.provider_status.copy()

    def get_pipeline_status(self) -> Optional[PipelineStatus]:
        """Get pipeline statistics"""
        with self.lock:
            return self.pipeline_status

    def snapshot(self) -> MonitoringSnapshot:
        """Get current statistics snapshot"""
        with self.lock:
            # Create snapshot directly with collected data to avoid deadlock
            summary = PerformanceMetrics()
            runtime = self.runtime()
            provider_status = self.provider_status.copy()
            pipeline_status = self.pipeline_status

            # Calculate summary metrics from provider stats
            tasks = sum(p.calls for p in provider_status.values())
            errors = sum(p.errors for p in provider_status.values())

            summary.tasks_per_second = tasks / max(runtime, 1)
            summary.error_rate = errors / max(tasks, 1)
            summary.success_rate = 1.0 - summary.error_rate
            providers_readonly = MappingProxyType(provider_status)

            return MonitoringSnapshot(
                runtime=runtime,
                pipeline=pipeline_status,
                providers=providers_readonly,
                summary=summary,
            )

    def summary(self) -> MonitoringSummary:
        """Get summarized statistics as strong-typed object"""
        with self.lock:
            tasks = sum(stats.calls for stats in self.provider_status.values())
            completed = sum(stats.calls - stats.errors for stats in self.provider_status.values())
            failed = sum(stats.errors for stats in self.provider_status.values())
            valid = sum(stats.resource.valid for stats in self.provider_status.values())
            links = sum(stats.resource.links for stats in self.provider_status.values())

            runtime = self.runtime()
            summary = MonitoringSummary(
                tasks=tasks,
                completed=completed,
                failed=failed,
                runtime=runtime,
                links=links,
                keys=valid,
            )
            # Update performance metrics based on task statistics
            summary.update_performance_metrics()
            return summary

    def _console_alert_handler(self, alert: Alert) -> None:
        """Default console alert handler"""
        timestamp = time.strftime("%H:%M:%S")
        logger.warning(f"[{timestamp}] ALERT ({alert.type.value}): {alert.message}")


def create_monitoring(config: MonitoringConfig) -> ProviderMonitoring:
    """Factory function to create monitoring system"""
    return ProviderMonitoring(config)
