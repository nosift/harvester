#!/usr/bin/env python3

"""
Monitoring Configuration Constants

This module defines constants used by the state management system,
including collector configurations, field mappings, and cache settings.
"""

from typing import Dict, Optional, Tuple, TypedDict, Union

from .runtime import StandardPipelineStage

# Type aliases for different mapping shapes
ProviderToSystemMapping = Dict[str, Tuple[str, Optional[str]]]  # (target_path, target_field)
PipelineToSystemMapping = Dict[str, str]  # Simple string mapping
ApplicationToSystemMapping = Dict[str, str]  # Simple string mapping
PipelineStatsMapping = Dict[str, Tuple[str, str]]  # (target_field, unused)

# Union type for all mapping values
MappingValue = Union[str, Tuple[str, Optional[str]], Tuple[str, str]]


class FieldMappingsDict(TypedDict):
    """Typed structure for FIELD_MAPPINGS configuration"""

    provider_stats_mappings: ProviderToSystemMapping
    pipeline_stats_mappings: PipelineStatsMapping
    application_to_system: ApplicationToSystemMapping
    pipeline_to_system: PipelineToSystemMapping
    provider_to_system: PipelineToSystemMapping


def _get_pipeline_stats_mappings() -> PipelineStatsMapping:
    """Get pipeline stats mappings using StandardPipelineStage enum"""
    return {
        f"{StandardPipelineStage.SEARCH.value}_queue": ("queue_metrics", StandardPipelineStage.SEARCH.value),
        f"{StandardPipelineStage.GATHER.value}_queue": ("queue_metrics", StandardPipelineStage.GATHER.value),
        f"{StandardPipelineStage.CHECK.value}_queue": ("queue_metrics", StandardPipelineStage.CHECK.value),
        f"{StandardPipelineStage.INSPECT.value}_queue": ("queue_metrics", StandardPipelineStage.INSPECT.value),
        "active_workers": ("worker_metrics", "active"),
        "total_workers": ("worker_metrics", "total"),
    }


# Collector cache configuration
COLLECTOR_CACHE_TTL: float = 300.0  # 5 minutes cache TTL

COLLECTOR_CACHE_KEYS: Dict[str, str] = {
    "SYSTEM_STATUS": "sys_status",
    "PIPELINE_DATA": "pipeline_data",
    "PROVIDER_DATA": "provider_data",
    "APPLICATION_STATUS": "app_status",
}

# Collector alert sources
COLLECTOR_ALERT_SOURCES: Dict[str, str] = {
    "APPLICATION": "app_alerts",
    "COLLECTOR": "collector_alerts",
    "TASK": "task_alerts",
    "MONITORING": "monitor_alerts",
}

# Collector error templates
COLLECTOR_ERROR_TEMPLATES: Dict[str, str] = {
    "connection_error": "Failed to connect to {service}: {error}",
    "timeout_error": "Request timeout for {service}: {timeout}s",
    "rate_limit_error": "Rate limit exceeded for {service}",
    "auth_error": "Authentication failed for {service}",
}

# Field mapping configurations for data transformation
FIELD_MAPPINGS: FieldMappingsDict = {
    "provider_stats_mappings": {
        "valid_keys": ("key_metrics", "valid"),
        "invalid_keys": ("key_metrics", "invalid"),
        "no_quota_keys": ("key_metrics", "no_quota"),
        "wait_check_keys": ("key_metrics", "wait_check"),
        "total_links": ("resource_metrics", "total_links"),
        "total_models": ("resource_metrics", "total_models"),
    },
    "pipeline_stats_mappings": _get_pipeline_stats_mappings(),
    "application_to_system": {
        "runtime": "system.runtime",
        "state": "system.state",
        "timestamp": "system.timestamp",
    },
    "pipeline_to_system": {
        "queue_size": "pipeline.queue_size",
        "active_workers": "pipeline.active_workers",
        "processing_rate": "pipeline.processing_rate",
    },
    "provider_to_system": {
        "valid_keys": "provider.valid_keys",
        "invalid_keys": "provider.invalid_keys",
        "total_links": "provider.total_links",
    },
}


def validate_field_mappings() -> None:
    """Validate FIELD_MAPPINGS structure at startup to catch configuration errors early"""
    try:
        # Validate provider_stats_mappings - should be tuples
        provider_mappings = FIELD_MAPPINGS["provider_stats_mappings"]
        for key, value in provider_mappings.items():
            if not isinstance(value, tuple) or len(value) != 2:
                raise ValueError(f"provider_stats_mappings['{key}'] must be a 2-tuple, got: {type(value)}")
            target_path, target_field = value
            if not isinstance(target_path, str):
                raise ValueError(f"provider_stats_mappings['{key}'][0] must be string, got: {type(target_path)}")
            if target_field is not None and not isinstance(target_field, str):
                raise ValueError(
                    f"provider_stats_mappings['{key}'][1] must be string or None, got: {type(target_field)}"
                )

        # Validate string mappings
        for mapping_name in ["application_to_system", "pipeline_to_system", "provider_to_system"]:
            mapping = FIELD_MAPPINGS[mapping_name]
            for key, value in mapping.items():
                if not isinstance(value, str):
                    raise ValueError(f"{mapping_name}['{key}'] must be string, got: {type(value)}")

        # Validate pipeline_stats_mappings - should be tuples
        pipeline_mappings = FIELD_MAPPINGS["pipeline_stats_mappings"]
        for key, value in pipeline_mappings.items():
            if not isinstance(value, tuple) or len(value) != 2:
                raise ValueError(f"pipeline_stats_mappings['{key}'] must be a 2-tuple, got: {type(value)}")

    except Exception as e:
        raise RuntimeError(f"FIELD_MAPPINGS validation failed: {e}") from e


# Validate mappings at module import time
validate_field_mappings()

# Monitoring configuration (legacy compatibility)
MONITORING_CONFIG: Dict[str, float] = {
    "update_interval": 2.0,
    "stats_interval": 10.0,
}

MONITORING_THRESHOLDS: Dict[str, float] = {
    "error_rate": 0.1,
    "queue_size": 1000,
    "memory_usage": 1073741824,  # 1GB in bytes
    "min_sample_size": 10,
}
