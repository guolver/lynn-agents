"""PostgreSQL repository implementing the same contract as the SQLite MVP.

Entity payloads are stored in JSONB columns on dedicated domain tables. The
repository maps ``kind`` strings to SQLAlchemy model classes and preserves
backward-compatible dictionary response shapes.
"""

from __future__ import annotations

import hashlib
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from agent_hub.database.models import (
    Approval,
    AuditLog,
    Base,
    Candidate,
    ChatMessage,
    ChatSession,
    Feedback,
    IdempotencyRecord,
    Job,
    JobSource,
    Match,
    Notification,
)

_active_session: ContextVar[Session | None] = ContextVar("_active_session", default=None)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# Entity kind -> (Model class, typed-column extractors from payload)
_KIND_MAP: dict[str, type[Base]] = {
    "source": JobSource,
    "job": Job,
    "candidate": Candidate,
    "match": Match,
    "approval": Approval,
    "notification": Notification,
    "feedback": Feedback,
    "chat_session": ChatSession,
    "chat_message": ChatMessage,
}

# Typed columns to populate from payload for each kind.
_TYPED_COLUMNS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "source": lambda p: {
        "name": p.get("name", ""),
        "source_type": p.get("source_type", "api"),
        "base_url": str(p.get("base_url", "")),
        "review_status": p.get("review_status", "pending"),
        "enabled": bool(p.get("enabled", False)),
    },
    "job": lambda p: {
        "source_id": p.get("source_id", ""),
        "dedup_key": p.get("dedup_key") or p.get("id", ""),
        "title_original": p.get("title_original", ""),
        "company_name": p.get("company_name", ""),
        "status": p.get("status", "active"),
        "review_status": p.get("review_status", "not_required"),
        "risk_level": p.get("risk_level", "low"),
        "risk_score": float(p.get("risk_score", 0.0)),
    },
    "candidate": lambda p: {
        "country": p.get("country", ""),
        "timezone": p.get("timezone", ""),
        "email": p.get("email"),
        "consent_status": p.get("consent_status", "not_requested"),
    },
    "match": lambda p: {
        "candidate_id": p.get("candidate_id", ""),
        "job_id": p.get("job_id", ""),
        "score": float(p.get("score", 0.0)),
        "hard_filter_passed": bool(p.get("hard_filter_passed", True)),
    },
    "approval": lambda p: {
        "action": p.get("action", ""),
        "target_id": p.get("target_id", ""),
        "status": p.get("status", "pending"),
        "requested_by": p.get("requested_by", ""),
    },
    "notification": lambda p: {
        "candidate_id": p.get("candidate_id", ""),
        "status": p.get("status", "pending_approval"),
        "provider_message_id": p.get("provider_message_id"),
    },
    "feedback": lambda p: {
        "match_id": p.get("match_id", ""),
        "candidate_id": p.get("candidate_id", ""),
        "value": p.get("value", ""),
    },
    "chat_session": lambda p: {
        "candidate_id": p.get("candidate_id"),
        "actor": p.get("actor", "anonymous"),
        "status": p.get("status", "active"),
    },
    "chat_message": lambda p: {
        "session_id": p.get("session_id", ""),
        "role": p.get("role", "user"),
        "content": p.get("content", ""),
        "tool_calls": p.get("tool_calls"),
        "tool_call_id": p.get("tool_call_id"),
    },
}

# Natural-key columns used for conflict resolution (upsert on these).
_NATURAL_KEYS: dict[str, list[str]] = {
    "job": ["dedup_key"],
    "match": ["candidate_id", "job_id"],
}


class PostgresRepository:
    """Dictionary-based repository backed by PostgreSQL via SQLAlchemy."""

    def __init__(self, database_url: str):
        self._engine = create_engine(database_url, pool_pre_ping=True)
        self._session_factory = sessionmaker(bind=self._engine)

    def _session(self) -> Session:
        """Return the active context session or create a new one."""
        return _active_session.get() or self._session_factory()

    def _is_context_session(self) -> bool:
        return _active_session.get() is not None

    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        model_cls = _KIND_MAP.get(kind)
        if model_cls is None:
            raise ValueError(f"unknown entity kind: {kind}")

        now = _utcnow()
        item.setdefault("created_at", now)
        item["updated_at"] = now

        typed = _TYPED_COLUMNS[kind](item)
        natural = _NATURAL_KEYS.get(kind)
        session = self._session()
        owns_session = not self._is_context_session()

        try:
            if natural:
                # Use savepoint for natural-key conflict resolution.
                nk_values = {col: typed[col] for col in natural}
                if all(nk_values.values()):
                    existing = session.execute(
                        select(model_cls).filter_by(**nk_values)
                    ).scalar_one_or_none()
                    if existing is not None and existing.id != item["id"]:
                        # Return the already-persisted record.
                        return dict(existing.payload)

            row = session.get(model_cls, item["id"])
            if row is not None:
                row.payload = item
                for col, val in typed.items():
                    setattr(row, col, val)
                if hasattr(row, "updated_at"):
                    row.updated_at = datetime.now(timezone.utc)
            else:
                row = model_cls(id=item["id"], payload=item, **typed)
                session.add(row)

            if owns_session:
                session.commit()
            else:
                session.flush()

            return dict(row.payload)
        except Exception:
            if owns_session:
                session.rollback()
            raise
        finally:
            if owns_session:
                session.close()

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        model_cls = _KIND_MAP.get(kind)
        if model_cls is None:
            raise ValueError(f"unknown entity kind: {kind}")

        session = self._session()
        owns_session = not self._is_context_session()
        try:
            row = session.get(model_cls, entity_id)
            return dict(row.payload) if row else None
        finally:
            if owns_session:
                session.close()

    def list(self, kind: str) -> list[dict[str, Any]]:
        model_cls = _KIND_MAP.get(kind)
        if model_cls is None:
            raise ValueError(f"unknown entity kind: {kind}")

        session = self._session()
        owns_session = not self._is_context_session()
        try:
            rows = (
                session.execute(select(model_cls).order_by(model_cls.created_at.desc()))
                .scalars()
                .all()
            )
            return [dict(row.payload) for row in rows]
        finally:
            if owns_session:
                session.close()

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Return all chat messages for a session, ordered by creation time ascending."""
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            from agent_hub.database.models import ChatMessage

            rows = (
                session.execute(
                    select(ChatMessage)
                    .filter_by(session_id=session_id)
                    .order_by(ChatMessage.created_at.asc())
                )
                .scalars()
                .all()
            )
            return [
                {
                    "id": row.id,
                    "session_id": row.session_id,
                    "role": row.role,
                    "content": row.content,
                    "tool_calls": row.tool_calls,
                    "tool_call_id": row.tool_call_id,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
                for row in rows
            ]
        finally:
            if owns_session:
                session.close()

    def delete(self, kind: str, entity_id: str) -> None:
        model_cls = _KIND_MAP.get(kind)
        if model_cls is None:
            raise ValueError(f"unknown entity kind: {kind}")

        session = self._session()
        owns_session = not self._is_context_session()
        try:
            row = session.get(model_cls, entity_id)
            if row is not None:
                session.delete(row)
                if owns_session:
                    session.commit()
                else:
                    session.flush()
        except Exception:
            if owns_session:
                session.rollback()
            raise
        finally:
            if owns_session:
                session.close()

    def audit(
        self,
        event: str,
        kind: str,
        entity_id: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            row = AuditLog(
                id=str(uuid.uuid4()),
                event=event,
                kind=kind,
                entity_id=entity_id,
                actor=actor,
                details=details,
            )
            session.add(row)
            if owns_session:
                session.commit()
            else:
                session.flush()
        except Exception:
            if owns_session:
                session.rollback()
            raise
        finally:
            if owns_session:
                session.close()

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        capped = min(limit, 1000)
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            rows = (
                session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(capped))
                .scalars()
                .all()
            )
            return [
                {
                    "id": row.id,
                    "event": row.event,
                    "entity_kind": row.kind,
                    "entity_id": row.entity_id,
                    "actor": row.actor,
                    "details": row.details or {},
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
                for row in rows
            ]
        finally:
            if owns_session:
                session.close()

    def idempotent(
        self, action: str, key: str, operation: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        """Execute *operation* exactly once for the given (action, key) pair.

        All repository writes made inside *operation* share the same session
        and transaction, committed atomically with the idempotency record.
        """
        session = self._session_factory()
        try:
            session.begin()

            # Check for existing record.
            existing = session.execute(
                select(IdempotencyRecord).filter_by(action=action, key=key)
            ).scalar_one_or_none()
            if existing is not None:
                session.rollback()
                return dict(existing.response)

            # Acquire advisory lock to prevent concurrent execution.
            lock_key = int.from_bytes(
                hashlib.sha256(f"{action}:{key}".encode()).digest()[:8], "big", signed=True
            )
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

            # Re-check after acquiring lock.
            existing = session.execute(
                select(IdempotencyRecord).filter_by(action=action, key=key)
            ).scalar_one_or_none()
            if existing is not None:
                session.rollback()
                return dict(existing.response)

            # Run the operation within this session's transaction.
            token = _active_session.set(session)
            try:
                result = operation()
            except Exception:
                _active_session.reset(token)
                session.rollback()
                raise

            _active_session.reset(token)

            # Record the result.
            session.add(
                IdempotencyRecord(
                    id=str(uuid.uuid4()),
                    action=action,
                    key=key,
                    response=result,
                )
            )
            session.commit()
            return result
        except Exception:
            if session.is_active:
                session.rollback()
            raise
        finally:
            session.close()
