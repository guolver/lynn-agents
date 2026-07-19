"""兼职 Agent 的持久化边界。

Repository 是领域服务唯一接触存储的位置。生产实现为
``agent_hub.database.repository.PostgresRepository``；单元测试使用
``tests/inmemory_repo.InMemoryRepository``。两者同受
``tests/test_repository_contract.py`` 契约约束。
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class RepositoryProtocol(Protocol):
    """Storage contract shared by SQLite and PostgreSQL implementations."""

    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]: ...

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None: ...

    def list(self, kind: str) -> list[dict[str, Any]]: ...

    def delete(self, kind: str, entity_id: str) -> None: ...

    def audit(
        self,
        event: str,
        kind: str,
        entity_id: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None: ...

    def audits(self, limit: int = 100) -> list[dict[str, Any]]: ...

    def idempotent(
        self, action: str, key: str, operation: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]: ...

    def search_jobs(
        self,
        q: str | None = None,
        work_mode: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[int, list[dict[str, Any]]]: ...

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]: ...

    def delete_by_session(self, session_id: str) -> None: ...
