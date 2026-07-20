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
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    encode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from .domain import normalize_email, validate_email, validate_password
from .rate_limiter import LoginRateLimiterProtocol
from .repository import DuplicateEmailError, IdentityRepository

ACCESS_TOKEN_TTL_SECONDS = int(ACCESS_TOKEN_TTL.total_seconds())

# Precomputed once at import time so the timing-safety fix in login() doesn't
# pay an extra argon2 hashing cost on every failed login for an unknown email
# — verify_password() is called against this instead of skipping the call.
_DUMMY_PASSWORD_HASH = hash_password("timing-safety-dummy-password-never-used-for-login")


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
        email = normalize_email(email)
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
        tokens = self._issue_tokens(user)
        self._repo.audit(
            event="user.registered",
            tenant_id=user["tenant_id"],
            actor=user["id"],
            details={"email": user["email"]},
        )
        return tokens

    def login(self, email: str, password: str) -> dict[str, Any]:
        email = normalize_email(email)
        rate_key = f"{self._tenant_id}:{email}"
        if self._rate_limiter.is_locked(rate_key):
            raise LoginRateLimitedError(email)

        user = self._repo.get_user_by_email(self._tenant_id, email)
        password_hash = user["password_hash"] if user is not None else _DUMMY_PASSWORD_HASH
        password_ok = verify_password(password, password_hash)
        if user is None or not password_ok:
            self._rate_limiter.record_failure(rate_key)
            self._repo.audit(
                event="user.login_failed",
                tenant_id=self._tenant_id,
                actor=email,
                details=None,
            )
            raise InvalidCredentialsError()

        self._rate_limiter.reset(rate_key)
        self._repo.audit(
            event="user.login_succeeded",
            tenant_id=user["tenant_id"],
            actor=user["id"],
            details=None,
        )
        return self._issue_tokens(user)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        record = self._repo.claim_refresh_token(hash_refresh_token(refresh_token))
        if record is None:
            raise InvalidRefreshTokenError()

        user = self._repo.get_user_by_id(record["user_id"])
        if user is None:
            raise InvalidRefreshTokenError()
        tokens = self._issue_tokens(user)
        self._repo.audit(
            event="user.token_refreshed",
            tenant_id=user["tenant_id"],
            actor=user["id"],
            details=None,
        )
        return tokens

    def logout(self, refresh_token: str) -> None:
        record = self._repo.get_refresh_token(hash_refresh_token(refresh_token))
        if record is not None and record["revoked_at"] is None:
            self._repo.revoke_refresh_token(record["id"])
            self._repo.audit(
                event="user.logged_out",
                tenant_id=record["tenant_id"],
                actor=record["user_id"],
                details=None,
            )

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
