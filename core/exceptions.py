#!/usr/bin/env python3

"""
Core Exception Classes

This module provides essential exception classes for the application.
"""

import functools
import traceback
from typing import Any, Callable, Optional, TypeVar

from tools.logger import get_logger

from .enums import ErrorReason

logger = get_logger("exceptions")
F = TypeVar("F", bound=Callable[..., Any])


class BaseError(Exception):
    """Base exception class for the application"""

    def __init__(
        self,
        message: str,
        reason: ErrorReason = ErrorReason.UNKNOWN,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.cause = cause

    def is_retryable(self) -> bool:
        """Check if error is retryable based on reason"""
        return self.reason.is_retryable()


class NetworkError(BaseError):
    """Network-related errors"""

    def __init__(self, message: str, reason: ErrorReason = ErrorReason.NETWORK_ERROR, **kwargs):
        super().__init__(message=message, reason=reason, **kwargs)


class ValidationError(BaseError):
    """Input validation errors"""

    def __init__(self, message: str, field: Optional[str] = None, **kwargs):
        super().__init__(
            message=message,
            reason=ErrorReason.BAD_REQUEST,
            **kwargs,
        )
        self.field = field


# Additional exception classes for core functionality
class CoreException(BaseError):
    """Core system exception"""

    def __init__(self, message: str, **kwargs):
        super().__init__(message=message, **kwargs)


class BusinessLogicError(BaseError):
    """Business logic errors"""

    def __init__(self, message: str, **kwargs):
        super().__init__(message=message, **kwargs)


class ProcessingError(BaseError):
    """Processing-related errors"""

    def __init__(self, message: str, **kwargs):
        super().__init__(message=message, **kwargs)


class RetrievalError(BaseError):
    """Data retrieval errors"""

    def __init__(self, message: str, **kwargs):
        super().__init__(message=message, **kwargs)


class ConfigurationError(BaseError):
    """Configuration-related errors"""

    def __init__(self, message: str, **kwargs):
        super().__init__(message=message, **kwargs)


def handle_exceptions(
    default_result: Any = None, log_level: str = "error", reraise: bool = False, exception_types: tuple = (Exception,)
) -> Callable[[F], F]:
    """Decorator for consistent exception handling.

    Args:
        default_result: Value to return on exception
        log_level: Logging level (debug, info, warning, error, critical)
        reraise: Whether to reraise the exception after logging
        exception_types: Tuple of exception types to catch

    Returns:
        Decorated function with exception handling
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exception_types as e:
                # Extract context information
                context = {
                    "function": func.__name__,
                    "module": func.__module__,
                    "args_count": len(args),
                }

                # Log the exception
                log_message = f"Exception in {func.__name__}: {str(e)}"
                log_func = getattr(logger, log_level, logger.error)
                log_func(f"{log_message} | Context: {context}")

                # Log traceback for debugging
                if log_level in ("error", "critical"):
                    logger.debug(f"Traceback for {func.__name__}:\n{traceback.format_exc()}")

                if reraise:
                    raise

                return default_result

        return wrapper

    return decorator
