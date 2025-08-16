#!/usr/bin/env python3

"""
Core Metrics - Monitoring and Performance Metrics

This module defines all metrics-related data models used throughout the application
for monitoring, performance tracking, and system health assessment.
"""

import time
from dataclasses import dataclass, field
from typing import Dict

from .enums import SystemState


# Base metrics classes
@dataclass
class BaseMetrics:
    """Base class for all metrics to reduce field duplication"""

    timestamp: float = field(default_factory=time.time)

    def age(self) -> float:
        """Get metrics age in seconds"""
        return time.time() - self.timestamp


@dataclass
class BaseStats(BaseMetrics):
    """Base class for statistics with common functionality"""

    @property
    def empty(self) -> bool:
        """Check if statistics are empty"""
        return self.total == 0

    @property
    def total(self) -> int:
        """Total count - to be overridden by subclasses"""
        return 0


# Core metrics models
@dataclass
class TaskMetrics(BaseStats):
    """Task execution metrics"""

    completed: int = 0
    failed: int = 0
    pending: int = 0
    running: int = 0

    @property
    def total(self) -> int:
        """Total tasks"""
        return self.completed + self.failed + self.pending + self.running

    @property
    def success_rate(self) -> float:
        """Task success rate"""
        processed = self.completed + self.failed
        return self.completed / processed if processed > 0 else 0.0

    @property
    def error_rate(self) -> float:
        """Task error rate"""
        processed = self.completed + self.failed
        return self.failed / processed if processed > 0 else 0.0

    def add_completed(self, count: int = 1) -> None:
        """Add completed tasks"""
        self.completed += count

    def add_failed(self, count: int = 1) -> None:
        """Add failed tasks"""
        self.failed += count


@dataclass
class StageMetrics(BaseMetrics):
    """Stage-level metrics"""

    name: str = ""
    running: bool = False
    disabled: bool = False

    # Task metrics
    tasks: TaskMetrics = field(default_factory=TaskMetrics)

    # Stage-specific fields
    queue_size: int = 0
    last_activity: float = 0.0
    workers: int = 0

    @property
    def total_processed(self) -> int:
        return self.tasks.completed

    @property
    def total_errors(self) -> int:
        return self.tasks.failed


@dataclass
class PipelineStatus:
    """Pipeline status information"""

    state: SystemState = SystemState.UNKNOWN
    active: int = 0
    total: int = 0

    # Core pipeline data
    stages: Dict[str, StageMetrics] = field(default_factory=dict)
    runtime: float = 0.0
    start: float = field(default_factory=time.monotonic)  # Use monotonic for interval calculations
    finished: bool = False

    def queue_size(self) -> int:
        """Get total queue size across all stages"""
        return sum(stage.queue_size for stage in self.stages.values())

    def processed(self) -> int:
        """Get total processed tasks across all stages"""
        return sum(stage.total_processed for stage in self.stages.values())

    def errors(self) -> int:
        """Get total errors across all stages"""
        return sum(stage.total_errors for stage in self.stages.values())
