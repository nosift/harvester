#!/usr/bin/env python3

"""
Core Types - Fundamental Data Types and Interfaces

This module defines core types, interfaces, and abstract base classes
used throughout the application for type safety and clear contracts.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Protocol

from .models import Condition

if TYPE_CHECKING:
    from .metrics import PipelineStatus


@dataclass
class CheckResult:
    """Result of provider token validation check"""

    valid: bool
    message: str = ""
    error_code: Optional[str] = None
    response_time: float = 0.0
    model_tested: Optional[str] = None

    @property
    def is_success(self) -> bool:
        """Check if validation was successful"""
        return self.valid and not self.error_code


class IAuthProvider(Protocol):
    """Protocol for resource management with dependency injection support.

    This interface defines the contract for resource providers that can be
    injected into components that need access to credentials and user agents.
    """

    def get_session(self) -> Optional[str]:
        """Get next GitHub session token."""
        ...

    def get_token(self) -> Optional[str]:
        """Get next GitHub API token."""
        ...

    def get_credential(self, prefer_token: bool = True) -> tuple[str, str]:
        """Get next credential with type preference."""
        ...

    def get_user_agent(self) -> str:
        """Get random User-Agent string."""
        ...


class IProvider(ABC):
    """Core provider interface with essential properties and methods

    This interface defines the contract that all AI service providers must implement.
    It provides type safety without creating circular dependencies.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name identifier"""
        pass

    @property
    @abstractmethod
    def conditions(self) -> List[Condition]:
        """Search conditions for this provider"""
        pass

    @abstractmethod
    def check(self, token: str, address: str = "", endpoint: str = "", model: str = "", **kwargs) -> CheckResult:
        """Check if token is valid for this provider

        Args:
            token: API token to validate
            address: Optional custom address
            endpoint: Optional custom endpoint
            model: Optional model to test
            kwargs: Optional additional keyword arguments

        Returns:
            CheckResult: Result of the validation check
        """
        pass

    @abstractmethod
    def inspect(self, token: str, address: str = "", endpoint: str = "", **kwargs) -> List[str]:
        """Inspect available models for this provider

        Args:
            token: API token for authentication
            address: Optional custom address
            endpoint: Optional custom endpoint
            kwargs: Optional additional keyword arguments

        Returns:
            List[str]: Available model names
        """
        pass


# Abstract Interfaces and Protocols
class IPipelineBase(ABC):
    """Abstract base class for pipeline objects that provide statistics

    This abstract base class defines the interface that pipeline objects must implement
    to be compatible with StatusBuilder. It provides stronger type safety than Protocol
    and enables better IDE support and runtime type checking.
    """

    @abstractmethod
    def get_all_stats(self) -> "PipelineStatus":
        """Get comprehensive pipeline statistics

        Returns:
            PipelineStatus: Complete pipeline statistics including all stages
        """
        pass

    @abstractmethod
    def get_dynamic_stats(self) -> "PipelineStatus":
        """Get dynamic pipeline statistics

        Returns:
            PipelineStatus: Current dynamic statistics for active stages
        """
        pass

    def get_stats_summary(self) -> str:
        """Get a human-readable summary of pipeline statistics

        Returns:
            str: Summary string with key pipeline metrics
        """
        try:
            stats = self.get_all_stats()
            # Access dataclass fields directly instead of dict-like access
            active = getattr(stats, "active", 0)
            total = getattr(stats, "total", 0)
            state = getattr(stats, "state", None)
            state_str = getattr(state, "name", str(state)) if state is not None else "unknown"
            return f"Pipeline: {active}/{total} stages active, state={state_str}"
        except Exception as e:
            return f"Pipeline: Error getting statistics - {e}"
