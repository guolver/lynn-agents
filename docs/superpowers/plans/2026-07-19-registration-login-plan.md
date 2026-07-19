# 注册/登录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement real email/password registration and login (argon2 password hashing, self-issued JWT access tokens, revocable refresh tokens) and wire it end-to-end from the FastAPI backend through the Next.js BFF, replacing the hardcoded `X-Actor: chat-user` proxy headers.

**Architecture:** A new `src/agent_hub/identity/` module (domain/repository/service/http_api layering, mirroring `agents/global_part_time/`) owns user accounts and tokens. `core/security.py`'s `IdentityMiddleware` gains an additional, independent `Authorization: Bearer <JWT>` verification path that builds a `Principal` directly from the token — the existing `trusted_gateway`/`development` header-based paths are untouched. The Next.js BFF stores tokens in httpOnly cookies and forwards `Authorization: Bearer` to FastAPI.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, argon2-cffi, PyJWT, Redis (rate limiting, already in the stack via Celery), Next.js Route Handlers.

**Spec:** `docs/superpowers/specs/2026-07-19-registration-login-design.md`

---

## Implementation note on the `AUTH_JWT_SECRET` fail-fast requirement

The spec says the app should refuse to start in production if `AUTH_JWT_SECRET` is missing, mirroring how `trusted_gateway` mode fail-fasts on a missing `TRUSTED_GATEWAY_SECRET`. Five existing test files (`test_api.py`, `test_app_skill_graph_lifecycle.py`, `test_chat_stream_api.py`, `test_platform.py`, plus any future ones) call `create_app(repo)` without passing `security_settings`, which falls through to `SecuritySettings.from_env()` — and none of them set `AUTH_JWT_SECRET`. Making `from_env()` unconditionally require it would break all of them.

Instead: `SecuritySettings.auth_jwt_secret` stays optional (`None` if the env var is unset), no fail-fast inside `from_env()`. The identity feature is wired in `create_app()` using the same **optional-subsystem** pattern already used for `workflow_tracker`/`celery_instance`/Neo4j/embeddings: if a real engine-backed repository is present **and** `AUTH_JWT_SECRET` is set, the identity router and Bearer-JWT verification are enabled; otherwise the app logs a warning and boots without registration/login (existing functionality is unaffected either way). This achieves the same real-world safety goal — you cannot accidentally run real login with a missing secret, because the feature simply won't be present — without touching the blast radius of `SecuritySettings.from_env()` and its existing callers.

---

## Task 1: Add identity dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `PyJWT` and `argon2-cffi` to `dependencies`**

In `pyproject.toml`, the `dependencies` list currently ends with `"python-dotenv>=1.0,<2",`. Add two entries so the block reads:

```toml
dependencies = [
  "alembic>=1.16,<2",
  "argon2-cffi>=23.1,<24",
  "celery[redis]>=5.4,<6",
  "fastapi>=0.115,<1",
  "langfuse>=3,<4",
  "neo4j>=5.20,<6",
  "openai>=1.30",
  "pgvector>=0.3,<1",
  "pydantic>=2.9,<3",
  "psycopg[binary]>=3.2,<4",
  "pyjwt>=2.13,<3",
  "pypdf>=4.0",
  "python-multipart>=0.0.9",
  "sqlalchemy>=2.0,<3",
  "uvicorn[standard]>=0.30,<1",
  "python-dotenv>=1.0,<2",
]
```

(`PyJWT` and `redis` are already present in `.venv` as transitive dependencies of `mcp` and `celery[redis]` respectively, but neither is declared as a direct dependency of this project — `identity/` will import both directly, so they must be declared explicitly.)

- [ ] **Step 2: Install into the venv**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: `argon2-cffi` installs; `PyJWT` and `redis` are confirmed already satisfied.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: declare argon2-cffi and pyjwt as direct dependencies"
```

---

## Task 2: Add `User` and `RefreshToken` models

**Files:**
- Modify: `src/agent_hub/database/models.py`
- Modify: `tests/test_database_models.py`

- [ ] **Step 1: Write the failing test — extend the exhaustive table/constraint assertions**

In `tests/test_database_models.py`, add `"users"` and `"refresh_tokens"` to `EXPECTED_TABLES`:

```python
EXPECTED_TABLES = {
    "job_sources",
    "source_sync_runs",
    "raw_jobs",
    "jobs",
    "job_versions",
    "candidates",
    "candidate_experiences",
    "candidate_skills",
    "skills",
    "skill_aliases",
    "skill_relations",
    "job_skills",
    "matches",
    "match_evidence",
    "match_score_items",
    "workflow_runs",
    "workflow_steps",
    "approvals",
    "notifications",
    "feedback",
    "audit_logs",
    "idempotency_records",
    "chat_sessions",
    "chat_messages",
    "workflow_commands",
    "workflow_command_payloads",
    "users",
    "refresh_tokens",
}
```

In `test_natural_keys_have_database_unique_constraints`, add an entry to `expected`:

```python
        expected = {
            "raw_jobs": {
                ("source_id", "source_job_id"),
                ("canonical_url",),
                ("content_fingerprint",),
            },
            "jobs": {("tenant_id", "dedup_key")},
            "matches": {("tenant_id", "candidate_id", "job_id")},
            "notifications": {("provider_message_id",)},
            "idempotency_records": {("tenant_id", "action", "key")},
            "workflow_commands": {("tenant_id", "action", "idempotency_key")},
            "users": {("tenant_id", "email")},
        }
```

In `test_relationship_tables_have_explicit_foreign_keys`, add an entry to `expected`:

```python
            "notifications": {"candidate_id"},
            "feedback": {"match_id", "candidate_id"},
            "refresh_tokens": {"user_id"},
        }
```

Add a new test method to `DatabaseModelTest`:

```python
    def test_users_table_has_tenant_scoped_non_nullable_columns(self):
        table = Base.metadata.tables["users"]
        for column_name in ("tenant_id", "email", "password_hash", "roles"):
            self.assertFalse(table.c[column_name].nullable)
        self.assertFalse(table.c.email_verified.nullable)

    def test_refresh_tokens_table_has_revocation_columns(self):
        table = Base.metadata.tables["refresh_tokens"]
        for column_name in ("user_id", "tenant_id", "token_hash", "expires_at"):
            self.assertFalse(table.c[column_name].nullable)
        self.assertTrue(table.c.revoked_at.nullable)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m unittest tests.test_database_models -v`
Expected: FAIL — `KeyError: 'users'` (table doesn't exist yet) and the `EXPECTED_TABLES` set comparison fails.

- [ ] **Step 3: Add the models**

In `src/agent_hub/database/models.py`, find the `AuditLog` class (the last model in the file) and add two new classes after it:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[str] = mapped_column(String(100), nullable=False, default="user")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        Index("ix_refresh_tokens_user_id", "user_id"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m unittest tests.test_database_models -v`
Expected: PASS (all `DatabaseModelTest` methods).

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/database/models.py tests/test_database_models.py
git commit -m "feat(identity): add User and RefreshToken models"
```

---

## Task 3: Alembic migration for `users` and `refresh_tokens`

**Files:**
- Create: `alembic/versions/20260719_0009_users_and_refresh_tokens.py`

- [ ] **Step 1: Write the migration**

```python
"""Add users and refresh_tokens tables for self-issued authentication.

Revision ID: 20260719_0009
Revises: 20260719_0008
Create Date: 2026-07-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260719_0009"
down_revision: Union[str, None] = "20260719_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("roles", sa.String(100), nullable=False, server_default="user"),
        sa.Column(
            "email_verified", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
```

- [ ] **Step 2: Verify against a real database (manual, requires `TEST_DATABASE_URL`-style Postgres)**

Run:
```bash
source .venv/bin/activate
DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test alembic upgrade head
DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test alembic downgrade -1
DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test alembic upgrade head
```
Expected: all three commands succeed with no errors. This project's Postgres integration tests build schema via `Base.metadata.create_all` rather than by running Alembic (see `tests/test_workflow_tracker.py`, `tests/test_postgres_repository.py`), so this manual round-trip is the verification step for the migration file itself — consistent with how migrations 0002–0006 and 0008 were handled (only the complex data-backfilling 0007 migration got a dedicated test).

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/20260719_0009_users_and_refresh_tokens.py
git commit -m "feat(identity): add users and refresh_tokens migration"
```

---

## Task 4: `identity/domain.py` — email and password validation

**Files:**
- Create: `src/agent_hub/identity/__init__.py`
- Create: `src/agent_hub/identity/domain.py`
- Create: `tests/test_identity_domain.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for pure identity validation rules."""

from __future__ import annotations

import pytest

from agent_hub.identity.domain import ValidationError, validate_email, validate_password


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_identity_domain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.identity'`

- [ ] **Step 3: Create the package and implementation**

Create `src/agent_hub/identity/__init__.py` (empty):

```python
```

Create `src/agent_hub/identity/domain.py`:

```python
"""Pure validation rules for registration — no I/O, no side effects.

Password rules deliberately check length only (>= 8 characters), not
composition (uppercase/digit/symbol). NIST SP 800-63B recommends length over
composition rules: forced complexity pushes users toward predictable patterns
(``Passw0rd!``) without meaningfully raising resistance to brute force.
"""

from __future__ import annotations

import re

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LENGTH = 8


class ValidationError(ValueError):
    """Raised when registration input fails a domain rule."""


def validate_email(email: str) -> None:
    if not _EMAIL_PATTERN.match(email):
        raise ValidationError("invalid email format")


def validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise ValidationError(f"password must be at least {_MIN_PASSWORD_LENGTH} characters")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_identity_domain.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/identity/__init__.py src/agent_hub/identity/domain.py tests/test_identity_domain.py
git commit -m "feat(identity): add email and password validation rules"
```

---

## Task 5: `identity/crypto.py` — password hashing, JWT, token hashing

**Files:**
- Create: `src/agent_hub/identity/crypto.py`
- Create: `tests/test_identity_crypto.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for identity crypto primitives: password hashing, JWT, token hashing."""

from __future__ import annotations

import time

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_identity_crypto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.identity.crypto'`

- [ ] **Step 3: Write the implementation**

```python
"""Crypto primitives for self-issued authentication.

- Passwords: argon2id via ``argon2-cffi``.
- Access tokens: stateless JWT (HS256), short-lived, never persisted.
- Refresh tokens: random opaque strings; only their SHA-256 hash is persisted,
  so a database read alone never reveals a usable credential.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)
_JWT_ALGORITHM = "HS256"

_hasher = PasswordHasher()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    return True


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def encode_access_token(
    *, actor_id: str, tenant_id: str, roles: list[str], secret: str
) -> str:
    now = _utcnow()
    payload = {
        "sub": actor_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=[_JWT_ALGORITHM])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_identity_crypto.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/identity/crypto.py tests/test_identity_crypto.py
git commit -m "feat(identity): add password hashing and JWT crypto primitives"
```

---

## Task 6: `identity/rate_limiter.py` — Redis-backed login rate limiting

**Files:**
- Create: `src/agent_hub/identity/rate_limiter.py`
- Create: `tests/test_identity_rate_limiter.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the Redis-backed login rate limiter.

依赖本地 Redis（docker compose 的 redis 服务，localhost:6379），沿用
tests/test_stream_hub.py 的可用性探测 + skip 模式。
"""

from __future__ import annotations

import uuid

import pytest

from agent_hub.identity.rate_limiter import RedisLoginRateLimiter

REDIS_URL = "redis://localhost:6379/0"


@pytest.fixture()
def limiter():
    instance = RedisLoginRateLimiter(REDIS_URL, max_failures=3, window_seconds=900)
    if not instance.available():
        pytest.skip("Redis not available at localhost:6379")
    return instance


@pytest.fixture()
def key():
    return f"test:{uuid.uuid4()}"


def test_is_locked_false_when_no_failures(limiter, key):
    assert limiter.is_locked(key) is False


def test_locks_after_max_failures(limiter, key):
    for _ in range(3):
        limiter.record_failure(key)
    assert limiter.is_locked(key) is True


def test_reset_clears_failures(limiter, key):
    for _ in range(3):
        limiter.record_failure(key)
    limiter.reset(key)
    assert limiter.is_locked(key) is False


def test_fails_open_when_redis_unreachable():
    unreachable = RedisLoginRateLimiter(
        "redis://127.0.0.1:1/0", max_failures=3, window_seconds=900
    )
    assert unreachable.available() is False
    assert unreachable.is_locked("any-key") is False
    unreachable.record_failure("any-key")  # must not raise
    unreachable.reset("any-key")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_identity_rate_limiter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.identity.rate_limiter'`

- [ ] **Step 3: Write the implementation**

```python
"""Login attempt rate limiting.

``LoginRateLimiterProtocol`` lets ``IdentityService`` be tested with a fake
(no Redis dependency); ``RedisLoginRateLimiter`` is the production
implementation, reusing the same Redis instance as Celery/StreamHub.

Fails open: if Redis is unreachable, login proceeds without rate limiting
rather than locking every user out — consistent with how ``StreamHub`` and
the skill graph degrade when their backing service is unavailable.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class LoginRateLimiterProtocol(Protocol):
    def is_locked(self, key: str) -> bool: ...

    def record_failure(self, key: str) -> None: ...

    def reset(self, key: str) -> None: ...


class RedisLoginRateLimiter:
    """Fixed-window login failure counter backed by Redis."""

    def __init__(self, redis_url: str, *, max_failures: int = 5, window_seconds: int = 900):
        import redis

        self._redis = redis.Redis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )
        self._max_failures = max_failures
        self._window_seconds = window_seconds

    def available(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    @staticmethod
    def _redis_key(key: str) -> str:
        return f"login_fail:{key}"

    def is_locked(self, key: str) -> bool:
        try:
            count = self._redis.get(self._redis_key(key))
        except Exception:
            logger.warning("Redis unreachable for login rate limit check", exc_info=True)
            return False
        return count is not None and int(count) >= self._max_failures

    def record_failure(self, key: str) -> None:
        try:
            redis_key = self._redis_key(key)
            pipeline = self._redis.pipeline()
            pipeline.incr(redis_key)
            pipeline.expire(redis_key, self._window_seconds)
            pipeline.execute()
        except Exception:
            logger.warning("Redis unreachable for login failure recording", exc_info=True)

    def reset(self, key: str) -> None:
        try:
            self._redis.delete(self._redis_key(key))
        except Exception:
            logger.warning("Redis unreachable for login rate limit reset", exc_info=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_identity_rate_limiter.py -v`
Expected: PASS (4 tests) if local Redis is running (`docker compose up -d redis`), otherwise the first three SKIP and the fail-open test PASSes (it never touches real Redis).

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/identity/rate_limiter.py tests/test_identity_rate_limiter.py
git commit -m "feat(identity): add Redis-backed login rate limiter"
```

---

## Task 7: `identity/repository.py` — user and refresh token persistence

**Files:**
- Create: `src/agent_hub/identity/repository.py`
- Create: `tests/test_identity_repository.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test source .venv/bin/activate && python -m pytest tests/test_identity_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.identity.repository'` (if `TEST_DATABASE_URL` isn't set, the whole class SKIPs instead — start a local Postgres via `docker compose up -d postgres` and point at a scratch database first, e.g. `agent_hub_test`, created with `createdb agent_hub_test` or by connecting once and running `CREATE DATABASE agent_hub_test;`).

- [ ] **Step 3: Write the implementation**

```python
"""User and refresh-token persistence.

Mirrors ``worker/workflow.py``'s ``WorkflowTracker``: owns an independent
sessionmaker over the shared engine and returns plain dicts rather than ORM
objects, matching the rest of the repository layer's conventions. Bypasses
the generic ``put``/``get``/``list`` kind-based ``RepositoryProtocol`` because
identity needs query-by-email and query-by-token-hash, which that protocol
does not support.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from agent_hub.database.models import RefreshToken, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class DuplicateEmailError(Exception):
    """Raised when a (tenant_id, email) pair already has a user."""


def _user_to_dict(row: User) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "email": row.email,
        "password_hash": row.password_hash,
        "roles": row.roles,
        "email_verified": row.email_verified,
    }


def _refresh_token_to_dict(row: RefreshToken) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "tenant_id": row.tenant_id,
        "token_hash": row.token_hash,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
    }


class IdentityRepository:
    """Storage for ``users`` and ``refresh_tokens``."""

    def __init__(self, engine: Engine):
        self._session_factory = sessionmaker(bind=engine)

    def _session(self) -> Session:
        return self._session_factory()

    def create_user(
        self, *, tenant_id: str, email: str, password_hash: str, roles: str
    ) -> dict[str, Any]:
        session = self._session()
        try:
            user = User(
                id=_new_id(),
                tenant_id=tenant_id,
                email=email,
                password_hash=password_hash,
                roles=roles,
            )
            session.add(user)
            session.commit()
            return _user_to_dict(user)
        except IntegrityError:
            session.rollback()
            raise DuplicateEmailError(email) from None
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_user_by_email(self, tenant_id: str, email: str) -> dict[str, Any] | None:
        session = self._session()
        try:
            row = session.execute(
                select(User).filter_by(tenant_id=tenant_id, email=email)
            ).scalar_one_or_none()
            return _user_to_dict(row) if row else None
        finally:
            session.close()

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        session = self._session()
        try:
            row = session.get(User, user_id)
            return _user_to_dict(row) if row else None
        finally:
            session.close()

    def create_refresh_token(
        self, *, user_id: str, tenant_id: str, token_hash: str, expires_at: datetime
    ) -> dict[str, Any]:
        session = self._session()
        try:
            token = RefreshToken(
                id=_new_id(),
                user_id=user_id,
                tenant_id=tenant_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            session.add(token)
            session.commit()
            return _refresh_token_to_dict(token)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_refresh_token(self, token_hash: str) -> dict[str, Any] | None:
        session = self._session()
        try:
            row = session.execute(
                select(RefreshToken).filter_by(token_hash=token_hash)
            ).scalar_one_or_none()
            return _refresh_token_to_dict(row) if row else None
        finally:
            session.close()

    def revoke_refresh_token(self, token_id: str) -> None:
        session = self._session()
        try:
            token = session.get(RefreshToken, token_id)
            if token is not None:
                token.revoked_at = _utcnow()
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test python -m pytest tests/test_identity_repository.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/identity/repository.py tests/test_identity_repository.py
git commit -m "feat(identity): add IdentityRepository for users and refresh tokens"
```

---

## Task 8: `identity/service.py` — register/login/refresh/logout use cases

**Files:**
- Create: `src/agent_hub/identity/service.py`
- Create: `tests/test_identity_service.py`

- [ ] **Step 1: Write the failing test**

```python
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

    def test_logout_revokes_refresh_token(self):
        tokens = self.service.register(self.email, self.password)
        self.service.logout(tokens["refresh_token"])
        with self.assertRaises(InvalidRefreshTokenError):
            self.service.refresh(tokens["refresh_token"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test python -m pytest tests/test_identity_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.identity.service'`

- [ ] **Step 3: Write the implementation**

```python
"""Registration/login/refresh/logout use cases.

Orchestrates domain validation, password/JWT crypto, rate limiting, and
persistence. Collaborators (repository, rate limiter) are constructor-injected
— composition happens at the call site (``app.py`` for production, test
fixtures for tests), matching this codebase's stated composition-root
philosophy (see ``app.py``'s ``create_app`` docstring).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .crypto import (
    REFRESH_TOKEN_TTL,
    encode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from .domain import validate_email, validate_password
from .rate_limiter import LoginRateLimiterProtocol
from .repository import DuplicateEmailError, IdentityRepository

ACCESS_TOKEN_TTL_SECONDS = 15 * 60


class EmailAlreadyRegisteredError(Exception):
    """A user with this (tenant_id, email) already exists."""


class InvalidCredentialsError(Exception):
    """Email/password did not match — deliberately does not say which."""


class LoginRateLimitedError(Exception):
    """Too many recent failed login attempts for this email."""


class InvalidRefreshTokenError(Exception):
    """Refresh token is unknown, expired, or already revoked."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IdentityService:
    def __init__(
        self,
        repository: IdentityRepository,
        *,
        rate_limiter: LoginRateLimiterProtocol,
        jwt_secret: str,
        tenant_id: str = "default",
    ):
        self._repo = repository
        self._rate_limiter = rate_limiter
        self._jwt_secret = jwt_secret
        self._tenant_id = tenant_id

    def register(self, email: str, password: str) -> dict[str, Any]:
        validate_email(email)
        validate_password(password)
        try:
            user = self._repo.create_user(
                tenant_id=self._tenant_id,
                email=email,
                password_hash=hash_password(password),
                roles="user",
            )
        except DuplicateEmailError:
            raise EmailAlreadyRegisteredError(email) from None
        return self._issue_tokens(user)

    def login(self, email: str, password: str) -> dict[str, Any]:
        rate_key = f"{self._tenant_id}:{email}"
        if self._rate_limiter.is_locked(rate_key):
            raise LoginRateLimitedError(email)

        user = self._repo.get_user_by_email(self._tenant_id, email)
        if user is None or not verify_password(password, user["password_hash"]):
            self._rate_limiter.record_failure(rate_key)
            raise InvalidCredentialsError()

        self._rate_limiter.reset(rate_key)
        return self._issue_tokens(user)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        record = self._repo.get_refresh_token(hash_refresh_token(refresh_token))
        if record is None or record["revoked_at"] is not None or record["expires_at"] <= _utcnow():
            raise InvalidRefreshTokenError()

        self._repo.revoke_refresh_token(record["id"])
        user = self._repo.get_user_by_id(record["user_id"])
        if user is None:
            raise InvalidRefreshTokenError()
        return self._issue_tokens(user)

    def logout(self, refresh_token: str) -> None:
        record = self._repo.get_refresh_token(hash_refresh_token(refresh_token))
        if record is not None and record["revoked_at"] is None:
            self._repo.revoke_refresh_token(record["id"])

    def _issue_tokens(self, user: dict[str, Any]) -> dict[str, Any]:
        roles = user["roles"].split(",")
        access_token = encode_access_token(
            actor_id=user["id"], tenant_id=user["tenant_id"], roles=roles, secret=self._jwt_secret
        )
        refresh_token = new_refresh_token()
        self._repo.create_refresh_token(
            user_id=user["id"],
            tenant_id=user["tenant_id"],
            token_hash=hash_refresh_token(refresh_token),
            expires_at=_utcnow() + REFRESH_TOKEN_TTL,
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test python -m pytest tests/test_identity_service.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/identity/service.py tests/test_identity_service.py
git commit -m "feat(identity): add IdentityService register/login/refresh/logout"
```

---

## Task 9: `IdentityMiddleware` Bearer JWT path

**Files:**
- Modify: `src/agent_hub/core/security.py`
- Modify: `tests/test_security.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_security.py`, update the `_app` helper to accept an optional JWT secret, and add new test cases. Replace the existing `_app` function and add tests after `test_identity_middleware_does_not_bypass_similar_path`:

```python
def _app(mode="trusted_gateway", secret="secret", auth_jwt_secret=None):
    app = FastAPI()
    app.add_middleware(
        IdentityMiddleware, mode=mode, gateway_secret=secret, auth_jwt_secret=auth_jwt_secret
    )

    @app.get("/protected", dependencies=[require_roles(Role.OPERATOR)])
    def protected():
        return {"ok": True}

    return TestClient(app)
```

(This changes the signature but keeps all existing default-argument call sites working unchanged.)

Add at the end of the file:

```python
def test_bearer_token_builds_trusted_principal():
    import jwt

    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "acme", "roles": ["operator"]},
        "jwt-secret",
        algorithm="HS256",
    )
    client = _app(auth_jwt_secret="jwt-secret")

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_bearer_token_with_wrong_secret_is_rejected():
    import jwt

    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "acme", "roles": ["operator"]},
        "wrong-secret",
        algorithm="HS256",
    )
    client = _app(auth_jwt_secret="jwt-secret")

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_bearer_token_with_unknown_role_is_rejected():
    import jwt

    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "acme", "roles": ["superuser"]},
        "jwt-secret",
        algorithm="HS256",
    )
    client = _app(auth_jwt_secret="jwt-secret")

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_bearer_path_ignored_when_no_secret_configured_falls_back_to_headers():
    client = _app(auth_jwt_secret=None)

    response = client.get(
        "/protected",
        headers={
            "Authorization": "Bearer whatever",
            "X-Actor": "op-1",
            "X-Tenant-Id": "acme",
            "X-Roles": "operator",
            "X-Gateway-Token": "secret",
        },
    )

    assert response.status_code == 200


def test_auth_endpoints_are_bypassed_by_identity_middleware():
    client = _app()

    response = client.get("/auth/login")  # no route registered, but must not 401

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_security.py -v`
Expected: FAIL — `TypeError: IdentityMiddleware.__init__() got an unexpected keyword argument 'auth_jwt_secret'`

- [ ] **Step 3: Modify `IdentityMiddleware` and `SecuritySettings`**

In `src/agent_hub/core/security.py`, replace the `SecuritySettings` class:

```python
@dataclass(frozen=True)
class SecuritySettings:
    mode: Literal["trusted_gateway", "development"]
    gateway_secret: str | None
    development_default_roles: frozenset[Role]
    auth_jwt_secret: str | None = None

    @classmethod
    def from_env(cls) -> "SecuritySettings":
        mode = os.getenv("SECURITY_MODE", "development")
        if mode not in {"trusted_gateway", "development"}:
            raise RuntimeError(f"unsupported SECURITY_MODE: {mode}")
        secret = os.getenv("TRUSTED_GATEWAY_SECRET")
        if mode == "trusted_gateway" and not secret:
            raise RuntimeError("TRUSTED_GATEWAY_SECRET is required in trusted_gateway mode")
        roles = parse_roles(os.getenv("DEVELOPMENT_DEFAULT_ROLES", "admin,operator,user"))
        return cls(
            mode=mode,
            gateway_secret=secret,
            development_default_roles=roles,
            auth_jwt_secret=os.getenv("AUTH_JWT_SECRET"),
        )
```

Replace the `IdentityMiddleware` class's `_BYPASS_PATHS`, `__init__`, and `dispatch`:

```python
class IdentityMiddleware(BaseHTTPMiddleware):
    _BYPASS_PATHS = frozenset(
        {
            "/health",
            "/live",
            "/ready",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/auth/register",
            "/auth/login",
            "/auth/refresh",
            "/auth/logout",
        }
    )

    def __init__(
        self,
        app: ASGIApp,
        *,
        mode: Literal["trusted_gateway", "development"],
        gateway_secret: str | None = None,
        development_default_roles: frozenset[Role] = frozenset(Role),
        auth_jwt_secret: str | None = None,
    ) -> None:
        super().__init__(app)
        self.mode = mode
        self.gateway_secret = gateway_secret
        self.development_default_roles = development_default_roles
        self.auth_jwt_secret = auth_jwt_secret

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._BYPASS_PATHS:
            return await call_next(request)

        if self.auth_jwt_secret:
            authorization = request.headers.get("Authorization")
            if authorization and authorization.startswith("Bearer "):
                principal = self._principal_from_bearer_token(
                    authorization.removeprefix("Bearer ")
                )
                if principal is None:
                    return self._unauthorized()
                request.state.principal = principal
                return await call_next(request)

        actor = request.headers.get("X-Actor")
        tenant_id = request.headers.get("X-Tenant-Id")
        roles = request.headers.get("X-Roles")
        if self.mode == "development":
            if not actor:
                return self._unauthorized()
            try:
                parsed_roles = (
                    parse_roles(roles) if roles is not None else self.development_default_roles
                )
            except ValueError:
                return self._unauthorized()
            request.state.principal = Principal(
                actor_id=actor,
                tenant_id=tenant_id or "default",
                roles=parsed_roles,
                trusted=False,
            )
            return await call_next(request)

        token = request.headers.get("X-Gateway-Token")
        if not all((actor, tenant_id, roles, token)) or not hmac.compare_digest(
            token or "", self.gateway_secret or ""
        ):
            return self._unauthorized()
        try:
            parsed_roles = parse_roles(roles)
        except ValueError:
            return self._unauthorized()
        request.state.principal = Principal(actor, tenant_id, parsed_roles, True)
        return await call_next(request)

    def _principal_from_bearer_token(self, token: str) -> Principal | None:
        import jwt as pyjwt

        try:
            claims = pyjwt.decode(token, self.auth_jwt_secret, algorithms=["HS256"])
            roles = frozenset(Role(value) for value in claims["roles"])
            if not roles:
                return None
            return Principal(
                actor_id=claims["sub"],
                tenant_id=claims["tenant_id"],
                roles=roles,
                trusted=True,
            )
        except (pyjwt.InvalidTokenError, KeyError, ValueError):
            return None

    @staticmethod
    def _unauthorized() -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "trusted gateway authentication required"},
        )
```

- [ ] **Step 4: Update the existing env-based settings test for the new field**

In `tests/test_security.py`, update `test_security_settings_load_development_roles` to also assert the new field defaults to `None` when unset (no other change needed since `AUTH_JWT_SECRET` stays optional):

```python
def test_security_settings_load_development_roles(monkeypatch):
    monkeypatch.setenv("SECURITY_MODE", "development")
    monkeypatch.setenv("DEVELOPMENT_DEFAULT_ROLES", "operator,user")
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    settings = SecuritySettings.from_env()

    assert settings.mode == "development"
    assert settings.gateway_secret is None
    assert settings.development_default_roles == frozenset({Role.OPERATOR, Role.USER})
    assert settings.auth_jwt_secret is None


def test_security_settings_load_auth_jwt_secret_when_set(monkeypatch):
    monkeypatch.setenv("SECURITY_MODE", "development")
    monkeypatch.setenv("AUTH_JWT_SECRET", "jwt-secret")

    settings = SecuritySettings.from_env()

    assert settings.auth_jwt_secret == "jwt-secret"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_security.py -v`
Expected: PASS (all tests, including the new ones).

- [ ] **Step 6: Run the full existing security-dependent suite for regressions**

Run: `source .venv/bin/activate && python -m pytest tests/test_security.py tests/test_platform.py -v`
Expected: PASS, zero regressions.

- [ ] **Step 7: Commit**

```bash
git add src/agent_hub/core/security.py tests/test_security.py
git commit -m "feat(security): add Bearer JWT verification path to IdentityMiddleware"
```

---

## Task 10: `identity/http_api.py` — REST endpoints

**Files:**
- Create: `src/agent_hub/identity/http_api.py`
- Create: `tests/test_identity_api.py`

- [ ] **Step 1: Write the failing test**

```python
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
        service = IdentityService(
            repo, rate_limiter=FakeRateLimiter(), jwt_secret=JWT_SECRET
        )
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
        response = self.client.post(
            "/auth/login", json={"email": self.email, "password": "wrong"}
        )
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test python -m pytest tests/test_identity_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.identity.http_api'`

- [ ] **Step 3: Write the implementation**

```python
"""REST endpoints for registration/login/refresh/logout.

These four routes are listed in ``IdentityMiddleware._BYPASS_PATHS`` — they
establish identity, so they cannot themselves require an already-authenticated
principal. Errors are handled inline (matching the style already used in
``agents/global_part_time/http_api.py``) rather than via app-wide exception
handlers, keeping this router self-contained.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .domain import ValidationError
from .service import (
    EmailAlreadyRegisteredError,
    IdentityService,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    LoginRateLimitedError,
)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


def create_identity_router(service: IdentityService) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["identity"])

    @router.post("/register", status_code=201)
    def register(body: RegisterRequest):
        try:
            return service.register(body.email, body.password)
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": str(exc)})
        except EmailAlreadyRegisteredError:
            return JSONResponse(status_code=409, content={"detail": "email already registered"})

    @router.post("/login")
    def login(body: LoginRequest):
        try:
            return service.login(body.email, body.password)
        except LoginRateLimitedError:
            return JSONResponse(
                status_code=429, content={"detail": "too many failed login attempts"}
            )
        except InvalidCredentialsError:
            return JSONResponse(
                status_code=401, content={"detail": "invalid email or password"}
            )

    @router.post("/refresh")
    def refresh(body: RefreshRequest):
        try:
            return service.refresh(body.refresh_token)
        except InvalidRefreshTokenError:
            return JSONResponse(status_code=401, content={"detail": "invalid refresh token"})

    @router.post("/logout", status_code=204)
    def logout(body: LogoutRequest):
        service.logout(body.refresh_token)
        return None

    return router
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test python -m pytest tests/test_identity_api.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/identity/http_api.py tests/test_identity_api.py
git commit -m "feat(identity): add /auth register, login, refresh, logout endpoints"
```

---

## Task 11: Wire identity into `create_app`

**Files:**
- Modify: `src/agent_hub/app.py`

- [ ] **Step 1: Add the middleware secret and optional identity wiring**

In `src/agent_hub/app.py`, update the `IdentityMiddleware` registration (around line 166) to pass the new secret:

```python
    application.add_middleware(
        IdentityMiddleware,
        mode=settings.mode,
        gateway_secret=settings.gateway_secret,
        development_default_roles=settings.development_default_roles,
        auth_jwt_secret=settings.auth_jwt_secret,
    )
```

Immediately after the existing `# --- Workflow tracker (PostgreSQL only) ---` block (which sets `workflow_tracker`), add a new optional-subsystem block:

```python
    # --- Identity: registration/login (PostgreSQL + AUTH_JWT_SECRET required) ---
    identity_router = None
    if hasattr(repo, "_engine") and settings.auth_jwt_secret:
        try:
            from .identity.http_api import create_identity_router
            from .identity.rate_limiter import RedisLoginRateLimiter
            from .identity.repository import IdentityRepository
            from .identity.service import IdentityService

            identity_repo = IdentityRepository(repo._engine)
            identity_rate_limiter = RedisLoginRateLimiter(stream_redis_url)
            identity_service = IdentityService(
                identity_repo,
                rate_limiter=identity_rate_limiter,
                jwt_secret=settings.auth_jwt_secret,
            )
            identity_router = create_identity_router(identity_service)
            logger.info("Identity service initialized (registration/login enabled)")
        except Exception:
            logger.warning("Failed to initialize identity service", exc_info=True)
    elif hasattr(repo, "_engine"):
        logger.warning("AUTH_JWT_SECRET not set — registration/login endpoints disabled")
```

This block must come after `stream_redis_url` is computed (search for `stream_redis_url = (` — it's defined just below the `# --- Chat stream hub` comment, before the `workflow_tracker` block) so it can reuse the same Redis instance as `StreamHub`.

Finally, register the router next to the other `include_router` calls (after `application.include_router(http_api.router)`):

```python
    application.include_router(http_api.router)
    if identity_router is not None:
        application.include_router(identity_router)
    if skill_graph_router is not None:
        application.include_router(skill_graph_router)
```

- [ ] **Step 2: Run the full existing suite to confirm zero regressions**

Run: `source .venv/bin/activate && python -m unittest discover -s tests -v 2>&1 | tail -40`
Expected: same pass/skip counts as before this task for every test file untouched by this plan (identity tests SKIP unless `TEST_DATABASE_URL` is set; that's expected and matches how `test_workflow_tracker.py` already behaves).

- [ ] **Step 3: Manually verify end-to-end against Docker Compose**

Run:
```bash
echo "AUTH_JWT_SECRET=local-dev-secret-change-me" >> .env
docker compose up --build -d postgres redis api
sleep 5
curl -s -X POST http://localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"correct horse battery staple"}'
```
Expected: JSON response with `access_token`, `refresh_token`, `expires_in`.

- [ ] **Step 4: Commit**

```bash
git add src/agent_hub/app.py
git commit -m "feat(identity): wire registration/login into create_app"
```

---

## Task 12: Document and provision `AUTH_JWT_SECRET`

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `docs/dev-guide.md`

- [ ] **Step 1: Add the env var to `.env.example`**

Add a line (grouped with any existing secret-like entries):

```
AUTH_JWT_SECRET=change-me-to-a-random-secret
```

- [ ] **Step 2: Add it to the `api` service environment in `docker-compose.yml`**

In the `api` service's `environment:` block, add:

```yaml
      AUTH_JWT_SECRET: ${AUTH_JWT_SECRET:-dev-insecure-secret-change-me}
```

- [ ] **Step 3: Document it in `docs/dev-guide.md`**

Open `docs/dev-guide.md`, find where `SECURITY_MODE`/`TRUSTED_GATEWAY_SECRET` (or equivalent env var docs) are described, and add a short entry:

```markdown
- `AUTH_JWT_SECRET`：注册/登录签发的 access token 签名密钥。本地开发用
  `.env.example` 里的默认值即可；缺失时应用仍能启动，但 `/auth/*` 路由不会注册
  （日志会打印警告）。
```

If `docs/dev-guide.md` has no existing env var section, add this as a new small subsection near wherever `DATABASE_URL`/`SECURITY_MODE` are already documented.

- [ ] **Step 4: Commit**

```bash
git add .env.example docker-compose.yml docs/dev-guide.md
git commit -m "docs: document AUTH_JWT_SECRET for local dev and docker compose"
```

---

## Task 13: Frontend — cookie option helper

**Files:**
- Create: `frontend/lib/auth-cookies.ts`

- [ ] **Step 1: Write the helper**

```typescript
export const ACCESS_TOKEN_COOKIE = 'access_token';
export const REFRESH_TOKEN_COOKIE = 'refresh_token';
const REFRESH_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days, matches backend REFRESH_TOKEN_TTL

type CookieOptions = {
  httpOnly: true;
  secure: boolean;
  sameSite: 'lax';
  path: '/';
  maxAge: number;
};

function baseCookieOptions(maxAge: number): CookieOptions {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    maxAge,
  };
}

export function accessTokenCookieOptions(expiresInSeconds: number): CookieOptions {
  return baseCookieOptions(expiresInSeconds);
}

export function refreshTokenCookieOptions(): CookieOptions {
  return baseCookieOptions(REFRESH_TOKEN_MAX_AGE_SECONDS);
}

export function expiredCookieOptions(): CookieOptions {
  return baseCookieOptions(0);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/auth-cookies.ts
git commit -m "feat(frontend): add auth cookie option helpers"
```

(No dedicated test — this file has no branching logic beyond `NODE_ENV`, consistent with this frontend's existing test depth; it's exercised indirectly by the route handlers in the following tasks.)

---

## Task 14: Frontend — `/api/auth/register` and `/api/auth/login` routes

**Files:**
- Create: `frontend/app/api/auth/register/route.ts`
- Create: `frontend/app/api/auth/login/route.ts`

- [ ] **Step 1: Write `frontend/app/api/auth/register/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, accessTokenCookieOptions, refreshTokenCookieOptions } from '../../../../lib/auth-cookies';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export async function POST(request: NextRequest) {
  const body = await request.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }

  if (!upstream.ok) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const tokens = (await upstream.json()) as TokenResponse;
  const response = NextResponse.json({ ok: true }, { status: 201 });
  response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, accessTokenCookieOptions(tokens.expires_in));
  response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, refreshTokenCookieOptions());
  return response;
}
```

- [ ] **Step 2: Write `frontend/app/api/auth/login/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, accessTokenCookieOptions, refreshTokenCookieOptions } from '../../../../lib/auth-cookies';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export async function POST(request: NextRequest) {
  const body = await request.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }

  if (!upstream.ok) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const tokens = (await upstream.json()) as TokenResponse;
  const response = NextResponse.json({ ok: true });
  response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, accessTokenCookieOptions(tokens.expires_in));
  response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, refreshTokenCookieOptions());
  return response;
}
```

- [ ] **Step 3: Manually verify**

With `docker compose up -d postgres redis api` and `AUTH_JWT_SECRET` set, run `cd frontend && pnpm dev`, then:

```bash
curl -i -c /tmp/cookies.txt -X POST http://localhost:3000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"frontend-demo@example.com","password":"correct horse battery staple"}'
```
Expected: `201`, response body `{"ok":true}`, and `Set-Cookie` headers for `access_token`/`refresh_token` (visible with `-i`).

- [ ] **Step 4: Commit**

```bash
git add frontend/app/api/auth/register/route.ts frontend/app/api/auth/login/route.ts
git commit -m "feat(frontend): add register and login BFF routes"
```

---

## Task 15: Frontend — `/api/auth/refresh` and `/api/auth/logout` routes

**Files:**
- Create: `frontend/app/api/auth/refresh/route.ts`
- Create: `frontend/app/api/auth/logout/route.ts`

- [ ] **Step 1: Write `frontend/app/api/auth/refresh/route.ts`**

```typescript
import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  accessTokenCookieOptions,
  expiredCookieOptions,
  refreshTokenCookieOptions,
} from '../../../../lib/auth-cookies';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export async function POST() {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) {
    return Response.json({ detail: '未登录' }, { status: 401 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }

  if (!upstream.ok) {
    const response = new Response(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
    return response;
  }

  const tokens = (await upstream.json()) as TokenResponse;
  const response = NextResponse.json({ ok: true });
  response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, accessTokenCookieOptions(tokens.expires_in));
  response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, refreshTokenCookieOptions());
  return response;
}
```

- [ ] **Step 2: Write `frontend/app/api/auth/logout/route.ts`**

```typescript
import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, expiredCookieOptions } from '../../../../lib/auth-cookies';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export async function POST() {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;

  if (refreshToken) {
    try {
      await fetch(`${API_URL}/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
        signal: AbortSignal.timeout(5000),
      });
    } catch {
      // Best-effort revocation server-side; cookies are cleared regardless.
    }
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(ACCESS_TOKEN_COOKIE, '', expiredCookieOptions());
  response.cookies.set(REFRESH_TOKEN_COOKIE, '', expiredCookieOptions());
  return response;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/api/auth/refresh/route.ts frontend/app/api/auth/logout/route.ts
git commit -m "feat(frontend): add refresh and logout BFF routes"
```

---

## Task 16: Frontend — authenticated fetch helper with silent refresh

**Files:**
- Create: `frontend/lib/agent-hub-authed-fetch.ts`

- [ ] **Step 1: Write the helper**

```typescript
import { cookies } from 'next/headers';
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, accessTokenCookieOptions, refreshTokenCookieOptions } from './auth-cookies';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export class UnauthenticatedError extends Error {
  constructor() {
    super('no valid session');
  }
}

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

async function fetchWithToken(path: string, init: RequestInit, accessToken: string): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${accessToken}`);
  return fetch(`${API_URL}${path}`, { ...init, headers, signal: AbortSignal.timeout(10000) });
}

async function refreshTokens(refreshToken: string): Promise<TokenResponse | null> {
  try {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    return (await response.json()) as TokenResponse;
  } catch {
    return null;
  }
}

/**
 * Proxies a request to the Agent Hub API with the caller's Bearer token.
 * On a 401 (expired access token), transparently refreshes once via the
 * refresh_token cookie and retries, rotating both cookies in the process.
 * Throws UnauthenticatedError when there is no session or refresh fails —
 * callers should catch this and return a 401 to the browser.
 */
export async function callAgentHub(path: string, init: RequestInit = {}): Promise<Response> {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) throw new UnauthenticatedError();

  const first = await fetchWithToken(path, init, accessToken);
  if (first.status !== 401) return first;

  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) throw new UnauthenticatedError();

  const refreshed = await refreshTokens(refreshToken);
  if (!refreshed) throw new UnauthenticatedError();

  cookieStore.set(ACCESS_TOKEN_COOKIE, refreshed.access_token, accessTokenCookieOptions(refreshed.expires_in));
  cookieStore.set(REFRESH_TOKEN_COOKIE, refreshed.refresh_token, refreshTokenCookieOptions());

  return fetchWithToken(path, init, refreshed.access_token);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/agent-hub-authed-fetch.ts
git commit -m "feat(frontend): add authenticated fetch helper with silent token refresh"
```

---

## Task 17: Frontend — replace hardcoded `X-Actor` with real auth

**Files:**
- Modify: `frontend/app/api/chat/sessions/route.ts`
- Modify: `frontend/app/api/chat/sessions/[id]/upload/route.ts`

- [ ] **Step 1: Rewrite `frontend/app/api/chat/sessions/route.ts`**

```typescript
import { callAgentHub, UnauthenticatedError } from '../../../../lib/agent-hub-authed-fetch';

export async function POST() {
  try {
    const response = await callAgentHub('/api/v1/chat/sessions', { method: 'POST' });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return Response.json({ detail: '未登录' }, { status: 401 });
    }
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}

export async function GET() {
  try {
    const response = await callAgentHub('/api/v1/chat/sessions');
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return Response.json({ detail: '未登录' }, { status: 401 });
    }
    return Response.json([], { status: 200 });
  }
}
```

- [ ] **Step 2: Rewrite `frontend/app/api/chat/sessions/[id]/upload/route.ts`**

```typescript
import { NextRequest } from 'next/server';
import { callAgentHub, UnauthenticatedError } from '../../../../../../lib/agent-hub-authed-fetch';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const formData = await request.formData();

  try {
    const response = await callAgentHub(`/api/v1/chat/sessions/${id}/upload`, {
      method: 'POST',
      body: formData,
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return Response.json({ detail: '未登录' }, { status: 401 });
    }
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
```

- [ ] **Step 3: Manually verify against a running stack**

```bash
docker compose up -d postgres redis api
cd frontend && pnpm dev
```
In a browser: register at `http://localhost:3000/register` (built in Task 20 below — if that task isn't done yet, use the `curl -c` flow from Task 14 to obtain cookies), then confirm `POST /api/chat/sessions` returns `200` with cookies present and `401` without them (test with `curl` omitting `-b`).

- [ ] **Step 4: Commit**

```bash
git add frontend/app/api/chat/sessions/route.ts "frontend/app/api/chat/sessions/[id]/upload/route.ts"
git commit -m "feat(frontend): forward real session identity instead of hardcoded X-Actor"
```

---

## Task 18: Frontend — `/register` page

**Files:**
- Create: `frontend/app/register/page.tsx`

- [ ] **Step 1: Write the page**

```typescript
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: '注册失败' }));
        setError(body.detail ?? '注册失败');
        return;
      }
      router.push('/');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4">
      <h1 className="mb-6 text-xl font-semibold">注册</h1>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          邮箱
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="rounded border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          密码（至少 8 位）
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="rounded border border-gray-300 px-3 py-2"
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-black px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? '注册中…' : '注册'}
        </button>
      </form>
      <p className="mt-4 text-sm text-gray-600">
        已有账号？<Link href="/login" className="underline">去登录</Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/register/page.tsx
git commit -m "feat(frontend): add registration page"
```

---

## Task 19: Frontend — `/login` page

**Files:**
- Create: `frontend/app/login/page.tsx`

- [ ] **Step 1: Write the page**

```typescript
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: '登录失败' }));
        setError(body.detail ?? '登录失败');
        return;
      }
      router.push('/');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4">
      <h1 className="mb-6 text-xl font-semibold">登录</h1>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          邮箱
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="rounded border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          密码
          <input
            type="password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="rounded border border-gray-300 px-3 py-2"
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-black px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? '登录中…' : '登录'}
        </button>
      </form>
      <p className="mt-4 text-sm text-gray-600">
        还没有账号？<Link href="/register" className="underline">去注册</Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Manually verify both pages**

```bash
cd frontend && pnpm dev
```
Visit `http://localhost:3000/register`, submit a new account, confirm redirect to `/`. Visit `http://localhost:3000/login` in a private browser window, log in with the same credentials, confirm redirect to `/`.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/login/page.tsx
git commit -m "feat(frontend): add login page"
```

---

## Task 20: Frontend — protect the console route group

**Files:**
- Create: `frontend/middleware.ts`

- [ ] **Step 1: Write the middleware**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { ACCESS_TOKEN_COOKIE } from './lib/auth-cookies';

export function middleware(request: NextRequest) {
  const hasSession = Boolean(request.cookies.get(ACCESS_TOKEN_COOKIE)?.value);
  if (hasSession) return NextResponse.next();

  const loginUrl = new URL('/login', request.url);
  loginUrl.searchParams.set('return_to', request.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ['/jobs/:path*', '/chat/:path*', '/agents/:path*'],
};
```

(The matcher lists the three route groups under `app/(console)/` — `jobs`, `chat`, `agents` — by their URL paths; Next.js route groups like `(console)` don't appear in the URL, so the matcher targets the paths directly. `/login` and `/register` themselves stay unmatched, avoiding a redirect loop.)

- [ ] **Step 2: Manually verify redirect behavior**

```bash
cd frontend && pnpm dev
```
Visit `http://localhost:3000/jobs` in a private browser window (no cookies) — expect redirect to `/login?return_to=%2Fjobs`. Log in, then visit `/jobs` again — expect the page to load normally.

- [ ] **Step 3: Commit**

```bash
git add frontend/middleware.ts
git commit -m "feat(frontend): redirect unauthenticated users away from the console"
```

---

## Final verification

- [ ] **Run the full Python suite**

Run: `source .venv/bin/activate && python -m unittest discover -s tests -v 2>&1 | tail -60`
Expected: all non-Postgres/non-Redis tests PASS; Postgres/Redis-dependent tests PASS if `TEST_DATABASE_URL` and local Redis are available, otherwise SKIP — zero FAIL.

- [ ] **Run ruff**

Run: `source .venv/bin/activate && ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: no errors.

- [ ] **Run frontend lint and build**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: no errors.

- [ ] **End-to-end smoke test against Docker Compose**

```bash
docker compose up --build -d
```
In a browser: visit `http://localhost:3000/register`, create an account, get redirected to `/`, navigate to `/jobs` or `/chat`, confirm the page loads (no 401 loop). Log out (once a logout control exists in the UI — not built by this plan; use `curl -X POST http://localhost:3000/api/auth/logout -b cookies.txt` to verify server-side revocation instead), then confirm `/jobs` redirects back to `/login`.
