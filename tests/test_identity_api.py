"""HTTP-level tests for the identity router — requires PostgreSQL.

Run with:
    TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test \
      python -m unittest tests.test_identity_api -v
"""

from __future__ import annotations

import os
import unittest
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from agent_hub.database.models import Base
from agent_hub.identity.http_api import create_identity_router
from agent_hub.identity.repository import IdentityRepository
from agent_hub.identity.service import IdentityService
from tests.factories import ensure_vector_extension
from tests.test_identity_service import FakeRateLimiter

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
JWT_SECRET = "test-jwt-secret"


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set — skipping PostgreSQL tests")
class TestIdentityApi(unittest.TestCase):
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
        repo = IdentityRepository(self.engine)
        service = IdentityService(repo, rate_limiter=FakeRateLimiter(), jwt_secret=JWT_SECRET)
        app = FastAPI()
        app.include_router(create_identity_router(service))
        self.client = TestClient(app)
        self.email = f"user-{uuid.uuid4()}@example.com"
        self.password = "correct horse battery staple"

    def test_register_returns_201_with_tokens(self):
        response = self.client.post(
            "/auth/register", json={"email": self.email, "password": self.password}
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("access_token", body)
        self.assertIn("refresh_token", body)

    def test_register_invalid_email_returns_422(self):
        response = self.client.post(
            "/auth/register", json={"email": "not-an-email", "password": self.password}
        )
        self.assertEqual(response.status_code, 422)

    def test_register_duplicate_email_returns_409(self):
        self.client.post("/auth/register", json={"email": self.email, "password": self.password})
        response = self.client.post(
            "/auth/register", json={"email": self.email, "password": self.password}
        )
        self.assertEqual(response.status_code, 409)

    def test_login_returns_200_with_tokens(self):
        self.client.post("/auth/register", json={"email": self.email, "password": self.password})
        response = self.client.post(
            "/auth/login", json={"email": self.email, "password": self.password}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())

    def test_login_wrong_password_returns_401_with_generic_message(self):
        self.client.post("/auth/register", json={"email": self.email, "password": self.password})
        response = self.client.post("/auth/login", json={"email": self.email, "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid email or password")

    def test_login_unknown_email_returns_same_401_message(self):
        response = self.client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "irrelevant"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid email or password")

    def test_refresh_returns_new_tokens(self):
        register = self.client.post(
            "/auth/register", json={"email": self.email, "password": self.password}
        )
        refresh_token = register.json()["refresh_token"]
        response = self.client.post("/auth/refresh", json={"refresh_token": refresh_token})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["refresh_token"], refresh_token)

    def test_refresh_invalid_token_returns_401(self):
        response = self.client.post("/auth/refresh", json={"refresh_token": "bogus"})
        self.assertEqual(response.status_code, 401)

    def test_logout_returns_204(self):
        register = self.client.post(
            "/auth/register", json={"email": self.email, "password": self.password}
        )
        refresh_token = register.json()["refresh_token"]
        response = self.client.post("/auth/logout", json={"refresh_token": refresh_token})
        self.assertEqual(response.status_code, 204)
