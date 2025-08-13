#!/usr/bin/env python3

"""
Dependency resolution engine for pipeline stages.
Calculates stage creation order and validates dependency chains.
"""

from typing import Dict, List

from stage.registry import StageDefinition, StageRegistry
from tools.logger import get_logger

logger = get_logger("stage")


class CircularDependencyError(Exception):
    """Raised when circular dependencies are detected"""

    pass


class MissingDependencyError(Exception):
    """Raised when required dependencies are missing"""

    pass


class DependencyResolver:
    """Resolves stage dependencies and calculates creation order"""

    def __init__(self, registry: StageRegistry):
        self.registry = registry

    def resolve_order(self, requested_stages: List[str]) -> List[str]:
        """
        Resolve stage creation order based on dependencies.
        Returns stages in the order they should be created.
        """
        # Get all stage definitions
        all_stages = {stage.name: stage for stage in self.registry.list_all()}

        # Filter to only requested stages that exist
        available_stages = {}
        for name in requested_stages:
            if name in all_stages:
                available_stages[name] = all_stages[name]
            else:
                logger.warning(f"Requested stage '{name}' not found in registry")

        if not available_stages:
            return []

        # Add dependencies recursively
        needed_stages = self._collect_dependencies(available_stages, all_stages)

        # Perform topological sort
        ordered_stages = self._topological_sort(needed_stages)

        logger.info(f"Resolved stage order: {ordered_stages}")
        return ordered_stages

    def validate_dependencies(self, stages: List[str]) -> bool:
        """Validate that all dependencies can be satisfied"""
        try:
            self.resolve_order(stages)
            return True
        except (CircularDependencyError, MissingDependencyError):
            return False

    def get_dependencies(self, stage_name: str) -> List[str]:
        """Get direct dependencies of a stage"""
        definition = self.registry.get(stage_name)
        return definition.depends_on if definition else []

    def get_dependents(self, stage_name: str) -> List[str]:
        """Get stages that depend on the given stage"""
        dependents = []
        for definition in self.registry.list_all():
            if stage_name in definition.depends_on:
                dependents.append(definition.name)
        return dependents

    def _collect_dependencies(
        self, requested: Dict[str, StageDefinition], all_stages: Dict[str, StageDefinition]
    ) -> Dict[str, StageDefinition]:
        """Recursively collect all required dependencies"""
        needed = requested.copy()
        to_process = list(requested.keys())

        while to_process:
            current = to_process.pop(0)
            definition = needed[current]

            for dep_name in definition.depends_on:
                if dep_name not in needed:
                    if dep_name in all_stages:
                        needed[dep_name] = all_stages[dep_name]
                        to_process.append(dep_name)
                        logger.debug(f"Added dependency: {dep_name} for {current}")
                    else:
                        raise MissingDependencyError(
                            f"Stage '{current}' depends on '{dep_name}' which is not registered"
                        )

        return needed

    def _topological_sort(self, stages: Dict[str, StageDefinition]) -> List[str]:
        """Perform topological sort to determine creation order"""
        # Build adjacency list and in-degree count
        graph = {}
        in_degree = {}

        for name in stages:
            graph[name] = []
            in_degree[name] = 0

        for name, definition in stages.items():
            for dep in definition.depends_on:
                if dep in graph:  # Only consider dependencies that are in our stage set
                    graph[dep].append(name)
                    in_degree[name] += 1

        # Kahn's algorithm
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for circular dependencies
        if len(result) != len(stages):
            remaining = set(stages.keys()) - set(result)
            raise CircularDependencyError(f"Circular dependency detected among stages: {remaining}")

        return result

    def build_dependency_graph(self, stages: List[str]) -> Dict[str, Dict[str, List[str]]]:
        """Build a complete dependency graph for visualization/debugging"""
        ordered_stages = self.resolve_order(stages)

        graph = {"nodes": ordered_stages, "dependencies": {}, "dependents": {}}

        for stage in ordered_stages:
            graph["dependencies"][stage] = self.get_dependencies(stage)
            graph["dependents"][stage] = [dep for dep in ordered_stages if stage in self.get_dependencies(dep)]

        return graph
