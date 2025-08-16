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

from core.enums import ErrorType, SystemState
from core.metrics import TaskMetrics
from core.types import IPipelineStats, IProvider
from tools.logger import get_logger

from .collector import StatusCollector
from .enums import ProviderState
from .models import PerformanceMetrics, PersistenceMetrics, ProviderStatus, SystemStatus
from .types import ICollectorWithAlerts


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

    def __init__(self, collector: Optional[StatusCollector] = None):
        """Initialize builder with dependency injection

        Args:
            collector: StatusCollector instance for pipeline data collection
        """
        self.collector = collector  # StatusCollector now requires monitoring parameter
        self.status = SystemStatus()
        self._built = False  # Track if build() has been called

    @classmethod
    def create(cls, collector: Optional[StatusCollector] = None) -> "StatusBuilder":
        """Factory method to create a new StatusBuilder instance

        Args:
            collector: Optional StatusCollector instance

        Returns:
            New StatusBuilder instance
        """
        return cls(collector)

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

        # Add error alert to status if collector supports alerts
        if isinstance(self.collector, ICollectorWithAlerts):
            try:
                self.collector._add_error_alert(self.status, ErrorType.DATA_COLLECTION_ERROR.value, error)
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

    def with_pipeline_stats(self, pipeline: IPipelineStats) -> "StatusBuilder":
        """Set pipeline statistics using collector

        Args:
            pipeline: Pipeline object implementing IPipelineBase interface

        Returns:
            Self for method chaining

        Raises:
            RuntimeError: If builder has already been built
        """
        self._ensure_not_built()

        if pipeline:
            try:
                # Try primary stats method first
                try:
                    pipeline_stats = pipeline.get_all_stats()
                    self.status.pipeline = pipeline_stats
                except AttributeError:
                    # Fallback to dynamic stats method
                    pipeline_stats = pipeline.get_dynamic_stats()
                    logger.debug(f"Got dynamic pipeline stats: {type(pipeline_stats)}")
                    self.status.pipeline = pipeline_stats

            except Exception as e:
                self._handle_collection_error("collect pipeline statistics", e)

        return self

    def with_result_stats(self, result_stats: Dict[str, PersistenceMetrics]) -> "StatusBuilder":
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

    def _update_system_level_metrics(self, result_stats: Dict[str, PersistenceMetrics]) -> None:
        """Update system-level aggregated metrics

        Args:
            result_stats: Dictionary of provider statistics
        """
        try:
            self._update_provider_level_metrics(result_stats)
            self.status.calculate_overall_metrics()

            logger.debug(
                f"Updated system metrics: keys={self.status.resource.total}, links={self.status.resource.links}"
            )
        except Exception as e:
            self._handle_collection_error("update system-level metrics", e)

    def _update_provider_level_metrics(self, result_stats: Dict[str, PersistenceMetrics]) -> None:
        """Update individual provider metrics

        Args:
            result_stats: Dictionary of provider statistics
        """
        for name, stats in result_stats.items():
            if not stats or not isinstance(stats, PersistenceMetrics):
                logger.warning(f"Skip update provider {name} due to invalid metrics: {stats}")
                continue

            try:
                if name in self.status.providers:
                    provider_status = self.status.providers[name]
                    provider_status.resource = stats.resource
                    logger.debug(
                        f"Updated provider {name} metrics: valid={provider_status.resource.valid}, links={provider_status.resource.links}"
                    )
                else:
                    logger.warning(f"Provider {name} not found in status.providers, skipping metrics update")
            except Exception as e:
                self._handle_collection_error(f"update metrics for provider {name}", e)

    def with_providers_info(self, providers: Dict[str, IProvider]) -> "StatusBuilder":
        """Set providers information

        Args:
            providers: Dictionary mapping provider names to Provider instances

        Returns:
            Self for method chaining
        """

        if providers:
            for name in providers.keys():
                status = self._create_provider_status(name)
                self.status.providers[name] = status

        return self

    def with_provider_status(self, provider_statuses: List[ProviderStatus]) -> "StatusBuilder":
        """Set provider stage configurations

        Args:
            stages: List of provider stage configuration objects

        Returns:
            Self for method chaining

        Raises:
            BuilderAlreadyBuiltError: If builder has already been built
        """
        self._ensure_not_built()

        logger.debug(
            f"StatusBuilder.with_provider_stages called with {len(provider_statuses) if provider_statuses else 0} stages"
        )
        if provider_statuses:
            self._update_provider_status(provider_statuses)
        return self

    def with_custom_field(self, field: str, value: Any) -> "StatusBuilder":
        """Set a custom field on the status object

        Args:
            field: Name of the field to set
            value: Value to set

        Returns:
            Self for method chaining

        Raises:
            BuilderAlreadyBuiltError: If builder has already been built
            InvalidParameterError: If field doesn't exist on status object
        """
        self._ensure_not_built()

        if not hasattr(self.status, field):
            raise InvalidParameterError(f"Status object has no field '{field}'")

        setattr(self.status, field, value)
        logger.debug(f"Set custom field {field} = {value}")
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

        for field, value in kwargs.items():
            try:
                if hasattr(self.status, field):
                    setattr(self.status, field, value)
                    logger.debug(f"Set additional field {field} = {value}")
                else:
                    logger.debug(f"Skipping unknown field {field}")
            except Exception as e:
                logger.warning(f"Failed to set additional field {field}: {e}")

        return self

    def _create_provider_status(self, name: str, enabled: bool = True) -> ProviderStatus:
        """Create a ProviderStatus object with default values

        Args:
            name: Name of the provider
            enabled: Whether the provider is enabled

        Returns:
            ProviderStatus: Configured provider status object
        """
        return ProviderStatus(
            name=name,
            enabled=enabled,
            state=ProviderState.ACTIVE if enabled else ProviderState.DISABLED,
        )

    def _update_provider_status(self, provider_statuses: List[ProviderStatus]) -> None:
        """Update provider stage configurations"""
        try:
            for provider_status in provider_statuses:
                if provider_status.name in self.status.providers:
                    # Update existing provider
                    ps = self.status.providers[provider_status.name]
                    ps.searchable = provider_status.searchable
                    ps.gatherable = provider_status.gatherable
                    ps.checkable = provider_status.checkable
                    ps.inspectable = provider_status.inspectable
                    logger.debug(
                        f"Updated provider {provider_status.name} stages: S={ps.searchable}, G={ps.gatherable}, V={ps.checkable}, I={ps.inspectable}"
                    )
                else:
                    # Create new provider if it doesn't exist
                    logger.debug(f"Creating new provider status for {provider_status.name}")
                    self.status.providers[provider_status.name] = provider_status
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
        try:
            self.status.calculate_overall_metrics()
        except Exception as e:
            logger.warning(f"Failed to calculate derived metrics: {e}")

        self._built = True
        return self.status
