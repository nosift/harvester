#!/usr/bin/env python3

"""
Status Manager for Monitor Package

This module provides the single entry point for all status monitoring and display operations.
It replaces all scattered display methods throughout the system.
"""


from tools.logger import get_logger
from tools.utils import handle_exceptions

from .collector import StatusCollector
from .config import DisplayConfigManager
from .display import DisplayConfig, StatusDisplayEngine
from .models import DisplayMode, StatusContext, SystemStatus

logger = get_logger("state")


class StatusManager:
    """
    Unified Status Manager - Single entry point for all status operations

    This class replaces all scattered display methods:
    - monitoring.print_status()
    - application.print_status()
    - task_manager._print_progress()
    - main.print_stats()
    - StatusDisplayService.display_status()
    """

    def __init__(self, task_manager=None, monitoring=None, application=None):
        """Initialize with optional component references"""
        self.task_manager = task_manager
        self.monitoring = monitoring
        self.application = application

        # Initialize components
        self.data_collector = StatusCollector(task_manager, monitoring, application)
        self.display_engine = StatusDisplayEngine()
        self.config_manager = DisplayConfigManager()

        # Cache for performance
        self._last_status = None
        self._last_update = 0.0

        logger.debug("Initialized StatusManager")

    def show_status(
        self,
        context: StatusContext = StatusContext.SYSTEM,
        mode: DisplayMode = DisplayMode.STANDARD,
        force_refresh: bool = False,
        **options,
    ) -> None:
        """
        Single entry point for all status display operations

        Args:
            context: Display context (system, monitoring, application, etc.)
            mode: Display mode (compact, standard, detailed, etc.)
            force_refresh: Force data refresh (bypass cache)
            **options: Additional display options
        """
        try:

            # 1. Collect system status
            try:
                system_status = self.data_collector.status(force_refresh)
            except Exception as e:
                raise

            # 2. Get display configuration
            try:
                display_config = self._get_display_config(context, mode, **options)
            except Exception as e:
                raise

            # 3. Render status
            try:
                self.display_engine.render(system_status, display_config)
            except Exception as e:
                raise

            # 4. Cache for future use
            self._last_status = system_status
            self._last_update = system_status.timestamp

        except Exception as e:
            logger.error(f"Status display failed: {e}")
            self._show_emergency_status(context, mode)

    def get_system_status(self, force_refresh: bool = False) -> SystemStatus:
        """Get current system status without displaying it"""
        return self.data_collector.status(force_refresh)

    @handle_exceptions(default_result=False, log_level="error")
    def is_system_healthy(self) -> bool:
        """Check if system is in healthy state"""
        status = self.get_system_status()
        return status.is_healthy()

    @handle_exceptions(default_result=[], log_level="error")
    def get_critical_alerts(self) -> list:
        """Get list of critical alerts"""
        status = self.get_system_status()
        return status.critical_alerts()

    def show_compact_status(self, context: StatusContext = StatusContext.SYSTEM) -> None:
        """Convenience method for compact status display"""
        self.show_status(context, DisplayMode.COMPACT)

    def show_detailed_status(self, context: StatusContext = StatusContext.SYSTEM) -> None:
        """Convenience method for detailed status display"""
        self.show_status(context, DisplayMode.DETAILED)

    def show_monitoring_status(self, detailed: bool = False) -> None:
        """Convenience method for monitoring status display"""
        mode = DisplayMode.DETAILED if detailed else DisplayMode.MONITORING
        self.show_status(StatusContext.MONITORING, mode)

    def show_application_status(self, detailed: bool = False) -> None:
        """Convenience method for application status display"""
        mode = DisplayMode.DETAILED if detailed else DisplayMode.APPLICATION
        self.show_status(StatusContext.APPLICATION, mode)

    def show_task_manager_progress(self) -> None:
        """Convenience method for task manager progress display"""
        self.show_status(StatusContext.TASK_MANAGER, DisplayMode.COMPACT)

    def show_main_stats(self) -> None:
        """Convenience method for main script stats display"""
        self.show_status(StatusContext.MAIN, DisplayMode.STANDARD)

    def update_components(self, task_manager=None, monitoring=None, application=None) -> None:
        """Update component references"""
        if task_manager is not None:
            self.task_manager = task_manager
            self.data_collector.task_manager = task_manager

        if monitoring is not None:
            self.monitoring = monitoring
            self.data_collector.monitoring = monitoring

        if application is not None:
            self.application = application
            self.data_collector.application = application

        logger.debug("Updated StatusManager components")

    def clear_cache(self) -> None:
        """Clear all cached data"""
        self.data_collector.clear_cache()
        self._last_status = None
        self._last_update = 0.0
        logger.debug("StatusManager cache cleared")

    def _get_display_config(self, context: StatusContext, mode: DisplayMode, **options) -> DisplayConfig:
        """Get display configuration for the given context and mode"""
        try:
            # Get base configuration from config manager
            display_config = self.config_manager.config(context, mode)

            # Create display config with overrides
            config = DisplayConfig(
                context=context,
                mode=mode,
                title=display_config.title,
                show_workers=display_config.workers,
                show_alerts=display_config.alerts,
                show_performance=display_config.performance,
                show_newline_prefix=display_config.newline,
                **options,
            )

            return config

        except Exception as e:
            logger.debug(f"Error getting display config: {e}")
            # Return default config
            return DisplayConfig(context=context, mode=mode, **options)

    def _show_emergency_status(self, context: StatusContext, mode: DisplayMode) -> None:
        """Show emergency status when main display fails"""
        try:
            lines = [
                "=" * 60,
                f"{'Emergency Status Display':^60}",
                "=" * 60,
                f"Context: {context.value}",
                f"Mode: {mode.value}",
                "Status display system encountered an error.",
                "Basic system information:",
            ]

            # Try to get basic info
            if self.task_manager:
                lines.append("  Task Manager: Available")
            else:
                lines.append("  Task Manager: Not available")

            if self.monitoring:
                lines.append("  Monitoring: Available")
            else:
                lines.append("  Monitoring: Not available")

            if self.application:
                lines.append("  Application: Available")
            else:
                lines.append("  Application: Not available")

            lines.append("=" * 60)

            for line in lines:
                logger.info(line)

        except Exception as e:
            logger.error(f"Emergency status display also failed: {e}")
            logger.info("=" * 40)
            logger.info("CRITICAL: Status system failure")
            logger.info("=" * 40)
