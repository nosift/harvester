#!/usr/bin/env python3

"""
Core Types - Fundamental Data Types and Interfaces

This module defines core types, interfaces, and abstract base classes
used throughout the application for type safety and clear contracts.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Protocol

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


class ProviderInterface(Protocol):
    """Protocol for AI service providers with typed method signatures"""

    @property
    def name(self) -> str:
        """Provider name identifier"""
        ...

    @property
    def base_url(self) -> str:
        """Base URL for the provider's API"""
        ...

    @property
    def default_model(self) -> str:
        """Default model for this provider"""
        ...

    @property
    def conditions(self) -> List[Condition]:
        """Search conditions for this provider"""
        ...

    def check(self, token: str, address: str = "", endpoint: str = "", model: str = "") -> CheckResult:
        """Check if token is valid for this provider"""
        ...

    def list_models(self, token: str, address: str = "", endpoint: str = "") -> List[str]:
        """List available models for this provider"""
        ...


class AuthProvider(Protocol):
    """Protocol for providing authentication artifacts and User-Agent.

    This decouples stages from upper-layer manager.coordinator module.
    """

    def get_session(self) -> Optional[str]:
        """Get GitHub web session token."""
        ...

    def get_token(self) -> Optional[str]:
        """Get GitHub API token."""
        ...

    def get_user_agent(self) -> str:
        """Get User-Agent string."""
        ...


class ResourceProvider(Protocol):
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


class Provider(ABC):
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
    def base_url(self) -> str:
        """Base URL for the provider's API"""
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model for this provider"""
        pass

    @property
    @abstractmethod
    def conditions(self) -> List[Condition]:
        """Search conditions for this provider"""
        pass

    @abstractmethod
    def check(self, token: str, address: str = "", endpoint: str = "", model: str = "") -> CheckResult:
        """Check if token is valid for this provider

        Args:
            token: API token to validate
            address: Optional custom address
            endpoint: Optional custom endpoint
            model: Optional model to test

        Returns:
            CheckResult: Result of the validation check
        """
        pass

    @abstractmethod
    def list_models(self, token: str, address: str = "", endpoint: str = "") -> List[str]:
        """List available models for this provider

        Args:
            token: API token for authentication
            address: Optional custom address
            endpoint: Optional custom endpoint

        Returns:
            List[str]: Available model names
        """
        pass

    def get_display_name(self) -> str:
        """Get human-readable display name"""
        return self.name.replace("_", " ").title()

    def supports_model(self, model: str) -> bool:
        """Check if provider supports a specific model"""
        try:
            available_models = self.list_models("")
            return model in available_models
        except Exception:
            return False


# Abstract Interfaces and Protocols
class PipelineBase(ABC):
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


class RateLimiterInterface(Protocol):
    """Protocol for rate limiting functionality"""

    def acquire(self, service_type: str) -> bool:
        """Acquire permission to make a request

        Args:
            service_type: Type of service requesting permission

        Returns:
            bool: True if permission granted, False if rate limited
        """
        ...

    def report_result(self, service_type: str, success: bool) -> None:
        """Report the result of a request for adaptive rate limiting

        Args:
            service_type: Type of service reporting result
            success: Whether the request was successful
        """
        ...


class TaskManagerInterface(Protocol):
    """Protocol for task manager objects with typed providers and config"""

    start_time: float
    running: bool
    providers: Dict[str, ProviderInterface]
    pipeline: Optional["PipelineBase"]

    @property
    def config(self):
        """Task manager configuration"""
        ...

    def start(self) -> None:
        """Start the task manager"""
        ...

    def stop(self, timeout: float = 30.0) -> None:
        """Stop the task manager

        Args:
            timeout: Maximum time to wait for graceful shutdown
        """
        ...

    def wait_completion(self) -> None:
        """Wait for all tasks to complete"""
        ...
