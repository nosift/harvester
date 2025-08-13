#!/usr/bin/env python3

"""
Configuration Validator

This module provides comprehensive validation for configuration objects.
It ensures configuration completeness, correctness, and consistency.

Key Features:
- Type validation
- Business rule validation
- Dependency checking
- Error reporting
"""

from typing import List

from .schemas import Config, LoadBalanceStrategy


class ConfigValidator:
    """Configuration validator with comprehensive checks"""

    def __init__(self):
        """Initialize configuration validator"""
        self.errors: List[str] = []

    def validate(self, config: Config) -> None:
        """Validate complete configuration

        Args:
            config: Configuration object to validate

        Raises:
            ValueError: If validation fails
        """
        self.errors.clear()

        # Validate global configuration
        self._validate_global_config(config)

        # Validate pipeline configuration
        self._validate_pipeline_config(config)

        # Validate stats configuration
        self._validate_stats_config(config)

        # Validate monitoring configuration
        self._validate_monitoring_config(config)

        # Validate tasks configuration
        self._validate_tasks_config(config)

        # Validate worker manager configuration
        self._validate_worker_manager_config(config)

        # Validate rate limits
        self._validate_rate_limits(config)

        # Check for validation errors
        if self.errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"- {error}" for error in self.errors)
            raise ValueError(error_msg)

    def _validate_global_config(self, config: Config) -> None:
        """Validate global configuration section

        Args:
            config: Configuration object
        """
        global_config = config.global_config

        # Validate workspace
        if not global_config.workspace:
            self.errors.append("Global workspace cannot be empty")

        # Validate GitHub credentials
        credentials = global_config.github_credentials
        if not credentials.sessions and not credentials.tokens:
            self.errors.append("At least one GitHub session or token must be provided")

        # Validate load balance strategy
        if credentials.strategy not in LoadBalanceStrategy:
            self.errors.append(f"Invalid load balance strategy: {credentials.strategy}")

        # Validate user agents
        if not global_config.user_agents:
            self.errors.append("At least one user agent must be provided")

        # Validate max retries
        if global_config.max_retries_requeued < 0:
            self.errors.append("Max retries requeued must be non-negative")

    def _validate_pipeline_config(self, config: Config) -> None:
        """Validate pipeline configuration section

        Args:
            config: Configuration object
        """
        pipeline = config.pipeline

        # Validate thread counts
        required_stages = {"search", "gather", "check", "inspect"}
        for stage in required_stages:
            if stage not in pipeline.threads:
                self.errors.append(f"Missing thread count for stage: {stage}")
            elif pipeline.threads[stage] <= 0:
                self.errors.append(f"Thread count for {stage} must be positive")

        # Validate queue sizes
        for stage in required_stages:
            if stage not in pipeline.queue_sizes:
                self.errors.append(f"Missing queue size for stage: {stage}")
            elif pipeline.queue_sizes[stage] <= 0:
                self.errors.append(f"Queue size for {stage} must be positive")

    def _validate_stats_config(self, config: Config) -> None:
        """Validate stats configuration section

        Args:
            config: Configuration object
        """
        stats = config.stats

        if stats.interval <= 0:
            self.errors.append("Stats interval must be positive")

    def _validate_monitoring_config(self, config: Config) -> None:
        """Validate monitoring configuration section

        Args:
            config: Configuration object
        """
        monitoring = config.monitoring

        if monitoring.update_interval <= 0:
            self.errors.append("Monitoring update interval must be positive")

        if not (0 <= monitoring.error_threshold <= 1):
            self.errors.append("Error threshold must be between 0 and 1")

        if monitoring.queue_threshold < 0:
            self.errors.append("Queue threshold must be non-negative")

        if monitoring.memory_threshold <= 0:
            self.errors.append("Memory threshold must be positive")

        if monitoring.response_threshold <= 0:
            self.errors.append("Response threshold must be positive")

    def _validate_tasks_config(self, config: Config) -> None:
        """Validate tasks configuration section

        Args:
            config: Configuration object
        """
        if not config.tasks:
            self.errors.append("At least one task must be configured")

        enabled_tasks = [task for task in config.tasks if task.enabled]
        if not enabled_tasks:
            self.errors.append("At least one task must be enabled")

        # Validate task names are unique
        task_names = [task.name for task in config.tasks if task.enabled]
        if len(task_names) != len(set(task_names)):
            self.errors.append("Task names must be unique")

        # Validate individual tasks
        for task in config.tasks:
            self._validate_task(task)

    def _validate_task(self, task) -> None:
        """Validate individual task configuration

        Args:
            task: Task configuration object
        """
        if not task.name:
            self.errors.append("Task name cannot be empty")

        if not task.provider_type:
            self.errors.append(f"Provider type cannot be empty for task: {task.name}")

        # Validate stage dependencies
        try:
            task.stages.validate()
        except ValueError as e:
            self.errors.append(f"Task {task.name} stage validation failed: {e}")

        # Validate API configuration if use_api is True
        if task.use_api:
            if not task.api.base_url:
                self.errors.append(f"API base URL required for task: {task.name}")

            if not task.api.default_model:
                self.errors.append(f"Default model required for API task: {task.name}")

        # Validate patterns
        if not task.patterns.key_pattern:
            self.errors.append(f"Key pattern required for task: {task.name}")

    def _validate_worker_manager_config(self, config: Config) -> None:
        """Validate worker manager configuration

        Args:
            config: Configuration object
        """
        worker_manager = config.worker_manager

        if worker_manager.min_workers < 1:
            self.errors.append("Worker manager min_workers must be at least 1")

        if worker_manager.max_workers < worker_manager.min_workers:
            self.errors.append("Worker manager max_workers must be >= min_workers")

        if worker_manager.target_queue_size < 0:
            self.errors.append("Worker manager target_queue_size must be non-negative")

        if worker_manager.adjustment_interval <= 0:
            self.errors.append("Worker manager adjustment_interval must be positive")

        if not (0 < worker_manager.scale_up_threshold < 1):
            self.errors.append("Worker manager scale_up_threshold must be between 0 and 1")

        if not (0 < worker_manager.scale_down_threshold < 1):
            self.errors.append("Worker manager scale_down_threshold must be between 0 and 1")

        if worker_manager.scale_down_threshold >= worker_manager.scale_up_threshold:
            self.errors.append("Worker manager scale_down_threshold must be < scale_up_threshold")

    def _validate_rate_limits(self, config: Config) -> None:
        """Validate rate limits configuration

        Args:
            config: Configuration object
        """
        for name, rate_limit in config.rate_limits.items():
            if rate_limit.base_rate <= 0:
                self.errors.append(f"Base rate must be positive for rate limit: {name}")

            if rate_limit.burst_limit <= 0:
                self.errors.append(f"Burst limit must be positive for rate limit: {name}")

            if not (0 < rate_limit.backoff_factor < 1):
                self.errors.append(f"Backoff factor must be between 0 and 1 for rate limit: {name}")

            if rate_limit.recovery_factor <= 1:
                self.errors.append(f"Recovery factor must be > 1 for rate limit: {name}")
