#!/usr/bin/env python3

"""
User-Agent Manager

This module manages User-Agent strings with random load balancing.
It provides thread-safe access to multiple User-Agent strings for web scraping.

Key Features:
- Random User-Agent selection (default strategy)
- Thread-safe User-Agent access
- Usage statistics and monitoring
- Easy User-Agent list updates
- Built-in common User-Agent strings
"""

import threading
from typing import List

from .balancer import Balancer, Strategy


class Agents:
    """User-Agent manager with random load balancing"""

    def __init__(self, user_agents: List[str]):
        """Initialize User-Agent manager

        Args:
            user_agents: List of User-Agent strings
        """
        if not user_agents:
            raise ValueError("User agents list cannot be empty")

        self.user_agents = user_agents.copy()

        # Always use random strategy for User-Agents
        self.balancer = Balancer(self.user_agents, Strategy.RANDOM)

        self.lock = threading.Lock()
        self.total_requests = 0

    def get(self) -> str:
        """Get random User-Agent string

        Returns:
            str: Random User-Agent string
        """
        with self.lock:
            self.total_requests += 1
            return self.balancer.get()

    def next(self) -> str:
        """Alias for get() method for convenience

        Returns:
            str: Random User-Agent string
        """
        return self.get()

    def get_random(self) -> str:
        """Get random User-Agent string (explicit method name)

        Returns:
            str: Random User-Agent string
        """
        return self.get()

    def update_agents(self, user_agents: List[str]) -> None:
        """Update User-Agent strings list

        Args:
            user_agents: New list of User-Agent strings
        """
        if not user_agents:
            raise ValueError("User agents list cannot be empty")

        with self.lock:
            self.user_agents = user_agents.copy()
            self.balancer.update_items(self.user_agents)

    def add_agent(self, user_agent: str) -> None:
        """Add a new User-Agent string

        Args:
            user_agent: User-Agent string to add
        """
        if not user_agent:
            raise ValueError("User agent cannot be empty")

        with self.lock:
            if user_agent not in self.user_agents:
                self.user_agents.append(user_agent)
                self.balancer.update_items(self.user_agents)

    def remove_agent(self, user_agent: str) -> bool:
        """Remove a User-Agent string

        Args:
            user_agent: User-Agent string to remove

        Returns:
            bool: True if removed, False if not found
        """
        with self.lock:
            if user_agent in self.user_agents and len(self.user_agents) > 1:
                self.user_agents.remove(user_agent)
                self.balancer.update_items(self.user_agents)
                return True
            return False

    def reset_stats(self) -> None:
        """Reset usage statistics"""
        with self.lock:
            self.total_requests = 0
            self.balancer.reset()

    def get_stats(self) -> dict:
        """Get usage statistics

        Returns:
            dict: Usage statistics
        """
        with self.lock:
            stats = self.balancer.get_stats()
            stats["total_requests"] = self.total_requests
            return stats

    def get_agents_list(self) -> List[str]:
        """Get copy of current User-Agent strings list

        Returns:
            List[str]: Copy of User-Agent strings list
        """
        with self.lock:
            return self.user_agents.copy()

    def count(self) -> int:
        """Get number of User-Agent strings

        Returns:
            int: Number of User-Agent strings
        """
        return len(self.user_agents)

    def is_empty(self) -> bool:
        """Check if User-Agent list is empty

        Returns:
            bool: True if list is empty
        """
        return len(self.user_agents) == 0

    def __len__(self) -> int:
        """Get number of User-Agent strings

        Returns:
            int: Number of User-Agent strings
        """
        return len(self.user_agents)

    def __str__(self) -> str:
        """String representation

        Returns:
            str: String representation
        """
        return f"Agents(count={len(self.user_agents)}, requests={self.total_requests})"

    def __repr__(self) -> str:
        """Detailed string representation

        Returns:
            str: Detailed representation
        """
        return f"Agents(user_agents={self.user_agents})"

    @classmethod
    def create_default(cls) -> "Agents":
        """Create Agents instance with default User-Agent strings

        Returns:
            Agents: Agents instance with default User-Agents
        """
        default_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
        ]
        return cls(default_agents)
