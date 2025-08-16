#!/usr/bin/env python3

"""
Monitor Package - Unified Status Monitoring System

This package provides a unified, modular approach to system status monitoring and display.
It consolidates all monitoring-related functionality into a single, cohesive package.

Architecture:
- models.py: Core data models (SystemStatus, metrics, alerts)
- collector.py: Data collection from various sources
- display.py: Unified display rendering engine
- manager.py: Single entry point for all status operations
- config.py: Configuration management

Key Features:
- Single entry point for all status display
- Unified data models eliminating redundancy
- Strong typing replacing dictionary-based data passing
- Modular, extensible architecture
- Comprehensive caching and performance optimization

Usage:
    from manager.status import StatusManager
    from state.collector import StatusCollector
    from state.models import DisplayMode, StatusContext

    # Create status collector and manager
    collector = StatusCollector(monitoring=monitoring)
    status_manager = StatusManager(collector=collector, task_provider=task_manager)

    # Display status (single entry point)
    status_manager.show_status(StatusContext.MONITORING, DisplayMode.DETAILED)
"""

from .builder import StatusBuilder
from .collector import StatusCollector
from .display import StatusDisplayEngine, get_display_config
from .enums import AlertLevel, DisplayMode, ProviderState, StatusContext
from .models import (
    Alert,
    ApplicationStatus,
    BaseKeyStats,
    IMonitorProvider,
    MonitoringSnapshot,
    MonitoringSummary,
    PerformanceMetrics,
    PersistenceMetrics,
    ProviderStatus,
    QueueStateMetrics,
    SystemStatus,
    WorkerMetrics,
)

# Public API
__all__ = [
    # Core data models
    "MonitoringSnapshot",
    "MonitoringSummary",
    "get_display_config",
    "ProviderState",
    # Alert system
    "Alert",
    "AlertKeyType",
    "AlertLevel",
    # Enums
    "DisplayMode",
    "StatusContext",
    # Components
    "StatusCollector",
    "StatusDisplayEngine",
    # Enhanced statistics tools
    "StatusBuilder",
    "ApplicationStatus",
    "BaseKeyStats",
    "IMonitorProvider",
    "PerformanceMetrics",
    "PersistenceMetrics",
    "ProviderStatus",
    "QueueStateMetrics",
    "SystemStatus",
    "WorkerMetrics",
]
