#!/usr/bin/env python3

"""
Core Status Models for Monitor Package

This module contains all unified data models that replace the scattered status models
throughout the system. It provides strong typing and eliminates dictionary-based data passing.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, unique
from types import MappingProxyType
from typing import Any, Dict, List, Optional

from core.enums import SystemState
from core.metrics import BaseMetrics, PipelineStatus, TaskMetrics


@unique
class QueueStatus(Enum):
    """Queue status enumeration for type safety"""

    ACTIVE = "active"
    EMPTY = "empty"
    ERROR = "error"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass
class KeyMetrics(BaseMetrics):
    """Key-related metrics"""

    valid: int = 0
    invalid: int = 0
    no_quota: int = 0
    wait_check: int = 0
    material: int = 0

    @property
    def total(self) -> int:
        """Override total calculation"""
        return self.valid + self.invalid + self.no_quota + self.wait_check

    @property
    def success_rate(self) -> float:
        """Key validation success rate"""
        return self.valid / self.total if self.total > 0 else 0.0

    @property
    def empty(self) -> bool:
        """Check if statistics are empty"""
        return self.total == 0


@dataclass
class ResourceMetrics(BaseMetrics):
    """Resource-related metrics"""

    links: int = 0
    models: int = 0
    memory: float = 0.0
    cpu: float = 0.0
    disk: float = 0.0

    @property
    def total(self) -> int:
        """Total resources"""
        return self.links + self.models

    @property
    def empty(self) -> bool:
        """Check if statistics are empty"""
        return self.total == 0


@dataclass
class PersistenceMetrics(BaseMetrics):
    """Persistence metrics"""

    keys: KeyMetrics = field(default_factory=KeyMetrics)
    resources: ResourceMetrics = field(default_factory=ResourceMetrics)

    # Persistence-specific fields
    start: float = field(default_factory=time.time)
    last_save: float = field(default_factory=time.time)
    last_snapshot: float = field(default_factory=time.time)

    # Enhanced metrics
    snapshot_count: int = 0
    bad_line_count: int = 0
    repair_count: int = 0
    total_append_time: float = 0.0
    total_snapshot_time: float = 0.0
    append_operations: int = 0
    snapshot_operations: int = 0

    @property
    def total_keys(self) -> int:
        """Total keys processed"""
        return self.keys.total

    @property
    def success_rate(self) -> float:
        """Key validation success rate"""
        return self.keys.success_rate

    @property
    def avg_append_time(self) -> float:
        """Average append operation time in seconds"""
        return self.total_append_time / max(1, self.append_operations)

    @property
    def avg_snapshot_time(self) -> float:
        """Average snapshot operation time in seconds"""
        return self.total_snapshot_time / max(1, self.snapshot_operations)


@dataclass
class WorkerMetrics(BaseMetrics):
    """Worker thread metrics for load balancer and performance monitoring

    This class tracks performance metrics for individual worker threads
    in pipeline stages, enabling dynamic load balancing decisions and
    system status monitoring.
    """

    stage_name: str = ""
    current_workers: int = 0
    target_workers: int = 0
    queue_size: int = 0
    processing_rate: float = 0.0
    avg_processing_time: float = 0.0
    success_rate: float = 1.0
    error_count: int = 0
    utilization: float = 0.0
    last_adjustment: float = 0.0
    last_updated: float = field(default_factory=time.monotonic)  # Use monotonic for intervals

    # Additional fields for system status
    active: int = 0
    total: int = 0
    idle: int = 0
    busy: int = 0

    def get_utilization(self) -> float:
        """Worker utilization rate"""
        return self.busy / self.total if self.total > 0 else self.utilization

    def update_metrics(
        self,
        queue_size: int,
        processing_rate: float,
        avg_time: float,
        success_rate: float = 1.0,
        error_count: int = 0,
    ) -> None:
        """Update worker metrics with new values"""
        self.queue_size = queue_size
        self.processing_rate = processing_rate
        self.avg_processing_time = avg_time
        self.success_rate = success_rate
        self.error_count = error_count
        self.last_updated = time.monotonic()

    def calculate_load_score(self) -> float:
        """Calculate load score for load balancing decisions"""
        if self.current_workers == 0:
            return float("inf")

        queue_factor = self.queue_size / max(self.current_workers, 1)
        time_factor = self.avg_processing_time
        error_factor = 1.0 - self.success_rate

        return queue_factor * (1.0 + time_factor + error_factor)


@unique
class DisplayMode(Enum):
    """Display modes for status output"""

    COMPACT = "compact"  # Compact single-line format
    STANDARD = "standard"  # Standard multi-line format
    DETAILED = "detailed"  # Detailed with all information
    MONITORING = "monitoring"  # Monitoring-specific format with performance data
    SUMMARY = "summary"  # Brief summary format
    APPLICATION = "application"  # Application-level overview


@unique
class StatusContext(Enum):
    """Status display context"""

    SYSTEM = "system"
    TASK_MANAGER = "task"
    MONITORING = "monitoring"
    APPLICATION = "application"
    MAIN = "main"


@unique
class AlertType(Enum):
    """Alert types"""

    SYSTEM = "system"
    PROVIDER = "provider"
    PIPELINE = "pipeline"
    PERFORMANCE = "performance"
    RESOURCE = "resource"


@unique
class AlertLevel(Enum):
    """Alert severity levels"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@unique
class ProviderState(Enum):
    """Provider operational state"""

    UNKNOWN = "unknown"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class PerformanceMetrics(BaseMetrics):
    """Performance metrics"""

    throughput: float = 0.0
    tasks_per_second: float = 0.0
    success_rate: float = 0.0
    error_rate: float = 0.0
    avg_response_time: float = 0.0

    def calculate_derived_metrics(self, tasks: TaskMetrics, runtime: float) -> None:
        """Calculate derived performance metrics"""
        if runtime > 0:
            self.throughput = tasks.completed / runtime
            self.tasks_per_second = self.throughput

        self.success_rate = tasks.success_rate
        self.error_rate = tasks.error_rate


@dataclass
class QueueMetrics(BaseMetrics):
    """Queue metrics for pipeline stages"""

    search: int = 0
    gather: int = 0
    check: int = 0
    inspect: int = 0

    @property
    def total_queued(self) -> int:
        """Total items in all queues"""
        return self.search + self.gather + self.check + self.inspect


@dataclass
class QueueStateMetrics(BaseMetrics):
    """Queue state metrics for individual stage monitoring and persistence"""

    stage: str = ""
    task_count: int = 0
    saved_at: datetime = field(default_factory=datetime.now)
    age_hours: float = 0.0
    file_size: int = 0
    status: QueueStatus = QueueStatus.ACTIVE
    last_operation: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def is_healthy(self) -> bool:
        """Check if queue is in healthy state"""
        return self.status in (QueueStatus.ACTIVE, QueueStatus.EMPTY)

    @property
    def is_stale(self) -> bool:
        """Check if queue state is stale (older than 24 hours)"""
        return self.age_hours > 24.0

    def calculate_age(self) -> None:
        """Calculate age in hours from saved_at timestamp"""
        now = datetime.now()
        delta = now - self.saved_at
        self.age_hours = delta.total_seconds() / 3600.0


@dataclass
class MonitoringSummary:
    """Monitoring summary"""

    tasks: int = 0
    completed: int = 0
    failed: int = 0
    throughput: float = 0.0
    success_rate: float = 0.0
    runtime: float = 0.0
    links: int = 0
    keys: int = 0


@dataclass
class StatsTotals:
    """Statistics totals"""

    valid: int = 0
    invalid: int = 0
    quota: int = 0
    waiting: int = 0
    material: int = 0
    links: int = 0
    models: int = 0


@dataclass
class MonitoringSnapshot(BaseMetrics):
    """Monitoring snapshot"""

    runtime: float = 0.0
    pipeline: Optional["PipelineStatus"] = None
    providers: Dict[str, "ProviderStatus"] = field(default_factory=dict)
    summary: PerformanceMetrics = field(default_factory=PerformanceMetrics)

    @classmethod
    def create_from_monitoring(cls, monitoring) -> "MonitoringSnapshot":
        """Create snapshot from monitoring system"""
        summary = PerformanceMetrics()
        total_tasks = sum(p.calls for p in monitoring.provider_stats.values())
        total_errors = sum(p.errors for p in monitoring.provider_stats.values())
        runtime = monitoring.runtime() if hasattr(monitoring, "runtime") else 0.0

        summary.tasks_per_second = total_tasks / max(runtime, 1)
        summary.error_rate = total_errors / max(total_tasks, 1)
        summary.success_rate = 1.0 - summary.error_rate

        # Use MappingProxyType for zero-copy read-only access to provider stats
        provider_stats = getattr(monitoring, "provider_stats", {})
        providers_readonly = MappingProxyType(provider_stats) if provider_stats else MappingProxyType({})

        return cls(
            runtime=runtime,
            pipeline=getattr(monitoring, "pipeline_stats", None),
            providers=providers_readonly,
            summary=summary,
        )


@dataclass
class PipelineUpdate(BaseMetrics):
    """Pipeline update data"""

    search_queue: int = 0
    gather_queue: int = 0
    check_queue: int = 0
    inspect_queue: int = 0
    active_workers: int = 0
    total_workers: int = 0
    is_finished: bool = False

    @classmethod
    def from_metrics(
        cls, queue_metrics: QueueMetrics, worker_metrics: WorkerMetrics, is_finished: bool
    ) -> "PipelineUpdate":
        """Create update from metrics"""
        return cls(
            search_queue=queue_metrics.search,
            gather_queue=queue_metrics.gather,
            check_queue=queue_metrics.check,
            inspect_queue=queue_metrics.inspect,
            active_workers=worker_metrics.current_workers,
            total_workers=worker_metrics.total,
            is_finished=is_finished,
        )


# Component status models
@dataclass
class ProviderStatus:
    """Provider status information"""

    name: str
    state: ProviderState = ProviderState.UNKNOWN
    enabled: bool = True

    # Stage configuration
    searchable: bool = False
    gatherable: bool = False
    checkable: bool = False
    inspectable: bool = False

    # Metrics
    keys: KeyMetrics = field(default_factory=KeyMetrics)
    resources: ResourceMetrics = field(default_factory=ResourceMetrics)

    # API metrics
    calls: int = 0
    errors: int = 0
    limits: int = 0

    def abbreviations(self) -> str:
        """Get standardized stage abbreviations"""
        abbrev = []
        if self.searchable:
            abbrev.append("S")
        if self.gatherable:
            abbrev.append("G")
        if self.checkable:
            abbrev.append("V")
        if self.inspectable:
            abbrev.append("I")

        return "/".join(abbrev)

    @property
    def success_rate(self) -> float:
        """API call success rate"""
        if self.calls > 0:
            return (self.calls - self.errors) / self.calls
        return 0.0


@dataclass
class Alert:
    """Strong-typed alert"""

    type: AlertType
    level: AlertLevel
    message: str
    timestamp: float
    source: str = ""
    context: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def create_system_alert(cls, level: AlertLevel, message: str, source: str = "system") -> "Alert":
        """Create a system alert"""
        return cls(type=AlertType.SYSTEM, level=level, message=message, timestamp=time.time(), source=source)

    @classmethod
    def create_performance_alert(cls, level: AlertLevel, message: str, metric_name: str, value: float) -> "Alert":
        """Create a performance alert"""
        return cls(
            type=AlertType.PERFORMANCE,
            level=level,
            message=message,
            timestamp=time.time(),
            source="performance_monitor",
            context={"metric": metric_name, "value": str(value)},
        )

    def is_critical(self) -> bool:
        """Check if alert is critical"""
        return self.level == AlertLevel.CRITICAL

    def age_seconds(self) -> float:
        """Get alert age in seconds"""
        return time.time() - self.timestamp


# Main unified status model
@dataclass
class SystemStatus:
    """
    Unified system status data model
    """

    # Basic information
    timestamp: float = field(default_factory=time.time)
    runtime: float = 0.0
    state: SystemState = SystemState.UNKNOWN

    # Core metrics
    tasks: TaskMetrics = field(default_factory=TaskMetrics)
    keys: KeyMetrics = field(default_factory=KeyMetrics)
    resources: ResourceMetrics = field(default_factory=ResourceMetrics)
    performance: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    workers: WorkerMetrics = field(default_factory=WorkerMetrics)
    queues: QueueMetrics = field(default_factory=QueueMetrics)

    # Component status
    providers: Dict[str, ProviderStatus] = field(default_factory=dict)
    pipeline: PipelineStatus = field(default_factory=PipelineStatus)

    # Alerts and events
    alerts: List[Alert] = field(default_factory=list)

    # Application state
    monitored: bool = False
    balanced: bool = False

    def abbreviations(self, provider_name: str) -> str:
        """Get stage abbreviations for a provider"""
        if provider_name not in self.providers:
            return ""
        return self.providers[provider_name].abbreviations()

    def add_provider(self, provider_status: ProviderStatus) -> None:
        """Add a provider to the system status"""
        self.providers[provider_status.name] = provider_status

    def active_providers(self) -> List[ProviderStatus]:
        """Get list of active providers"""
        return [p for p in self.providers.values() if p.state == ProviderState.ACTIVE]

    def critical_alerts(self) -> List[Alert]:
        """Get critical alerts"""
        return [alert for alert in self.alerts if alert.is_critical()]

    def calculate_overall_metrics(self) -> None:
        """Calculate overall system metrics from component metrics"""
        # Aggregate provider metrics
        total_keys = KeyMetrics()
        total_resources = ResourceMetrics()

        for provider in self.providers.values():
            total_keys.valid += provider.keys.valid
            total_keys.invalid += provider.keys.invalid
            total_keys.no_quota += provider.keys.no_quota
            total_keys.wait_check += provider.keys.wait_check
            total_keys.material += provider.keys.material

            total_resources.links += provider.resources.links
            total_resources.models += provider.resources.models

        self.keys = total_keys
        self.resources = total_resources

        # Calculate performance metrics
        self.performance.calculate_derived_metrics(self.tasks, self.runtime)

    def has_pipeline_data(self) -> bool:
        """Check if pipeline data is available"""
        return bool(self.pipeline.stages)

    def has_provider_data(self) -> bool:
        """Check if provider data is available"""
        return bool(self.providers)

    def has_alerts(self) -> bool:
        """Check if there are any alerts"""
        return bool(self.alerts)

    def healthy(self) -> bool:
        """Check if system is in healthy state"""
        return (
            self.state == SystemState.RUNNING
            and not self.critical_alerts()
            and self.performance.error_rate < 0.1  # Less than 10% error rate
        )


@dataclass
class ApplicationStatus(SystemStatus):
    """Application-specific status extending SystemStatus"""

    shutdown_requested: bool = False
    task_manager_status: Optional[Any] = None
    monitoring_status: Optional[Any] = None
    worker_manager_status: Optional[Any] = None
