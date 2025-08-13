#!/usr/bin/env python3

"""
OpenAI provider implementation.
"""

from typing import List

from core.models import Condition
from tools.utils import trim

from .openai_like import OpenAILikeProvider
from .registry import register_provider


class OpenAIProvider(OpenAILikeProvider):
    """OpenAI provider implementation."""

    def __init__(self, conditions: List[Condition], default_model: str = ""):
        default_model = trim(default_model) or "gpt-4o-mini"
        base_url = "https://api.openai.com"

        super().__init__("openai", base_url, default_model, conditions)


register_provider("openai", OpenAIProvider)
