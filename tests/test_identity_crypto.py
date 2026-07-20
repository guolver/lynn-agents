"""Tests for identity crypto primitives: password hashing, JWT, token hashing."""

from __future__ import annotations

import jwt
import pytest

from agent_hub.identity.crypto import (
    decode_access_token,
    encode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)


def test_hash_password_produces_verifiable_hash():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_new_refresh_token_is_random_and_hash_is_deterministic():
    token_a = new_refresh_token()
    token_b = new_refresh_token()
    assert token_a != token_b
    assert hash_refresh_token(token_a) == hash_refresh_token(token_a)
    assert hash_refresh_token(token_a) != hash_refresh_token(token_b)


def test_encode_and_decode_access_token_round_trips_claims():
    token = encode_access_token(
        actor_id="user-1", tenant_id="default", roles=["user"], secret="test-secret"
    )
    claims = decode_access_token(token, secret="test-secret")
    assert claims["sub"] == "user-1"
    assert claims["tenant_id"] == "default"
    assert claims["roles"] == ["user"]


def test_decode_access_token_rejects_wrong_secret():
    token = encode_access_token(
        actor_id="user-1", tenant_id="default", roles=["user"], secret="test-secret"
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, secret="wrong-secret")
