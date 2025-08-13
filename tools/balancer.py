#!/usr/bin/env python3

"""
Generic Load Balancer

This module provides a generic load balancer for distributing requests
across multiple resources (sessions, tokens, user-agents, etc.).

Key Features:
- Round-robin and random load balancing strategies
- Thread-safe resource allocation
- Usage statistics tracking
- Simple and efficient implementation
"""

import random
import threading
from typing import Generic, List, TypeVar

from core.enums import LoadBalanceStrategy as Strategy

T = TypeVar("T")


class Balancer(Generic[T]):
    """Generic load balancer for resource distribution"""

    def __init__(self, items: List[T], strategy: Strategy = Strategy.ROUND_ROBIN):
        """Initialize load balancer

        Args:
            items: List of items to balance across
            strategy: Load balancing strategy to use
        """
        if not items:
            raise ValueError("Items list cannot be empty")

        self.items: List[T] = items.copy()
        self.strategy = strategy
        self.index = 0
        self.lock = threading.Lock()

        # Usage statistics
        self.usage_count = dict.fromkeys(range(len(self.items)), 0)
        self.total_requests = 0

    def get(self) -> T:
        """Get next item according to load balancing strategy

        Returns:
            Any: Next item from the pool
        """
        with self.lock:
            self.total_requests += 1

            if self.strategy == Strategy.ROUND_ROBIN:
                item_index = self.index
                self.index = (self.index + 1) % len(self.items)
            else:  # RANDOM
                item_index = random.randint(0, len(self.items) - 1)

            self.usage_count[item_index] += 1
            return self.items[item_index]

    def next(self) -> T:
        """Alias for get() method for convenience

        Returns:
            Any: Next item from the pool
        """
        return self.get()

    def reset(self) -> None:
        """Reset load balancer state and statistics"""
        with self.lock:
            self.index = 0
            self.usage_count = dict.fromkeys(range(len(self.items)), 0)
            self.total_requests = 0

    def update_items(self, items: List[T]) -> None:
        """Update items list

        Args:
            items: New list of items to balance across
        """
        if not items:
            raise ValueError("Items list cannot be empty")

        with self.lock:
            self.items = items.copy()
            self.index = 0
            self.usage_count = dict.fromkeys(range(len(self.items)), 0)

    def get_stats(self) -> dict:
        """Get usage statistics

        Returns:
            dict: Usage statistics including counts and percentages
        """
        with self.lock:
            if self.total_requests == 0:
                return {
                    "total_requests": 0,
                    "items_count": len(self.items),
                    "strategy": self.strategy.value,
                    "usage_distribution": {},
                }

            distribution = {}
            for i, count in self.usage_count.items():
                percentage = (count / self.total_requests) * 100
                distribution[f"item_{i}"] = {"count": count, "percentage": round(percentage, 2)}

            return {
                "total_requests": self.total_requests,
                "items_count": len(self.items),
                "strategy": self.strategy.value,
                "usage_distribution": distribution,
            }

    def get_current_item(self) -> T:
        """Get current item without advancing the index

        Returns:
            T: Current item (for round-robin) or random item
        """
        with self.lock:
            if self.strategy == Strategy.ROUND_ROBIN:
                return self.items[self.index]
            else:
                return random.choice(self.items)

    def size(self) -> int:
        """Get number of items in the pool

        Returns:
            int: Number of items
        """
        return len(self.items)

    def is_empty(self) -> bool:
        """Check if items pool is empty

        Returns:
            bool: True if pool is empty
        """
        return len(self.items) == 0

    def __len__(self) -> int:
        """Get number of items in the pool

        Returns:
            int: Number of items
        """
        return len(self.items)

    def __str__(self) -> str:
        """String representation of the balancer

        Returns:
            str: String representation
        """
        return f"Balancer(items={len(self.items)}, strategy={self.strategy.value}, requests={self.total_requests})"

    def __repr__(self) -> str:
        """Detailed string representation

        Returns:
            str: Detailed representation
        """
        return f"Balancer(items={self.items}, strategy={self.strategy}, index={self.index})"
