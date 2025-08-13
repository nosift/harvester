#!/usr/bin/env python3

"""
Main application class for the async pipeline system.
Integrates all components: task management, monitoring, load balancing, and graceful shutdown.
"""

import argparse
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Optional

import yaml

from config import load_config
from config.defaults import get_default_config
from config.schemas import Config, WorkerManagerConfig
from constant.runtime import StandardPipelineStage
from constant.system import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_SHUTDOWN_TIMEOUT,
    DEFAULT_STATS_INTERVAL,
)
from core.enums import SystemState
from manager.monitor import MultiProviderMonitoring, create_monitoring_system
from manager.shutdown import ShutdownCoordinator
from manager.task import TaskManager, create_task_manager
from manager.worker import WorkerManager, create_worker_manager
from state.models import (
    ApplicationStatus,
    DisplayMode,
    KeyMetrics,
    PipelineUpdate,
    QueueMetrics,
    ResourceMetrics,
    StatusContext,
    WorkerMetrics,
)
from state.renderer import AppStyleRenderer, MainStyleRenderer, StatusRenderer
from state.status import StatusManager
from state.watcher import StatusLooper
from tools.coordinator import init_managers
from tools.logger import flush_logs, get_logger, init_logging

logger = get_logger("main")


class AsyncPipelineApplication:
    """Main application class for the async pipeline system"""

    def __init__(self, config_path: str = DEFAULT_CONFIG_FILE) -> None:
        self.config_path = config_path
        self.config: Optional[Config] = None
        self.task_manager: Optional[TaskManager] = None
        self.monitoring: Optional[MultiProviderMonitoring] = None
        self.worker_manager: Optional[WorkerManager] = None
        self.status_manager: Optional[StatusManager] = None

        # Application state
        self.running = False
        self.start_time = 0.0

        # Enhanced shutdown control
        self.shutdown_event = threading.Event()
        self.force_shutdown = False
        self.signal_count = 0
        self.shutdown_lock = threading.Lock()

        # New coordinated components
        self.shutdown_coordinator: Optional[ShutdownCoordinator] = None
        self.status_looper: Optional[StatusLooper] = None

        # Statistics
        self.stats_display_interval = float(DEFAULT_STATS_INTERVAL)

        # Status rendering strategy (default to MainStyle per user preference)
        self.renderer: StatusRenderer = MainStyleRenderer()

        logger.info(f"Initialized application with config: {config_path}")

    def initialize(self) -> bool:
        """Initialize all application components"""
        try:
            # Load configuration
            self.config = load_config(self.config_path)
            logger.info("Configuration loaded successfully")

            # Initialize global resource managers
            init_managers()
            logger.info("Global resource managers initialized")

            # Create task manager
            self.task_manager = create_task_manager(self.config_path)
            logger.info(f"Task manager created with {len(self.task_manager.providers)} providers")

            # Create monitoring system using monitoring config
            monitoring_config = self.config.monitoring
            self.monitoring = create_monitoring_system(monitoring_config)
            logger.info("Monitoring system created")

            # Create worker manager
            worker_manager_config = WorkerManagerConfig(
                min_workers=self.config.worker_manager.min_workers,
                max_workers=self.config.worker_manager.max_workers,
                target_queue_size=self.config.worker_manager.target_queue_size,
                adjustment_interval=self.config.worker_manager.adjustment_interval,
                scale_up_threshold=self.config.worker_manager.scale_up_threshold,
                scale_down_threshold=self.config.worker_manager.scale_down_threshold,
                log_recommendations=self.config.worker_manager.log_recommendations,
            )
            self.worker_manager = create_worker_manager(
                worker_manager_config, shutdown_timeout=float(self.config.persistence.shutdown_timeout)
            )
            logger.info("Worker manager created")

            # Register pipeline stages with worker manager
            if self.task_manager.pipeline:
                pipeline = self.task_manager.pipeline
                for stage in StandardPipelineStage:
                    stage_instance = pipeline.get_stage(stage.value)
                    if stage_instance:
                        self.worker_manager.register_stage(stage.value, stage_instance)

            # Initialize unified status manager
            self.status_manager = StatusManager(
                task_manager=self.task_manager, monitoring=self.monitoring, application=self
            )
            logger.info("Status manager initialized")

            # Initialize shutdown coordinator
            components = [self.task_manager, self.worker_manager, self.monitoring]
            self.shutdown_coordinator = ShutdownCoordinator(
                components=components,
                shutdown_timeout=float(getattr(self.config.persistence, "shutdown_timeout", DEFAULT_SHUTDOWN_TIMEOUT)),
                monitor_interval=5.0,  # Check every 2 seconds by default
            )
            logger.info("Shutdown coordinator initialized")

            # Initialize status looper
            self.status_looper = StatusLooper(
                status_manager=self.status_manager,
                renderer=self.renderer,
                update_interval=self.stats_display_interval,
                render_interval=1.0,
            )
            logger.info("Status looper initialized")

            # Register completion event listeners
            self.task_manager.add_completion_listener(self.worker_manager._on_task_completion)
            self.task_manager.add_completion_listener(self.monitoring._on_task_completion)
            logger.info("Completion event listeners registered")

            logger.info("Application initialization completed")
            return True

        except Exception as e:
            logger.error(f"Application initialization failed: {e}")
            return False

    def run(self) -> bool:
        """Main run method with improved shutdown handling"""
        try:
            # Setup signal handlers first
            self._setup_signal_handlers()

            if not self.initialize():
                return False

            self.running = True
            self.start_time = time.time()

            # Start components with error handling
            try:
                logger.info("Starting application components...")
                self.monitoring.start()
                logger.debug("Monitoring started")

                self.worker_manager.start()
                logger.debug("Worker manager started")

                self.task_manager.start()
                logger.debug("Task manager started")

            except Exception as e:
                logger.error(f"Failed to start components: {e}")
                return False

            logger.info("Application started successfully. You can press Ctrl+C twice to stop gracefully")

            # Start coordinated components
            self.shutdown_coordinator.start_completion_monitor()
            self.status_looper.start()

            # Simplified main loop using shutdown coordinator
            while self.running:
                # Check for shutdown conditions
                if self.shutdown_event.is_set() or self.force_shutdown:
                    break

                # Check if shutdown coordinator signaled completion
                if self.shutdown_coordinator.is_shutdown_requested():
                    logger.info("Shutdown coordinator signaled completion")
                    break

                # Interruptible wait
                if self.shutdown_event.wait(timeout=0.5):
                    break

            logger.info("Main loop exited")
            return True

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received in main thread")
            self.shutdown_event.set()
            return False
        except Exception as e:
            logger.error(f"Application error: {e}")
            traceback.print_exc()
            return False
        finally:
            self._graceful_shutdown()

    def start(self) -> bool:
        """Start the application - deprecated, use run() instead"""
        logger.warning("start() method is deprecated, use run() instead")
        return self.run()

    def _graceful_shutdown(self) -> None:
        """Enhanced graceful shutdown using shutdown coordinator"""
        with self.shutdown_lock:
            if not self.running:
                return

            logger.info("Starting graceful shutdown...")
            self.running = False
            self.shutdown_event.set()

            # Stop status looper first
            if self.status_looper:
                self.status_looper.stop()

            # Use shutdown coordinator for graceful component shutdown
            if self.shutdown_coordinator:
                success = self.shutdown_coordinator.graceful_shutdown()
                if success:
                    logger.info("Graceful shutdown completed successfully")
                else:
                    logger.warning("Graceful shutdown completed with some errors")
            else:
                logger.warning("No shutdown coordinator available, using fallback")
                self._fallback_shutdown()

    def _fallback_shutdown(self) -> None:
        """Fallback shutdown method when coordinator is not available"""
        components = [
            ("task manager", self.task_manager),
            ("worker manager", self.worker_manager),
            ("monitoring", self.monitoring),
        ]

        for name, component in components:
            if component:
                try:
                    logger.info(f"Stopping {name}")
                    if hasattr(component, "stop"):
                        component.stop()
                    logger.info(f"{name} stopped")
                except Exception as e:
                    logger.error(f"Error stopping {name}: {e}")

    def _force_exit(self) -> None:
        """Force exit the application"""
        logger.warning("Force exiting application due to shutdown timeout")
        os._exit(1)

    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """Wait for application to complete processing using shutdown coordinator"""
        if not self.running or not self.shutdown_coordinator:
            return False

        try:
            return self.shutdown_coordinator.wait_for_completion(timeout)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received in wait_for_completion")
            self.shutdown_event.set()
            return False

    def get_status(self) -> ApplicationStatus:
        """Get comprehensive application status"""
        try:
            status = ApplicationStatus(
                shutdown_requested=self.shutdown_event.is_set(),
            )

            # Set inherited SystemStatus fields
            status.timestamp = time.time()
            status.runtime = time.time() - self.start_time if self.start_time > 0 else 0
            status.state = SystemState.RUNNING if self.running else SystemState.STOPPED

            # Get task manager status
            if self.task_manager:
                try:
                    status.task_manager_status = self.task_manager.get_stats()
                except Exception as e:
                    status.task_manager_status = {"error": str(e)}

            # Get monitoring status
            if self.monitoring:
                try:
                    status.monitoring_status = self.monitoring.summary()
                except Exception as e:
                    status.monitoring_status = {"error": str(e)}

            # Get worker manager status
            if self.worker_manager:
                try:
                    status.worker_manager_status = self.worker_manager.get_worker_stats()
                except Exception as e:
                    status.worker_manager_status = {"error": str(e)}

            return status
        except Exception:
            raise

    def _update_monitoring_stats(self) -> None:
        """Update monitoring system with current statistics"""
        if not self.monitoring or not self.task_manager:
            return

        try:
            # Get task manager stats
            tm_stats = self.task_manager.get_stats()

            # Update provider statistics
            if tm_stats.result_stats:
                for provider_name, result_stats in tm_stats.result_stats.items():
                    key_metrics = KeyMetrics(
                        valid=result_stats.valid_keys,
                        invalid=result_stats.invalid_keys,
                        no_quota=result_stats.no_quota_keys,
                        wait_check=result_stats.wait_check_keys,
                    )
                    resource_metrics = ResourceMetrics(
                        total_links=result_stats.total_links,
                        total_models=result_stats.total_models,
                    )

                    provider_update = type(
                        "ProviderUpdate",
                        (),
                        {
                            "valid_keys": key_metrics.valid,
                            "invalid_keys": key_metrics.invalid,
                            "no_quota_keys": key_metrics.no_quota,
                            "wait_check_keys": key_metrics.wait_check,
                            "total_links": resource_metrics.total_links,
                            "total_models": resource_metrics.total_models,
                        },
                    )()
                    self.monitoring.update_provider_stats(provider_name, provider_update)

            # Update pipeline statistics
            if tm_stats.pipeline_stats:
                pipeline_stats = tm_stats.pipeline_stats

                # Get stage stats safely
                search_stats = pipeline_stats.get_stage_stats(StandardPipelineStage.SEARCH.value)
                gather_stats = pipeline_stats.get_stage_stats(StandardPipelineStage.GATHER.value)
                check_stats = pipeline_stats.get_stage_stats(StandardPipelineStage.CHECK.value)
                inspect_stats = pipeline_stats.get_stage_stats(StandardPipelineStage.INSPECT.value)

                # Calculate total workers
                total_workers = 0
                if search_stats:
                    total_workers += search_stats.workers
                if gather_stats:
                    total_workers += gather_stats.workers
                if check_stats:
                    total_workers += check_stats.workers
                if inspect_stats:
                    total_workers += inspect_stats.workers

                queue_metrics = QueueMetrics(
                    search=search_stats.queue_size if search_stats else 0,
                    gather=gather_stats.queue_size if gather_stats else 0,
                    check=check_stats.queue_size if check_stats else 0,
                    inspect=inspect_stats.queue_size if inspect_stats else 0,
                )
                worker_metrics = WorkerMetrics(
                    active=total_workers,
                    total=total_workers,
                )

                is_finished = self.task_manager.pipeline.is_finished() if self.task_manager.pipeline else False
                pipeline_update = PipelineUpdate.from_metrics(queue_metrics, worker_metrics, is_finished)
                self.monitoring.update_pipeline_stats(pipeline_update)

        except Exception as e:
            logger.debug(f"Error updating monitoring stats: {e}")

    def _update_worker_manager_metrics(self) -> None:
        """Update worker manager with current metrics"""
        if not self.worker_manager or not self.task_manager:
            return

        try:
            tm_stats = self.task_manager.get_stats()

            if tm_stats.pipeline_stats:
                pipeline_stats = tm_stats.pipeline_stats

                # Update metrics for each stage that exists
                for stage in StandardPipelineStage:
                    stage_stats = pipeline_stats.get_stage_stats(stage.value)
                    if stage_stats:

                        metrics_update = WorkerMetrics(
                            stage_name=stage.value,
                            queue_size=stage_stats.queue_size,
                            current_workers=stage_stats.workers,
                            processing_rate=stage_stats.processing_rate,
                            avg_processing_time=0.0,
                        )
                        self.worker_manager.update_metrics(stage.value, metrics_update)

        except Exception as e:
            logger.debug(f"Error updating worker manager metrics: {e}")

    def _setup_signal_handlers(self) -> None:
        """Set up enhanced signal handlers for graceful and force shutdown"""

        def signal_handler(signum: int, frame: Optional[Any]) -> None:
            _ = frame  # Suppress unused parameter warning

            self.signal_count += 1

            if self.signal_count == 1:
                logger.info(f"Received signal {signum}, initiating graceful shutdown...")
                logger.info("Press Ctrl+C again within 5 seconds to force exit")
                self.shutdown_event.set()

                # Set up force exit timer for second signal
                def force_exit_on_second_signal():
                    time.sleep(5.0)
                    if self.signal_count >= 2:
                        logger.warning("Force exit due to repeated signals")
                        self._force_exit()

                force_timer = threading.Thread(target=force_exit_on_second_signal, daemon=True)
                force_timer.start()

            elif self.signal_count >= 2:
                logger.warning(f"Received signal {signum} again, forcing immediate exit...")
                self.force_shutdown = True
                self._force_exit()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


def validate_config(config_path: str) -> bool:
    """Validate configuration file exists and is readable"""
    try:
        config_file = Path(config_path)
        if not config_file.exists():
            print(f"Error: Configuration file '{config_path}' not found.")
            return False

        if not config_file.is_file():
            print(f"Error: '{config_path}' is not a file.")
            return False

        # Try to load the configuration
        try:
            load_config(config_path)
            print(f"Configuration file '{config_path}' is valid.")
            return True
        except Exception as e:
            print(f"Error: Invalid configuration file '{config_path}': {e}")
            return False
    except Exception as e:
        print(f"Error validating configuration: {e}")
        return False


def create_sample_config(output_path: str = DEFAULT_CONFIG_FILE) -> bool:
    """Create a sample configuration file using default configuration"""
    try:
        # Get default configuration
        config = get_default_config()

        # Create YAML content with comments
        content = yaml.dump(
            config,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
            allow_unicode=True,
        )

        output_file = Path(output_path)
        output_file.write_text(content, encoding="utf-8")
        print(f"Sample configuration created at: {output_path}")
        return True
    except Exception as e:
        print(f"Error creating sample configuration: {e}")
        return False


def setup_signal_handlers(app: "AsyncPipelineApplication") -> None:
    """Setup signal handlers for graceful shutdown"""

    def signal_handler(signum, _frame):
        """Handle shutdown signals gracefully"""
        signal_name = signal.Signals(signum).name
        print(f"\nReceived {signal_name} signal. Initiating graceful shutdown...")
        app.shutdown()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # On Windows, also handle SIGBREAK
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal_handler)


def create_application(config_path: str = DEFAULT_CONFIG_FILE, style: str = "classic") -> AsyncPipelineApplication:
    """Factory function to create application instance"""
    app = AsyncPipelineApplication(config_path)
    # Configure renderer based on style
    if str(style).lower() in ("classic", "main"):
        app.renderer = MainStyleRenderer()
    else:
        app.renderer = AppStyleRenderer()
    return app


if __name__ == "__main__":
    # Parse command line arguments first to handle special commands
    parser = argparse.ArgumentParser(
        description="Async Pipeline System for Multi-Provider API Key Discovery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Run with default config.yaml
  %(prog)s -c custom.yaml           # Run with custom config
  %(prog)s --validate               # Validate configuration
  %(prog)s --create-config          # Create sample configuration
  %(prog)s --log-level DEBUG        # Enable debug logging
  %(prog)s --timeout 300            # Set maximum runtime
        """,
    )

    parser.add_argument(
        "-c", "--config", default=DEFAULT_CONFIG_FILE, help=f"Configuration file path (default: {DEFAULT_CONFIG_FILE})"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    parser.add_argument("--timeout", type=float, help="Maximum runtime in seconds")

    parser.add_argument(
        "--stats-interval",
        type=float,
        default=float(DEFAULT_STATS_INTERVAL),
        help="Statistics display interval in seconds",
    )

    parser.add_argument("--validate", action="store_true", help="Validate configuration and exit")

    parser.add_argument("--create-config", action="store_true", help="Create sample configuration file and exit")

    parser.add_argument(
        "--style",
        choices=["classic", "detailed"],
        default="classic",
        help="Output style: classic (main-like) or detailed (application-like)",
    )

    args = parser.parse_args()

    # Handle special commands first
    if args.create_config:
        success = create_sample_config(args.config)
        sys.exit(0 if success else 1)

    if args.validate:
        success = validate_config(args.config)
        sys.exit(0 if success else 1)

    # Check if config file exists
    if not Path(args.config).exists():
        print(f"Error: Configuration file not found: {args.config}")
        print("Use --create-config to create a sample configuration")
        sys.exit(1)

    # Initialize logging with specified level
    init_logging(args.log_level)

    # Create and configure application
    app = create_application(args.config, style=args.style)
    app.stats_display_interval = args.stats_interval

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers(app)

    try:
        logger.info("Starting Async Pipeline Application")
        logger.info("=" * 60)

        # Run application with timeout handling
        if args.timeout:
            # Start timeout thread
            def timeout_handler():
                time.sleep(args.timeout)
                logger.warning(f"Processing timed out after {args.timeout} seconds")
                app.shutdown_event.set()

            timeout_thread = threading.Thread(target=timeout_handler, daemon=True)
            timeout_thread.start()

        # Run the application
        success = app.run()

        if success:
            if app.task_manager and app.task_manager.pipeline and app.task_manager.pipeline.is_finished():
                logger.info("Processing completed successfully!")
            elif args.timeout and app.shutdown_event.is_set():
                logger.info(f"Processing timed out after {args.timeout} seconds")
            else:
                logger.info("🛑 Processing stopped by user")
        else:
            logger.error("Application failed to run")

        # Print final status
        logger.info("Final Status:")
        try:
            if app.status_manager:
                app.status_manager.show_status(StatusContext.APPLICATION, DisplayMode.DETAILED)
        except Exception as e:
            logger.debug(f"Error showing final status: {e}")

    except KeyboardInterrupt:
        logger.info("🛑 Shutdown requested by user")

    except Exception as e:
        logger.error(f"Application error: {e}")
        traceback.print_exc()

    finally:
        logger.info("Shutting down...")
        try:
            # Ensure graceful shutdown is called
            app._graceful_shutdown()

            # Get final status
            status = app.get_status()
            logger.info(f"Summary: Runtime {status.runtime:.1f}s")

            if status.monitoring_status:
                monitoring_stats = status.monitoring_status
                if isinstance(monitoring_stats, dict):
                    logger.info(
                        f"Results: {monitoring_stats.get('total_valid_keys', 0)} valid keys, "
                        f"{monitoring_stats.get('total_links', 0)} links processed"
                    )
        except Exception as e:
            logger.warning(f"Could not retrieve final status: {e}")

        # Flush logs before exit
        try:
            flush_logs()
            logger.info("Logs flushed to disk")
        except Exception as e:
            logger.error(f"Error flushing logs: {e}")

        # Clean exit
        sys.exit(0)
