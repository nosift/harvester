#!/usr/bin/env python3

"""
Status Builders - System Status Construction Utilities

This module provides a robust, type-safe builder pattern implementation for constructing
SystemStatus objects with the following features:

- Type-safe interfaces with Protocol definitions for external dependencies
- Comprehensive parameter validation with custom exception types
- Dependency injection support for better testability
- Unified error handling with structured logging
- Method responsibility separation for maintainability
- Factory methods for convenient builder creation
- Build state tracking to prevent misuse

Key Components:
    StatusBuilder: Main builder class with full validation and error handling
    Custom Exceptions: Specific exception types for better error handling
    IPipelineBase: Abstract base class for pipeline implementations
    Type Protocols: Interface definitions for external dependencies

Usage Examples:
    # Basic usage with validation
    builder = StatusBuilder.quick()
    status = (builder
        .with_basic_info(runtime=10.5, state=SystemState.RUNNING)
        .with_task_metrics(completed=100, failed=2)
        .build())

    # Advanced usage with dependency injection
    custom_collector = StatusCollector(...)
    builder = StatusBuilder.create(collector=custom_collector)
"""

import time
from typing import Any, Dict, List, Optional

from core.enums import SystemState
from core.metrics import TaskMetrics
from core.types import IPipelineBase, IProvider
from tools.logger import get_logger

from .collector import StatusCollector
from .mapper import FieldMapper
from .models import (
    PerformanceMetrics,
    PersistenceMetrics,
    ProviderState,
    ProviderStatus,
    SystemStatus,
)

# Type aliases for better readability
ProviderDict = Dict[str, IProvider]
ResultStatsDict = Dict[str, PersistenceMetrics]


# Custom exceptions for better error handling
class StatusBuilderError(Exception):
    """Base exception for StatusBuilder errors"""

    pass


class BuilderAlreadyBuiltError(StatusBuilderError):
    """Raised when trying to modify a builder that has already been built"""

    pass


class InvalidParameterError(StatusBuilderError):
    """Raised when invalid parameters are provided to builder methods"""

    pass


class DataCollectionError(StatusBuilderError):
    """Raised when data collection from external sources fails"""

    pass


logger = get_logger("state")


class StatusBuilder:
    """Builder pattern for constructing SystemStatus objects with dependency injection"""

    def __init__(self, collector: Optional[StatusCollector] = None, mapper: Optional[FieldMapper] = None):
        """Initialize builder with dependency injection

        Args:
            collector: StatusCollector instance for pipeline data collection
            mapper: FieldMapper instance for field mapping operations
        """
        self.collector = collector or StatusCollector()
        self.mapper = mapper or FieldMapper()
        self.status = SystemStatus()
        self._built = False  # Track if build() has been called

    @classmethod
    def create(
        cls, collector: Optional[StatusCollector] = None, mapper: Optional[FieldMapper] = None
    ) -> "StatusBuilder":
        """Factory method to create a new StatusBuilder instance

        Args:
            collector: Optional StatusCollector instance
            mapper: Optional FieldMapper instance

        Returns:
            New StatusBuilder instance
        """
        return cls(collector, mapper)

    @classmethod
    def quick(cls) -> "StatusBuilder":
        """Create a StatusBuilder with default dependencies for quick usage

        Returns:
            StatusBuilder with default dependencies
        """
        return cls()

    def _ensure_not_built(self) -> None:
        """Ensure builder hasn't been built yet"""
        if self._built:
            raise BuilderAlreadyBuiltError("Cannot modify StatusBuilder after build() has been called")

    def _validate_runtime(self, runtime: float) -> None:
        """Validate runtime parameter"""
        if not isinstance(runtime, (int, float)) or runtime < 0:
            raise InvalidParameterError(f"Runtime must be a non-negative number, got: {runtime}")

    def _handle_collection_error(self, operation: str, error: Exception) -> None:
        """Handle data collection errors consistently

        Args:
            operation: Description of the operation that failed
            error: The original exception
        """
        error_msg = f"Failed to {operation}: {error.__class__.__name__}: {error}"
        logger.error(error_msg)

        # Add error alert to status if collector is available
        if hasattr(self.collector, "_add_error_alert"):
            try:
                self.collector._add_error_alert(self.status, "DATA_COLLECTION_ERROR", error)
            except Exception as alert_error:
                logger.warning(f"Failed to add error alert: {alert_error}")

        # Don't re-raise the error, just log it and continue

    def with_basic_info(self, runtime: float, state: SystemState) -> "StatusBuilder":
        """Set basic system information

        Args:
            runtime: System runtime in seconds (must be non-negative)
            state: Current system state

        Returns:
            Self for method chaining

        Raises:
            BuilderAlreadyBuiltError: If builder has already been built
            InvalidParameterError: If runtime is invalid
        """
        self._ensure_not_built()
        self._validate_runtime(runtime)

        self.status.runtime = runtime
        self.status.state = state
        self.status.timestamp = time.time()
        return self

    def with_task_metrics(self, completed: int = 0, failed: int = 0, pending: int = 0) -> "StatusBuilder":
        """Set task metrics

        Args:
            completed: Completed tasks (must be non-negative)
            failed: Failed tasks (must be non-negative)
            pending: Pending tasks (must be non-negative)

        Returns:
            Self for method chaining

        Raises:
            RuntimeError: If builder has already been built
            ValueError: If any metric is negative
        """
        self._ensure_not_built()

        # Validate metrics
        for name, value in [("completed", completed), ("failed", failed), ("pending", pending)]:
            if not isinstance(value, int) or value < 0:
                raise InvalidParameterError(f"{name} must be a non-negative integer, got: {value}")

        self.status.tasks = TaskMetrics(completed=completed, failed=failed, pending=pending)
        return self

    def with_performance_metrics(self, throughput: float = 0.0, success_rate: float = 0.0) -> "StatusBuilder":
        """Set performance metrics

        Args:
            throughput: Tasks per second (must be non-negative)
            success_rate: Success rate (must be between 0.0 and 1.0)

        Returns:
            Self for method chaining

        Raises:
            RuntimeError: If builder has already been built
            ValueError: If metrics are out of valid range
        """
        self._ensure_not_built()

        # Validate metrics
        if not isinstance(throughput, (int, float)) or throughput < 0:
            raise InvalidParameterError(f"Throughput must be non-negative, got: {throughput}")
        if not isinstance(success_rate, (int, float)) or not (0.0 <= success_rate <= 1.0):
            raise InvalidParameterError(f"Success rate must be between 0.0 and 1.0, got: {success_rate}")

        self.status.performance = PerformanceMetrics(
            throughput=throughput,
            tasks_per_second=throughput,
            success_rate=success_rate,
            error_rate=1.0 - success_rate if success_rate > 0 else 0.0,
        )
        return self

    def with_pipeline_stats(self, pipeline: IPipelineBase) -> "StatusBuilder":
        """Set pipeline statistics using collector

        Args:
            pipeline: Pipeline object that inherits from PipelineBase

        Returns:
            Self for method chaining

        Raises:
            RuntimeError: If builder has already been built
        """
        self._ensure_not_built()

        if pipeline:
            try:
                if hasattr(pipeline, "get_all_stats"):
                    pipeline_stats = pipeline.get_all_stats()
                    logger.debug(f"Got pipeline stats: {type(pipeline_stats)}")

                    # Use collector to gather pipeline data
                    self.collector._collect_pipeline_data(self.status, pipeline_stats)
                elif hasattr(pipeline, "get_dynamic_stats"):
                    # Fallback to dynamic stats method
                    pipeline_stats = pipeline.get_dynamic_stats()
                    logger.debug(f"Got dynamic pipeline stats: {type(pipeline_stats)}")
                    self.collector._collect_pipeline_data(self.status, pipeline_stats)
                else:
                    logger.debug(f"Pipeline object has no stats methods: {type(pipeline)}")

            except Exception as e:
                self._handle_collection_error("collect pipeline statistics", e)

        return self

    def with_result_stats(self, result_stats: ResultStatsDict) -> "StatusBuilder":
        """Set result statistics using direct field mapping

        Args:
            result_stats: Dictionary mapping provider names to their persistence metrics

        Returns:
            Self for method chaining

        Raises:
            BuilderAlreadyBuiltError: If builder has already been built
        """
        self._ensure_not_built()

        if result_stats:
            self._update_system_level_metrics(result_stats)
            self._update_provider_level_metrics(result_stats)

        return self

    def _update_system_level_metrics(self, result_stats: ResultStatsDict) -> None:
        """Update system-level aggregated metrics

        Args:
            result_stats: Dictionary of provider statistics
        """
        try:
            key_metrics = self.mapper.aggregate_key_metrics(result_stats)
            resource_metrics = self.mapper.aggregate_resource_metrics(result_stats)

            self.status.keys = key_metrics
            self.status.resources = resource_metrics

            logger.debug(f"Updated system metrics: keys={key_metrics.total}, resources={resource_metrics.total}")
        except Exception as e:
            self._handle_collection_error("update system-level metrics", e)

    def _update_provider_level_metrics(self, result_stats: ResultStatsDict) -> None:
        """Update individual provider metrics

        Args:
            result_stats: Dictionary of provider statistics
        """
        for provider_name, stats in result_stats.items():
            try:
                if provider_name in self.status.providers:
                    provider_status = self.status.providers[provider_name]
                    # Use FieldMapper for consistent field mapping
                    provider_status.keys = self.mapper.map_to_key_metrics(stats)
                    provider_status.resources = self.mapper.map_to_resource_metrics(stats)
                    logger.debug(
                        f"Updated provider {provider_name} metrics: valid={provider_status.keys.valid}, links={provider_status.resources.links}"
                    )
                else:
                    logger.warning(f"Provider {provider_name} not found in status.providers, skipping metrics update")
            except Exception as e:
                self._handle_collection_error(f"update metrics for provider {provider_name}", e)

    def with_providers_info(self, providers: ProviderDict) -> "StatusBuilder":
        """Set providers information

        Args:
            providers: Dictionary mapping provider names to Provider instances

        Returns:
            Self for method chaining
        """
        # Convert provider objects to ProviderStatus objects
        if providers:
            for provider_name in providers.keys():
                provider_status = self._create_provider_status(provider_name)
                self.status.providers[provider_name] = provider_status

        return self

    def with_provider_stages(self, provider_stages: List[Any]) -> "StatusBuilder":
        """Set provider stage configurations

        Args:
            provider_stages: List of provider stage configuration objects

        Returns:
            Self for method chaining

        Raises:
            BuilderAlreadyBuiltError: If builder has already been built
        """
        self._ensure_not_built()

        if provider_stages:
            self._update_provider_stages(provider_stages)
        return self

    def with_custom_field(self, field_name: str, value: Any) -> "StatusBuilder":
        """Set a custom field on the status object

        Args:
            field_name: Name of the field to set
            value: Value to set

        Returns:
            Self for method chaining

        Raises:
            BuilderAlreadyBuiltError: If builder has already been built
            InvalidParameterError: If field doesn't exist on status object
        """
        self._ensure_not_built()

        if not hasattr(self.status, field_name):
            raise InvalidParameterError(f"Status object has no field '{field_name}'")

        setattr(self.status, field_name, value)
        logger.debug(f"Set custom field {field_name} = {value}")
        return self

    def with_additional_data(self, **kwargs) -> "StatusBuilder":
        """Set additional data fields

        Args:
            **kwargs: Additional data to set as custom fields

        Returns:
            Self for method chaining

        Raises:
            BuilderAlreadyBuiltError: If builder has already been built
        """
        self._ensure_not_built()

        for field_name, value in kwargs.items():
            try:
                if hasattr(self.status, field_name):
                    setattr(self.status, field_name, value)
                    logger.debug(f"Set additional field {field_name} = {value}")
                else:
                    logger.debug(f"Skipping unknown field {field_name}")
            except Exception as e:
                logger.warning(f"Failed to set additional field {field_name}: {e}")

        return self

    def _create_provider_status(self, provider_name: str, enabled: bool = True) -> Any:
        """Create a ProviderStatus object with default values

        Args:
            provider_name: Name of the provider
            enabled: Whether the provider is enabled

        Returns:
            ProviderStatus: Configured provider status object
        """
        return ProviderStatus(
            name=provider_name,
            enabled=enabled,
            state=ProviderState.ACTIVE if enabled else ProviderState.DISABLED,
        )

    def _update_provider_stages(self, provider_stages) -> None:
        """Update provider stage configurations"""
        try:
            for stage_info in provider_stages:
                provider_name = stage_info.name
                if provider_name in self.status.providers:
                    provider_status = self.status.providers[provider_name]
                    # Update stage configuration
                    provider_status.searchable = stage_info.searchable
                    provider_status.gatherable = stage_info.gatherable
                    provider_status.checkable = stage_info.checkable
                    provider_status.inspectable = stage_info.inspectable
                    logger.debug(
                        f"Updated provider {provider_name} stages: S={provider_status.searchable}, G={provider_status.gatherable}, V={provider_status.checkable}, I={provider_status.inspectable}"
                    )
        except Exception as e:
            self._handle_collection_error("update provider stages", e)

    def build(self) -> SystemStatus:
        """Build final SystemStatus object

        Returns:
            Constructed SystemStatus object

        Raises:
            BuilderAlreadyBuiltError: If build() has already been called
        """
        if self._built:
            raise BuilderAlreadyBuiltError("build() can only be called once per StatusBuilder instance")

        # Calculate derived metrics if needed
        if hasattr(self.status, "calculate_overall_metrics"):
            try:
                self.status.calculate_overall_metrics()
            except Exception as e:
                logger.warning(f"Failed to calculate derived metrics: {e}")

        self._built = True
        return self.status
