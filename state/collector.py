#!/usr/bin/env python3

"""
Status Data Collector for Monitor Package

This module provides a unified, configuration-driven data collection system for monitoring
various components of the application pipeline. It features:

- Type-safe configuration management with validation
- LRU cache with size limits and statistics
- Unified error handling with structured alerts
- Modular data collection from multiple sources
- Strong typing throughout for better maintainability

Key Components:
    CollectorConfig: Configuration dataclass with validation
    CacheStats: Cache performance monitoring
    StatusCollector: Main collector class with pluggable data sources

Usage:
    collector = StatusCollector(task_manager, monitoring, application)
    status = collector.status(refresh=False)
    cache_stats = collector.get_cache_stats()
"""

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from constant.monitoring import (
    COLLECTOR_ALERT_SOURCES,
    COLLECTOR_CACHE_KEYS,
    COLLECTOR_CACHE_TTL,
    COLLECTOR_ERROR_TEMPLATES,
    FIELD_MAPPINGS,
    FieldMappingsDict,
)
from constant.runtime import StandardPipelineStage
from tools.logger import get_logger

from .mapper import FieldMapper
from .models import (
    Alert,
    AlertLevel,
    PipelineStatus,
    ProviderState,
    ProviderStatus,
    SystemState,
    SystemStatus,
)

logger = get_logger("state")


@dataclass
class CollectorConfig:
    """Collector configuration class with validation and type safety"""

    # Cache configuration
    cache_ttl: float = field(default=COLLECTOR_CACHE_TTL)
    cache_keys: Dict[str, str] = field(default_factory=lambda: COLLECTOR_CACHE_KEYS.copy())
    cache_max_size: int = field(default=100)  # Maximum number of cache entries

    # Alert configuration
    alert_sources: Dict[str, str] = field(default_factory=lambda: COLLECTOR_ALERT_SOURCES.copy())
    error_templates: Dict[str, str] = field(default_factory=lambda: COLLECTOR_ERROR_TEMPLATES.copy())

    # Field mapping configuration
    field_mappings: FieldMappingsDict = field(default_factory=lambda: FIELD_MAPPINGS.copy())

    def __post_init__(self) -> None:
        """Validate configuration after initialization"""
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate configuration values and structure"""
        if self.cache_ttl <= 0:
            raise ValueError("cache_ttl must be positive")

        required_cache_keys = {"SYSTEM_STATUS", "PIPELINE_DATA", "PROVIDER_DATA"}
        if not required_cache_keys.issubset(self.cache_keys.keys()):
            missing = required_cache_keys - self.cache_keys.keys()
            raise ValueError(f"Missing required cache keys: {missing}")

        required_alert_sources = {"APPLICATION", "COLLECTOR", "TASK", "MONITORING"}
        if not required_alert_sources.issubset(self.alert_sources.keys()):
            missing = required_alert_sources - self.alert_sources.keys()
            raise ValueError(f"Missing required alert sources: {missing}")


@dataclass
class CacheStats:
    """Cache statistics for monitoring and debugging"""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class StatusCollector:
    """
    Status data collector with configuration-driven approach.
    Eliminates hardcoded values and uses strong-typed objects.
    """

    def __init__(
        self,
        task_manager: Optional[Any] = None,
        monitoring: Optional[Any] = None,
        application: Optional[Any] = None,
        config: Optional[CollectorConfig] = None,
    ) -> None:
        """Initialize collector with optional component references

        Args:
            task_manager: Task management component for pipeline data
            monitoring: Monitoring component for metrics collection
            application: Application component for status information
            config: Custom configuration, uses default if None
        """
        self.task_manager = task_manager
        self.monitoring = monitoring
        self.application = application
        self.config = config or CollectorConfig()
        self.mapper = FieldMapper()

        # Cache storage with type hints and O(1) LRU tracking
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_access_order: OrderedDict[str, None] = OrderedDict()  # O(1) LRU eviction
        self._cache_stats = CacheStats()

        # Precompile field mapping accessors for performance
        self._compiled_mappings = self._compile_field_mappings()

        # Metrics for setter robustness
        self.setter_error_counts: Dict[str, int] = {}  # mapping_name -> error_count
        self.setter_sample_errors: Dict[str, str] = {}  # mapping_name -> last_error_sample

        logger.debug("Initialized StatusCollector with configuration-driven approach")

    def _compile_field_mappings(self) -> Dict[str, Dict[str, Callable]]:
        """Precompile field mapping accessors to avoid runtime path parsing"""
        compiled = {}

        for mapping_name, mappings in self.config.field_mappings.items():
            compiled[mapping_name] = {}
            for source_field, target_path in mappings.items():
                compiled[mapping_name][source_field] = self._create_field_setter(target_path)

        return compiled

    def _create_field_setter(self, field_path) -> Callable:
        """Create optimized field setter for a specific path"""
        # Handle tuple format (target_path, target_field) for provider mappings
        if isinstance(field_path, tuple):
            target_path, target_field = field_path
            if target_field is None:
                # Simple field access
                return lambda target, value: setattr(target, target_path, value)
            else:
                # Nested assignment (e.g., stats.keys.valid)
                return lambda target, value: setattr(getattr(target, target_path), target_field, value)

        # Handle string format for other mappings
        field_path_str = str(field_path)

        # Handle special field mappings with type conversion
        if field_path_str == "state":
            return lambda target, value: setattr(target, "state", SystemState.RUNNING if value else SystemState.STOPPED)
        elif field_path_str == "runtime":
            return lambda target, value: setattr(target, "runtime", float(value) if value is not None else 0.0)
        elif field_path_str == "monitored":
            return lambda target, value: setattr(target, "monitored", bool(value))
        else:
            # Precompile nested field access
            parts = field_path_str.split(".")
            if len(parts) == 1:
                # Simple field access
                field_name = parts[0]
                return lambda target, value: setattr(target, field_name, value)
            else:
                # Nested field access - precompile the path
                return lambda target, value: self._set_compiled_nested_field(target, parts, value)

    def _set_compiled_nested_field(self, obj: Any, parts: List[str], value: Any) -> None:
        """Set nested field using precompiled path parts"""
        try:
            current = obj
            # Navigate to the parent object
            for part in parts[:-1]:
                current = getattr(current, part)
            # Set the final field
            setattr(current, parts[-1], value)
        except (AttributeError, IndexError) as e:
            logger.debug(f"Failed to set nested field {'.'.join(parts)}: {e}")

    def _record_setter_error(self, mapping_name: str, source_field: str, error: Exception) -> None:
        """Record setter error with counting and sampling for observability"""
        error_key = f"{mapping_name}.{source_field}"

        # Increment error count
        self.setter_error_counts[error_key] = self.setter_error_counts.get(error_key, 0) + 1

        # Sample error message (keep latest)
        self.setter_sample_errors[error_key] = str(error)

        # Log at debug level to avoid noise, but sample at info level for high counts
        error_count = self.setter_error_counts[error_key]
        if error_count == 1 or error_count % 100 == 0:  # First error or every 100th
            logger.info(f"Setter error for {error_key} (count: {error_count}): {error}")
        else:
            logger.debug(f"Setter error for {error_key}: {error}")

    def get_setter_error_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get setter error statistics for monitoring"""
        return {
            "error_counts": self.setter_error_counts.copy(),
            "sample_errors": self.setter_sample_errors.copy(),
            "total_errors": sum(self.setter_error_counts.values()),
        }

    def status(self, refresh: bool = False) -> SystemStatus:
        """Collect and return unified system status

        Main entry point using configuration-driven data collection.

        Args:
            refresh: Force refresh of cached data if True

        Returns:
            SystemStatus: Complete system status with all collected metrics
        """
        try:
            cache_key = self.config.cache_keys["SYSTEM_STATUS"]

            # Try to get from cache first
            cached_status = self._get_cached_status(cache_key, refresh)
            if cached_status is not None:
                return cached_status

            # Collect fresh status data
            status = self._collect_fresh_status()

            # Cache and return
            self._update_cache(cache_key, status)
            return status
        except Exception:
            raise

    def _get_cached_status(self, cache_key: str, refresh: bool) -> Optional[SystemStatus]:
        """Get status from cache if valid and not forcing refresh

        Args:
            cache_key: Cache key to check
            refresh: Whether to force refresh

        Returns:
            SystemStatus if cached and valid, None otherwise
        """
        if not refresh and self._cache_valid(cache_key):
            logger.debug("Returning cached system status")
            return self._cache[cache_key]
        return None

    def _collect_fresh_status(self) -> SystemStatus:
        """Collect fresh system status from all sources

        Returns:
            SystemStatus: Newly collected system status
        """
        try:
            status = SystemStatus()
            status.timestamp = time.time()

            logger.debug(
                f"Starting fresh status collection - task_manager: {self.task_manager is not None}, "
                f"monitoring: {self.monitoring is not None}, application: {self.application is not None}"
            )

            # Collect data from all available sources
            self._collect_all_data(status)

            # Finalize status with derived metrics
            self._finalize_status(status)

            return status
        except Exception:
            raise

    def _collect_all_data(self, status: SystemStatus) -> None:
        """Collect data from all available sources

        Args:
            status: SystemStatus object to populate
        """
        try:
            self._collect_application_data(status)
            self._collect_task_manager_data(status)
            self._collect_monitoring_data(status)
        except Exception:
            raise

    def _finalize_status(self, status: SystemStatus) -> None:
        """Finalize status with derived metrics and logging

        Args:
            status: SystemStatus object to finalize
        """
        logger.debug(
            f"Data collection complete - pipeline stages: {len(status.pipeline.stages)}, "
            f"providers: {len(status.providers)}, alerts: {len(status.alerts)}"
        )

        # Calculate derived metrics
        status.calculate_overall_metrics()

        logger.debug("System status collection and calculation completed")

    def _collect_application_data(self, status: SystemStatus) -> None:
        """Collect data from application component using configuration-driven field mapping

        Extracts application status information and maps it to the system status object
        using configured field mappings. Handles type conversion and creates alerts
        for application-level issues.

        Args:
            status: SystemStatus object to populate with application data
        """
        if not self.application:
            return

        try:
            app_status = self.application.get_status()

            # Use precompiled field mapping accessors
            compiled_mappings = self._compiled_mappings.get("application_to_system", {})

            for source_field, setter in compiled_mappings.items():
                if hasattr(app_status, source_field):
                    value = getattr(app_status, source_field)
                    try:
                        setter(status, value)
                    except Exception as e:
                        self._record_setter_error("application_to_system", source_field, e)

            # Application-level alerts using configuration
            if not getattr(app_status, "running", True):
                alert = Alert.create_system_alert(
                    AlertLevel.WARNING, "Application is not running", self.config.alert_sources["APPLICATION"]
                )
                status.alerts.append(alert)

        except Exception as e:
            self._handle_collection_error(status, "APPLICATION_DATA_ERROR", e, "application data collection")

    def _collect_task_manager_data(self, status: SystemStatus) -> None:
        """Collect data from task manager component using configuration

        Retrieves comprehensive statistics from the task manager including pipeline
        state, provider information, worker metrics, and performance data. This is
        typically the primary source of detailed system metrics.

        Args:
            status: SystemStatus object to populate with task manager data
        """
        if not self.task_manager:
            logger.debug("No task manager available for data collection")
            return

        try:
            tm_stats = self.task_manager.get_stats()
            # Update runtime if not set
            if status.runtime == 0.0:
                status.runtime = tm_stats.runtime

            status.state = tm_stats.state

            # Copy pipeline data directly
            status.pipeline = tm_stats.pipeline

            # Copy provider data directly
            status.providers.update(tm_stats.providers)

            # Copy metrics directly
            status.keys = tm_stats.keys
            status.resources = tm_stats.resources
            status.workers = tm_stats.workers
            status.queues = tm_stats.queues
            status.tasks = tm_stats.tasks
            status.performance = tm_stats.performance

            # Copy alerts
            status.alerts.extend(tm_stats.alerts)

        except Exception as e:
            self._handle_collection_error(status, "TASK_MANAGER_DATA_ERROR", e, "task manager data collection")

    def _collect_monitoring_data(self, status: SystemStatus) -> None:
        """Collect data from monitoring component using configuration-driven field mapping

        Gathers monitoring metrics including task completion rates, performance statistics,
        and real-time provider status. Complements task manager data with operational metrics.

        Args:
            status: SystemStatus object to populate with monitoring data
        """
        if not self.monitoring:
            return

        try:
            monitoring_summary = self.monitoring.summary()

            # Map monitoring summary data using configuration
            self._map_monitoring_summary(status, monitoring_summary)

            # Get current stats for additional data
            monitoring_stats = self.monitoring.current_stats()

            # Process pipeline and provider data
            self._map_monitoring_stats(status, monitoring_stats)

        except Exception as e:
            self._handle_collection_error(status, "MONITORING_DATA_ERROR", e, "monitoring data collection")

    def _collect_pipeline_data(self, status: SystemStatus, pipeline_stats: PipelineStatus) -> None:
        """Collect pipeline-specific data using configuration-driven approach

        This method is used by StatusBuilder to process pipeline statistics.
        It maps pipeline data to the system status object using configured mappings.

        Args:
            status: SystemStatus object to populate with pipeline data
            pipeline_stats: Pipeline statistics object with type safety
        """
        try:
            logger.debug(f"Collecting pipeline data: {type(pipeline_stats)}")

            # Set pipeline state
            if hasattr(pipeline_stats, "state"):
                status.pipeline.state = pipeline_stats.state
            else:
                status.pipeline.state = SystemState.RUNNING

            # Process pipeline stages if available
            if hasattr(pipeline_stats, "stages"):
                logger.debug(f"Pipeline stages found: {list(pipeline_stats.stages.keys())}")
                status.pipeline.total = len(pipeline_stats.stages)
                status.pipeline.active = getattr(pipeline_stats, "active", len(pipeline_stats.stages))

                # Copy stages directly to pipeline status
                status.pipeline.stages = pipeline_stats.stages
                logger.debug(f"Copied {len(status.pipeline.stages)} stages to status")

                # Map stage metrics to queue information
                self._map_pipeline_stages_to_queues(status, pipeline_stats.stages)
            else:
                logger.debug("No stages found in pipeline_stats")

            # Set additional pipeline metrics if available
            if hasattr(pipeline_stats, "runtime"):
                status.pipeline.runtime = pipeline_stats.runtime
            if hasattr(pipeline_stats, "finished"):
                status.pipeline.finished = pipeline_stats.finished

            logger.debug("Pipeline data collection completed")

        except Exception as e:
            self._handle_collection_error(status, "PIPELINE_DATA_ERROR", e, "pipeline data collection")

    def _map_pipeline_stages_to_queues(self, status: SystemStatus, stages: Dict[str, Any]) -> None:
        """Map pipeline stage data to queue metrics

        Args:
            status: SystemStatus object to update
            stages: Dictionary of stage name to stage statistics
        """

        # Get valid stage names from enum
        valid_stages = {stage.value for stage in StandardPipelineStage}

        for stage_name, stage_stats in stages.items():
            logger.debug(f"Processing stage {stage_name}: {type(stage_stats)}")

            queue_size = getattr(stage_stats, "queue_size", 0)
            logger.debug(f"Stage {stage_name}: queue_size={queue_size}")

            # Directly set queue field if it's a valid stage and the field exists
            if stage_name in valid_stages and hasattr(status.queues, stage_name):
                setattr(status.queues, stage_name, queue_size)
                logger.debug(f"Set queue {stage_name} = {queue_size}")
            else:
                logger.debug(f"Unknown or invalid stage name: {stage_name}")

    def _map_monitoring_summary(self, status: SystemStatus, summary: Any) -> None:
        """Map monitoring summary data to system status

        Args:
            status: SystemStatus object to update
            summary: Monitoring summary object
        """
        # Map task metrics
        status.tasks.completed = getattr(summary, "completed", 0)
        status.tasks.failed = getattr(summary, "failed", 0)

        # Map performance metrics
        status.performance.throughput = getattr(summary, "throughput", 0.0)
        status.performance.tasks_per_second = status.performance.throughput
        status.performance.success_rate = getattr(summary, "success_rate", 0.0)

    def _map_monitoring_stats(self, status: SystemStatus, stats: Any) -> None:
        """Map monitoring stats data to system status

        Args:
            status: SystemStatus object to update
            stats: Monitoring stats object
        """
        # Process pipeline data
        if hasattr(stats, "pipeline"):
            compiled_mappings = self._compiled_mappings.get("pipeline_to_system", {})
            for source_field, setter in compiled_mappings.items():
                if hasattr(stats.pipeline, source_field):
                    value = getattr(stats.pipeline, source_field)
                    try:
                        setter(status, value)
                    except Exception as e:
                        self._record_setter_error("pipeline_to_system", source_field, e)

        # Process provider data
        if hasattr(stats, "providers"):
            self._map_provider_data(status, stats.providers)

    def _map_provider_data(self, status: SystemStatus, providers: Dict[str, Any]) -> None:
        """Map provider data to system status

        Args:
            status: SystemStatus object to update
            providers: Dictionary of provider data
        """
        for provider_name, provider_data in providers.items():
            if provider_name not in status.providers:
                provider_status = ProviderStatus(name=provider_name)
                status.providers[provider_name] = provider_status

            provider_status = status.providers[provider_name]
            provider_status.state = ProviderState.ACTIVE

            # Update provider metrics using precompiled field mapping
            compiled_mappings = self._compiled_mappings.get("provider_to_system", {})
            for source_field, setter in compiled_mappings.items():
                if hasattr(provider_data, source_field):
                    value = getattr(provider_data, source_field)
                    try:
                        setter(provider_status, value)
                    except Exception as e:
                        self._record_setter_error("provider_to_system", source_field, e)

    def _handle_collection_error(self, status: SystemStatus, error_type: str, error: Exception, context: str) -> None:
        """Unified error handling for data collection operations

        Args:
            status: SystemStatus object to add alert to
            error_type: Type of error for template lookup
            error: Exception that occurred
            context: Human-readable context for logging
        """
        # Log error with consistent format and level
        logger.error(f"Error during {context}: {error.__class__.__name__}: {error}")

        # Add structured alert
        self._add_error_alert(status, error_type, error)

    def _add_error_alert(self, status: SystemStatus, error_type: str, error: Exception) -> None:
        """Add error alert using configuration templates

        Args:
            status: SystemStatus object to add alert to
            error_type: Type of error for template lookup
            error: Exception that occurred
        """
        try:
            template = self.config.error_templates[error_type]
            message = template.format(error=str(error))
            alert = Alert.create_system_alert(AlertLevel.ERROR, message, self.config.alert_sources["COLLECTOR"])
            status.alerts.append(alert)
            logger.debug(f"Added error alert: {message}")
        except Exception as alert_error:
            # Log the meta-error but don't let it break the flow
            logger.error(f"Failed to create structured error alert: {alert_error}")

            # Create simple fallback alert that should always work
            try:
                fallback_message = f"Error in {error_type}: {str(error)}"
                fallback_alert = Alert.create_system_alert(AlertLevel.ERROR, fallback_message, "collector")
                status.alerts.append(fallback_alert)
                logger.debug(f"Added fallback error alert: {fallback_message}")
            except Exception as fallback_error:
                # Last resort: log only, don't break the application
                logger.critical(f"Failed to create any error alert: {fallback_error}")
                logger.critical(f"Original error was: {error_type} - {error}")

    def _cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid using configuration TTL

        Args:
            cache_key: Key to check in cache

        Returns:
            bool: True if cache entry is valid, False otherwise
        """
        if cache_key not in self._cache or cache_key not in self._cache_times:
            self._cache_stats.misses += 1
            return False

        age = time.time() - self._cache_times[cache_key]
        is_valid = age < self.config.cache_ttl

        if is_valid:
            self._cache_stats.hits += 1
            # Update LRU order
            self._update_access_order(cache_key)
        else:
            self._cache_stats.misses += 1

        return is_valid

    def _update_cache(self, cache_key: str, data: Any) -> None:
        """Update cache with new data and LRU management

        Args:
            cache_key: Key to store data under
            data: Data to cache
        """
        # Check if we need to evict entries
        if len(self._cache) >= self.config.cache_max_size and cache_key not in self._cache:
            self._evict_lru_entry()

        self._cache[cache_key] = data
        self._cache_times[cache_key] = time.time()
        self._update_access_order(cache_key)
        self._cache_stats.size = len(self._cache)

    def _update_access_order(self, cache_key: str) -> None:
        """Update LRU access order for a cache key

        Args:
            cache_key: Key that was accessed
        """
        # Move to end (most recently used) - O(1) operation in OrderedDict
        self._cache_access_order.pop(cache_key, None)  # Remove if exists
        self._cache_access_order[cache_key] = None  # Add to end

    def _evict_lru_entry(self) -> None:
        """Evict the least recently used cache entry with O(1) operation"""
        if not self._cache_access_order:
            return

        # Remove least recently used (first in OrderedDict) - O(1) operation
        lru_key, _ = self._cache_access_order.popitem(last=False)

        # Remove from cache
        self._cache.pop(lru_key, None)
        self._cache_times.pop(lru_key, None)

        self._cache_stats.evictions += 1
        logger.debug(f"Evicted LRU cache entry: {lru_key}")

    def get_cache_stats(self) -> CacheStats:
        """Get current cache statistics

        Returns:
            CacheStats: Current cache statistics
        """
        self._cache_stats.size = len(self._cache)
        return self._cache_stats

    def clear_cache(self) -> None:
        """Clear all cached data and reset cache timestamps"""
        self._cache.clear()
        self._cache_times.clear()
        self._cache_access_order.clear()
        self._cache_stats = CacheStats()
        logger.debug("StatusCollector cache cleared")
