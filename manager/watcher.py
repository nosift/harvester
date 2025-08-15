#!/usr/bin/env python3

"""
Status loop management for continuous status updates and rendering.
Handles periodic status collection and display coordination.
"""

import time
from typing import Any

from manager.base import PeriodicTaskManager
from state.models import DisplayMode, StatusContext
from tools.logger import get_logger

logger = get_logger("manager")


class StatusLooper(PeriodicTaskManager):
    """Manages continuous status update and rendering loop"""

    def __init__(
        self,
        status_manager: Any,
        display_style: str = "classic",
        update_interval: float = 5.0,
        render_interval: float = 1.0,
        context: StatusContext = StatusContext.SYSTEM,
        mode: DisplayMode = DisplayMode.STANDARD,
    ):
        """Initialize status looper

        Args:
            status_manager: Status manager for data collection
            display_style: Display style ("classic" or "detailed")
            update_interval: Interval for status updates in seconds
            render_interval: Interval for rendering in seconds
            context: Status context for rendering
            mode: Display mode for rendering
        """
        # Initialize base class with the shorter interval for responsiveness
        super().__init__("StatusLooper", min(update_interval, render_interval))

        self.status_manager = status_manager
        self.display_style = display_style
        self.update_interval = update_interval
        self.render_interval = render_interval
        self.context = context
        self.mode = mode

        # Track timing for different operations
        self.last_update_time = 0.0
        self.last_render_time = 0.0

    def _on_start(self) -> None:
        """Initialize status looper when starting"""
        self.last_update_time = 0.0
        self.last_render_time = 0.0

    def _on_stop(self) -> None:
        """Cleanup when stopping status looper"""
        pass

    def _execute_periodic_task(self) -> None:
        """Execute periodic status update and render tasks"""
        current_time = time.time()

        # Check if it's time to update status
        if current_time - self.last_update_time >= self.update_interval:
            try:
                self._update_status()
                self.last_update_time = current_time
            except Exception as e:
                logger.debug(f"Error in status update: {e}")

        # Check if it's time to render status
        if current_time - self.last_render_time >= self.render_interval:
            try:
                self._render_status()
                self.last_render_time = current_time
            except Exception as e:
                logger.debug(f"Error in status render: {e}")

    def _update_status(self) -> None:
        """Update status data from components"""
        if hasattr(self.status_manager, "update_status"):
            self.status_manager.update_status()
        elif hasattr(self.status_manager, "update"):
            self.status_manager.update()

    def _render_status(self) -> None:
        """Render current status"""
        if self.display_style == "classic":
            # Classic style: force MAIN context with STANDARD mode
            self.status_manager.show_status(StatusContext.MAIN, DisplayMode.STANDARD, force_refresh=True)
        else:
            # Detailed style: use provided context and mode
            self.status_manager.show_status(self.context, self.mode or DisplayMode.DETAILED)

    def get_status(self) -> dict:
        """Get current status information

        Returns:
            dict: Status information
        """
        return {
            "running": self.running,
            "update_interval": self.update_interval,
            "render_interval": self.render_interval,
            "last_update_time": self.last_update_time,
            "last_render_time": self.last_render_time,
            "thread_alive": self._thread.is_alive() if self._thread else False,
        }
