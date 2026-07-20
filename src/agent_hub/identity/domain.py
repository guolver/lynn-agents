"""Pure validation rules for registration — no I/O, no side effects.

Password rules deliberately check length only (>= 8 characters), not
composition (uppercase/digit/symbol). NIST SP 800-63B recommends length over
composition rules: forced complexity pushes users toward predictable patterns
(``Passw0rd!``) without meaningfully raising resistance to brute force.
"""

from __future__ import annotations

import re

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_EMAIL_LENGTH = 255
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 128


class ValidationError(ValueError):
    """Raised when registration input fails a domain rule."""


def normalize_email(email: str) -> str:
    """Lowercase and trim an email so storage/lookup are case-insensitive.

    Without this, ``Alice@example.com`` and ``alice@example.com`` would pass
    the database's ``(tenant_id, email)`` unique constraint as two distinct
    accounts, defeating its purpose.
    """
    return email.strip().lower()


def validate_email(email: str) -> None:
    if len(email) > _MAX_EMAIL_LENGTH:
        raise ValidationError(f"email must be at most {_MAX_EMAIL_LENGTH} characters")
    if not _EMAIL_PATTERN.match(email):
        raise ValidationError("invalid email format")


def validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise ValidationError(f"password must be at least {_MIN_PASSWORD_LENGTH} characters")
    if len(password) > _MAX_PASSWORD_LENGTH:
        raise ValidationError(f"password must be at most {_MAX_PASSWORD_LENGTH} characters")
