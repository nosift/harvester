#!/usr/bin/env python3

"""
Base classes for thread lifecycle management in manager components.
"""

import threading
from abc import ABC, abstractmethod
from typing import Optional

from tools.logger import get_logger

logger = get_logger("manager")


class LifecycleManager(ABC):
    """Base class for components that manage lifecycle."""

    def __init__(self, name: str):
        """
        Initialize lifecycle manager.

        Args:
            name: Component name for logging
        """
        self.name = name
        self.running = False

        # External completion tracking
        self._externally_finished = False

        # Thread safety
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the component."""
        with self._lock:
            if self.running:
                logger.warning(f"{self.name} already running")
                return

            self.running = True

            # Component-specific initialization
            self._on_start()

            logger.info(f"Started {self.name}")

    def stop(self, timeout: Optional[float] = None) -> None:
        """Stop the component."""
        if not self.running:
            return

        with self._lock:
            self.running = False

            # Component-specific cleanup
            self._on_stop()

        # Final cleanup
        self._on_stopped()

        logger.info(f"Stopped {self.name}")

    def is_finished(self) -> bool:
        """Check if component is finished."""
        return not self.running or self._externally_finished

    def mark_finished(self) -> None:
        """Mark component as finished by external signal."""
        self._externally_finished = True
        logger.info(f"{self.name} marked as finished externally")

    @property
    def is_running(self) -> bool:
        """Check if component is currently running."""
        return self.running

    def _on_start(self) -> None:
        """Hook called during start."""
        pass

    def _on_stop(self) -> None:
        """Hook called during stop."""
        pass

    def _on_stopped(self) -> None:
        """Hook called after component has stopped."""
        pass


class ThreadManager(LifecycleManager):
    """Base class for components that manage background threads."""

    def __init__(self, name: str, shutdown_timeout: float = 5.0, daemon: bool = True):
        """
        Initialize thread manager.

        Args:
            name: Component name for logging
            shutdown_timeout: Maximum time to wait for graceful shutdown
            daemon: Whether the thread should be daemon
        """
        # Initialize parent class
        super().__init__(name)

        # Thread-specific configuration
        self.shutdown_timeout = max(1.0, float(shutdown_timeout))
        self.daemon = daemon

        # Thread management
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the background thread if not already running."""
        with self._lock:
            if self.running:
                logger.warning(f"{self.name} is already running")
                return

            self.running = True
            self._externally_finished = False
            self._stop_event.clear()

            # Component-specific initialization
            self._on_start()

            # Create and start thread
            self._thread = threading.Thread(
                target=self._thread_wrapper, name=f"{self.name.lower()}-thread", daemon=self.daemon
            )
            self._thread.start()

            logger.info(f"Started {self.name}")

    def stop(self, timeout: Optional[float] = None) -> None:
        """Stop the background thread gracefully."""
        if not self.running:
            return

        stop_timeout = timeout or self.shutdown_timeout

        with self._lock:
            self.running = False
            self._stop_event.set()

            # Component-specific cleanup
            self._on_stop()

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=stop_timeout)
            if self._thread.is_alive():
                logger.warning(f"{self.name} thread did not stop gracefully")

        # Final cleanup
        self._on_stopped()

        logger.info(f"Stopped {self.name}")

    def _thread_wrapper(self) -> None:
        """Wrapper for main thread loop with error handling."""
        try:
            self._main_loop()
        except Exception as e:
            logger.error(f"Error in {self.name} thread: {e}")
        finally:
            logger.debug(f"{self.name} thread finished")

    @abstractmethod
    def _main_loop(self) -> None:
        """Main thread loop implementation."""
        pass


class PeriodicTaskManager(ThreadManager):
    """Base class for components that perform periodic tasks."""

    def __init__(self, name: str, interval: float, shutdown_timeout: float = 5.0):
        """
        Initialize periodic task manager.

        Args:
            name: Component name for logging
            interval: Interval between task executions in seconds
            shutdown_timeout: Maximum time to wait for graceful shutdown
        """
        super().__init__(name, shutdown_timeout)
        self.interval = max(0.1, float(interval))

    def _main_loop(self) -> None:
        """Main loop that executes periodic tasks."""
        while self.running:
            try:
                # Execute the periodic task
                self._execute_periodic_task()

                # Wait until next execution or stop signal
                if self.running:
                    self._stop_event.wait(timeout=self.interval)

            except Exception as e:
                logger.error(f"Error in {self.name} periodic task: {e}")
                # Brief wait before retrying to avoid tight error loops
                if self.running:
                    self._stop_event.wait(timeout=min(1.0, self.interval))

    @abstractmethod
    def _execute_periodic_task(self) -> None:
        """Execute the periodic task."""
        pass


class ConditionalTaskManager(ThreadManager):
    """Base class for components that respond to conditions."""

    def __init__(self, name: str, check_interval: float = 1.0, shutdown_timeout: float = 5.0):
        """
        Initialize conditional task manager.

        Args:
            name: Component name for logging
            check_interval: Interval between condition checks in seconds
            shutdown_timeout: Maximum time to wait for graceful shutdown
        """
        super().__init__(name, shutdown_timeout)
        self.check_interval = max(0.1, float(check_interval))

    def _main_loop(self) -> None:
        """Main loop that checks conditions and responds to events."""
        while self.running:
            try:
                # Check conditions and handle events
                if self._should_execute():
                    self._handle_condition()

                # Wait until next check or stop signal
                if self.running:
                    self._stop_event.wait(timeout=self.check_interval)

            except Exception as e:
                logger.error(f"Error in {self.name} condition handling: {e}")
                # Brief wait before retrying
                if self.running:
                    self._stop_event.wait(timeout=min(1.0, self.check_interval))

    @abstractmethod
    def _should_execute(self) -> bool:
        """Check if condition should be handled."""
        pass

    @abstractmethod
    def _handle_condition(self) -> None:
        """Handle the detected condition."""
        pass
