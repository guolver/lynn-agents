"""纯内存 Repository 实现，单元测试专用。

与 PostgresRepository 同受 tests/test_repository_contract.py 契约约束。
语义对齐旧 SQLite 版：存取经 JSON 序列化往返（快照隔离外部突变）；
list 按 created_at 倒序；list_by_session 升序；audits 插入序倒序。

存储按 tenant_id 隔离（tenant -> kind -> id -> item）。``InMemoryRepository``
本身是 root repository：``for_tenant(tenant_id)`` 返回一个按租户隔离的视图
(``_TenantInMemoryRepository``)；未加租户前缀的直接方法（兼容旧调用点，如
``InMemoryRepository()``、``InMemoryRepository(":memory:")``）委托到固定的
``"default"`` 租户，保持既有行为不变。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from agent_hub.agents.global_part_time.domain import utcnow
from agent_hub.core.contracts import AuthorizationError

_DEFAULT_TENANT = "default"


def _snapshot(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


class InMemoryRepository:
    """dict 存储的 RootRepositoryProtocol 实现；构造参数兼容旧 Repository(":memory:") 调用点。"""

    def __init__(self, path: str | None = None):
        # tenant_id -> kind -> id -> item
        self._entities: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        # tenant_id -> ordered list of audit records
        self._audits: dict[str, list[dict[str, Any]]] = {}
        # tenant_id -> (action, key) -> result
        self._idempotency: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        self._default = self.for_tenant(_DEFAULT_TENANT)

    def for_tenant(self, tenant_id: str) -> "_TenantInMemoryRepository":
        """Return a view scoped to *tenant_id*.

        ``tenant_id`` must be a non-empty string. Mirrors the same guard on
        ``PostgresRepository.for_tenant`` so both backends fail the same way
        (raise) instead of one failing open and the other failing closed.
        """
        if not tenant_id:
            raise ValueError("tenant_id must be a non-empty string")
        return _TenantInMemoryRepository(self, tenant_id)

    # ------------------------------------------------------------------
    # Legacy direct methods: delegate to the "default" tenant scope so
    # existing call sites (InMemoryRepository() constructed directly across
    # the test suite) keep working unchanged.
    # ------------------------------------------------------------------

    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        return self._default.put(kind, item)

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        return self._default.get(kind, entity_id)

    def list(self, kind: str) -> list[dict[str, Any]]:
        return self._default.list(kind)

    def delete(self, kind: str, entity_id: str) -> None:
        self._default.delete(kind, entity_id)

    def search_jobs(
        self,
        q: str | None = None,
        work_mode: str | None = None,
        category: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[int, list[dict[str, Any]]]:
        return self._default.search_jobs(
            q=q, work_mode=work_mode, category=category, offset=offset, limit=limit
        )

    def list_job_categories(self, limit: int = 30) -> list[dict[str, Any]]:
        return self._default.list_job_categories(limit)

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        return self._default.list_by_session(session_id)

    def delete_by_session(self, session_id: str) -> None:
        self._default.delete_by_session(session_id)

    def audit(
        self,
        event: str,
        kind: str,
        entity_id: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._default.audit(event, kind, entity_id, actor, details)

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._default.audits(limit)

    def idempotent(
        self, action: str, key: str, operation: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        return self._default.idempotent(action, key, operation)


class _TenantInMemoryRepository:
    """View over :class:`InMemoryRepository` storage scoped to a single tenant."""

    def __init__(self, root: InMemoryRepository, tenant_id: str):
        self._root = root
        self.tenant_id = tenant_id

    def _chat_session_belongs_to_tenant(self, session_id: str | None) -> bool:
        """Mirrors ``PostgresRepository._chat_session_belongs_to_tenant``: chat
        messages carry no tenant of their own, so ownership is checked via the
        session they reference.
        """
        if not session_id:
            return False
        session = self._root._entities.get(self.tenant_id, {}).get("chat_session", {})
        return session_id in session

    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        if kind == "chat_message" and not self._chat_session_belongs_to_tenant(
            item.get("session_id")
        ):
            raise AuthorizationError(
                f"chat_session {item.get('session_id')!r} does not belong to tenant "
                f"{self.tenant_id!r}"
            )
        now = utcnow()
        item.setdefault("created_at", now)
        item["updated_at"] = now
        item["tenant_id"] = self.tenant_id
        self._root._entities.setdefault(self.tenant_id, {}).setdefault(kind, {})[item["id"]] = (
            _snapshot(item)
        )
        return item

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        found = self._root._entities.get(self.tenant_id, {}).get(kind, {}).get(entity_id)
        return _snapshot(found) if found is not None else None

    def list(self, kind: str) -> list[dict[str, Any]]:
        items = list(self._root._entities.get(self.tenant_id, {}).get(kind, {}).values())
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return [_snapshot(x) for x in items]

    def delete(self, kind: str, entity_id: str) -> None:
        self._root._entities.get(self.tenant_id, {}).get(kind, {}).pop(entity_id, None)

    def search_jobs(
        self,
        q: str | None = None,
        work_mode: str | None = None,
        category: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[int, list[dict[str, Any]]]:
        filtered = self.list("job")
        if q:
            q_lower = q.lower()
            filtered = [
                j
                for j in filtered
                if q_lower in (j.get("title_original") or "").lower()
                or q_lower in (j.get("company_name") or "").lower()
                or q_lower in (j.get("title_zh") or "").lower()
            ]
        if work_mode:
            filtered = [j for j in filtered if j.get("work_mode") == work_mode]
        if category:
            filtered = [j for j in filtered if category in (j.get("categories") or [])]
        return len(filtered), filtered[offset : offset + limit]

    def list_job_categories(self, limit: int = 30) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for job in self.list("job"):
            if job.get("status") != "active":
                continue
            for cat in job.get("categories") or []:
                counts[cat] = counts.get(cat, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"name": name, "count": count} for name, count in ranked[:limit]]

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        messages = [
            m
            for m in self._root._entities.get(self.tenant_id, {}).get("chat_message", {}).values()
            if m.get("session_id") == session_id
        ]
        messages.sort(key=lambda x: x.get("created_at") or "")
        return [_snapshot(m) for m in messages]

    def delete_by_session(self, session_id: str) -> None:
        messages = self._root._entities.get(self.tenant_id, {}).get("chat_message", {})
        for mid in [k for k, m in messages.items() if m.get("session_id") == session_id]:
            messages.pop(mid, None)
        self._root._entities.get(self.tenant_id, {}).get("chat_session", {}).pop(session_id, None)

    def audit(
        self,
        event: str,
        kind: str,
        entity_id: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        bucket = self._root._audits.setdefault(self.tenant_id, [])
        bucket.append(
            {
                "id": len(bucket) + 1,
                "event": event,
                "entity_kind": kind,
                "entity_id": entity_id,
                "actor": actor,
                "details": _snapshot(details or {}),
                "created_at": utcnow(),
            }
        )

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        bucket = self._root._audits.get(self.tenant_id, [])
        capped = bucket[-min(limit, 1000) :]
        return [_snapshot(a) for a in reversed(capped)]

    def idempotent(
        self, action: str, key: str, operation: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        store = self._root._idempotency.setdefault(self.tenant_id, {})
        existing = store.get((action, key))
        if existing is not None:
            return _snapshot(existing)
        result = operation()
        store[(action, key)] = _snapshot(result)
        return result
