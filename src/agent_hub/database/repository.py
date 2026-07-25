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

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from agent_hub.core.contracts import AuthorizationError
from agent_hub.database.models import (
    Approval,
    AuditLog,
    Base,
    Candidate,
    ChatMessage,
    ChatSession,
    Feedback,
    IdempotencyRecord,
    InterviewKnowledge,
    InterviewMessage,
    InterviewSession,
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
    "interview_knowledge": InterviewKnowledge,
    "interview_session": InterviewSession,
    "interview_message": InterviewMessage,
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
        "title": p.get("title"),
        "actor": p.get("actor", "anonymous"),
        "status": p.get("status", "active"),
    },
    "chat_message": lambda p: {
        "session_id": p.get("session_id", ""),
        "role": p.get("role", "user"),
        "content": p.get("content", ""),
        "tool_calls": p.get("tool_calls"),
        "tool_call_id": p.get("tool_call_id"),
        "attachment": p.get("attachment"),
    },
    "interview_knowledge": lambda p: {
        "category": p.get("category", ""),
        "title": p.get("title", ""),
        "content": p.get("content", ""),
        "source_file": p.get("source_file"),
        "source_format": p.get("source_format", "markdown"),
        "metadata": p.get("metadata", {}),
    },
    "interview_session": lambda p: {
        "actor": p.get("actor", "anonymous"),
        "target_role": p.get("target_role", ""),
        "difficulty": p.get("difficulty", "medium"),
        "status": p.get("status", "in_progress"),
        "summary": p.get("summary"),
    },
    "interview_message": lambda p: {
        "session_id": p.get("session_id", ""),
        "role": p.get("role", "user"),
        "content": p.get("content", ""),
        "evaluation": p.get("evaluation"),
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

    def _has_payload(self, model_cls: type) -> bool:
        """Check if a model class has a JSONB payload column."""
        return hasattr(model_cls, "payload")

    def _chat_session_belongs_to_tenant(
        self, session: Session, session_id: str | None, tenant_id: str
    ) -> bool:
        """``ChatMessage`` has no ``tenant_id`` column of its own — every
        tenant-scoped chat_message operation must instead verify ownership of
        the *session_id* it references against the owning ``ChatSession``.
        """
        if not session_id:
            return False
        owning = session.get(ChatSession, session_id)
        return owning is not None and owning.tenant_id == tenant_id

    def _owned_by(self, row: Any, model_cls: type, tenant_id: str) -> bool:
        """True if *row* may be read/written under tenant scope *tenant_id*.

        Kinds whose model has no ``tenant_id`` column (currently only
        ``chat_message``) aren't gated here — they're handled separately via
        :meth:`_chat_session_belongs_to_tenant`. For every other kind, all of
        ``_put``/``_get``/``_delete`` must reject access to a row that already
        belongs to a *different* tenant: without this, a scoped repo could
        silently overwrite (put), read (get), or remove (delete) another
        tenant's row just by reusing its id — ids are a single global primary
        key per kind, not composite with ``tenant_id``.
        """
        if not hasattr(model_cls, "tenant_id"):
            return True
        return row.tenant_id == tenant_id

    def _row_to_dict(self, row: Any, kind: str) -> dict[str, Any]:
        """Convert a model row to a dict, handling both payload and non-payload models."""
        if hasattr(row, "payload"):
            return dict(row.payload)
        # For models without payload, build dict from typed columns + common fields
        result: dict[str, Any] = {"id": row.id}
        typed_fn = _TYPED_COLUMNS.get(kind)
        if typed_fn:
            # Get the column names from the typed columns spec
            sample = typed_fn({})
            for col in sample:
                result[col] = getattr(row, col, None)
        if hasattr(row, "created_at"):
            result["created_at"] = row.created_at.isoformat() if row.created_at else ""
        if hasattr(row, "updated_at"):
            result["updated_at"] = row.updated_at.isoformat() if row.updated_at else ""
        return result

    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        return self._put(kind, item, tenant_id=None)

    def _put(
        self, kind: str, item: dict[str, Any], *, tenant_id: str | None = None
    ) -> dict[str, Any]:
        model_cls = _KIND_MAP.get(kind)
        if model_cls is None:
            raise ValueError(f"unknown entity kind: {kind}")

        now = _utcnow()
        item.setdefault("created_at", now)
        item["updated_at"] = now
        if tenant_id is not None:
            # Reflect the scope tenant in the JSONB payload too (used by
            # kinds whose row dict is derived from `payload`).
            item["tenant_id"] = tenant_id

        typed = _TYPED_COLUMNS[kind](item)
        has_tenant_column = hasattr(model_cls, "tenant_id")
        if tenant_id is not None and has_tenant_column:
            typed["tenant_id"] = tenant_id
        natural = _NATURAL_KEYS.get(kind)
        has_payload = self._has_payload(model_cls)
        session = self._session()
        owns_session = not self._is_context_session()

        try:
            if kind == "chat_message" and tenant_id is not None:
                # ChatMessage has no tenant_id column: verify the referenced
                # session belongs to this tenant before allowing the write,
                # so a scoped repo can never insert into another tenant's
                # session undetected.
                if not self._chat_session_belongs_to_tenant(
                    session, item.get("session_id"), tenant_id
                ):
                    raise AuthorizationError(
                        f"chat_session {item.get('session_id')!r} does not belong to tenant "
                        f"{tenant_id!r}"
                    )

            if natural:
                # Use savepoint for natural-key conflict resolution.
                nk_values = {col: typed[col] for col in natural}
                if all(nk_values.values()):
                    nk_stmt = select(model_cls).filter_by(**nk_values)
                    if tenant_id is not None and has_tenant_column:
                        nk_stmt = nk_stmt.where(model_cls.tenant_id == tenant_id)
                    existing = session.execute(nk_stmt).scalar_one_or_none()
                    if existing is not None and existing.id != item["id"]:
                        # Return the already-persisted record.
                        return self._row_to_dict(existing, kind)

            row = session.get(model_cls, item["id"])
            if (
                row is not None
                and tenant_id is not None
                and not self._owned_by(row, model_cls, tenant_id)
            ):
                # The id belongs to another tenant's row — refuse to overwrite
                # it instead of silently upserting across the tenant boundary.
                raise AuthorizationError(
                    f"entity {item['id']!r} of kind {kind!r} does not belong to tenant "
                    f"{tenant_id!r}"
                )
            if row is not None:
                if has_payload:
                    row.payload = item
                for col, val in typed.items():
                    setattr(row, col, val)
                if hasattr(row, "updated_at"):
                    row.updated_at = datetime.now(timezone.utc)
            else:
                if has_payload:
                    row = model_cls(id=item["id"], payload=item, **typed)
                else:
                    row = model_cls(id=item["id"], **typed)
                session.add(row)

            if owns_session:
                session.commit()
            else:
                session.flush()

            return self._row_to_dict(row, kind)
        except Exception:
            if owns_session:
                session.rollback()
            raise
        finally:
            if owns_session:
                session.close()

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        return self._get(kind, entity_id, tenant_id=None)

    def _get(
        self, kind: str, entity_id: str, *, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        model_cls = _KIND_MAP.get(kind)
        if model_cls is None:
            raise ValueError(f"unknown entity kind: {kind}")

        session = self._session()
        owns_session = not self._is_context_session()
        try:
            if kind == "chat_message":
                row = session.get(ChatMessage, entity_id)
                if (
                    row is not None
                    and tenant_id is not None
                    and not self._chat_session_belongs_to_tenant(session, row.session_id, tenant_id)
                ):
                    return None
                return self._row_to_dict(row, kind) if row else None
            row = session.get(model_cls, entity_id)
            if (
                row is not None
                and tenant_id is not None
                and not self._owned_by(row, model_cls, tenant_id)
            ):
                return None
            return self._row_to_dict(row, kind) if row else None
        finally:
            if owns_session:
                session.close()

    def list(self, kind: str) -> list[dict[str, Any]]:
        return self._list(kind, tenant_id=None)

    def _list(self, kind: str, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        model_cls = _KIND_MAP.get(kind)
        if model_cls is None:
            raise ValueError(f"unknown entity kind: {kind}")

        session = self._session()
        owns_session = not self._is_context_session()
        try:
            if kind == "chat_message":
                stmt = select(ChatMessage).order_by(ChatMessage.created_at.desc())
                if tenant_id is not None:
                    stmt = stmt.join(ChatSession, ChatMessage.session_id == ChatSession.id).where(
                        ChatSession.tenant_id == tenant_id
                    )
                rows = session.execute(stmt).scalars().all()
                return [self._row_to_dict(row, kind) for row in rows]
            stmt = select(model_cls).order_by(model_cls.created_at.desc())
            if tenant_id is not None and hasattr(model_cls, "tenant_id"):
                stmt = stmt.where(model_cls.tenant_id == tenant_id)
            rows = session.execute(stmt).scalars().all()
            return [self._row_to_dict(row, kind) for row in rows]
        finally:
            if owns_session:
                session.close()

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Return all chat messages for a session, ordered by creation time ascending."""
        return self._list_by_session(session_id, tenant_id=None)

    def _list_by_session(
        self, session_id: str, *, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            if tenant_id is not None and not self._chat_session_belongs_to_tenant(
                session, session_id, tenant_id
            ):
                return []

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
                    "attachment": row.attachment,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
                for row in rows
            ]
        finally:
            if owns_session:
                session.close()

    def delete(self, kind: str, entity_id: str) -> None:
        self._delete(kind, entity_id, tenant_id=None)

    def _delete(self, kind: str, entity_id: str, *, tenant_id: str | None = None) -> None:
        model_cls = _KIND_MAP.get(kind)
        if model_cls is None:
            raise ValueError(f"unknown entity kind: {kind}")

        session = self._session()
        owns_session = not self._is_context_session()
        try:
            if kind == "chat_message":
                row = session.get(ChatMessage, entity_id)
                if (
                    row is not None
                    and tenant_id is not None
                    and not self._chat_session_belongs_to_tenant(session, row.session_id, tenant_id)
                ):
                    row = None
            else:
                row = session.get(model_cls, entity_id)
                if (
                    row is not None
                    and tenant_id is not None
                    and not self._owned_by(row, model_cls, tenant_id)
                ):
                    row = None
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

    def delete_by_session(self, session_id: str) -> None:
        """Delete a chat session and all its messages."""
        self._delete_by_session(session_id, tenant_id=None)

    def _delete_by_session(self, session_id: str, *, tenant_id: str | None = None) -> None:
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            if tenant_id is not None and not self._chat_session_belongs_to_tenant(
                session, session_id, tenant_id
            ):
                return  # not this tenant's session: no-op

            # Delete messages first
            session.execute(
                text("DELETE FROM chat_messages WHERE session_id = :sid"),
                {"sid": session_id},
            )
            # Delete the session
            session.execute(
                text("DELETE FROM chat_sessions WHERE id = :sid"),
                {"sid": session_id},
            )
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

    def search_jobs(
        self,
        q: str | None = None,
        work_mode: str | None = None,
        category: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Search jobs with keyword, work_mode and category filtering using SQL-level filters."""
        return self._search_jobs(q, work_mode, category, offset, limit, tenant_id=None)

    def _search_jobs(
        self,
        q: str | None = None,
        work_mode: str | None = None,
        category: str | None = None,
        offset: int = 0,
        limit: int = 20,
        *,
        tenant_id: str | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            stmt = select(Job).where(Job.status == "active")
            if tenant_id is not None:
                stmt = stmt.where(Job.tenant_id == tenant_id)
            if q:
                pattern = f"%{q}%"
                stmt = stmt.where(
                    Job.title_original.ilike(pattern) | Job.company_name.ilike(pattern)
                )
            if work_mode:
                stmt = stmt.where(Job.payload["work_mode"].astext == work_mode)
            if category:
                stmt = stmt.where(func.jsonb_exists(Job.payload["categories"], category))
            count_stmt = select(text("count(*)")).select_from(stmt.subquery())
            total = session.execute(count_stmt).scalar() or 0
            rows = (
                session.execute(stmt.order_by(Job.created_at.desc()).offset(offset).limit(limit))
                .scalars()
                .all()
            )
            return int(total), [self._row_to_dict(row, "job") for row in rows]
        finally:
            if owns_session:
                session.close()

    def list_job_categories(self, limit: int = 30) -> list[dict[str, Any]]:
        """活跃职位的类别聚合（按数量降序），用于筛选器选项。"""
        return self._list_job_categories(limit, tenant_id=None)

    def _list_job_categories(
        self, limit: int = 30, *, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            query = (
                "SELECT cat AS name, count(*) AS count "
                "FROM jobs, jsonb_array_elements_text("
                "  COALESCE(payload->'categories', '[]'::jsonb)) AS cat "
                "WHERE status = 'active' "
            )
            params: dict[str, Any] = {"limit": limit}
            if tenant_id is not None:
                query += "AND tenant_id = :tenant_id "
                params["tenant_id"] = tenant_id
            query += "GROUP BY cat ORDER BY count DESC, cat LIMIT :limit"
            rows = session.execute(text(query), params).all()
            return [{"name": row.name, "count": int(row.count)} for row in rows]
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
        self._audit(event, kind, entity_id, actor, details, tenant_id=None)

    def _audit(
        self,
        event: str,
        kind: str,
        entity_id: str,
        actor: str,
        details: dict[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
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
                **({"tenant_id": tenant_id} if tenant_id is not None else {}),
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
        return self._audits(limit, tenant_id=None)

    def _audits(self, limit: int = 100, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        capped = min(limit, 1000)
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            stmt = select(AuditLog)
            if tenant_id is not None:
                stmt = stmt.where(AuditLog.tenant_id == tenant_id)
            stmt = stmt.order_by(AuditLog.created_at.desc()).limit(capped)
            rows = session.execute(stmt).scalars().all()
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
        return self._idempotent(action, key, operation, tenant_id=None)

    def _idempotent(
        self,
        action: str,
        key: str,
        operation: Callable[[], dict[str, Any]],
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        session = self._session_factory()
        try:
            session.begin()

            filters: dict[str, Any] = {"action": action, "key": key}
            if tenant_id is not None:
                filters["tenant_id"] = tenant_id

            # Check for existing record.
            existing = session.execute(
                select(IdempotencyRecord).filter_by(**filters)
            ).scalar_one_or_none()
            if existing is not None:
                session.rollback()
                return dict(existing.response)

            # Acquire advisory lock to prevent concurrent execution.
            lock_text = f"{action}:{key}" if tenant_id is None else f"{tenant_id}:{action}:{key}"
            lock_key = int.from_bytes(
                hashlib.sha256(lock_text.encode()).digest()[:8], "big", signed=True
            )
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

            # Re-check after acquiring lock.
            existing = session.execute(
                select(IdempotencyRecord).filter_by(**filters)
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
                    **({"tenant_id": tenant_id} if tenant_id is not None else {}),
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

    # ------------------------------------------------------------------
    # Vector search (pgvector)
    # ------------------------------------------------------------------

    def search_jobs_by_embedding(
        self, vec: list[float], limit: int = 200
    ) -> list[tuple[dict[str, Any], float]]:
        """按余弦相似度检索活跃且已向量化的职位，返回 (job_dict, similarity) 降序列表。"""
        return self._search_jobs_by_embedding(vec, limit, tenant_id=None)

    def _search_jobs_by_embedding(
        self, vec: list[float], limit: int = 200, *, tenant_id: str | None = None
    ) -> list[tuple[dict[str, Any], float]]:
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            distance = Job.embedding.cosine_distance(vec)
            stmt = select(Job, distance.label("distance")).where(
                Job.status == "active", Job.embedding.isnot(None)
            )
            if tenant_id is not None:
                stmt = stmt.where(Job.tenant_id == tenant_id)
            rows = session.execute(stmt.order_by(distance).limit(limit)).all()
            return [(self._row_to_dict(row.Job, "job"), 1.0 - float(row.distance)) for row in rows]
        finally:
            if owns_session:
                session.close()

    def for_tenant(self, tenant_id: str) -> "_TenantPostgresRepository":
        """Return a lightweight view of this repository scoped to *tenant_id*.

        Reuses this repository's engine/session factory — no new engine is
        created per tenant scope. ``tenant_id`` must be a non-empty string:
        internally, ``None`` means "unscoped" to the private ``_method(...,
        tenant_id=None)`` twins, so silently accepting ``None``/``""`` here
        would produce an object that looks tenant-scoped but actually reads
        and writes across every tenant — a fail-open security bug.
        """
        if not tenant_id:
            raise ValueError("tenant_id must be a non-empty string")
        return _TenantPostgresRepository(self, tenant_id)

    def update_job_embeddings(self, embeddings: dict[str, list[float]]) -> int:
        """批量写入职位向量，返回实际更新条数。"""
        session = self._session()
        owns_session = not self._is_context_session()
        updated = 0
        try:
            for job_id, vec in embeddings.items():
                if vec is None:
                    continue
                row = session.get(Job, job_id)
                if row is not None:
                    row.embedding = vec
                    updated += 1
            if owns_session:
                session.commit()
            else:
                session.flush()
            return updated
        except Exception:
            if owns_session:
                session.rollback()
            raise
        finally:
            if owns_session:
                session.close()

    def list_jobs_missing_embedding(self, limit: int = 500) -> list[str]:
        """返回缺失向量的活跃职位 id（新职位优先）。"""
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            rows = (
                session.execute(
                    select(Job.id)
                    .where(Job.status == "active", Job.embedding.is_(None))
                    .order_by(Job.created_at.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return list(rows)
        finally:
            if owns_session:
                session.close()


class _TenantPostgresRepository:
    """Tenant-scoped view over a :class:`PostgresRepository`.

    Holds a reference to the parent repository (reusing its engine/session
    factory — no new engine is opened per tenant scope) plus the tenant_id
    to filter/stamp on every operation.
    """

    def __init__(self, root: PostgresRepository, tenant_id: str):
        self._root = root
        self.tenant_id = tenant_id

    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        return self._root._put(kind, item, tenant_id=self.tenant_id)

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        return self._root._get(kind, entity_id, tenant_id=self.tenant_id)

    def list(self, kind: str) -> list[dict[str, Any]]:
        return self._root._list(kind, tenant_id=self.tenant_id)

    def delete(self, kind: str, entity_id: str) -> None:
        self._root._delete(kind, entity_id, tenant_id=self.tenant_id)

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        return self._root._list_by_session(session_id, tenant_id=self.tenant_id)

    def delete_by_session(self, session_id: str) -> None:
        self._root._delete_by_session(session_id, tenant_id=self.tenant_id)

    def search_jobs(
        self,
        q: str | None = None,
        work_mode: str | None = None,
        category: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[int, list[dict[str, Any]]]:
        return self._root._search_jobs(
            q, work_mode, category, offset, limit, tenant_id=self.tenant_id
        )

    def list_job_categories(self, limit: int = 30) -> list[dict[str, Any]]:
        return self._root._list_job_categories(limit, tenant_id=self.tenant_id)

    def audit(
        self,
        event: str,
        kind: str,
        entity_id: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._root._audit(event, kind, entity_id, actor, details, tenant_id=self.tenant_id)

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._root._audits(limit, tenant_id=self.tenant_id)

    def idempotent(
        self, action: str, key: str, operation: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        return self._root._idempotent(action, key, operation, tenant_id=self.tenant_id)

    def search_jobs_by_embedding(
        self, vec: list[float], limit: int = 200
    ) -> list[tuple[dict[str, Any], float]]:
        return self._root._search_jobs_by_embedding(vec, limit, tenant_id=self.tenant_id)
