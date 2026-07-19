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

from sqlalchemy import select, update
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

    def claim_refresh_token(self, token_hash: str) -> dict[str, Any] | None:
        """Atomically revoke an unexpired, unrevoked refresh token and return it.

        Uses a single conditional UPDATE (not a separate SELECT then UPDATE) so
        two concurrent callers racing on the same token can't both observe it
        as valid and both mint a new token pair — only one UPDATE can match
        the ``revoked_at IS NULL`` condition and actually revoke the row.
        """
        session = self._session()
        try:
            row = session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > _utcnow(),
                )
                .values(revoked_at=_utcnow())
                .returning(RefreshToken)
            ).scalar_one_or_none()
            session.commit()
            return _refresh_token_to_dict(row) if row else None
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
