# 彻底移除 SQLite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SQLite 从运行时、代码、数据文件三个层面彻底消失；历史数据全量入 PostgreSQL；单测改用内存 Fake。

**Architecture:** 先补迁数据（audit/idempotency，表级 SQL，一次性脚本不入库）；再新增 `tests/inmemory_repo.py` 并让契约测试约束它；最后删除 `SQLiteRepository` 与 SQLite 配置分支、切换全部测试 import、清理配置与文档。

**Tech Stack:** Python 3.10 / unittest / SQLAlchemy / ruff。测试从仓库根目录跑：`.venv/bin/python -m unittest ...`。

**Spec:** `docs/superpowers/specs/2026-07-19-remove-sqlite-design.md`

**注意：** 工作区可能有其他会话的未提交改动。提交只 add 本任务列出的文件，禁止 `git add -A`。

---

### Task 1: 数据补迁 + 删除备份（由主会话内联执行，脚本不入库）

**Files:** 无入库文件；脚本写到 scratchpad。

- [ ] **Step 1: 记录迁移前 Postgres 计数**

```bash
docker compose exec -T postgres psql -U agent_hub -d agent_hub -tc "SELECT count(*) FROM audit_logs;"
```

- [ ] **Step 2: 在 scratchpad 写脚本并执行**

```python
"""audit_logs + idempotency 一次性补迁（SQLite → Postgres）。"""
import json
import sqlite3
import uuid

from sqlalchemy import create_engine, text

SQLITE = "data/agent.db.bak"
PG = "postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub"

src = sqlite3.connect(SQLITE)
src.row_factory = sqlite3.Row
engine = create_engine(PG)

rows = src.execute("SELECT * FROM audit_logs ORDER BY id").fetchall()
with engine.begin() as conn:
    for r in rows:
        try:
            details = json.loads(r["details"])
            if not isinstance(details, dict):
                details = {"raw": details}
        except Exception:
            details = {"raw": r["details"]}
        conn.execute(
            text(
                "INSERT INTO audit_logs (id, event, kind, entity_id, actor, details, created_at) "
                "VALUES (:id, :event, :kind, :eid, :actor, CAST(:details AS jsonb), CAST(:ts AS timestamptz))"
            ),
            {
                "id": str(uuid.uuid4()),
                "event": r["event"][:100],
                "kind": r["entity_kind"][:50],
                "eid": r["entity_id"][:36],
                "actor": r["actor"][:255],
                "details": json.dumps(details, ensure_ascii=False),
                "ts": r["created_at"],
            },
        )
print("audit_logs migrated:", len(rows))

idem = src.execute("SELECT * FROM idempotency").fetchall()
with engine.begin() as conn:
    for r in idem:
        conn.execute(
            text(
                "INSERT INTO idempotency_records (id, action, key, response, created_at) "
                "VALUES (:id, :action, :key, CAST(:response AS jsonb), CAST(:ts AS timestamptz)) "
                "ON CONFLICT (action, key) DO NOTHING"
            ),
            {
                "id": str(uuid.uuid4()),
                "action": r["action"][:100],
                "key": r["key"][:255],
                "response": r["response"],
                "ts": r["created_at"],
            },
        )
print("idempotency migrated:", len(idem))
```

每表单事务：中途失败则整表回滚，修复后重跑，不会产生半迁移状态。**成功后不得重复执行**（audit 行会重复）。

- [ ] **Step 3: 验证计数**

Postgres `audit_logs` 计数应 = Step 1 计数 + 3685（±期间线上新增）。抽查最早一条时间戳与 SQLite 首条一致。

- [ ] **Step 4: 删除备份**

```bash
rm data/agent.db.bak
```

---

### Task 2: InMemoryRepository + 契约约束（TDD）

**Files:**
- Create: `tests/inmemory_repo.py`
- Modify: `tests/test_repository_contract.py`

- [ ] **Step 1: 创建 `tests/inmemory_repo.py`**

```python
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
        return len(filtered), filtered[offset : offset + limit]

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
```

- [ ] **Step 2: 契约测试接入**

读 `tests/test_repository_contract.py`，把针对 SQLite `Repository` 的被测目标改为 `InMemoryRepository`（`from tests.inmemory_repo import InMemoryRepository`；若测试以 `Repository(":memory:")` 实例化，同名替换即可，构造参数兼容）。Postgres 侧（TEST_DATABASE_URL 门控）不动。

- [ ] **Step 3: 运行契约测试**

Run: `.venv/bin/python -m unittest tests.test_repository_contract -v`
Expected: 内存实现全部 PASS（Postgres 侧照旧 skip/pass）。若有语义偏差，修 `inmemory_repo.py`（不修契约测试）。

- [ ] **Step 4: 确认协议匹配**

```bash
.venv/bin/python -c "
from agent_hub.agents.global_part_time.repository import RepositoryProtocol
from tests.inmemory_repo import InMemoryRepository
assert isinstance(InMemoryRepository(), RepositoryProtocol)
print('protocol OK')"
```

- [ ] **Step 5: Commit**

```bash
git add tests/inmemory_repo.py tests/test_repository_contract.py
git commit -m "test: in-memory repository fake constrained by contract tests

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fhZLk4jQRXeDcuCkx5H58" -- tests/inmemory_repo.py tests/test_repository_contract.py
```

---

### Task 3: 删除 SQLite 代码 + 全面切换

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/repository.py`（只留协议）
- Modify: `src/agent_hub/database/config.py`
- Modify: `tests/test_service.py`、`tests/test_api.py`、`tests/test_app_skill_graph_lifecycle.py`、`tests/test_remotive_fetcher.py`、`tests/test_remoteok_fetcher.py`、`tests/test_celery_tasks.py`、`tests/test_database_config.py`
- Modify: `.env.example`、`CLAUDE.md`
- Delete: `scripts/migrate_sqlite_to_pg.py`
- 另（不入库）：`.env` 加 `DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub`，删注释的 `DATABASE_PATH` 行

- [ ] **Step 1: repository.py 只留协议**

删除 `SCHEMA` 常量、`SQLiteRepository` 类、`Repository = SQLiteRepository` 别名及 `json/os/sqlite3/contextmanager/Path/Iterator/utcnow` 等仅被它们使用的 import。文件保留：模块 docstring（改写为下文）、`RepositoryProtocol`。

```python
"""兼职 Agent 的持久化边界。

Repository 是领域服务唯一接触存储的位置。生产实现为
``agent_hub.database.repository.PostgresRepository``；单元测试使用
``tests/inmemory_repo.InMemoryRepository``。两者同受
``tests/test_repository_contract.py`` 契约约束。
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable
```

（`RepositoryProtocol` 本体逐字保留。）

- [ ] **Step 2: config.py 仅认 DATABASE_URL**

整文件替换为：

```python
"""Repository factory: PostgreSQL only.

``DATABASE_URL``（参数或环境变量）必须提供，形如
``postgresql+psycopg://user:pass@host:5432/dbname``。
"""

from __future__ import annotations

import os

from agent_hub.agents.global_part_time.repository import RepositoryProtocol


def create_repository(database_url: str | None = None) -> RepositoryProtocol:
    """Return a configured PostgreSQL repository instance."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required (e.g. postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub)"
        )
    from agent_hub.database.repository import PostgresRepository

    return PostgresRepository(url)
```

注意：先 `grep -rn "create_repository(" src/ tests/` 确认没有调用方还传 `sqlite_path=` 关键字参数；有则一并修正。

- [ ] **Step 3: 测试 import 切换**

- `test_service.py`、`test_api.py`、`test_app_skill_graph_lifecycle.py`、`test_remotive_fetcher.py`、`test_remoteok_fetcher.py`：
  `from agent_hub.agents.global_part_time.repository import Repository`
  → `from tests.inmemory_repo import InMemoryRepository as Repository`
  （调用点 `Repository(":memory:")` 与子类 `class FakeVectorRepo(Repository)` 不需要改。）
- `test_celery_tasks.py`：`SQLiteRepository` 的 import 与 3 处使用改为 `InMemoryRepository`（`from tests.inmemory_repo import InMemoryRepository`）。
- `test_database_config.py`：整文件重写——删除 SQLite 分支用例，保留/新增：①无参数且无 `DATABASE_URL` 环境变量时 `create_repository()` 抛 `RuntimeError`；②显式传 `database_url` 返回 `PostgresRepository`（mock `PostgresRepository.__init__` 返回 None 以免真连库，沿用文件中现有的 mock 手法）；③环境变量 `DATABASE_URL` 生效。

- [ ] **Step 4: 配置与文档**

- `.env`（不入库）：删除 `# DATABASE_PATH=./data/agent.db` 行；顶部加 `DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub`
- `.env.example`：同样把 DATABASE_PATH 行替换为上述 DATABASE_URL 示例行
- `CLAUDE.md` 技术栈表数据库行改为：`| 数据库 | PostgreSQL + pgvector |`
- `git rm scripts/migrate_sqlite_to_pg.py`

- [ ] **Step 5: 验证**

```bash
.venv/bin/python -m unittest discover -s tests 2>&1 | tail -5
.venv/bin/ruff check src/ tests/
grep -rin "sqlite" src/ tests/ scripts/ 2>/dev/null
```

Expected: 测试除既有无关失败（remoteok/remotive 国家码、database_models chat 表、Neo4j 连接）外全绿；ruff 通过；grep 零命中（scripts/ 目录此时可能已空或不存在，报错可忽略）。另跑 `curl -s http://127.0.0.1:8000/api/v1/jobs?limit=1 | head -c 120` 确认线上栈不受影响。

- [ ] **Step 6: Commit**

```bash
git add src/agent_hub/agents/global_part_time/repository.py src/agent_hub/database/config.py \
  tests/test_service.py tests/test_api.py tests/test_app_skill_graph_lifecycle.py \
  tests/test_remotive_fetcher.py tests/test_remoteok_fetcher.py tests/test_celery_tasks.py \
  tests/test_database_config.py .env.example CLAUDE.md
git rm --cached scripts/migrate_sqlite_to_pg.py 2>/dev/null; git add scripts/ 2>/dev/null
git commit -m "refactor(db)!: remove SQLite entirely, PostgreSQL is the only runtime store

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fhZLk4jQRXeDcuCkx5H58"
```

（commit 不用 `-- 路径` 限定时必须先 `git status` 核对暂存区只有上述文件。）

---

### Task 4: 最终验证 + 审查

- [ ] **Step 1:** 全量测试 + ruff + `grep -ri sqlite src/ tests/`（零命中）+ compose 栈健康检查（`docker compose ps`、`/api/v1/jobs`、前端 `/api/jobs`）
- [ ] **Step 2:** 派最终审查子代理对照 spec 逐项核验（含数据侧：Postgres audit_logs 计数、`data/agent.db.bak` 不存在）
- [ ] **Step 3:** 按 verification-before-completion 汇报，所有结论附证据
