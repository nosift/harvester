#!/usr/bin/env python3

"""
Resource Management - Resource Pool and Context Managers

This module provides resource management utilities including resource pools
and context managers for network connections.
"""

import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, TypeVar

from .logger import get_logger

logger = get_logger("resources")

T = TypeVar("T")


@dataclass
class ResourceStats:
    """Statistics for resource pool"""

    created: int = 0
    acquired: int = 0
    released: int = 0
    expired: int = 0
    active: int = 0
    pool_size: int = 0


class ResourcePool(Generic[T]):
    """Generic resource pool for managing reusable resources"""

    def __init__(
        self,
        factory: Callable[[], T],
        max_size: int = 10,
        max_age: float = 300.0,
        cleanup_func: Optional[Callable[[T], None]] = None,
    ):
        """Initialize resource pool

        Args:
            factory: Function to create new resources
            max_size: Maximum number of resources in pool
            max_age: Maximum age of resources in seconds
            cleanup_func: Optional cleanup function for resources
        """
        self.factory = factory
        self.max_size = max_size
        self.max_age = max_age
        self.cleanup_func = cleanup_func

        self._pool = []
        self._active = weakref.WeakSet()
        self._lock = threading.Lock()
        self._stats = ResourceStats()

    def acquire(self) -> T:
        """Acquire a resource from the pool"""
        with self._lock:
            # Try to get a resource from pool
            while self._pool:
                resource_info = self._pool.pop()
                resource, created_at = resource_info

                # Check if resource is still valid
                if time.time() - created_at < self.max_age:
                    self._active.add(resource)
                    self._stats.acquired += 1
                    self._stats.active += 1
                    return resource
                else:
                    # Resource expired, clean it up
                    if self.cleanup_func:
                        try:
                            self.cleanup_func(resource)
                        except Exception as e:
                            logger.warning(f"Failed to cleanup expired resource: {e}")
                    self._stats.expired += 1

            # No valid resources in pool, create new one
            try:
                resource = self.factory()
                self._active.add(resource)
                self._stats.created += 1
                self._stats.acquired += 1
                self._stats.active += 1
                return resource
            except Exception as e:
                logger.error(f"Failed to create new resource: {e}")
                raise

    def release(self, resource: T) -> None:
        """Release a resource back to the pool"""
        with self._lock:
            if resource in self._active:
                self._active.discard(resource)
                self._stats.active -= 1
                self._stats.released += 1

                # Add back to pool if there's space
                if len(self._pool) < self.max_size:
                    self._pool.append((resource, time.time()))
                    self._stats.pool_size = len(self._pool)
                else:
                    # Pool is full, cleanup resource
                    if self.cleanup_func:
                        try:
                            self.cleanup_func(resource)
                        except Exception as e:
                            logger.warning(f"Failed to cleanup resource: {e}")

    def get_stats(self) -> ResourceStats:
        """Get pool statistics"""
        with self._lock:
            self._stats.pool_size = len(self._pool)
            return self._stats

    def cleanup(self) -> None:
        """Cleanup all resources in pool"""
        with self._lock:
            if self.cleanup_func:
                for resource, _ in self._pool:
                    try:
                        self.cleanup_func(resource)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup resource during pool cleanup: {e}")

            self._pool.clear()
            self._stats.pool_size = 0


@contextmanager
def managed_network(connection: Any, connection_type: str = "network"):
    """Context manager for network connections

    Args:
        connection: Network connection object
        connection_type: Type of connection for logging
    """
    try:
        logger.debug(f"Acquired {connection_type} connection")
        yield connection
    except Exception as e:
        logger.error(f"Error with {connection_type} connection: {e}")
        raise
    finally:
        try:
            if hasattr(connection, "close"):
                connection.close()
            logger.debug(f"Released {connection_type} connection")
        except Exception as e:
            logger.warning(f"Failed to close {connection_type} connection: {e}")
