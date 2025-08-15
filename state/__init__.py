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
    from monitor import StatusManager, DisplayMode, StatusContext

    # Create status manager
    status_manager = StatusManager(task_manager, monitoring, application)

    # Display status (single entry point)
    status_manager.show_status(StatusContext.MONITORING, DisplayMode.DETAILED)
"""

from .builder import StatusBuilder
from .collector import StatusCollector
from .display import DisplayConfig, StatusDisplayEngine
from .mapper import FieldMapper
from .models import (
    Alert,
    AlertLevel,
    AlertType,
    ApplicationStatus,
    DisplayMode,
    KeyMetrics,
    MonitoringSnapshot,
    MonitoringSummary,
    PerformanceMetrics,
    PersistenceMetrics,
    PipelineUpdate,
    ProviderState,
    ProviderStatus,
    QueueMetrics,
    QueueStateMetrics,
    ResourceMetrics,
    StatsTotals,
    StatusContext,
    SystemStatus,
    WorkerMetrics,
)
from .status import StatusManager

# Public API
__all__ = [
    # Main entry point
    "StatusManager",
    # Core data models
    "MonitoringSnapshot",
    "MonitoringSummary",
    "DisplayConfig",
    "StatsTotals",
    "PipelineUpdate",
    "ProviderState",
    # Alert system
    "Alert",
    "AlertType",
    "AlertLevel",
    # Enums
    "SystemState",
    "DisplayMode",
    "StatusContext",
    # Components
    "StatusCollector",
    "StatusDisplayEngine",
    # Enhanced statistics tools
    "StatusBuilder",
    "FieldMapper",
    "ApplicationStatus",
    "KeyMetrics",
    "PerformanceMetrics",
    "PersistenceMetrics",
    "ProviderStatus",
    "QueueMetrics",
    "QueueStateMetrics",
    "ResourceMetrics",
    "SystemStatus",
    "WorkerMetrics",
]
