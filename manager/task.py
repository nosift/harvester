#!/usr/bin/env python3

"""
Task manager for coordinating multi-provider pipeline processing.
Creates provider instances from configuration and manages task distribution.
"""

import copy
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

import constant
from config import load_config
from config.schemas import Config, TaskConfig
from constant.system import PATTERN_KEY
from core.models import Condition, ProviderPatterns, TaskRecoveryInfo
from core.tasks import ProviderTask, SearchTask
from core.types import Provider
from search import client
from search.provider.base import BaseProvider
from search.provider.registry import GlobalProviderRegistry
from stage.base import StageUtils
from stage.factory import TaskFactory
from state.builder import StatusBuilder
from state.models import ProviderStatus, SystemState, SystemStatus
from state.status import StatusManager
from storage.recovery import TaskRecoveryStrategy
from tools.coordinator import get_session, get_token
from tools.logger import get_logger
from tools.utils import get_service_name

from .pipeline import Pipeline

logger = get_logger("manager")


class CompletionEventManager:
    """Simple completion event manager for task completion notifications"""

    def __init__(self):
        self._listeners: Set[Callable[[], None]] = set()
        self._lock = threading.Lock()
        self._completion_notified = False

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Add completion event listener"""
        with self._lock:
            self._listeners.add(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        """Remove completion event listener"""
        with self._lock:
            self._listeners.discard(callback)

    def notify_completion(self) -> None:
        """Notify all listeners of completion"""
        with self._lock:
            if self._completion_notified:
                return

            success = True
            for callback in self._listeners:
                try:
                    callback()
                except Exception as e:
                    success = False
                    logger.error(f"Error in completion callback: {e}")

            self._completion_notified = success

    @property
    def is_notified(self) -> bool:
        """Check if completion has been notified"""
        with self._lock:
            return self._completion_notified


@dataclass
class ConditionConfig:
    """Configuration for a single condition"""

    query: str = ""
    pattern: str = ""


class ProviderFactory:
    """Factory for creating provider instances from configuration"""

    @staticmethod
    def create_provider(task_config: TaskConfig, conditions: List[Condition]) -> BaseProvider:
        """Create provider instance using global registry"""
        provider_type = task_config.provider_type
        name = task_config.name
        api_config = task_config.api
        extras = task_config.extras

        # Prepare parameters for provider creation
        kwargs = extras or {}
        kwargs["default_model"] = api_config.default_model

        # Add specific parameters for openai_like providers
        if provider_type == "openai_like":
            kwargs.update(
                {
                    "name": name,
                    "base_url": api_config.base_url,
                    "completion_path": getattr(api_config, "completion_path", ""),
                    "model_path": getattr(api_config, "model_path", ""),
                }
            )

        # Use global registry for all providers
        return GlobalProviderRegistry.create(provider_type, conditions=conditions, **kwargs)


class TaskManager:
    """Main task manager for multi-provider coordination"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.providers: Dict[str, Provider] = {}
        self.pipeline: Optional[Pipeline] = None
        self.running = False
        self.start_time = time.time()

        # Cache for provider stages to avoid duplicate construction
        self._cached_provider_stages = None
        self._config_hash = None

        # Status manager for unified status display
        self._status_manager = None

        # Completion event manager
        self.completion_events = CompletionEventManager()

        # Initialize providers
        self._initialize_providers()

        # Create pipeline
        self._create_pipeline()

        logger.info(f"Initialized task manager with {len(self.providers)} providers")

    def _get_provider_stages(self) -> List[ProviderStatus]:
        """Get provider status information with caching to avoid duplicate construction"""
        # Create a simple hash of the configuration to detect changes
        config_str = str(
            [
                (
                    task.name,
                    task.enabled,
                    task.stages.search,
                    task.stages.gather,
                    task.stages.check,
                    task.stages.inspect,
                )
                for task in self.config.tasks
            ]
        )
        current_hash = hash(config_str)

        # Return cached result if configuration hasn't changed
        if self._cached_provider_stages is not None and self._config_hash == current_hash:
            return self._cached_provider_stages

        # Rebuild cache
        provider_stages = []
        for task_config in self.config.tasks:
            if task_config.enabled and task_config.name in self.providers:
                provider_status = ProviderStatus(
                    name=task_config.name,
                    enabled=task_config.enabled,
                    searchable=task_config.stages.search,
                    gatherable=task_config.stages.gather,
                    checkable=task_config.stages.check,
                    inspectable=task_config.stages.inspect,
                )
                provider_stages.append(provider_status)

        # Update cache
        self._cached_provider_stages = provider_stages
        self._config_hash = current_hash

        return provider_stages

    def get_status_manager(self) -> StatusManager:
        """Get or create status manager instance"""
        if self._status_manager is None:
            self._status_manager = StatusManager(task_manager=self)
        return self._status_manager

    def _initialize_providers(self) -> None:
        """Initialize all enabled providers from configuration"""
        for task_config in self.config.tasks:
            if not task_config.enabled:
                logger.info(f"Skipping disabled provider: {task_config.name}")
                continue

            try:
                # Parse conditions with flexible regex support
                conditions = self._parse_conditions(task_config)

                if not conditions:
                    logger.warning(f"No valid conditions for provider {task_config.name}, skipping")
                    continue

                # Create provider instance
                provider = ProviderFactory.create_provider(task_config, conditions)
                self.providers[task_config.name] = provider

                # Log provider creation with stage information
                enabled_stages = StageUtils.get_enabled(task_config)

                logger.info(
                    f"Created provider: {task_config.name} ({task_config.provider_type}) "
                    f"with {len(conditions)} conditions, stages: [{', '.join(enabled_stages)}]"
                )

            except Exception as e:
                logger.error(f"Failed to create provider {task_config.name}: {e}")
                continue

        if not self.providers:
            raise ValueError("No valid providers configured")

    def _parse_conditions(self, task: TaskConfig) -> List[Condition]:
        """Parse flexible condition configuration from task config

        Args:
            task: Task configuration containing conditions and patterns

        Returns:
            List[Condition]: List of parsed condition objects
        """
        conditions: List[Condition] = []
        global_pattern = task.patterns.key_pattern

        for condition_data in task.conditions:
            # Convert dict to typed config
            config = self._parse_condition_config(condition_data, global_pattern)

            if config.pattern:  # pattern is required, query is optional
                conditions.append(Condition(regex=config.pattern, query=config.query))
            else:
                logger.warning(f"Invalid condition (missing regex pattern): {condition_data}")

        return conditions

    def _parse_condition_config(self, condition_data: Dict[str, Any], global_pattern: str) -> ConditionConfig:
        """Parse condition data into typed config"""
        query = condition_data.get("query", "")
        # Use condition-specific pattern if provided, otherwise use global pattern
        pattern = condition_data.get(PATTERN_KEY, global_pattern)

        return ConditionConfig(query=query, pattern=pattern)

    def _create_pipeline(self) -> None:
        """Create pipeline with all components"""
        # Add provider-specific rate limits
        rate_limits = self.config.rate_limits.copy()

        for task_config in self.config.tasks:
            if task_config.enabled:
                service_name = get_service_name(task_config.name)
                rate_limits[service_name] = task_config.rate_limit

        # Create runtime config with provider rate limits (avoid mutating original config)
        runtime_config = copy.deepcopy(self.config)
        runtime_config.rate_limits = rate_limits

        self.pipeline = Pipeline(runtime_config, self.providers)

        logger.info("Created pipeline with all providers")

    def start(self) -> None:
        """Start the task manager and pipeline"""
        if self.running:
            return

        # 1. Start pipeline (creates ResultManager without backup)
        self.pipeline.start()

        # 2. Recover queue tasks
        recoverd_tasks = self.pipeline.queue_manager.load_all_queues()

        # 3. Filter recovered tasks by stage configuration
        undo_tasks = self._filter_recovery(recoverd_tasks)

        # 4. Recover result file tasks (material.txt, links.txt) and invalid keys
        old_tasks = self.pipeline.result_manager.recover_all_tasks()

        # 5. Add recovered tasks to appropriate queues
        recovery_info = TaskRecoveryInfo(
            queue_tasks=undo_tasks,
            result_tasks=old_tasks,
            total_queue_tasks=sum(len(tasks) for tasks in undo_tasks.values()),
            total_result_tasks=old_tasks.total_check_tasks() + old_tasks.total_acquisition_tasks(),
        )
        self._add_recovered_tasks(recovery_info)

        # 6. Backup existing files (after recovery is complete)
        self.pipeline.result_manager.backup_all_existing_files()

        # 7. Add initial search tasks
        initial_tasks = self._create_initial_tasks()
        if initial_tasks:
            self.pipeline.add_initial_tasks(initial_tasks)

        self.running = True

        # Log recovery and startup info
        logger.info(
            f"Started task manager: {recovery_info.total_queue_tasks} queue tasks, {recovery_info.total_result_tasks} result tasks, {len(initial_tasks)} initial tasks"
        )

    def stop(self, timeout: float = 30.0) -> None:
        """Stop the task manager gracefully"""
        if not self.running:
            return

        self.running = False

        if self.pipeline:
            self.pipeline.stop(timeout)

        logger.info("Stopped task manager")

    def add_completion_listener(self, callback: Callable[[], None]) -> None:
        """Add completion event listener"""
        self.completion_events.add_listener(callback)

    def remove_completion_listener(self, callback: Callable[[], None]) -> None:
        """Remove completion event listener"""
        self.completion_events.remove_listener(callback)

    def is_finished(self) -> bool:
        """Check if task manager is finished processing all tasks"""
        if not self.running:
            return True

        if not self.pipeline:
            return True

        finished = self.pipeline.is_finished()

        # Send completion event once when finished
        if finished and not self.completion_events.is_notified:
            self.completion_events.notify_completion()
            logger.info("TaskManager finished, notified other components")

        return finished

    def get_stats(self) -> SystemStatus:
        """Get current task manager statistics using enhanced StatusBuilder"""

        # Use StatusBuilder for clean, maintainable status construction
        builder = StatusBuilder()

        # Set basic system information
        runtime = time.time() - self.start_time if self.start_time > 0 else 0
        state = SystemState.RUNNING if self.running else SystemState.STOPPED
        builder.with_basic_info(runtime, state)

        # Set providers information
        builder.with_providers_info(self.providers)

        # Set pipeline statistics if available
        if self.pipeline:
            builder.with_pipeline_stats(self.pipeline)

            # Set result statistics using enhanced aggregator
            if self.pipeline.result_manager:
                result_stats = self.pipeline.result_manager.get_all_stats()
                builder.with_result_stats(result_stats)

        # Set provider stage configurations
        builder.with_provider_stages(self._get_provider_stages())

        # Set additional compatibility data
        builder.with_additional_data(github_stats=client.get_github_stats())

        return builder.build()

    def _create_initial_tasks(self) -> List[SearchTask]:
        """Create initial search tasks for all providers"""
        tasks = []

        for task_config in self.config.tasks:
            if not task_config.enabled:
                continue

            if not task_config.stages.search:
                logger.info(f"Skipping initial search tasks for provider {task_config.name} - search stage disabled")
                continue

            # Check if we have GitHub credentials
            try:
                # Try to get either token or session to verify availability
                has_token = get_token() is not None
                has_session = get_session() is not None
                if not has_token and not has_session:
                    logger.warning(
                        f"Skipping search for provider {task_config.name} as no github token or session is provided"
                    )
                    continue
            except Exception:
                logger.warning(
                    f"Skipping search for provider {task_config.name} as no github token or session is provided"
                )
                continue

            provider = self.providers.get(task_config.name)
            if not provider:
                continue

            for condition in provider.conditions:
                # Create search task for each condition
                task = TaskFactory.create_search_task(
                    provider=task_config.name,
                    query=condition.query or condition.regex,
                    regex=condition.regex,
                    page=1,
                    use_api=task_config.use_api,
                    address_pattern=task_config.patterns.address_pattern
                    or provider.extras.get(constant.PATTERN_ADDRESS, ""),
                    endpoint_pattern=task_config.patterns.endpoint_pattern
                    or provider.extras.get(constant.PATTERN_ENDPOINT, ""),
                    model_pattern=task_config.patterns.model_pattern or provider.extras.get(constant.PATTERN_MODEL, ""),
                )
                tasks.append(task)

        # Log summary of initial task creation
        if tasks:
            providers_with_tasks = set(task.provider for task in tasks)
            logger.info(
                f"Created {len(tasks)} initial search tasks for {len(providers_with_tasks)} providers: {', '.join(providers_with_tasks)}"
            )
        else:
            logger.info(
                "No initial search tasks created - all providers have search stage disabled or missing credentials"
            )

        return tasks

    def _add_recovered_tasks(self, recovery_info: TaskRecoveryInfo) -> None:
        """Add recovered tasks using enhanced TaskRecoveryStrategy"""

        # Use TaskRecoveryStrategy for type-safe, maintainable task recovery
        recovery_strategy = TaskRecoveryStrategy(self.pipeline, self.providers)

        # Recover queue tasks using enhanced strategy
        recovery_strategy.recover_queue_tasks(recovery_info.queue_tasks)

        # Recover result tasks using enhanced strategy
        recovery_strategy.recover_result_tasks(recovery_info.result_tasks)

    def _get_provider_patterns(self, provider: BaseProvider) -> ProviderPatterns:
        """Extract patterns from provider conditions"""
        patterns = ProviderPatterns()

        # Use first condition's regex as key pattern
        if provider.conditions:
            patterns.key_pattern = provider.conditions[0].regex

        return patterns

    def _filter_recovery(self, recovered: Dict[str, List[ProviderTask]]) -> Dict[str, List[ProviderTask]]:
        """Filter recovered tasks based on stage configuration"""
        filtered = {}

        for stage, tasks in recovered.items():
            valid_tasks = []
            for task in tasks:
                if not task or task.provider not in self.providers:
                    continue

                config = self._get_config(task.provider)
                if config and self._stage_enabled(config, stage):
                    valid_tasks.append(task)
                else:
                    logger.debug(f"Skipping recovery of {stage} task for provider {task.provider} - stage disabled")

            if valid_tasks:
                filtered[stage] = valid_tasks

        return filtered

    def _get_config(self, provider: str) -> Optional[TaskConfig]:
        """Get task config for provider"""
        return next((t for t in self.config.tasks if t.name == provider), None)

    def _stage_enabled(self, config: TaskConfig, stage: str) -> bool:
        """Check if stage is enabled for task"""
        return getattr(config.stages, stage, False)


def create_task_manager(config_file: str = constant.DEFAULT_CONFIG_FILE) -> TaskManager:
    """Factory function to create task manager from configuration"""
    config = load_config(config_file)
    if not config:
        return None

    return TaskManager(config)


if __name__ == "__main__":
    # Test task manager creation
    try:
        # Create task manager
        manager = create_task_manager()

        logger.info(f"Created task manager with providers: {list(manager.providers.keys())}")

        # Test provider creation
        for name, provider in manager.providers.items():
            logger.info(f"  {name}: {provider.__class__.__name__} with {len(provider.conditions)} conditions")

        # Test stats
        stats = manager.get_stats()
        logger.info(f"Manager stats: {stats.providers}")

        logger.info("Task manager test completed!")

    except Exception as e:
        logger.error(f"Task manager test failed: {e}")
        traceback.print_exc()
