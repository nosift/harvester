#!/usr/bin/env python3

"""
Shutdown coordination for graceful application termination.
Manages component shutdown sequence and completion monitoring.
"""

import threading
import time
from typing import List, Optional

from tools.logger import get_logger

from .base import LifecycleManager

logger = get_logger("manager")


class ShutdownCoordinator:
    """Coordinates graceful shutdown of application components"""

    def __init__(
        self,
        components: List[LifecycleManager],
        shutdown_timeout: float = 30.0,
        monitor_interval: float = 2.0,
    ):
        """Initialize shutdown coordinator

        Args:
            components: List of components to shutdown
            shutdown_timeout: Total timeout for shutdown process
            monitor_interval: Interval between completion checks in seconds
        """
        self.components = components
        self.shutdown_timeout = max(1.0, shutdown_timeout)
        self.monitor_interval = max(0, monitor_interval)
        self.shutdown_event = threading.Event()
        self.completion_thread: Optional[threading.Thread] = None
        self.completion_stop = threading.Event()

    def start_completion_monitor(self, interval: Optional[float] = None) -> None:
        """Start completion monitoring thread

        Args:
            interval: Override monitor interval for this session (optional)
        """
        if self.completion_thread and self.completion_thread.is_alive():
            logger.warning("Completion monitor already running")
            return

        # Use provided interval or default
        if interval is not None and interval > 0:
            self.monitor_interval = interval
            logger.info(f"Using custom monitor interval: {interval}s")

        self.completion_stop.clear()
        self.completion_thread = threading.Thread(
            target=self._completion_monitor_loop,
            name="completion-monitor",
            daemon=False,  # Non-daemon to ensure graceful shutdown
        )
        self.completion_thread.start()
        logger.info(f"Started completion monitoring thread, interval: {self.monitor_interval}s")

    def stop_completion_monitor(self) -> None:
        """Stop completion monitoring thread"""
        if not self.completion_thread or not self.completion_thread.is_alive():
            return

        logger.info("Stopping completion monitoring thread")
        self.completion_stop.set()

        try:
            self.completion_thread.join(timeout=5.0)
            if self.completion_thread.is_alive():
                logger.warning("Completion monitor thread did not stop gracefully")
            else:
                logger.info("Completion monitor thread stopped")
        except Exception as e:
            logger.error(f"Error stopping completion monitor: {e}")

    def _completion_monitor_loop(self) -> None:
        """Monitor completion status and trigger shutdown when done"""
        try:
            while not self.completion_stop.is_set():
                # Check if all components are finished
                all_finished = True
                for component in self.components:
                    if not component.is_finished():
                        all_finished = False
                        break

                if all_finished:
                    logger.info("All components finished, triggering shutdown")
                    self.shutdown_event.set()
                    break

                # Wait before next check
                if self.completion_stop.wait(timeout=self.monitor_interval):
                    break

        except Exception as e:
            logger.error(f"Error in completion monitor: {e}")

    def graceful_shutdown(self) -> bool:
        """Perform graceful shutdown of all components

        Returns:
            bool: True if shutdown completed successfully
        """
        logger.info("Starting graceful shutdown")
        start_time = time.time()

        # Stop completion monitoring first
        self.stop_completion_monitor()

        # Calculate timeout per component
        component_timeout = self.shutdown_timeout / max(len(self.components), 1)

        success = True
        for i, component in enumerate(self.components):
            component_name = component.__class__.__name__

            try:
                logger.info(f"Stopping component {i+1}/{len(self.components)}: {component_name}")
                component.stop()

                # Wait for component to stop
                timeout_start = time.time()
                while time.time() - timeout_start < component_timeout:
                    # Check if component is still running
                    if not component.is_running:
                        break
                    time.sleep(0.1)
                else:
                    logger.warning(f"Component {component_name} did not stop within timeout")
                    success = False

                logger.info(f"Component {component_name} stopped")

            except Exception as e:
                logger.error(f"Error stopping component {component_name}: {e}")
                success = False

        elapsed = time.time() - start_time
        if success:
            logger.info(f"Graceful shutdown completed successfully in {elapsed:.1f}s")
        else:
            logger.warning(f"Graceful shutdown completed with errors in {elapsed:.1f}s")

        return success

    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """Wait for completion signal

        Args:
            timeout: Maximum time to wait

        Returns:
            bool: True if completion was signaled
        """
        return self.shutdown_event.wait(timeout=timeout)

    def signal_shutdown(self) -> None:
        """Signal shutdown request"""
        logger.info("Shutdown signal received")
        self.shutdown_event.set()

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested

        Returns:
            bool: True if shutdown was requested
        """
        return self.shutdown_event.is_set()
