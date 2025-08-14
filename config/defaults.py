#!/usr/bin/env python3

"""
Default Configuration Values

This module provides default configuration values for the entire application.
It ensures consistent defaults across all configuration sections.

Key Features:
- Centralized default values
- Complete configuration template
- Easy customization
- Type-safe defaults
"""

from typing import Any, Dict

from constant.runtime import StandardPipelineStage


def _get_pipeline_defaults() -> Dict[str, Any]:
    """Get pipeline defaults using StandardPipelineStage enum"""
    return {
        "threads": {
            StandardPipelineStage.SEARCH.value: 1,
            StandardPipelineStage.GATHER.value: 8,
            StandardPipelineStage.CHECK.value: 4,
            StandardPipelineStage.INSPECT.value: 2,
        },
        "queue_sizes": {
            StandardPipelineStage.SEARCH.value: 100000,
            StandardPipelineStage.GATHER.value: 200000,
            StandardPipelineStage.CHECK.value: 500000,
            StandardPipelineStage.INSPECT.value: 1000000,
        },
    }


def _get_default_task_stages() -> Dict[str, bool]:
    """Get default task stages using StandardPipelineStage enum"""
    return {
        StandardPipelineStage.SEARCH.value: True,
        StandardPipelineStage.GATHER.value: True,
        StandardPipelineStage.CHECK.value: True,
        StandardPipelineStage.INSPECT.value: True,
    }


def get_default_config() -> Dict[str, Any]:
    """Get complete default configuration

    Returns:
        Dict[str, Any]: Default configuration dictionary
    """
    return {
        "global": {
            "workspace": "./data",
            "max_retries_requeued": 3,
            "github_credentials": {
                "sessions": ["your_github_session_here"],
                "tokens": ["your_github_token_here"],
                "strategy": "round_robin",
            },
            "user_agents": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            ],
        },
        "pipeline": _get_pipeline_defaults(),
        "stats": {
            "interval": 10,
            "show": True,
        },
        "monitoring": {
            "update_interval": 2.0,
            "error_threshold": 0.1,
            "queue_threshold": 1000,
            "memory_threshold": 1073741824,  # 1GB in bytes
            "response_threshold": 5.0,
        },
        "display": {
            "contexts": {
                "system": {
                    "standard": {
                        "title": "System Status",
                        "show_workers": True,
                        "show_alerts": True,
                        "show_performance": False,
                        "show_newline_prefix": False,
                    },
                    "compact": {
                        "title": "System Status",
                        "show_workers": False,
                        "show_alerts": False,
                        "show_performance": False,
                        "show_newline_prefix": False,
                    },
                    "detailed": {
                        "title": "Detailed System Status",
                        "show_workers": True,
                        "show_alerts": True,
                        "show_performance": True,
                        "show_newline_prefix": True,
                    },
                },
                "monitoring": {
                    "standard": {
                        "title": "Pipeline Monitoring",
                        "show_workers": True,
                        "show_alerts": True,
                        "show_performance": True,
                        "show_newline_prefix": False,
                    },
                    "detailed": {
                        "title": "Detailed Pipeline Monitoring",
                        "show_workers": True,
                        "show_alerts": True,
                        "show_performance": True,
                        "show_newline_prefix": True,
                    },
                },
                "task": {
                    "standard": {
                        "title": "Task Status",
                        "show_workers": True,
                        "show_alerts": False,
                        "show_performance": False,
                        "show_newline_prefix": False,
                    },
                    "compact": {
                        "title": "Task Progress",
                        "show_workers": False,
                        "show_alerts": False,
                        "show_performance": False,
                        "show_newline_prefix": False,
                    },
                },
                "application": {
                    "standard": {
                        "title": "Application Status",
                        "show_workers": False,
                        "show_alerts": True,
                        "show_performance": False,
                        "show_newline_prefix": False,
                    },
                    "detailed": {
                        "title": "Detailed Application Status",
                        "show_workers": True,
                        "show_alerts": True,
                        "show_performance": True,
                        "show_newline_prefix": False,
                    },
                },
                "main": {
                    "standard": {
                        "title": "Pipeline Status",
                        "show_workers": True,
                        "show_alerts": False,
                        "show_performance": False,
                        "show_newline_prefix": False,
                    },
                },
            }
        },
        "persistence": {
            "batch_size": 50,
            "save_interval": 30,
            "queue_interval": 60,
            "snapshot_interval": 300,
            "auto_restore": True,
            "shutdown_timeout": 30,
            "format": "txt",
        },
        "worker_manager": {
            "enabled": False,
            "min_workers": 1,
            "max_workers": 10,
            "target_queue_size": 100,
            "adjustment_interval": 5.0,
            "scale_up_threshold": 0.8,
            "scale_down_threshold": 0.2,
            "log_recommendations": True,
        },
        "ratelimits": {
            "github_api": {"base_rate": 0.15, "burst_limit": 3, "adaptive": True},
            "github_web": {"base_rate": 0.5, "burst_limit": 2, "adaptive": True},
        },
        "tasks": [
            {
                "name": "openai",
                "enabled": True,
                "provider_type": "openai_like",
                "use_api": False,
                "stages": _get_default_task_stages(),
                "api": {
                    "base_url": "https://api.openai.com",
                    "completion_path": "/v1/chat/completions",
                    "model_path": "/v1/models",
                    "default_model": "gpt-4o-mini",
                    "auth_key": "Authorization",
                },
                "patterns": {"key_pattern": "sk(?:-proj)?-[a-zA-Z0-9]{20}T3BlbkFJ[a-zA-Z0-9]{20}"},
                "conditions": [{"query": '"T3BlbkFJ"'}],
                "rate_limit": {"base_rate": 2.0, "burst_limit": 10, "adaptive": True},
            }
        ],
    }
