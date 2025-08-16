#!/usr/bin/env python3

"""
Monitoring and Type Configuration Constants

This module defines constants used by the state management system,
including collector configurations, field mappings, cache settings,
and type-safe constants for the status monitoring system.
"""

from typing import Dict, Final


# Cache configuration constants
class CacheConfig:
    """Cache configuration constants"""

    DEFAULT_TTL: Final[float] = 5.0
    DEFAULT_MAX_SIZE: Final[int] = 100
    DEFAULT_HISTORY_SIZE: Final[int] = 100


# Alert configuration constants
class AlertConfig:
    """Alert configuration constants"""

    DEFAULT_HISTORY_SIZE: Final[int] = 100
    DEFAULT_COOLDOWN_SECONDS: Final[float] = 300.0
    MIN_SAMPLE_SIZE: Final[int] = 10


# Display configuration constants
class DisplayConfig:
    """Display configuration constants"""

    DEFAULT_WIDTH: Final[int] = 60
    EMERGENCY_WIDTH: Final[int] = 40
    TITLE_CENTER_FORMAT: Final[str] = "{title:^{width}}"

    # Separator constants
    SEPARATOR_MAIN: Final[str] = "=" * 60
    SEPARATOR_EMERGENCY: Final[str] = "=" * 40

    # Emergency status messages
    EMERGENCY_TITLE: Final[str] = "Emergency Status Display"
    EMERGENCY_ERROR_MSG: Final[str] = "Status display system encountered an error."
    EMERGENCY_INFO_HEADER: Final[str] = "Basic system information:"
    CRITICAL_FAILURE_MSG: Final[str] = "CRITICAL: Status system failure"

    # Status availability messages
    MONITORING_AVAILABLE: Final[str] = "  Monitoring: Available"
    MONITORING_NOT_AVAILABLE: Final[str] = "  Monitoring: Not available"
    TASK_PROVIDER_AVAILABLE: Final[str] = "  Task Provider: Available"
    TASK_PROVIDER_NOT_AVAILABLE: Final[str] = "  Task Provider: Not available"


# Collector cache configuration
COLLECTOR_CACHE_TTL: float = 300.0  # 5 minutes cache TTL


MONITORING_THRESHOLDS: Dict[str, float] = {
    "error_rate": 0.1,
    "queue_size": 1000,
    "memory_usage": 1073741824,  # 1GB in bytes
    "min_sample_size": 10,
    "max_alert_history": 50,
    "max_stats_history": 100,
}
