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
from .domain import normalize_email, validate_email, validate_password
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
        return self._issue_tokens(user)

    def login(self, email: str, password: str) -> dict[str, Any]:
        email = normalize_email(email)
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
