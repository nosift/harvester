#!/usr/bin/env python3

"""
Protocol Interfaces for Status System

This module defines Protocol interfaces to replace hasattr/getattr checks
with proper type-safe interfaces. These protocols ensure compile-time
type checking and eliminate runtime attribute inspection.

Defines clean interfaces that eliminate circular dependencies by allowing
bottom layers to define contracts that upper layers implement.
"""

from typing import Optional, Protocol, runtime_checkable

from .models import CacheStats, IMonitorProvider, SystemStatus


@runtime_checkable
class TaskDataProvider(Protocol):
    """Task management data provider interface"""

    def stats(self) -> SystemStatus:
        """Get comprehensive task statistics

        Returns:
            SystemStatus: Complete system status including runtime, state,
                         pipeline info, provider stats, and all metrics
        """
        ...


@runtime_checkable
class ICollectorWithAlerts(Protocol):
    """Protocol for collectors that support alert management"""

    def _add_error_alert(self, status: SystemStatus, error_type: str, error: Exception) -> None:
        """Add error alert to status

        Args:
            status: System status to add alert to
            error_type: Type of error
            error: Original exception
        """
        ...


@runtime_checkable
class IStatusCollector(Protocol):
    """Protocol for status collectors that have monitoring capability"""

    monitoring: Optional["IMonitorProvider"]

    def status(self, refresh: bool = False) -> SystemStatus:
        """Get system status"""
        ...

    def cache_stats(self) -> CacheStats:
        """Get cache statistics"""
        ...

    def clear_cache(self) -> None:
        """Clear cache"""
        ...
