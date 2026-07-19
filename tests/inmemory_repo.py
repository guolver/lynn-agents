"""纯内存 Repository 实现，单元测试专用。

与 PostgresRepository 同受 tests/test_repository_contract.py 契约约束。
语义对齐旧 SQLite 版：存取经 JSON 序列化往返（快照隔离外部突变）；
list 按 created_at 倒序；list_by_session 升序；audits 插入序倒序。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from agent_hub.agents.global_part_time.domain import utcnow


def _snapshot(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


class InMemoryRepository:
    """dict 存储的 RepositoryProtocol 实现；构造参数兼容旧 Repository(":memory:") 调用点。"""

    def __init__(self, path: str | None = None):
        self._entities: dict[str, dict[str, dict[str, Any]]] = {}
        self._audits: list[dict[str, Any]] = []
        self._idempotency: dict[tuple[str, str], dict[str, Any]] = {}

    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        item.setdefault("created_at", now)
        item["updated_at"] = now
        self._entities.setdefault(kind, {})[item["id"]] = _snapshot(item)
        return item

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        found = self._entities.get(kind, {}).get(entity_id)
        return _snapshot(found) if found is not None else None

    def list(self, kind: str) -> list[dict[str, Any]]:
        items = list(self._entities.get(kind, {}).values())
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return [_snapshot(x) for x in items]

    def delete(self, kind: str, entity_id: str) -> None:
        self._entities.get(kind, {}).pop(entity_id, None)

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
            for m in self._entities.get("chat_message", {}).values()
            if m.get("session_id") == session_id
        ]
        messages.sort(key=lambda x: x.get("created_at") or "")
        return [_snapshot(m) for m in messages]

    def delete_by_session(self, session_id: str) -> None:
        messages = self._entities.get("chat_message", {})
        for mid in [k for k, m in messages.items() if m.get("session_id") == session_id]:
            messages.pop(mid, None)
        self._entities.get("chat_session", {}).pop(session_id, None)

    def audit(
        self,
        event: str,
        kind: str,
        entity_id: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audits.append(
            {
                "id": len(self._audits) + 1,
                "event": event,
                "entity_kind": kind,
                "entity_id": entity_id,
                "actor": actor,
                "details": _snapshot(details or {}),
                "created_at": utcnow(),
            }
        )

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        capped = self._audits[-min(limit, 1000) :]
        return [_snapshot(a) for a in reversed(capped)]

    def idempotent(
        self, action: str, key: str, operation: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        existing = self._idempotency.get((action, key))
        if existing is not None:
            return _snapshot(existing)
        result = operation()
        self._idempotency[(action, key)] = _snapshot(result)
        return result
