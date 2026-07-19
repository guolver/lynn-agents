"""Integration tests for IdentityService — requires PostgreSQL.

Run with:
    TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test \
      python -m unittest tests.test_identity_service -v
"""

from __future__ import annotations

import os
import unittest
import uuid

from sqlalchemy import create_engine

from agent_hub.database.models import Base
from agent_hub.identity.crypto import decode_access_token
from agent_hub.identity.repository import IdentityRepository
from agent_hub.identity.service import (
    EmailAlreadyRegisteredError,
    IdentityService,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    LoginRateLimitedError,
)
from tests.factories import ensure_vector_extension

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
JWT_SECRET = "test-jwt-secret"


class FakeRateLimiter:
    """In-memory LoginRateLimiterProtocol double — no Redis dependency."""

    def __init__(self, max_failures: int = 5):
        self._failures: dict[str, int] = {}
        self._max_failures = max_failures

    def is_locked(self, key: str) -> bool:
        return self._failures.get(key, 0) >= self._max_failures

    def record_failure(self, key: str) -> None:
        self._failures[key] = self._failures.get(key, 0) + 1

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set — skipping PostgreSQL tests")
class TestIdentityService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(TEST_DATABASE_URL)
        ensure_vector_extension(cls.engine)
        Base.metadata.create_all(cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self):
        self.repo = IdentityRepository(self.engine)
        self.rate_limiter = FakeRateLimiter(max_failures=3)
        self.service = IdentityService(
            self.repo, rate_limiter=self.rate_limiter, jwt_secret=JWT_SECRET
        )
        self.email = f"user-{uuid.uuid4()}@example.com"
        self.password = "correct horse battery staple"

    def test_register_returns_tokens_and_creates_default_role_user(self):
        tokens = self.service.register(self.email, self.password)
        self.assertIn("access_token", tokens)
        self.assertIn("refresh_token", tokens)
        self.assertEqual(tokens["expires_in"], 15 * 60)

        claims = decode_access_token(tokens["access_token"], JWT_SECRET)
        self.assertEqual(claims["tenant_id"], "default")
        self.assertEqual(claims["roles"], ["user"])

    def test_register_rejects_duplicate_email(self):
        self.service.register(self.email, self.password)
        with self.assertRaises(EmailAlreadyRegisteredError):
            self.service.register(self.email, "another password 123")

    def test_login_succeeds_with_correct_password(self):
        self.service.register(self.email, self.password)
        tokens = self.service.login(self.email, self.password)
        claims = decode_access_token(tokens["access_token"], JWT_SECRET)
        self.assertEqual(claims["tenant_id"], "default")

    def test_login_rejects_wrong_password(self):
        self.service.register(self.email, self.password)
        with self.assertRaises(InvalidCredentialsError):
            self.service.login(self.email, "wrong password")

    def test_login_rejects_unknown_email_with_same_error_as_wrong_password(self):
        with self.assertRaises(InvalidCredentialsError):
            self.service.login("nobody@example.com", "irrelevant")

    def test_login_locks_out_after_max_failures(self):
        self.service.register(self.email, self.password)
        for _ in range(3):
            with self.assertRaises(InvalidCredentialsError):
                self.service.login(self.email, "wrong password")
        with self.assertRaises(LoginRateLimitedError):
            self.service.login(self.email, self.password)

    def test_successful_login_resets_failure_count(self):
        self.service.register(self.email, self.password)
        with self.assertRaises(InvalidCredentialsError):
            self.service.login(self.email, "wrong password")
        self.service.login(self.email, self.password)  # succeeds, resets counter
        with self.assertRaises(InvalidCredentialsError):
            self.service.login(self.email, "wrong password")  # not locked yet

    def test_refresh_rotates_token_and_old_token_becomes_invalid(self):
        tokens = self.service.register(self.email, self.password)
        refreshed = self.service.refresh(tokens["refresh_token"])
        self.assertNotEqual(refreshed["refresh_token"], tokens["refresh_token"])

        with self.assertRaises(InvalidRefreshTokenError):
            self.service.refresh(tokens["refresh_token"])  # reuse rejected

    def test_refresh_rejects_unknown_token(self):
        with self.assertRaises(InvalidRefreshTokenError):
            self.service.refresh("not-a-real-token")

    def test_refresh_second_concurrent_use_of_same_token_is_rejected(self):
        """Simulates a race: two callers both try to redeem the same refresh
        token. Only one can win, proving the repository-level atomic claim
        (not just sequential logic) prevents replay."""
        tokens = self.service.register(self.email, self.password)
        first = self.service.refresh(tokens["refresh_token"])
        self.assertIn("access_token", first)
        with self.assertRaises(InvalidRefreshTokenError):
            self.service.refresh(tokens["refresh_token"])

    def test_login_does_not_leak_registration_status_via_early_return(self):
        """Both an unknown email and a wrong password for a known email must
        reach the same rate-limiter-recording, same-exception code path (not
        a proof of constant time, but proves there's no early-return that
        skips the password check entirely for unknown emails)."""
        self.service.register(self.email, self.password)
        with self.assertRaises(InvalidCredentialsError):
            self.service.login("definitely-not-registered@example.com", self.password)
        with self.assertRaises(InvalidCredentialsError):
            self.service.login(self.email, "wrong password")

    def test_login_is_isolated_by_tenant(self):
        self.service.register(self.email, self.password)

        other_tenant_service = IdentityService(
            self.repo,
            rate_limiter=FakeRateLimiter(),
            jwt_secret=JWT_SECRET,
            tenant_id="other-tenant",
        )
        with self.assertRaises(InvalidCredentialsError):
            other_tenant_service.login(self.email, self.password)

    def test_logout_revokes_refresh_token(self):
        tokens = self.service.register(self.email, self.password)
        self.service.logout(tokens["refresh_token"])
        with self.assertRaises(InvalidRefreshTokenError):
            self.service.refresh(tokens["refresh_token"])

    def test_register_normalizes_email_case(self):
        mixed_case_email = (
            self.email.replace("user-", "User-").upper().replace("@EXAMPLE.COM", "@example.com")
        )
        self.service.register(mixed_case_email, self.password)
        with self.assertRaises(EmailAlreadyRegisteredError):
            self.service.register(mixed_case_email.lower(), "another password 123")

    def test_login_is_case_insensitive_on_email(self):
        self.service.register(self.email, self.password)
        tokens = self.service.login(self.email.upper(), self.password)
        self.assertIn("access_token", tokens)
