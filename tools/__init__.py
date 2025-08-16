#!/usr/bin/env python3

"""
Tools Package - Performance and Resource Management Tools

This package provides essential tools for performance optimization and resource management:
- Generic load balancing for resource distribution
- User-Agent management with random selection
- Rate limiting with token bucket algorithm and adaptive adjustment
- Async support for rate limiting operations
"""

# Resource management components
from .agent import Agents

# Generic load balancing tools
from .balancer import Balancer

# Coordinator and resource management
from .coordinator import (
    ResourceManager,
    get_credential,
    get_managers_stats,
    get_session,
    get_token,
    get_user_agent,
    init_managers,
    reset_managers_stats,
    update_credentials,
    update_user_agents,
)
from .credential import Credentials
from .logger import Logger, get_logger

# Regex patterns for performance
from .patterns import (
    COMPILED_API_KEY_PATTERNS,
    extract_github_query_pattern,
    redact_api_key,
    redact_api_keys_in_text,
)

# Rate limiting tools
from .ratelimit import AsyncRateLimiter, RateLimiter, TokenBucket, create_rate_limiter

# Resource management tools
from .resources import ResourcePool, ResourceStats, managed_network

# Unified retry framework
from .retry import (
    ExponentialBackoff,
    FixedRetry,
    JitterBackoff,
    NoRetry,
    RetryCore,
    RetryPolicy,
    create_retry_policy,
    network_retry,
    retry_on_exception,
    smart_retry,
    with_retry,
)

# Utility functions
from .utils import handle_exceptions, isblank, trim

__all__ = [
    # Resource management components
    "Agents",
    # Generic load balancing
    "Balancer",
    # Regex patterns
    "COMPILED_API_KEY_PATTERNS",
    "extract_github_query_pattern",
    "redact_api_key",
    "redact_api_keys_in_text",
    # Coordinator and resource management
    "ResourceManager",
    "get_credential",
    "get_managers_stats",
    "get_session",
    "get_token",
    "get_user_agent",
    "init_managers",
    "reset_managers_stats",
    "update_credentials",
    "update_user_agents",
    # Credentials
    "Credentials",
    # Logging
    "Logger",
    "get_logger",
    # Rate limiting
    "AsyncRateLimiter",
    "RateLimiter",
    "TokenBucket",
    "create_rate_limiter",
    # Resource management
    "ResourcePool",
    "ResourceStats",
    "managed_network",
    # Unified retry framework
    "RetryCore",
    "RetryPolicy",
    "FixedRetry",
    "ExponentialBackoff",
    "JitterBackoff",
    "NoRetry",
    "create_retry_policy",
    "with_retry",
    "retry_on_exception",
    "network_retry",
    "smart_retry",
    # Utility functions
    "handle_exceptions",
    "isblank",
    "trim",
]
