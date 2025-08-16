#!/usr/bin/env python3

"""
Status Data Collector for Monitor Package

Pure data aggregation from monitoring sources without application dependencies.
Simplified architecture focusing on monitoring data collection and caching.
"""

import time
from collections import OrderedDict
from typing import Any, Dict, Optional

from constant.monitoring import COLLECTOR_CACHE_TTL, CacheConfig
from core.enums import SystemState
from tools.logger import get_logger

from .models import CacheStats, IMonitorProvider, SystemStatus
from .types import IStatusCollector

logger = get_logger("state")


class StatusCollector(IStatusCollector):
    """
    Simplified status data collector focusing on monitoring data aggregation.
    Removed application dependencies and complex field mapping logic.

    Implements IStatusCollectorWithMonitoring protocol for type safety.
    """

    def __init__(self, monitoring: Optional[IMonitorProvider] = None):
        """Initialize collector with monitoring data provider

        Args:
            monitoring: Monitoring component implementing MonitoringDataProvider interface
        """
        self.monitoring = monitoring

        # Simple cache with TTL
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_access_order: OrderedDict[str, None] = OrderedDict()
        self._cache_stats = CacheStats()
        self._cache_ttl = COLLECTOR_CACHE_TTL
        self._cache_max_size = CacheConfig.DEFAULT_MAX_SIZE

        logger.debug("StatusCollector initialized with simplified monitoring-only approach")

    def status(self, refresh: bool = False) -> SystemStatus:
        """Collect and return unified system status from monitoring data

        Args:
            refresh: Force refresh of cached data if True

        Returns:
            SystemStatus: Complete system status aggregated from monitoring
        """
        cache_key = "system_status"

        # Try to get from cache first
        if not refresh and self._is_cache_valid(cache_key):
            self._cache_stats.hits += 1
            self._update_access_order(cache_key)
            logger.debug("Returning cached system status")
            return self._cache[cache_key]

        # Collect fresh status data
        status = self._collect_fresh_status()

        # Cache and return
        self._update_cache(cache_key, status)
        self._cache_stats.misses += 1
        return status

    def _collect_fresh_status(self) -> SystemStatus:
        """Collect fresh system status from monitoring provider"""
        status = SystemStatus()
        status.timestamp = time.time()

        if not self.monitoring:
            logger.debug("No monitoring provider available")
            return status

        try:
            # Get monitoring summary and snapshot
            summary = self.monitoring.summary()
            snapshot = self.monitoring.snapshot()

            # Map summary data to system status
            status.runtime = summary.runtime
            # TaskMetrics.total is a computed property, set individual fields
            status.tasks.completed = summary.completed
            status.tasks.failed = summary.failed
            # Calculate pending from total if available
            status.tasks.pending = max(0, summary.tasks - summary.completed - summary.failed)
            status.performance.throughput = summary.throughput
            status.performance.success_rate = summary.success_rate
            status.resource.valid = summary.keys
            status.resource.links = summary.links

            # Map snapshot data to system status
            if snapshot.pipeline:
                status.pipeline = snapshot.pipeline
            if snapshot.providers:
                status.providers.update(snapshot.providers)

            # Set system state
            status.state = SystemState.RUNNING

            logger.debug(f"Fresh status collected - tasks: {summary.tasks}, providers: {len(snapshot.providers)}")

        except Exception as e:
            logger.error(f"Error collecting monitoring data: {e}")

        return status

    def cache_stats(self) -> CacheStats:
        """Get current cache statistics"""
        self._cache_stats.size = len(self._cache)
        return self._cache_stats

    def clear_cache(self) -> None:
        """Clear all cached data"""
        self._cache.clear()
        self._cache_times.clear()
        self._cache_access_order.clear()
        self._cache_stats = CacheStats()
        logger.debug("StatusCollector cache cleared")

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid"""
        if cache_key not in self._cache or cache_key not in self._cache_times:
            return False

        age = time.time() - self._cache_times[cache_key]
        return age < self._cache_ttl

    def _update_cache(self, cache_key: str, data: Any) -> None:
        """Update cache with new data and LRU management"""
        # Check if we need to evict entries
        if len(self._cache) >= self._cache_max_size and cache_key not in self._cache:
            self._evict_lru_entry()

        self._cache[cache_key] = data
        self._cache_times[cache_key] = time.time()
        self._update_access_order(cache_key)
        self._cache_stats.size = len(self._cache)

    def _update_access_order(self, cache_key: str) -> None:
        """Update LRU access order for a cache key"""
        # Move to end (most recently used) - O(1) operation in OrderedDict
        self._cache_access_order.pop(cache_key, None)  # Remove if exists
        self._cache_access_order[cache_key] = None  # Add to end

    def _evict_lru_entry(self) -> None:
        """Evict the least recently used cache entry"""
        if not self._cache_access_order:
            return

        # Remove least recently used (first in OrderedDict) - O(1) operation
        lru_key, _ = self._cache_access_order.popitem(last=False)

        # Remove from cache
        self._cache.pop(lru_key, None)
        self._cache_times.pop(lru_key, None)

        self._cache_stats.evictions += 1
        logger.debug(f"Evicted LRU cache entry: {lru_key}")
