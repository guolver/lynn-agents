"""Shared utilities for job source fetchers.

Each fetcher module (remoteok, remotive, etc.) imports strip_html and
_SSL_CONTEXT from here instead of duplicating them.
"""

from __future__ import annotations

import re
import ssl
from collections.abc import Callable
from html.parser import HTMLParser

try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None


class _TagStripper(HTMLParser):
    """Collect text nodes from an HTML fragment."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(html: str) -> str:
    """Remove HTML tags and return collapsed plain text."""
    stripper = _TagStripper()
    stripper.feed(html)
    text = stripper.get_text()
    return re.sub(r"\s+", " ", text).strip()


def get_fetcher(base_url: str) -> tuple[Callable, Callable] | None:
    """Return ``(fetch_fn, map_job_fn)`` for *base_url*, or ``None`` if unrecognised."""
    from .remoteok import fetch as remoteok_fetch, map_job as remoteok_map
    from .remotive import fetch as remotive_fetch, map_job as remotive_map

    _REGISTRY: dict[str, tuple[Callable, Callable]] = {
        "remoteok.com": (remoteok_fetch, remoteok_map),
        "remotive.com": (remotive_fetch, remotive_map),
    }
    for domain, funcs in _REGISTRY.items():
        if domain in base_url:
            return funcs
    return None
