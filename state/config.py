#!/usr/bin/env python3

"""
Configuration Management for Monitor Package

This module provides unified configuration management for all display settings.
It integrates with the new unified configuration system and eliminates JSON files.
"""

import json
from pathlib import Path
from typing import Any, Dict

from config import get_config
from tools.logger import get_logger

from .display import DisplayConfig
from .models import DisplayMode, StatusContext

logger = get_logger("state")


class DisplayConfigManager:
    """
    Centralized configuration manager for all display settings.
    Uses the unified configuration system instead of separate JSON files.
    """

    def __init__(self):
        """Initialize with unified configuration system"""
        self._configs = {}
        self._load_from_unified_config()

        logger.debug(f"Initialized DisplayConfigManager with {len(self._configs)} configurations")

    def config(self, context: StatusContext, mode: DisplayMode, **overrides) -> "DisplayConfig":
        """Get display configuration for a specific context and mode"""
        # Build configuration key
        config_key = f"{context.value}_{mode.value}"

        # Get base configuration
        base_config = self._configs.get(config_key, self._get_default_config(context, mode))

        # Apply any overrides
        final_config = {**base_config, **overrides}

        return DisplayConfig(
            context=context,
            mode=mode,
            title=final_config.get("title", ""),
            show_workers=final_config.get("show_workers", True),
            show_alerts=final_config.get("show_alerts", True),
            show_performance=final_config.get("show_performance", False),
            show_newline_prefix=final_config.get("show_newline_prefix", False),
        )

    def set_config(self, context: StatusContext, mode: DisplayMode, config: Dict[str, Any]) -> None:
        """Set configuration for a specific context and mode"""
        config_key = f"{context.value}_{mode.value}"
        self._configs[config_key] = config
        logger.debug(f"Updated configuration for {config_key}")

    def save_configs(self) -> None:
        """Save current configurations to file"""
        try:
            config_path = Path(self.config_file)

            # Convert enums to strings for JSON serialization
            serializable_configs = {}
            for key, config in self._configs.items():
                serializable_config = {}
                for k, v in config.items():
                    if hasattr(v, "value"):  # Enum
                        serializable_config[k] = v.value
                    else:
                        serializable_config[k] = v
                serializable_configs[key] = serializable_config

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(serializable_configs, f, indent=2)

            logger.info(f"Saved monitor configurations to {config_path}")

        except Exception as e:
            logger.error(f"Failed to save monitor configurations: {e}")

    def _load_from_unified_config(self) -> None:
        """Load configurations from unified configuration system"""
        try:
            config = get_config()
            display_config = config.display

            # Convert unified config to internal format
            for context_name, modes in display_config.contexts.items():
                for mode_name, mode_config in modes.items():
                    config_key = f"{context_name}_{mode_name}"
                    self._configs[config_key] = {
                        "title": mode_config.title,
                        "show_workers": mode_config.show_workers,
                        "show_alerts": mode_config.show_alerts,
                        "show_performance": mode_config.show_performance,
                        "show_newline_prefix": mode_config.show_newline_prefix,
                    }

            logger.info(f"Loaded {len(self._configs)} display configurations from unified config")

        except Exception as e:
            logger.error(f"Failed to load from unified config: {e}")
            # Fallback to minimal default configs
            self._load_fallback_configs()

    def _load_fallback_configs(self) -> None:
        """Load minimal fallback configurations if unified config fails"""
        self._configs = {
            "system_standard": {
                "title": "System Status",
                "show_workers": True,
                "show_alerts": True,
                "show_performance": False,
                "show_newline_prefix": False,
            },
            "system_compact": {
                "title": "System Status",
                "show_workers": False,
                "show_alerts": False,
                "show_performance": False,
                "show_newline_prefix": False,
            },
        }

    def _get_default_config(self, context: StatusContext, mode: DisplayMode) -> Dict[str, Any]:
        """Get default configuration for unknown context/mode combinations"""
        return {
            "title": f"{context.value.replace('_', ' ').title()} Status",
            "show_workers": mode not in [DisplayMode.COMPACT, DisplayMode.SUMMARY],
            "show_alerts": mode in [DisplayMode.DETAILED, DisplayMode.MONITORING],
            "show_performance": mode in [DisplayMode.STANDARD, DisplayMode.DETAILED, DisplayMode.MONITORING],
            "show_newline_prefix": mode in [DisplayMode.DETAILED, DisplayMode.MONITORING],
        }

    def get_available_contexts(self) -> list:
        """Get list of available configuration contexts"""
        contexts = set()
        for key in self._configs.keys():
            context = key.split("_")[0]
            contexts.add(context)
        return sorted(list(contexts))

    def get_available_modes(self, context: StatusContext) -> list:
        """Get list of available modes for a specific context"""
        modes = set()
        prefix = f"{context.value}_"
        for key in self._configs.keys():
            if key.startswith(prefix):
                mode_str = key[len(prefix) :]
                try:
                    mode = DisplayMode(mode_str)
                    modes.add(mode)
                except ValueError:
                    continue
        return sorted(list(modes), key=lambda x: x.value)

    def reset_to_defaults(self) -> None:
        """Reset all configurations to defaults"""
        self._configs.clear()
        self._load_from_unified_config()
        logger.info("Reset all monitor configurations to defaults")


# Global instance for easy access
_global_config_manager = None


def get_config_manager() -> DisplayConfigManager:
    """Get the global display configuration manager instance"""
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = DisplayConfigManager()
    return _global_config_manager


def get_display_config(
    context: StatusContext, mode: DisplayMode = DisplayMode.STANDARD, **overrides
) -> "DisplayConfig":
    """Convenience function to get display configuration"""
    manager = get_config_manager()
    return manager.config(context, mode, **overrides)
