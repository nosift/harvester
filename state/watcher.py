#!/usr/bin/env python3

"""
Status loop management for continuous status updates and rendering.
Handles periodic status collection and display coordination.
"""

import threading
from typing import Any, Optional

from tools.logger import get_logger

logger = get_logger("status")


class StatusLooper:
    """Manages continuous status update and rendering loop"""

    def __init__(self, status_manager: Any, renderer: Any, update_interval: float = 5.0, render_interval: float = 1.0):
        """Initialize status looper

        Args:
            status_manager: Status manager for data collection
            renderer: Status renderer for display
            update_interval: Interval for status updates in seconds
            render_interval: Interval for rendering in seconds
        """
        self.status_manager = status_manager
        self.renderer = renderer
        self.update_interval = update_interval
        self.render_interval = render_interval

        self.running = False
        self.update_thread: Optional[threading.Thread] = None
        self.render_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    def start(self) -> None:
        """Start status update and render loops"""
        if self.running:
            logger.warning("Status looper already running")
            return

        logger.info("Starting status looper")
        self.running = True
        self.stop_event.clear()

        # Start update thread
        self.update_thread = threading.Thread(target=self._update_loop, name="status-updater", daemon=True)
        self.update_thread.start()

        # Start render thread
        self.render_thread = threading.Thread(target=self._render_loop, name="status-renderer", daemon=True)
        self.render_thread.start()

        logger.info("Status looper started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop status loops

        Args:
            timeout: Maximum time to wait for threads to stop
        """
        if not self.running:
            return

        logger.info("Stopping status looper")
        self.running = False
        self.stop_event.set()

        # Wait for threads to stop
        threads = [("update", self.update_thread), ("render", self.render_thread)]

        for name, thread in threads:
            if thread and thread.is_alive():
                try:
                    thread.join(timeout=timeout / len(threads))
                    if thread.is_alive():
                        logger.warning(f"Status {name} thread did not stop gracefully")
                    else:
                        logger.debug(f"Status {name} thread stopped")
                except Exception as e:
                    logger.error(f"Error stopping status {name} thread: {e}")

        logger.info("Status looper stopped")

    def _update_loop(self) -> None:
        """Main status update loop"""
        logger.debug("Status update loop started")

        try:
            while self.running and not self.stop_event.is_set():
                try:
                    self._update_status()
                except Exception as e:
                    logger.debug(f"Error in status update: {e}")

                # Wait for next update
                if self.stop_event.wait(timeout=self.update_interval):
                    break

        except Exception as e:
            logger.error(f"Fatal error in status update loop: {e}")
        finally:
            logger.debug("Status update loop ended")

    def _render_loop(self) -> None:
        """Main status render loop"""
        logger.debug("Status render loop started")

        try:
            while self.running and not self.stop_event.is_set():
                try:
                    self._render_status()
                except Exception as e:
                    logger.debug(f"Error in status render: {e}")

                # Wait for next render
                if self.stop_event.wait(timeout=self.render_interval):
                    break

        except Exception as e:
            logger.error(f"Fatal error in status render loop: {e}")
        finally:
            logger.debug("Status render loop ended")

    def _update_status(self) -> None:
        """Update status data from components"""
        if hasattr(self.status_manager, "update_status"):
            self.status_manager.update_status()
        elif hasattr(self.status_manager, "update"):
            self.status_manager.update()

    def _render_status(self) -> None:
        """Render current status"""
        if hasattr(self.renderer, "render"):
            self.renderer.render()
        elif hasattr(self.renderer, "update"):
            self.renderer.update()

    def is_running(self) -> bool:
        """Check if status looper is running

        Returns:
            bool: True if looper is active
        """
        return self.running

    def get_status(self) -> dict:
        """Get current status information

        Returns:
            dict: Status information
        """
        return {
            "running": self.running,
            "update_interval": self.update_interval,
            "render_interval": self.render_interval,
            "update_thread_alive": self.update_thread.is_alive() if self.update_thread else False,
            "render_thread_alive": self.render_thread.is_alive() if self.render_thread else False,
        }
