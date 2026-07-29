"""Sensitive data sanitizer for logging."""

from __future__ import annotations

import logging
import re
from typing import Any


# Patterns for sensitive data
SENSITIVE_PATTERNS = [
    # Keys that indicate sensitive values (case-insensitive)
    (re.compile(r"(password|passwd|pwd)", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"(token|api_key|apikey|api-key|secret)", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"(auth|authorization|credential)", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"(private_key|privatekey|private-key)", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"(access_key|accesskey|access-key)", re.IGNORECASE), "[REDACTED]"),
]

# Patterns for values that look sensitive
VALUE_PATTERNS = [
    # Bearer tokens
    (
        re.compile(r"Bearer\s+[A-Za-z0-9\-_]+\.?[A-Za-z0-9\-_]*\.?[A-Za-z0-9\-_]*"),
        "Bearer [REDACTED]",
    ),
    # JWT-like patterns
    (re.compile(r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"), "[REDACTED_JWT]"),
    # API key patterns (common formats)
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED_SK]"),
    (re.compile(r"pk-[A-Za-z0-9]{20,}"), "[REDACTED_PK]"),
]


def sanitize_value(value: Any) -> Any:
    """Sanitize a single value, redacting sensitive data."""
    if not isinstance(value, str):
        return value

    result = value
    for pattern, replacement in VALUE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def sanitize_dict(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Recursively sanitize a dictionary, redacting sensitive keys and values."""
    if depth > 10:  # Prevent infinite recursion
        return {"__truncated__": "max depth exceeded"}

    result = {}
    for key, value in data.items():
        # Check if key indicates sensitive data
        is_sensitive_key = any(p.search(key) for p, _ in SENSITIVE_PATTERNS)

        if is_sensitive_key:
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value, depth + 1)
        elif isinstance(value, list):
            result[key] = [
                sanitize_dict(item, depth + 1) if isinstance(item, dict) else sanitize_value(item)
                for item in value
            ]
        else:
            result[key] = sanitize_value(value)

    return result


def sanitize_message(message: str) -> str:
    """Sanitize a log message string."""
    result = message
    for pattern, replacement in VALUE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class SanitizingFormatter(logging.Formatter):
    """Log formatter that sanitizes sensitive data from log records.

    Use this formatter to prevent sensitive data (passwords, tokens, API keys)
    from being written to log files.

    Example:
        handler = logging.StreamHandler()
        handler.setFormatter(SanitizingFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        logging.root.addHandler(handler)
    """

    def format(self, record: logging.LogRecord) -> str:
        # Sanitize the message
        record.msg = sanitize_message(str(record.msg))

        # Sanitize args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    sanitize_dict(arg) if isinstance(arg, dict) else sanitize_value(arg)
                    for arg in record.args
                )

        return super().format(record)


def configure_sanitized_logging(
    level: int = logging.INFO,
    format_string: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
) -> None:
    """Configure root logger with sanitizing formatter.

    Call this early in application startup to ensure all logs are sanitized.

    Args:
        level: Logging level (default: INFO)
        format_string: Log format string (default: timestamp - name - level - message)
    """
    handler = logging.StreamHandler()
    handler.setFormatter(SanitizingFormatter(format_string))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for existing_handler in root_logger.handlers[:]:
        root_logger.removeHandler(existing_handler)

    root_logger.addHandler(handler)
