#!/usr/bin/env python3

"""
Status rendering strategies for CLI output.

This module defines a pluggable interface and two renderers to keep the
runtime engine unified while allowing different output styles.
"""

from typing import Protocol

from .models import DisplayMode, StatusContext


class StatusRenderer(Protocol):
    """Render status information using a StatusManager."""

    def render(self, status_manager, context: StatusContext, mode: DisplayMode) -> None:  # noqa: ANN001
        ...


class MainStyleRenderer:
    """Classic concise style (main.py behavior)."""

    def render(self, status_manager, context: StatusContext, mode: DisplayMode) -> None:  # noqa: ANN001
        # Force MAIN context with STANDARD mode to render table-like classic output
        status_manager.show_status(StatusContext.MAIN, DisplayMode.STANDARD, force_refresh=True)


class AppStyleRenderer:
    """Detailed style (application.py behavior)."""

    def render(self, status_manager, context: StatusContext, mode: DisplayMode) -> None:  # noqa: ANN001
        # Use the provided mode; default to DETAILED if missing at call sites
        status_manager.show_status(context, mode or DisplayMode.DETAILED)
