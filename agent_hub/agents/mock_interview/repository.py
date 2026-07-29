"""面试 Agent 的持久化边界。

封装知识库和面试会话的存储操作。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_hub.database.models import (
    InterviewKnowledge,
    InterviewMessage,
    InterviewSession,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


@runtime_checkable
class InterviewRepositoryProtocol(Protocol):
    """面试 Agent 存储契约。"""

    tenant_id: str

    # 知识库操作
    def list_knowledge(
        self, category: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    def get_knowledge(self, knowledge_id: str) -> dict[str, Any] | None: ...

    def put_knowledge(self, item: dict[str, Any]) -> dict[str, Any]: ...

    def delete_knowledge(self, knowledge_id: str) -> None: ...

    def search_knowledge_by_embedding(
        self, vec: list[float], limit: int = 5
    ) -> list[tuple[dict[str, Any], float]]: ...

    def update_knowledge_embedding(self, knowledge_id: str, embedding: list[float]) -> None: ...

    # 会话操作
    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]: ...

    def get_session(self, session_id: str) -> dict[str, Any] | None: ...

    def put_session(self, item: dict[str, Any]) -> dict[str, Any]: ...

    def delete_session(self, session_id: str) -> None: ...

    # 消息操作
    def list_messages_by_session(self, session_id: str) -> list[dict[str, Any]]: ...

    def put_message(self, item: dict[str, Any]) -> dict[str, Any]: ...


class InterviewRepository:
    """SQLAlchemy 实现的面试存储库。"""

    def __init__(self, session_factory, tenant_id: str):
        self._session_factory = session_factory
        self.tenant_id = tenant_id

    def _session(self) -> Session:
        return self._session_factory()

    # -------------------------------------------------------------------------
    # 知识库操作
    # -------------------------------------------------------------------------

    def list_knowledge(self, category: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        session = self._session()
        try:
            stmt = (
                select(InterviewKnowledge)
                .where(InterviewKnowledge.tenant_id == self.tenant_id)
                .order_by(InterviewKnowledge.updated_at.desc())
                .limit(limit)
            )
            if category:
                stmt = stmt.where(InterviewKnowledge.category == category)
            rows = session.execute(stmt).scalars().all()
            return [self._knowledge_to_dict(row) for row in rows]
        finally:
            session.close()

    def get_knowledge(self, knowledge_id: str) -> dict[str, Any] | None:
        session = self._session()
        try:
            row = session.get(InterviewKnowledge, knowledge_id)
            if row is None or row.tenant_id != self.tenant_id:
                return None
            return self._knowledge_to_dict(row)
        finally:
            session.close()

    def put_knowledge(self, item: dict[str, Any]) -> dict[str, Any]:
        session = self._session()
        try:
            now = datetime.now(timezone.utc)
            item.setdefault("id", _new_id())
            item.setdefault("created_at", _utcnow())
            item["updated_at"] = _utcnow()

            row = session.get(InterviewKnowledge, item["id"])
            if row is not None and row.tenant_id != self.tenant_id:
                raise ValueError("Knowledge belongs to another tenant")

            if row is not None:
                row.category = item.get("category", row.category)
                row.title = item.get("title", row.title)
                row.content = item.get("content", row.content)
                row.source_file = item.get("source_file", row.source_file)
                row.source_format = item.get("source_format", row.source_format)
                row.metadata = item.get("metadata", row.metadata)
                row.updated_at = now
            else:
                row = InterviewKnowledge(
                    id=item["id"],
                    tenant_id=self.tenant_id,
                    category=item.get("category", ""),
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    source_file=item.get("source_file"),
                    source_format=item.get("source_format", "markdown"),
                    metadata=item.get("metadata", {}),
                )
                session.add(row)

            session.commit()
            return self._knowledge_to_dict(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_knowledge(self, knowledge_id: str) -> None:
        session = self._session()
        try:
            row = session.get(InterviewKnowledge, knowledge_id)
            if row is not None and row.tenant_id == self.tenant_id:
                session.delete(row)
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def search_knowledge_by_embedding(
        self, vec: list[float], limit: int = 5
    ) -> list[tuple[dict[str, Any], float]]:
        session = self._session()
        try:
            distance = InterviewKnowledge.embedding.cosine_distance(vec)
            stmt = (
                select(InterviewKnowledge, distance.label("distance"))
                .where(
                    InterviewKnowledge.tenant_id == self.tenant_id,
                    InterviewKnowledge.embedding.isnot(None),
                )
                .order_by(distance)
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            return [
                (self._knowledge_to_dict(row.InterviewKnowledge), 1.0 - float(row.distance))
                for row in rows
            ]
        finally:
            session.close()

    def update_knowledge_embedding(self, knowledge_id: str, embedding: list[float]) -> None:
        session = self._session()
        try:
            row = session.get(InterviewKnowledge, knowledge_id)
            if row is not None and row.tenant_id == self.tenant_id:
                row.embedding = embedding
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # 会话操作
    # -------------------------------------------------------------------------

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        session = self._session()
        try:
            stmt = (
                select(InterviewSession)
                .where(InterviewSession.tenant_id == self.tenant_id)
                .order_by(InterviewSession.updated_at.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()
            return [self._session_to_dict(row) for row in rows]
        finally:
            session.close()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self._session()
        try:
            row = session.get(InterviewSession, session_id)
            if row is None or row.tenant_id != self.tenant_id:
                return None
            return self._session_to_dict(row)
        finally:
            session.close()

    def put_session(self, item: dict[str, Any]) -> dict[str, Any]:
        session = self._session()
        try:
            now = datetime.now(timezone.utc)
            item.setdefault("id", _new_id())
            item.setdefault("created_at", _utcnow())
            item["updated_at"] = _utcnow()

            row = session.get(InterviewSession, item["id"])
            if row is not None and row.tenant_id != self.tenant_id:
                raise ValueError("Session belongs to another tenant")

            if row is not None:
                row.target_role = item.get("target_role", row.target_role)
                row.difficulty = item.get("difficulty", row.difficulty)
                row.status = item.get("status", row.status)
                row.summary = item.get("summary", row.summary)
                row.updated_at = now
            else:
                row = InterviewSession(
                    id=item["id"],
                    tenant_id=self.tenant_id,
                    actor=item.get("actor", "anonymous"),
                    target_role=item.get("target_role", ""),
                    difficulty=item.get("difficulty", "medium"),
                    status=item.get("status", "in_progress"),
                    summary=item.get("summary"),
                )
                session.add(row)

            session.commit()
            return self._session_to_dict(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_session(self, session_id: str) -> None:
        session = self._session()
        try:
            # 先删除所有消息
            stmt = select(InterviewMessage).where(InterviewMessage.session_id == session_id)
            messages = session.execute(stmt).scalars().all()
            for msg in messages:
                session.delete(msg)

            # 再删除会话
            row = session.get(InterviewSession, session_id)
            if row is not None and row.tenant_id == self.tenant_id:
                session.delete(row)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # 消息操作
    # -------------------------------------------------------------------------

    def list_messages_by_session(self, session_id: str) -> list[dict[str, Any]]:
        session = self._session()
        try:
            # 先验证会话属于当前租户
            interview_session = session.get(InterviewSession, session_id)
            if interview_session is None or interview_session.tenant_id != self.tenant_id:
                return []

            stmt = (
                select(InterviewMessage)
                .where(InterviewMessage.session_id == session_id)
                .order_by(InterviewMessage.created_at.asc())
            )
            rows = session.execute(stmt).scalars().all()
            return [self._message_to_dict(row) for row in rows]
        finally:
            session.close()

    def put_message(self, item: dict[str, Any]) -> dict[str, Any]:
        session = self._session()
        try:
            item.setdefault("id", _new_id())
            item.setdefault("created_at", _utcnow())

            # 验证会话属于当前租户
            interview_session = session.get(InterviewSession, item.get("session_id"))
            if interview_session is None or interview_session.tenant_id != self.tenant_id:
                raise ValueError("Session does not exist or belongs to another tenant")

            row = InterviewMessage(
                id=item["id"],
                session_id=item.get("session_id", ""),
                role=item.get("role", "user"),
                content=item.get("content", ""),
                evaluation=item.get("evaluation"),
            )
            session.add(row)

            # 更新会话的 updated_at
            interview_session.updated_at = datetime.now(timezone.utc)

            session.commit()
            return self._message_to_dict(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # 转换方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _knowledge_to_dict(row: InterviewKnowledge) -> dict[str, Any]:
        return {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "category": row.category,
            "title": row.title,
            "content": row.content,
            "source_file": row.source_file,
            "source_format": row.source_format,
            "metadata": row.metadata or {},
            "has_embedding": row.embedding is not None,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }

    @staticmethod
    def _session_to_dict(row: InterviewSession) -> dict[str, Any]:
        return {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "actor": row.actor,
            "target_role": row.target_role,
            "difficulty": row.difficulty,
            "status": row.status,
            "summary": row.summary,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }

    @staticmethod
    def _message_to_dict(row: InterviewMessage) -> dict[str, Any]:
        return {
            "id": row.id,
            "session_id": row.session_id,
            "role": row.role,
            "content": row.content,
            "evaluation": row.evaluation,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
