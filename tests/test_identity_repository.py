"""Integration tests for IdentityRepository — requires PostgreSQL.

Run with:
    TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test \
      python -m unittest tests.test_identity_repository -v
"""

from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine

from agent_hub.database.models import Base
from agent_hub.identity.repository import DuplicateEmailError, IdentityRepository
from tests.factories import ensure_vector_extension

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set — skipping PostgreSQL tests")
class TestIdentityRepository(unittest.TestCase):
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
        self.email = f"user-{uuid.uuid4()}@example.com"

    def test_create_and_get_user_by_email(self):
        created = self.repo.create_user(
            tenant_id="default", email=self.email, password_hash="hash", roles="user"
        )
        self.assertEqual(len(created["id"]), 36)
        self.assertEqual(created["roles"], "user")
        self.assertFalse(created["email_verified"])

        found = self.repo.get_user_by_email("default", self.email)
        self.assertEqual(found["id"], created["id"])

    def test_get_user_by_email_returns_none_when_missing(self):
        self.assertIsNone(self.repo.get_user_by_email("default", "nobody@example.com"))

    def test_create_user_rejects_duplicate_email_in_same_tenant(self):
        self.repo.create_user(
            tenant_id="default", email=self.email, password_hash="hash", roles="user"
        )
        with self.assertRaises(DuplicateEmailError):
            self.repo.create_user(
                tenant_id="default", email=self.email, password_hash="hash2", roles="user"
            )

    def test_create_user_allows_same_email_in_different_tenant(self):
        self.repo.create_user(
            tenant_id="default", email=self.email, password_hash="hash", roles="user"
        )
        other = self.repo.create_user(
            tenant_id="other-tenant", email=self.email, password_hash="hash", roles="user"
        )
        self.assertIsNotNone(other["id"])

    def test_get_user_by_id(self):
        created = self.repo.create_user(
            tenant_id="default", email=self.email, password_hash="hash", roles="user"
        )
        found = self.repo.get_user_by_id(created["id"])
        self.assertEqual(found["email"], self.email)

    def test_refresh_token_lifecycle(self):
        user = self.repo.create_user(
            tenant_id="default", email=self.email, password_hash="hash", roles="user"
        )
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        record = self.repo.create_refresh_token(
            user_id=user["id"],
            tenant_id="default",
            token_hash="hash-of-token",
            expires_at=expires_at,
        )
        self.assertIsNone(record["revoked_at"])

        found = self.repo.get_refresh_token("hash-of-token")
        self.assertEqual(found["id"], record["id"])
        self.assertEqual(found["user_id"], user["id"])

        self.repo.revoke_refresh_token(record["id"])
        revoked = self.repo.get_refresh_token("hash-of-token")
        self.assertIsNotNone(revoked["revoked_at"])

    def test_get_refresh_token_returns_none_when_missing(self):
        self.assertIsNone(self.repo.get_refresh_token("no-such-hash"))
