#!/usr/bin/env python3

"""
Core Authentication Services

This module provides a centralized authentication service that can be configured
by upper layers and used by lower layers without creating circular dependencies.
"""

import threading
from typing import Callable, Optional

from .types import AuthProvider


class AuthService:
    """Centralized authentication service with dependency injection."""

    _instance: Optional["AuthService"] = None
    _lock = threading.Lock()
    _session_provider: Optional[Callable[[], Optional[str]]] = None
    _token_provider: Optional[Callable[[], Optional[str]]] = None
    _user_agent_provider: Optional[Callable[[], str]] = None

    def __init__(self):
        """Initialize with default implementations."""
        pass

    @classmethod
    def get_instance(cls) -> "AuthService":
        """Get thread-safe singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (mainly for testing)."""
        with cls._lock:
            cls._instance = None

    @classmethod
    def configure(
        cls,
        session_provider: Callable[[], Optional[str]],
        token_provider: Callable[[], Optional[str]],
        user_agent_provider: Callable[[], str],
    ):
        """Configure authentication providers.

        Args:
            session_provider: Function to get GitHub session token
            token_provider: Function to get GitHub API token
            user_agent_provider: Function to get User-Agent string
        """
        instance = cls.get_instance()
        cls._session_provider = session_provider
        cls._token_provider = token_provider
        cls._user_agent_provider = user_agent_provider

    def get_session(self) -> Optional[str]:
        """Get GitHub web session token."""
        if self.__class__._session_provider:
            try:
                return self.__class__._session_provider()
            except Exception:
                return None
        return None

    def get_token(self) -> Optional[str]:
        """Get GitHub API token."""
        if self.__class__._token_provider:
            try:
                return self.__class__._token_provider()
            except Exception:
                return None
        return None

    def get_user_agent(self) -> str:
        """Get User-Agent string."""
        if self.__class__._user_agent_provider:
            try:
                return self.__class__._user_agent_provider()
            except Exception:
                pass
        return "DefaultUserAgent/1.0"


class GithubAuthProvider(AuthProvider):
    """AuthProvider implementation using the core auth service."""

    def __init__(self):
        self._auth_service = AuthService.get_instance()

    def get_session(self) -> Optional[str]:
        return self._auth_service.get_session()

    def get_token(self) -> Optional[str]:
        return self._auth_service.get_token()

    def get_user_agent(self) -> str:
        return self._auth_service.get_user_agent()


# Convenience functions for easy access
def get_auth_provider() -> AuthProvider:
    """Get the core auth provider instance."""
    return GithubAuthProvider()


def configure_auth(
    session_provider: Callable[[], Optional[str]],
    token_provider: Callable[[], Optional[str]],
    user_agent_provider: Callable[[], str],
):
    """Configure the global authentication service.

    This should be called by the manager layer during initialization.
    """
    AuthService.configure(session_provider, token_provider, user_agent_provider)
