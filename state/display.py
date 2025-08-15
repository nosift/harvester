#!/usr/bin/env python3

"""
Status Display Engine for Monitor Package

This module provides unified rendering for all status display needs.
It replaces the scattered display logic throughout the system.
"""

from dataclasses import dataclass
from typing import List

from config import get_config
from tools.logger import get_logger

from .models import AlertLevel, DisplayMode, StatusContext, SystemStatus

logger = get_logger("state")


@dataclass
class DisplayConfig:
    """Display configuration for rendering"""

    context: StatusContext
    mode: DisplayMode
    title: str
    workers: bool
    alerts: bool
    performance: bool
    newline: bool

    @classmethod
    def create(cls, context: StatusContext, mode: DisplayMode, **overrides) -> "DisplayConfig":
        """Create display configuration from unified config system"""
        try:
            config = get_config()
            context_configs = config.display.contexts.get(context.value, {})
            mode_config = context_configs.get(mode.value)

            if mode_config:
                base_config = {
                    "title": mode_config.title,
                    "workers": mode_config.show_workers,
                    "alerts": mode_config.show_alerts,
                    "performance": mode_config.show_performance,
                    "newline": mode_config.show_newline_prefix,
                }
            else:
                base_config = cls._get_defaults(context, mode)

        except Exception as e:
            logger.debug(f"Config load failed, using defaults: {e}")
            base_config = cls._get_defaults(context, mode)

        # Apply overrides
        final_config = {**base_config, **overrides}

        return cls(
            context=context,
            mode=mode,
            title=final_config["title"],
            workers=final_config["workers"],
            alerts=final_config["alerts"],
            performance=final_config["performance"],
            newline=final_config["newline"],
        )

    @staticmethod
    def _get_defaults(context: StatusContext, mode: DisplayMode) -> dict:
        """Get default configuration values"""
        titles = {
            StatusContext.SYSTEM: "System Status",
            StatusContext.TASK_MANAGER: "Task Manager Status",
            StatusContext.MONITORING: "Pipeline Monitoring",
            StatusContext.APPLICATION: "Application Status",
            StatusContext.MAIN: "Pipeline Status",
        }

        return {
            "title": titles.get(context, "Status"),
            "workers": mode not in [DisplayMode.COMPACT, DisplayMode.SUMMARY],
            "alerts": mode in [DisplayMode.DETAILED, DisplayMode.MONITORING],
            "performance": mode in [DisplayMode.DETAILED, DisplayMode.MONITORING],
            "newline": mode in [DisplayMode.DETAILED, DisplayMode.MONITORING],
        }


class StatusDisplayEngine:
    """
    Unified display engine that renders SystemStatus in various formats.
    Replaces all scattered display logic.
    """

    def render(self, status: SystemStatus, config: DisplayConfig) -> None:
        """Main rendering entry point"""
        try:
            # Choose renderer based on mode
            if config.mode == DisplayMode.COMPACT:
                self._render_compact(status, config)
            elif config.mode == DisplayMode.SUMMARY:
                self._render_summary(status, config)
            elif config.mode == DisplayMode.MONITORING:
                self._render_monitoring(status, config)
            elif config.mode == DisplayMode.DETAILED:
                self._render_detailed(status, config)
            else:  # STANDARD
                self._render_standard(status, config)

        except Exception as e:
            logger.error(f"Display rendering failed: {e}")
            self._render_fallback(status, config)

    def _render_compact(self, status: SystemStatus, config: DisplayConfig) -> None:
        """Render compact single-line format"""
        lines = []

        # Compact header
        lines.append("=" * 60)
        lines.append(f"{config.title:^60}")
        lines.append("=" * 60)

        # Compact pipeline info
        if status.has_pipeline_data():
            queue_total = status.queues.total_queued
            lines.append(f"Queues: {queue_total} | Runtime: {status.runtime:.1f}s")

        # Compact provider info
        if status.has_provider_data():
            for provider_name, provider in status.providers.items():
                abbrev = provider.abbreviations()  # Updated method name
                lines.append(
                    f"{provider_name:>10} [{abbrev}]: "
                    f"valid={provider.keys.valid:>3}, "
                    f"links={provider.resources.links:>4}"
                )

        lines.append("=" * 60)

        # Output
        for line in lines:
            logger.info(line)

    def _render_summary(self, status: SystemStatus, config: DisplayConfig) -> None:
        """Render brief summary format"""
        lines = []

        # Summary header
        lines.append("=" * 70)
        lines.append(f"{config.title:^70}")
        lines.append("=" * 70)

        # System summary
        lines.append(f"State: {status.state.value.title()} | Runtime: {status.runtime:.1f}s")

        if status.tasks.total > 0:
            lines.append(
                f"Tasks: {status.tasks.completed}/{status.tasks.total} " f"({status.tasks.success_rate:.1%} success)"
            )

        if status.keys.total > 0:
            lines.append(f"Keys: {status.keys.valid} valid, {status.keys.total} total")

        # Active providers summary - updated method name
        active_providers = status.active_providers()
        if active_providers:
            provider_names = [p.name for p in active_providers]
            lines.append(f"Active Providers: {', '.join(provider_names)}")

        lines.append("=" * 70)

        # Output
        for line in lines:
            logger.info(line)

    def _render_standard(self, status: SystemStatus, config: DisplayConfig) -> None:
        """Render standard multi-line format"""
        lines = []

        # Standard header
        lines.append("=" * 80)
        lines.append(f"{config.title:^80}")
        lines.append("=" * 80)

        # Debug logging for troubleshooting
        logger.debug(f"Rendering standard display - Context: {config.context}, Title: {config.title}")
        logger.debug(
            f"Pipeline data available: {status.has_pipeline_data()}, stages: {len(status.pipeline.stages) if status.pipeline else 0}"
        )
        logger.debug(
            f"Provider data available: {status.has_provider_data()}, providers: {len(status.providers) if status.providers else 0}"
        )

        # Pipeline section
        if status.has_pipeline_data():
            lines.extend(self._format_pipeline_section(status, config))
            lines.append("-" * 80)
        else:
            lines.append("No pipeline data available")
            lines.append("-" * 80)

        # Provider section
        if status.has_provider_data():
            lines.extend(self._format_provider_section(status, config))
        else:
            lines.append("No provider data available")

        # Performance section
        if config.performance and status.performance.throughput > 0:
            lines.append("-" * 80)
            lines.extend(self._format_performance_section(status, config))

        # Alerts section
        if config.alerts and status.has_alerts():
            lines.append("-" * 80)
            lines.extend(self._format_alerts_section(status, config))

        lines.append("=" * 80)

        # Output with compact formatting for stage tables
        for line in lines:
            if config.newline and line.startswith("="):
                logger.info("\n" + line)
            else:
                logger.info(line)

    def _render_monitoring(self, status: SystemStatus, config: DisplayConfig) -> None:
        """Render monitoring-specific format with performance data"""
        lines = []

        # Monitoring header with performance summary
        lines.append("=" * 80)
        lines.append(f"{config.title:^80}")
        lines.append("=" * 80)

        # Performance summary
        lines.append(
            f"Runtime: {status.runtime:.1f}s | "
            f"Throughput: {status.performance.throughput:.1f} tasks/sec | "
            f"Success: {status.performance.success_rate:.1%}"
        )

        if config.workers:
            lines.append(
                f"Workers: {status.workers.active}/{status.workers.total} active | "
                f"Queues: {status.queues.total_queued} total"
            )

        lines.append("-" * 80)

        # Detailed pipeline metrics
        if status.has_pipeline_data():
            lines.extend(self._format_pipeline_section(status, config))
            lines.append("-" * 80)

        # Provider performance metrics
        if status.has_provider_data():
            lines.extend(self._format_provider_monitoring_section(status, config))

        # Always show alerts in monitoring mode
        if status.has_alerts():
            lines.append("-" * 80)
            lines.extend(self._format_alerts_section(status, config))

        lines.append("=" * 80)

        # Output
        for line in lines:
            logger.info(line)

    def _render_detailed(self, status: SystemStatus, config: DisplayConfig) -> None:
        """Render detailed format with all information"""
        # Create detailed config with all sections enabled
        detailed_config = DisplayConfig.create(
            config.context,
            config.mode,
            title=config.title,
            workers=True,
            alerts=True,
            performance=True,
            newline=config.newline,
        )

        self._render_standard(status, detailed_config)

        # Add extra detailed sections
        lines = []

        # System health section
        lines.append("-" * 80)
        lines.append("System Health:")
        lines.append(f"  Overall Status: {'Healthy' if status.healthy() else 'Issues Detected'}")
        lines.append(f"  Error Rate: {status.performance.error_rate:.1%}")
        lines.append(f"  Critical Alerts: {len(status.critical_alerts())}")

        # Resource utilization
        if status.workers.total > 0:
            lines.append(f"  Worker Utilization: {status.workers.utilization:.1%}")

        lines.append("=" * 80)

        # Output additional sections
        for line in lines:
            logger.info(line)

    def _render_fallback(self, status: SystemStatus, config: DisplayConfig) -> None:
        """Render fallback display when main rendering fails"""
        lines = [
            "=" * 60,
            f"{'Status':^60}",
            "=" * 60,
            f"System State: {status.state.value}",
            f"Runtime: {status.runtime:.1f} seconds",
            f"Providers: {len(status.providers)}",
            "=" * 60,
        ]

        for line in lines:
            logger.info(line)

    def _format_pipeline_section(self, status: SystemStatus, config: DisplayConfig) -> List[str]:
        """Format pipeline section with table-like layout"""
        lines = []

        if not status.pipeline.stages:
            lines.append("No pipeline data available")
            return lines

        # Table header
        if config.workers:
            lines.append(f"{'Stage':<10} | {'Queue':<8} | {'Processed':<10} | {'Errors':<8} | {'Workers':<8}")
            lines.append("-" * 80)

        # Table rows
        for stage_name, stage_metrics in status.pipeline.stages.items():
            queue_size = getattr(stage_metrics, "queue_size", 0)
            processed = getattr(stage_metrics, "total_processed", 0)
            errors = getattr(stage_metrics, "total_errors", 0)
            workers = getattr(stage_metrics, "workers", 0)

            if config.workers:
                lines.append(f"{stage_name:<10} | {queue_size:<8} | {processed:<10} | {errors:<8} | {workers:<8}")
            else:
                lines.append(f"{stage_name:>10}: queue={queue_size:<4}, processed={processed:<6}, errors={errors}")

        return lines

    def _format_provider_section(self, status: SystemStatus, config: DisplayConfig) -> List[str]:
        """Format provider section with table-like layout"""
        lines = []

        if not status.providers:
            lines.append("No provider data available")
            return lines

        # Table header
        lines.append(
            f"{'Provider':<12} | {'Valid':<6} | {'No Quota':<9} | {'Wait':<6} | {'Invalid':<8} | {'Links':<6} | {'Mode':<10}"
        )
        lines.append("-" * 80)

        # Table rows
        for provider_name, provider in status.providers.items():
            abbrev = provider.abbreviations()
            lines.append(
                f"{provider_name:<12} | {provider.keys.valid:<6} | "
                f"{provider.keys.no_quota:<9} | {provider.keys.wait_check:<6} | "
                f"{provider.keys.invalid:<8} | {provider.resources.links:<6} | "
                f"{abbrev:<10}"
            )

        return lines

    def _format_provider_monitoring_section(self, status: SystemStatus, config: DisplayConfig) -> List[str]:
        """Format provider section with monitoring metrics"""
        lines = []

        for provider_name, provider in status.providers.items():
            abbrev = provider.abbreviations()
            success_rate = provider.keys.success_rate * 100

            lines.append(
                f"{provider_name:<12} [{abbrev:>8}] | "
                f"Valid: {provider.keys.valid:>4} | "
                f"Rate: {success_rate:>5.1f}% | "
                f"Links: {provider.resources.links:>5} | "
                f"API: {provider.success_rate:.1%}"
            )

        return lines

    def _format_performance_section(self, status: SystemStatus, config: DisplayConfig) -> List[str]:
        """Format performance metrics section"""
        lines = [
            "Performance Metrics:",
            f"  Throughput: {status.performance.throughput:.2f} tasks/sec",
            f"  Success Rate: {status.performance.success_rate:.1%}",
            f"  Error Rate: {status.performance.error_rate:.1%}",
        ]

        if status.performance.avg_response_time > 0:
            lines.append(f"  Avg Response Time: {status.performance.avg_response_time:.2f}s")

        return lines

    def _format_alerts_section(self, status: SystemStatus, config: DisplayConfig) -> List[str]:
        """Format alerts section"""
        lines = ["Alerts:"]

        # Group alerts by level
        critical_alerts = [a for a in status.alerts if a.level == AlertLevel.CRITICAL]
        error_alerts = [a for a in status.alerts if a.level == AlertLevel.ERROR]
        warning_alerts = [a for a in status.alerts if a.level == AlertLevel.WARNING]
        info_alerts = [a for a in status.alerts if a.level == AlertLevel.INFO]

        if critical_alerts:
            lines.append(f"  CRITICAL ({len(critical_alerts)}):")
            for alert in critical_alerts[:3]:  # Show max 3
                lines.append(f"    - {alert.message}")

        if error_alerts:
            lines.append(f"  ERROR ({len(error_alerts)}):")
            for alert in error_alerts[:3]:  # Show max 3
                lines.append(f"    - {alert.message}")

        if warning_alerts:
            lines.append(f"  WARNING ({len(warning_alerts)}):")
            for alert in warning_alerts[:3]:  # Show max 3
                lines.append(f"    - {alert.message}")

        if info_alerts and config.mode == DisplayMode.DETAILED:
            lines.append(f"  INFO ({len(info_alerts)}):")
            for alert in info_alerts[:2]:  # Show max 2
                lines.append(f"    - {alert.message}")

        # If no alerts of any level, show a message
        if not (critical_alerts or error_alerts or warning_alerts or info_alerts):
            lines.append("  No alerts")

        return lines
