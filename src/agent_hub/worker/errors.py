"""Error classification for Celery task retry logic.

Errors are classified as *retryable* (transient infrastructure issues) or
*permanent* (business logic violations that will never succeed on retry).
Unknown exceptions default to retryable so that ``max_retries`` provides
the safety net.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Base hierarchy
# ---------------------------------------------------------------------------


class RetryableError(Exception):
    """Transient failure — safe to retry with backoff."""


class PermanentError(Exception):
    """Business/validation failure — retrying will not help."""


# ---------------------------------------------------------------------------
# Retryable subtypes
# ---------------------------------------------------------------------------


class SourceTimeoutError(RetryableError):
    """External job source did not respond in time."""


class RateLimitError(RetryableError):
    """Upstream API returned 429."""


class EmailServiceTemporaryError(RetryableError):
    """Email provider returned a transient error."""


class TransientDatabaseError(RetryableError):
    """Deadlock, connection lost, or similar recoverable DB error."""


# ---------------------------------------------------------------------------
# Permanent subtypes
# ---------------------------------------------------------------------------


class SourceUnauthorizedError(PermanentError):
    """Credentials for the job source are invalid or revoked."""


class InputSchemaError(PermanentError):
    """Payload does not match the expected schema."""


class CandidateUnsubscribedError(PermanentError):
    """Candidate has opted out — must not receive notifications."""


class HighRiskFlaggedError(PermanentError):
    """Content flagged as high risk and rejected by policy."""


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

ErrorCategory = Literal["retryable", "permanent"]


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    error_class: str
    category: ErrorCategory
    message: str
    original: BaseException


# Imported domain errors that should be treated as permanent.
_PERMANENT_BUILTINS: tuple[type[BaseException], ...] = (
    ValueError,
    TypeError,
)

_RETRYABLE_BUILTINS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _domain_permanent_types() -> tuple[type[BaseException], ...]:
    """Lazily import domain error types to avoid circular imports."""
    try:
        from agent_hub.agents.global_part_time.service import NotFoundError, PolicyError

        return (NotFoundError, PolicyError)
    except ImportError:
        return ()


def classify(exc: BaseException) -> ClassifiedError:
    """Classify an exception as retryable or permanent.

    Returns a :class:`ClassifiedError` with structured information for
    workflow step recording.
    """
    msg = str(exc) or type(exc).__name__

    if isinstance(exc, PermanentError):
        return ClassifiedError(type(exc).__name__, "permanent", msg, exc)

    if isinstance(exc, RetryableError):
        return ClassifiedError(type(exc).__name__, "retryable", msg, exc)

    domain_permanent = _domain_permanent_types()
    if domain_permanent and isinstance(exc, domain_permanent):
        return ClassifiedError(type(exc).__name__, "permanent", msg, exc)

    if isinstance(exc, _PERMANENT_BUILTINS):
        return ClassifiedError(type(exc).__name__, "permanent", msg, exc)

    if isinstance(exc, _RETRYABLE_BUILTINS):
        return ClassifiedError(type(exc).__name__, "retryable", msg, exc)

    # Unknown → retryable (max_retries provides the safety net).
    return ClassifiedError(type(exc).__name__, "retryable", msg, exc)
