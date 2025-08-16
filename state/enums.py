#!/usr/bin/env python3

"""
Enumerations for State Package

This module contains all enumeration classes used throughout the state package.
These enums provide type-safe constants for various system states and configurations.
"""

from enum import Enum, unique


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
