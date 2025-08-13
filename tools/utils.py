#!/usr/bin/env python3

"""
Utility functions for the search engine.
"""

import re

from constant.system import PROVIDER_SERVICE_PREFIX

from .logger import get_logger

logger = get_logger("tools")


def trim(text: str) -> str:
    """Trim whitespace from text, return empty string if invalid."""
    if not text or type(text) != str:
        return ""
    return text.strip()


def isblank(text: str) -> bool:
    """Check if text is blank or invalid."""
    return not text or type(text) != str or not text.strip()


def encoding_url(url: str) -> str:
    """Encode Chinese characters in URL to punycode."""
    if not url:
        return ""

    url = url.strip()
    cn_chars = re.findall("[\u4e00-\u9fa5]+", url)
    if not cn_chars:
        return url

    punycodes = list(map(lambda x: "xn--" + x.encode("punycode").decode("utf-8"), cn_chars))
    for c, pc in zip(cn_chars, punycodes):
        url = url[: url.find(c)] + pc + url[url.find(c) + len(c) :]

    return url


def get_service_name(provider: str) -> str:
    """Get service name for rate limiting

    Args:
        provider: Provider name to process

    Returns:
        str: Processed service name for rate limiting
    """
    name = trim(provider)
    if not name:
        return ""

    return f"{PROVIDER_SERVICE_PREFIX}:{name}"
