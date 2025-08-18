#!/usr/bin/env python3

"""
Task Recovery Strategy - Enhanced Task Recovery Management

This module provides enhanced task recovery functionality using type-safe
stage management and configuration-driven approach.
"""

from typing import Any, Dict, List, Optional

from config.schemas import Patterns
from core.enums import PipelineStage
from core.models import AllRecoveredTasks, RecoveredTasks
from stage.factory import TaskFactory
from tools.logger import get_logger
from tools.utils import handle_exceptions

logger = get_logger("storage")


class TaskRecoveryStrategy:
    """Enhanced task recovery strategy using type-safe stage management"""

    def __init__(self, pipeline: Any, providers: Dict[str, Any]):
        """Initialize recovery strategy

        Args:
            pipeline: Pipeline instance
            providers: Dictionary of provider instances
        """
        self.pipeline = pipeline
        self.providers = providers

    def recover_queue_tasks(self, queue_tasks: Dict[str, List[Any]]) -> None:
        """Recover queue tasks using stage registry

        Args:
            queue_tasks: Dictionary mapping stage names to task lists
        """
        if not queue_tasks:
            return

        logger.info("Starting queue task recovery")

        for stage_name, tasks in queue_tasks.items():
            if not tasks:
                continue

            # Validate stage name using enum
            stage_enum = self._get_stage_enum(stage_name)
            if not stage_enum:
                logger.warning(f"Unknown stage name: {stage_name}")
                continue

            # Get stage instance from pipeline
            stage = self.pipeline.get_stage(stage_enum.value)
            if not stage:
                logger.warning(f"Stage not found: {stage_name}")
                continue

            # Recover tasks to stage
            for task in tasks:
                try:
                    stage.put_task(task)
                    logger.debug(f"Recovered task to {stage_name}: {task}")
                except Exception as e:
                    logger.error(f"Failed to recover task to {stage_name}: {e}")

        logger.info(f"Queue task recovery completed for {len(queue_tasks)} stages")

    def recover_result_tasks(self, result_tasks: AllRecoveredTasks) -> None:
        """Recover result tasks with stage enum validation

        Args:
            result_tasks: All recovered tasks data
        """
        if not result_tasks or not result_tasks.providers:
            return

        logger.info("Starting result task recovery")

        for provider_name, provider_tasks in result_tasks.providers.items():
            if provider_name not in self.providers:
                logger.warning(f"Provider not found: {provider_name}")
                continue

            self._recover_provider_tasks(provider_name, provider_tasks)

        logger.info(f"Result task recovery completed for {len(result_tasks.providers)} providers")

    def _recover_provider_tasks(self, provider_name: str, tasks: RecoveredTasks) -> None:
        """Recover tasks for specific provider

        Args:
            provider_name: Name of the provider
            tasks: Recovered tasks for the provider
        """
        config = self._get_provider_config(provider_name)
        if not config:
            logger.warning(f"No config found for provider: {provider_name}")
            return

        # Recover check tasks (Service objects can be used directly)
        if self._stage_enabled(config, PipelineStage.CHECK.value):
            self._recover_check_tasks(provider_name, tasks.check, tasks.invalid)

        # Recover acquisition tasks (URLs need to be converted to AcquisitionTask objects)
        if self._stage_enabled(config, PipelineStage.GATHER.value):
            self._recover_acquisition_tasks(provider_name, tasks.acquisition)

    def _recover_stage_tasks(self, stage: PipelineStage, provider_name: str, tasks: List[Any]) -> None:
        """Recover tasks for specific stage using enum

        Args:
            stage: Pipeline stage enum
            provider_name: Name of the provider
            tasks: List of tasks to recover
        """
        if not tasks:
            return

        stage_instance = self.pipeline.get_stage(stage.value)
        if not stage_instance:
            logger.warning(f"Stage not found: {stage.value}")
            return

        recovered_count = 0
        for task in tasks:
            try:
                stage_instance.put_task(task)
                recovered_count += 1
            except Exception as e:
                logger.error(f"Failed to recover {stage.value} task for {provider_name}: {e}")

        if recovered_count > 0:
            logger.info(f"Recovered {recovered_count} {stage.value} tasks for {provider_name}")

    def _recover_check_tasks(self, provider_name: str, check_tasks: List[Any], invalid_keys: set) -> None:
        """Recover check tasks with invalid key filtering

        Args:
            provider_name: Name of the provider
            check_tasks: List of Service objects for check tasks
            invalid_keys: Set of invalid Service objects to filter out
        """
        if not check_tasks:
            return

        stage_instance = self.pipeline.get_stage(PipelineStage.CHECK.value)
        if not stage_instance:
            logger.warning("Check stage not found")
            return

        filtered_count = 0
        recovered_count = 0

        for service in check_tasks:
            try:
                # Filter out invalid keys
                if service in invalid_keys:
                    filtered_count += 1
                    continue

                # Create check task
                check_task = TaskFactory.create_check_task(provider_name, service)
                stage_instance.put_task(check_task)
                recovered_count += 1

            except Exception as e:
                logger.error(f"Failed to create check task for {provider_name}: {e}")

        if filtered_count > 0:
            logger.info(f"Filtered {filtered_count} invalid check tasks for {provider_name}")
        if recovered_count > 0:
            logger.info(f"Recovered {recovered_count} check tasks for {provider_name}")

    def _recover_acquisition_tasks(self, name: str, acquisition_tasks: List[str]) -> None:
        """Recover acquisition tasks by creating AcquisitionTask objects from URLs

        Args:
            provider_name: Name of the provider
            acquisition_tasks: List of URL strings for acquisition tasks
        """
        if not acquisition_tasks:
            return

        stage_instance = self.pipeline.get_stage(PipelineStage.GATHER.value)
        if not stage_instance:
            logger.warning("Acquisition stage not found")
            return

        # Get provider patterns
        provider = self.providers.get(name)
        if not provider:
            logger.warning(f"Provider not found: {name}")
            return

        patterns = self._get_provider_patterns(provider)
        recovered_count = 0

        for url in acquisition_tasks:
            try:
                # Create acquisition task with patterns
                acquisition_task = TaskFactory.create_acquisition_task(name, url, patterns)
                stage_instance.put_task(acquisition_task)
                recovered_count += 1

            except Exception as e:
                logger.error(f"Failed to create acquisition task for {name}: {e}")

        if recovered_count > 0:
            logger.info(f"Recovered {recovered_count} acquisition tasks for {name}")

    def _get_provider_patterns(self, provider: Any) -> Patterns:
        """Extract patterns from provider conditions

        Args:
            provider: Provider object

        Returns:
            Patterns object with extracted patterns
        """
        patterns = Patterns()

        # Use first condition's patterns if available
        if hasattr(provider, "conditions") and provider.conditions:
            return provider.conditions[0].patterns

        return patterns

    @handle_exceptions(default_result=None, log_level="warning")
    def _get_stage_enum(self, stage_name: str) -> Optional[PipelineStage]:
        """Get stage enum from string name safely

        Args:
            stage_name: String stage name

        Returns:
            PipelineStage enum or None if not found
        """
        return PipelineStage(stage_name)

    def _get_provider_config(self, name: str) -> Optional[Any]:
        """Get provider configuration

        Args:
            provider_name: Name of the provider

        Returns:
            Provider configuration or None
        """
        provider = self.providers.get(name)
        if not provider:
            return None

        # Try to get config from provider or use provider itself
        return getattr(provider, "config", provider)

    def _stage_enabled(self, config: Any, stage_name: str) -> bool:
        """Check if stage is enabled for provider

        Args:
            config: Provider configuration
            stage_name: Name of the stage

        Returns:
            True if stage is enabled
        """
        if not config:
            return False

        # Check various possible config structures
        if hasattr(config, "stages"):
            stages = config.stages
            if isinstance(stages, dict):
                return stages.get(stage_name, False)
            elif isinstance(stages, list):
                return stage_name in stages

        # Check direct stage attributes
        stage_attr = f"{stage_name}_enabled"
        if hasattr(config, stage_attr):
            return getattr(config, stage_attr, False)

        # Default to enabled if no specific config found
        return True
