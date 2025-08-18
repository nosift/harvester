#!/usr/bin/env python3

"""
Rate limiting system using Token Bucket algorithm.
Supports per-service rate limits with adaptive adjustment and burst handling.
"""

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from constant.system import SERVICE_TYPE_GITHUB_API
from core.models import RateLimitConfig, TokenBucket

from .logger import get_logger

logger = get_logger("tools")


@dataclass
class TokenBucketStats:
    """Statistics for a single token bucket"""

    rate: float
    burst: float
    tokens: float
    utilization: float
    consecutive_success: float
    consecutive_failures: float
    adaptive: float
    original_rate: float


@dataclass
class RateLimiterStats:
    """Overall rate limiter statistics"""

    services: Dict[str, TokenBucketStats]


class RateLimiter:
    """Multi-service rate limiter with Token Bucket algorithm"""

    def __init__(self, rate_limits: Dict[str, RateLimitConfig]):
        self.buckets: Dict[str, TokenBucket] = {}
        self.lock = threading.Lock()

        # Initialize buckets for each service
        for service, limit in rate_limits.items():
            self.buckets[service] = TokenBucket(rate=limit.base_rate, burst=limit.burst_limit, adaptive=limit.adaptive)

        logger.info(f"Initialized rate limiter with {len(self.buckets)} services")

    def acquire(self, service: str, tokens: int = 1) -> bool:
        """Acquire tokens for a service"""
        bucket = self._get_bucket(service)
        if not bucket:
            return True  # No limit configured, allow request

        return bucket.acquire(tokens)

    def wait_time(self, service: str, tokens: int = 1) -> float:
        """Get wait time needed for tokens"""
        bucket = self._get_bucket(service)
        if not bucket:
            return 0.0

        return bucket.wait_time(tokens)

    def report_result(self, service: str, success: bool):
        """Report request result for adaptive rate adjustment"""
        bucket = self._get_bucket(service)
        if bucket:
            bucket.adjust_rate(success)

    def add_service(self, service: str, rate_limit: RateLimitConfig):
        """Add a new service rate limit"""
        with self.lock:
            self.buckets[service] = TokenBucket(
                rate=rate_limit.base_rate, burst=rate_limit.burst_limit, adaptive=rate_limit.adaptive
            )
            logger.info(f"Added rate limit for service: {service}")

    def update_service(self, service: str, rate_limit: RateLimitConfig):
        """Update existing service rate limit"""
        with self.lock:
            if service in self.buckets:
                bucket = self.buckets[service]
                bucket.rate = rate_limit.base_rate
                bucket.burst = rate_limit.burst_limit
                bucket.adaptive = rate_limit.adaptive
                bucket.original_rate = rate_limit.base_rate
                logger.info(f"Updated rate limit for service: {service}")

    def get_stats(self) -> RateLimiterStats:
        """Get statistics for all services"""
        services = {}
        with self.lock:
            for service, bucket in self.buckets.items():
                bucket_stats = bucket.get_stats()
                services[service] = TokenBucketStats(
                    rate=bucket_stats["rate"],
                    burst=bucket_stats["burst"],
                    tokens=bucket_stats["tokens"],
                    utilization=bucket_stats["utilization"],
                    consecutive_success=bucket_stats["consecutive_success"],
                    consecutive_failures=bucket_stats["consecutive_failures"],
                    adaptive=bucket_stats["adaptive"],
                    original_rate=bucket_stats["original_rate"],
                )
        return RateLimiterStats(services=services)

    def _get_bucket(self, service: str) -> Optional[TokenBucket]:
        """Get bucket for service, thread-safe"""
        with self.lock:
            return self.buckets.get(service)


class AsyncRateLimiter:
    """Async wrapper for rate limiter with automatic waiting"""

    def __init__(self, rate_limiter: RateLimiter):
        self.rate_limiter = rate_limiter

    async def acquire(self, service: str, tokens: int = 1) -> bool:
        """Acquire tokens, waiting if necessary"""

        # Try immediate acquisition
        if self.rate_limiter.acquire(service, tokens):
            return True

        # Wait for tokens to become available
        wait_time = self.rate_limiter.wait_time(service, tokens)
        if wait_time > 0:
            bucket = self.rate_limiter._get_bucket(service)
            max_value = bucket.burst if bucket else "unknown"
            logger.debug(f"Rate limit hit for {service}, waiting {wait_time:.2f}s, max: {max_value}")
            await asyncio.sleep(wait_time)
            return self.rate_limiter.acquire(service, tokens)

        return False

    def report_result(self, service: str, success: bool):
        """Report request result"""
        self.rate_limiter.report_result(service, success)


def create_rate_limiter(rate_limits: Dict[str, RateLimitConfig]) -> RateLimiter:
    """Factory function to create rate limiter"""
    return RateLimiter(rate_limits)


if __name__ == "__main__":
    # Test rate limiter

    limits = {
        SERVICE_TYPE_GITHUB_API: RateLimitConfig(base_rate=2.0, burst_limit=5, adaptive=True),
        "openai": RateLimitConfig(base_rate=1.0, burst_limit=3, adaptive=True),
    }

    limiter = create_rate_limiter(limits)

    # Test acquisition
    logger.info("Testing rate limiter...")

    # Burst test
    for i in range(7):
        success = limiter.acquire(SERVICE_TYPE_GITHUB_API)
        logger.info(f"Request {i+1}: {'✓' if success else '✗'}")

    # Wait and try again
    time.sleep(1)
    success = limiter.acquire(SERVICE_TYPE_GITHUB_API)
    logger.info(f"After 1s wait: {'✓' if success else '✗'}")

    # Test adaptive adjustment
    logger.info("Testing adaptive adjustment...")
    for i in range(5):
        limiter.report_result(SERVICE_TYPE_GITHUB_API, False)  # Report failures

    stats = limiter.get_stats()
    logger.info(f"Stats after failures: {stats}")

    logger.info("Rate limiter test completed!")
