"""兼职 Agent 的持久化边界和 SQLite MVP 实现。

Repository 是领域服务唯一接触存储的位置。未来切换 PostgreSQL 时，只需提供
相同接口的实现，不必修改平台注册表、HTTP 路由或匹配规则。
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from .domain import utcnow


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS entities (
  kind TEXT NOT NULL,
  id TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event TEXT NOT NULL,
  entity_kind TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  actor TEXT NOT NULL,
  details TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
  action TEXT NOT NULL,
  key TEXT NOT NULL,
  response TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (action, key)
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_kind, entity_id);
"""


class Repository:
    """以 JSON 实体保存 MVP 数据，并单独维护审计和幂等记录。"""
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("DATABASE_PATH", "./data/agent.db")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_connection = self._connect() if self.path == ":memory:" else None
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._memory_connection or self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self._memory_connection is None:
                conn.close()

    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        item.setdefault("created_at", now)
        item["updated_at"] = now
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO entities(kind,id,payload,created_at,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at""",
                (kind, item["id"], json.dumps(item, ensure_ascii=False), item["created_at"], now),
            )
        return item

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM entities WHERE kind=? AND id=?", (kind, entity_id)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM entities WHERE kind=? ORDER BY created_at DESC", (kind,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, kind: str, entity_id: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM entities WHERE kind=? AND id=?", (kind, entity_id))

    def audit(
        self, event: str, kind: str, entity_id: str, actor: str, details: dict[str, Any] | None = None
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs(event,entity_kind,entity_id,actor,details,created_at) VALUES(?,?,?,?,?,?)",
                (event, kind, entity_id, actor, json.dumps(details or {}, ensure_ascii=False), utcnow()),
            )

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (min(limit, 1000),)
            ).fetchall()
        return [{**dict(row), "details": json.loads(row["details"])} for row in rows]

    def idempotent(self, action: str, key: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """返回同一动作/键的首次结果，避免普通重试制造重复业务记录。

        生产实现应在 PostgreSQL 事务中锁定幂等键，从而覆盖并发请求；SQLite
        版本主要服务于本地开发和单进程 MVP。
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT response FROM idempotency WHERE action=? AND key=?", (action, key)
            ).fetchone()
        if row:
            return json.loads(row[0])
        result = operation()
        with self.connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO idempotency(action,key,response,created_at) VALUES(?,?,?,?)",
                    (action, key, json.dumps(result, ensure_ascii=False), utcnow()),
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT response FROM idempotency WHERE action=? AND key=?", (action, key)
                ).fetchone()
                return json.loads(row[0])
        return result
