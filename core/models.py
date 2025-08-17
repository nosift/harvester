#!/usr/bin/env python3

"""
Core Models - Fundamental Data Models

This module defines the core data models used throughout the application.
These models represent the fundamental entities and data structures that
form the foundation of the system.
"""

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .enums import ErrorReason


@dataclass
class RateLimitConfig:
    """Unified rate limiting configuration"""

    base_rate: float = 1.0
    burst_limit: int = 5
    adaptive: bool = True
    backoff_factor: float = 0.5
    recovery_factor: float = 1.1
    max_rate_multiplier: float = 2.0
    min_rate_multiplier: float = 0.1

    def __post_init__(self):
        """Validate rate limit configuration"""
        if self.base_rate <= 0:
            raise ValueError("base_rate must be positive")
        if self.burst_limit <= 0:
            raise ValueError("burst_limit must be positive")
        if not (0 < self.backoff_factor < 1):
            raise ValueError("backoff_factor must be between 0 and 1")
        if self.recovery_factor <= 1:
            raise ValueError("recovery_factor must be > 1")

    def calculate_adjusted_rate(self, success_ratio: float) -> float:
        """Calculate adjusted rate based on success ratio"""
        if not self.adaptive:
            return self.base_rate

        if success_ratio > 0.9:
            multiplier = min(self.max_rate_multiplier, self.recovery_factor)
        elif success_ratio < 0.5:
            multiplier = max(self.min_rate_multiplier, self.backoff_factor)
        else:
            multiplier = 1.0

        return self.base_rate * multiplier


# Task recovery and logging models
@dataclass
class LogFileInfo:
    """Information about a log file"""

    filename: str
    size: str
    modified: str
    path: str
    error: Optional[str] = None


@dataclass
class LoggingStats:
    """Logging system statistics"""

    active_loggers: int
    log_files: Dict[str, LogFileInfo] = field(default_factory=dict)
    logs_directory: Optional[str] = None


@dataclass
class RecoveredTasks:
    """Recovery data for a single provider"""

    check_tasks: List["Service"] = field(default_factory=list)
    acquisition_tasks: List[str] = field(default_factory=list)
    invalid_keys: Set["Service"] = field(default_factory=set)

    def has_tasks(self) -> bool:
        """Check if any tasks need recovery"""
        return bool(self.check_tasks or self.acquisition_tasks or self.invalid_keys)

    def check_count(self) -> int:
        """Get number of check tasks"""
        return len(self.check_tasks)

    def acquisition_count(self) -> int:
        """Get number of acquisition tasks"""
        return len(self.acquisition_tasks)

    def invalid_count(self) -> int:
        """Get number of invalid keys"""
        return len(self.invalid_keys)

    def valid_check_tasks(self) -> List["Service"]:
        """Get check tasks filtered by invalid keys"""
        return [task for task in self.check_tasks if task not in self.invalid_keys]

    def summary(self) -> str:
        """Get task summary string"""
        return f"check: {self.check_count()}, acquisition: {self.acquisition_count()}, invalid: {self.invalid_count()}"


@dataclass
class AllRecoveredTasks:
    """Recovery data for all providers"""

    providers: Dict[str, RecoveredTasks] = field(default_factory=dict)

    def add_provider(self, name: str, tasks: RecoveredTasks) -> None:
        """Add provider tasks if any exist"""
        if tasks.has_tasks():
            self.providers[name] = tasks

    def get_provider(self, name: str) -> RecoveredTasks:
        """Get provider tasks safely"""
        return self.providers.get(name, RecoveredTasks())

    def has_providers(self) -> bool:
        """Check if any providers have tasks"""
        return bool(self.providers)

    def provider_count(self) -> int:
        """Get number of providers with tasks"""
        return len(self.providers)

    def total_check_tasks(self) -> int:
        """Get total check tasks across all providers"""
        return sum(tasks.check_count() for tasks in self.providers.values())

    def total_acquisition_tasks(self) -> int:
        """Get total acquisition tasks across all providers"""
        return sum(tasks.acquisition_count() for tasks in self.providers.values())

    def total_invalid_keys(self) -> int:
        """Get total invalid keys across all providers"""
        return sum(tasks.invalid_count() for tasks in self.providers.values())

    def summary(self) -> str:
        """Get summary of all recovered tasks"""
        if not self.has_providers():
            return "No tasks recovered"

        return (
            f"Providers: {self.provider_count()}, "
            f"Check: {self.total_check_tasks()}, "
            f"Acquisition: {self.total_acquisition_tasks()}, "
            f"Invalid: {self.total_invalid_keys()}"
        )


@dataclass
class TaskRecoveryInfo:
    """Information for task recovery"""

    queue_tasks: Dict[str, List[Any]] = field(default_factory=dict)
    result_tasks: Optional[AllRecoveredTasks] = None
    total_queue_tasks: int = 0
    total_result_tasks: int = 0


@dataclass
class Service:
    """Core service data model representing an API service endpoint

    This is the fundamental data structure representing a discovered
    API service with its authentication and endpoint information.
    """

    # Server address
    address: str = ""

    # Application name or endpoint identifier
    endpoint: str = ""

    # API token/key for authentication
    key: str = ""

    # Model name for AI services
    model: str = ""

    def __hash__(self) -> int:
        """Hash based on all fields for use in sets and dicts"""
        return hash((self.address, self.endpoint, self.key, self.model))

    def __eq__(self, other: object) -> bool:
        """Equality comparison based on all fields"""
        if not isinstance(other, Service):
            return False

        return (
            self.address == other.address
            and self.endpoint == other.endpoint
            and self.key == other.key
            and self.model == other.model
        )

    def is_valid(self) -> bool:
        """Check if service has minimum required information"""
        return bool(self.key and (self.address or self.endpoint))

    def get_identifier(self) -> str:
        """Get unique identifier for this service"""
        return f"{self.address}:{self.endpoint}:{self.key[:8]}..."

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for serialization"""
        return {
            "address": self.address,
            "endpoint": self.endpoint,
            "key": self.key,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Service":
        """Create Service from dictionary"""
        return cls(
            address=data.get("address", ""),
            endpoint=data.get("endpoint", ""),
            key=data.get("key", ""),
            model=data.get("model", ""),
        )

    def serialize(self) -> str:
        if not self.address and not self.endpoint and not self.model:
            return self.key

        data = {}
        if self.address:
            data["address"] = self.address
        if self.endpoint:
            data["endpoint"] = self.endpoint
        if self.key:
            data["key"] = self.key
        if self.model:
            data["model"] = self.model

        return "" if not data else json.dumps(data)

    @classmethod
    def deserialize(cls, text: str) -> Optional["Service"]:
        if not text:
            return None

        try:
            item = json.loads(text)
            return cls(
                address=item.get("address", ""),
                endpoint=item.get("endpoint", ""),
                key=item.get("key", ""),
                model=item.get("model", ""),
            )
        except Exception:
            return cls(key=text)


@dataclass
class CheckResult:
    """Result of API token validation check

    Represents the outcome of validating an API token against a service,
    including success status, error information, and additional metadata.
    """

    available: bool = False
    error_reason: ErrorReason = ErrorReason.UNKNOWN
    message: str = ""
    response_time: float = 0.0
    status_code: Optional[int] = None

    @property
    def ok(self) -> bool:
        """Alias for available for backward compatibility"""
        return self.available

    @property
    def reason(self) -> ErrorReason:
        """Alias for error_reason for backward compatibility"""
        return self.error_reason

    @classmethod
    def success(cls, message: str = "Token is valid", response_time: float = 0.0) -> "CheckResult":
        """Create a successful check result"""
        return cls(
            available=True,
            error_reason=ErrorReason.UNKNOWN,
            message=message,
            response_time=response_time,
        )

    @classmethod
    def fail(
        cls, reason: ErrorReason, message: str = "", response_time: float = 0.0, status_code: Optional[int] = None
    ) -> "CheckResult":
        """Create a failed check result"""
        return cls(
            available=False,
            error_reason=reason,
            message=message or reason.value,
            response_time=response_time,
            status_code=status_code,
        )

    def is_retryable(self) -> bool:
        """Check if the error is retryable"""
        return self.error_reason.is_retryable()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "available": self.available,
            "error_reason": self.error_reason.value,
            "message": self.message,
            "response_time": self.response_time,
            "status_code": self.status_code,
        }


@dataclass
class Patterns:
    """Extraction patterns for keys and metadata"""

    key_pattern: str = ""
    address_pattern: str = ""
    endpoint_pattern: str = ""
    model_pattern: str = ""

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary"""
        return {
            "key_pattern": self.key_pattern,
            "address_pattern": self.address_pattern,
            "endpoint_pattern": self.endpoint_pattern,
            "model_pattern": self.model_pattern,
        }


@dataclass
class Condition:
    """Search condition with complete pattern configuration

    Defines search parameters and extraction patterns used to discover
    API keys and services for a specific provider.
    """

    query: Optional[str] = None
    patterns: Patterns = field(default_factory=Patterns)
    description: str = ""
    enabled: bool = True

    def __post_init__(self):
        """Validate condition after initialization"""
        if not self.query and not self.patterns.key_pattern:
            raise ValueError("Condition must have either query or key_pattern")

    def get_search_term(self) -> str:
        """Get the primary search term"""
        return self.query or self.patterns.key_pattern or ""

    def is_valid(self) -> bool:
        """Check if condition is valid and enabled"""
        return self.enabled and bool(self.get_search_term())

    def __hash__(self) -> int:
        """Hash based on query and patterns for use in sets and dicts"""
        return hash((self.query, self.patterns.key_pattern))

    def __eq__(self, other: object) -> bool:
        """Equality comparison based on query and patterns"""
        if not isinstance(other, Condition):
            return False
        return self.query == other.query and self.patterns == other.patterns

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "query": self.query,
            "patterns": self.patterns.to_dict(),
            "description": self.description,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Condition":
        """Create Condition from dictionary"""
        params = data.get("patterns", {})
        patterns = Patterns(**params) if params else Patterns()

        return cls(
            query=data.get("query"),
            patterns=patterns,
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
        )


@dataclass
class TokenBucket:
    """Token bucket for rate limiting with burst support

    Implements the token bucket algorithm for rate limiting with
    adaptive rate adjustment based on success/failure feedback.
    """

    def __init__(self, rate: float, burst: int, adaptive: bool = True):
        """Initialize token bucket

        Args:
            rate: Tokens per second
            burst: Maximum tokens (bucket capacity)
            adaptive: Enable adaptive rate adjustment
        """
        self.rate = rate
        self.burst = burst
        self.adaptive = adaptive
        self.tokens = float(burst)
        self.last_update = time.time()
        self.lock = threading.Lock()

        # Adaptive rate adjustment
        self.original_rate = rate
        self.consecutive_success = 0
        self.consecutive_failures = 0
        self.last_adjustment = time.time()

    def acquire(self, tokens: int = 1) -> bool:
        """Acquire tokens from bucket

        Args:
            tokens: Number of tokens to acquire

        Returns:
            bool: True if tokens were acquired, False if rate limited
        """
        with self.lock:
            now = time.time()

            # Add tokens based on elapsed time
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            # Check if enough tokens available
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False

    def wait_time(self, tokens: int = 1) -> float:
        """Calculate wait time needed to acquire tokens

        Args:
            tokens: Number of tokens needed

        Returns:
            float: Wait time in seconds
        """
        with self.lock:
            if self.tokens >= tokens:
                return 0.0

            needed = tokens - self.tokens
            return needed / self.rate

    def adjust_rate(self, success: bool) -> None:
        """Adjust rate based on success/failure feedback

        Args:
            success: Whether the operation was successful
        """
        if not self.adaptive:
            return

        with self.lock:
            if success:
                self.consecutive_success += 1
                self.consecutive_failures = 0

                # Gradually increase rate after sustained success
                if self.consecutive_success >= 10 and self.rate < self.original_rate * 2:
                    self.rate *= 1.1
                    self.consecutive_success = 0
            else:
                self.consecutive_failures += 1
                self.consecutive_success = 0

                # Quickly decrease rate after failures
                if self.consecutive_failures >= 3:
                    self.rate = max(self.original_rate * 0.1, self.rate * 0.5)
                    self.consecutive_failures = 0

    def reset(self) -> None:
        """Reset bucket to initial state"""
        with self.lock:
            self.tokens = float(self.burst)
            self.rate = self.original_rate
            self.consecutive_success = 0
            self.consecutive_failures = 0
            self.last_update = time.time()
            self.last_adjustment = time.time()

    def get_stats(self) -> Dict[str, float]:
        """Get current bucket statistics

        Returns:
            Dict[str, float]: Statistics including rate, tokens, burst, utilization
        """
        with self.lock:
            # Update tokens to current time
            now = time.time()
            elapsed = now - self.last_update
            current_tokens = min(self.burst, self.tokens + elapsed * self.rate)

            return {
                "rate": self.rate,
                "burst": float(self.burst),
                "tokens": current_tokens,
                "utilization": (self.burst - current_tokens) / self.burst if self.burst > 0 else 0.0,
                "consecutive_success": float(self.consecutive_success),
                "consecutive_failures": float(self.consecutive_failures),
                "adaptive": 1.0 if self.adaptive else 0.0,
                "original_rate": self.original_rate,
            }


@dataclass
class ResourceUsage:
    """Type-safe resource usage metrics"""

    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    disk_mb: float = 0.0
    network_kb: float = 0.0
    active_connections: int = 0

    def __post_init__(self):
        """Validate resource usage after initialization"""
        self.validate()

    def validate(self) -> None:
        """Validate resource usage metrics"""
        if self.cpu_percent < 0:
            raise ValueError("cpu_percent cannot be negative")
        if self.memory_mb < 0:
            raise ValueError("memory_mb cannot be negative")
        if self.disk_mb < 0:
            raise ValueError("disk_mb cannot be negative")
        if self.network_kb < 0:
            raise ValueError("network_kb cannot be negative")
        if self.active_connections < 0:
            raise ValueError("active_connections cannot be negative")


@dataclass
class HealthStatus:
    """Type-safe health status"""

    healthy: bool
    component: str
    message: str = ""
    last_check: float = 0.0
    check_count: int = 0
    error_count: int = 0

    @property
    def error_rate(self) -> float:
        """Calculate error rate"""
        if self.check_count == 0:
            return 0.0
        return self.error_count / self.check_count

    def is_degraded(self, max_error_rate: float = 0.1) -> bool:
        """Check if component is in degraded state"""
        return self.error_rate > max_error_rate


def inherit_patterns(parent: Patterns, condition: Condition) -> None:
    """Inherit global patterns to condition if fields are empty"""
    if not parent or not isinstance(parent, Patterns) or not condition or not isinstance(condition, Condition):
        return

    if not condition.patterns.key_pattern:
        condition.patterns.key_pattern = parent.key_pattern
    if not condition.patterns.address_pattern:
        condition.patterns.address_pattern = parent.address_pattern
    if not condition.patterns.endpoint_pattern:
        condition.patterns.endpoint_pattern = parent.endpoint_pattern
    if not condition.patterns.model_pattern:
        condition.patterns.model_pattern = parent.model_pattern
