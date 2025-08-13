#!/usr/bin/env python3

"""
Runtime Configuration Constants

This module contains constants related to pipeline stages, queue management,
and data processing workflows used during system runtime.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from core.enums import ResultType


# Pipeline stage enumeration for type-safe stage management
class StandardPipelineStage(Enum):
    """Pipeline stage names for type safety"""

    SEARCH = "search"
    GATHER = "gather"
    CHECK = "check"
    INSPECT = "inspect"


# Queue sizes for each stage
DEFAULT_SEARCH_QUEUE_SIZE: int = 100000
DEFAULT_GATHER_QUEUE_SIZE: int = 200000
DEFAULT_CHECK_QUEUE_SIZE: int = 500000
DEFAULT_INSPECT_QUEUE_SIZE: int = 1000000

# Queue and thread defaults using PipelineStage enum
DEFAULT_THREAD_COUNTS: Dict[str, int] = {
    StandardPipelineStage.SEARCH.value: 1,
    StandardPipelineStage.GATHER.value: 8,
    StandardPipelineStage.CHECK.value: 4,
    StandardPipelineStage.INSPECT.value: 2,
}

# Queue state constants
QUEUE_STATE_PROVIDER_MULTI: str = "multi"
QUEUE_STATE_MAX_AGE_HOURS: int = 24


# Queue management enums for type-safe operations
class QueueStateProvider(Enum):
    """Provider type for queue state management"""

    SINGLE = "single"
    MULTI = "multi"


class QueueStateStatus(Enum):
    """Status of queue state for monitoring and management"""

    ACTIVE = "active"
    EMPTY = "empty"
    ERROR = "error"
    ARCHIVED = "archived"


class QueueOperation(Enum):
    """Queue operation types for logging and monitoring"""

    SAVE = "save"
    LOAD = "load"
    CLEAR = "clear"
    ARCHIVE = "archive"
    FLUSH = "flush"


class QueueStateField(Enum):
    """Field names for queue state serialization"""

    STAGE = "stage"
    PROVIDER = "provider"
    TASK_COUNT = "task_count"
    SAVED_AT = "saved_at"
    TASKS = "tasks"
    STATUS = "status"
    AGE_HOURS = "age_hours"
    FILE_SIZE = "file_size"
    ERROR = "error"


# Statistics field enumeration for configuration-driven aggregation
class StatsField(Enum):
    """Statistics field names for type safety"""

    VALID_KEYS = "valid_keys"
    INVALID_KEYS = "invalid_keys"
    NO_QUOTA_KEYS = "no_quota_keys"
    WAIT_CHECK_KEYS = "wait_check_keys"
    MATERIAL_KEYS = "material_keys"
    TOTAL_LINKS = "total_links"
    INSPECT_COUNT = "inspect_count"


# Worker statistics field enumeration
class WorkerStatsField(Enum):
    """Worker statistics field names for type safety"""

    CURRENT_WORKERS = "current_workers"
    TARGET_WORKERS = "target_workers"
    QUEUE_SIZE = "queue_size"
    UTILIZATION = "utilization"
    PROCESSING_RATE = "processing_rate"
    LAST_ADJUSTMENT = "last_adjustment"


@dataclass
class StatsMapping:
    """Configuration for statistics field mapping"""

    result_field: str  # ResultStats field name
    key_field: Optional[str] = None  # KeyMetrics field name
    resource_field: Optional[str] = None  # ResourceMetrics field name


# Statistics field mapping configuration
STATS_MAPPINGS: Dict[StatsField, StatsMapping] = {
    StatsField.VALID_KEYS: StatsMapping("valid_keys", "valid"),
    StatsField.INVALID_KEYS: StatsMapping("invalid_keys", "invalid"),
    StatsField.NO_QUOTA_KEYS: StatsMapping("no_quota_keys", "no_quota"),
    StatsField.WAIT_CHECK_KEYS: StatsMapping("wait_check_keys", "wait_check"),
    StatsField.MATERIAL_KEYS: StatsMapping("material_keys", "material"),
    StatsField.TOTAL_LINKS: StatsMapping("total_links", None, "total_links"),
    StatsField.INSPECT_COUNT: StatsMapping("inspect_count", None, "total_models"),
}


@dataclass
class ResultTypeConfig:
    """Configuration for result type mapping"""

    filename_attr: str  # Provider attribute name for filename
    stats_attr: str  # ResultStats attribute name for statistics


# Result type configuration mapping
RESULT_TYPE_MAPPINGS: Dict[ResultType, ResultTypeConfig] = {
    ResultType.VALID_KEYS: ResultTypeConfig("keys_filename", "valid_keys"),
    ResultType.NO_QUOTA_KEYS: ResultTypeConfig("no_quota_filename", "no_quota_keys"),
    ResultType.WAIT_CHECK_KEYS: ResultTypeConfig("wait_check_filename", "wait_check_keys"),
    ResultType.INVALID_KEYS: ResultTypeConfig("invalid_keys_filename", "invalid_keys"),
    ResultType.MATERIAL_KEYS: ResultTypeConfig("material_filename", "material_keys"),
    ResultType.LINKS: ResultTypeConfig("links_filename", "total_links"),
    ResultType.SUMMARY: ResultTypeConfig("summary_filename", None),  # No stats for summary
}
