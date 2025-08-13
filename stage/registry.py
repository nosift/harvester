#!/usr/bin/env python3

"""
Stage registry system for dynamic pipeline management.
Provides registration, discovery, and metadata management for pipeline stages.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Type

from tools.logger import get_logger

from .base import BasePipelineStage

logger = get_logger("stage")


@dataclass
class StageDefinition:
    """Definition of a pipeline stage with metadata and dependencies"""

    name: str
    stage_class: Type["BasePipelineStage"]
    depends_on: List[str] = field(default_factory=list)
    produces_for: List[str] = field(default_factory=list)
    required: bool = True
    description: str = ""

    def __post_init__(self):
        """Validate stage definition"""
        if not self.name:
            raise ValueError("Stage name cannot be empty")
        if not self.stage_class:
            raise ValueError("Stage class cannot be None")


class StageRegistry:
    """Registry for managing pipeline stage definitions"""

    def __init__(self):
        self._stages: Dict[str, StageDefinition] = {}
        self._initialized = False

    def register(self, definition: StageDefinition) -> None:
        """Register a stage definition"""
        if definition.name in self._stages:
            logger.warning(f"Overriding existing stage definition: {definition.name}")

        self._stages[definition.name] = definition
        logger.debug(f"Registered stage: {definition.name}")

    def get(self, name: str) -> Optional[StageDefinition]:
        """Get stage definition by name"""
        return self._stages.get(name)

    def list_all(self) -> List[StageDefinition]:
        """Get all registered stage definitions"""
        return list(self._stages.values())

    def list_names(self) -> List[str]:
        """Get all registered stage names"""
        return list(self._stages.keys())

    def exists(self, name: str) -> bool:
        """Check if stage is registered"""
        return name in self._stages

    def clear(self) -> None:
        """Clear all registered stages"""
        self._stages.clear()
        logger.debug("Cleared all stage registrations")


# Global registry instance
_registry = StageRegistry()


def register_stage(
    name: str,
    depends_on: Optional[List[str]] = None,
    produces_for: Optional[List[str]] = None,
    required: bool = True,
    description: str = "",
) -> Callable:
    """Decorator for registering pipeline stages"""

    def decorator(stage_class: Type["BasePipelineStage"]) -> Type["BasePipelineStage"]:
        definition = StageDefinition(
            name=name,
            stage_class=stage_class,
            depends_on=depends_on or [],
            produces_for=produces_for or [],
            required=required,
            description=description,
        )
        _registry.register(definition)
        return stage_class

    return decorator


def get_registry() -> StageRegistry:
    """Get the global stage registry"""
    return _registry


def get_stage_definition(name: str) -> Optional[StageDefinition]:
    """Get stage definition by name"""
    return _registry.get(name)


def list_registered_stages() -> List[str]:
    """List all registered stage names"""
    return _registry.list_names()


class StageRegistryMixin:
    """Mixin to provide registry access to pipeline components"""

    @property
    def registry(self) -> StageRegistry:
        """Get the stage registry"""
        return _registry

    def get_stage_def(self, name: str) -> Optional[StageDefinition]:
        """Get stage definition by name"""
        return self.registry.get(name)

    def stage_exists(self, name: str) -> bool:
        """Check if stage exists in registry"""
        return self.registry.exists(name)
