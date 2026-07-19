"""Tests for pure identity validation rules."""

from __future__ import annotations

import pytest

from agent_hub.identity.domain import (
    ValidationError,
    normalize_email,
    validate_email,
    validate_password,
)


@pytest.mark.parametrize(
    "email",
    ["user@example.com", "first.last+tag@sub.example.co"],
)
def test_validate_email_accepts_valid_addresses(email):
    validate_email(email)  # must not raise


@pytest.mark.parametrize(
    "email",
    ["", "no-at-sign", "missing-domain@", "@missing-local.com", "spaces in@email.com"],
)
def test_validate_email_rejects_invalid_addresses(email):
    with pytest.raises(ValidationError):
        validate_email(email)


def test_validate_password_accepts_eight_characters():
    validate_password("12345678")  # must not raise


@pytest.mark.parametrize("password", ["", "short1", "1234567"])
def test_validate_password_rejects_short_passwords(password):
    with pytest.raises(ValidationError):
        validate_password(password)


def test_normalize_email_lowercases_and_strips_whitespace():
    assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"


def test_normalize_email_is_idempotent():
    normalized = normalize_email("Bob@Example.com")
    assert normalize_email(normalized) == normalized


def test_validate_password_rejects_over_128_characters():
    with pytest.raises(ValidationError):
        validate_password("a" * 129)


def test_validate_password_accepts_exactly_128_characters():
    validate_password("a" * 128)  # must not raise


def test_validate_email_rejects_over_255_characters():
    long_local_part = "a" * 250
    with pytest.raises(ValidationError):
        validate_email(f"{long_local_part}@example.com")
