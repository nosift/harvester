#!/usr/bin/env python3

"""
Pipeline stage management system.

This module provides a comprehensive framework for managing pipeline stages including:
- Base classes for stage implementation
- Stage registry for dynamic stage discovery
- Dependency resolution for proper stage ordering
- Built-in stage definitions for common operations

The stage system supports:
- Multi-threaded task processing
- Task deduplication and retry logic
- Dependency-based stage ordering
- Dynamic stage registration and discovery
- Comprehensive statistics and monitoring
"""

from .base import *
from .definition import *
from .factory import *
from .registry import *
from .resolver import *

__all__ = [
    # Base classes
    "BasePipelineStage",
    "StageUtils",
    # Types for hybrid architecture
    "StageResources",
    "StageOutput",
    "OutputHandler",
    # Registry system
    "StageRegistry",
    "StageDefinition",
    "StageRegistryMixin",
    # Dependency resolution
    "DependencyResolver",
    "CircularDependencyError",
    "MissingDependencyError",
    # Built-in stages
    "SearchStage",
    "AcquisitionStage",
    "CheckStage",
    "InspectStage",
    # Task factories
    "TaskFactory",
]
