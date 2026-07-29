# 彻底移除 SQLite

日期：2026-07-19
状态：已确认

## 目标

运行时与代码库中不再存在 SQLite；SQLite 备份中所有数据（含上次未迁的审计日志与幂等记录）迁入 PostgreSQL 后删除备份文件。单元测试改用纯内存 Fake（用户已确认，替代"保留 SQLite 作测试基座"的旧决定）。

## Part 1 · 数据补迁（业务实体 6 类已于 2026-07-19 迁完）

| 数据 | SQLite (`data/agent.db.bak`) | 目标 | 映射 |
|---|---|---|---|
| audit_logs | 3685 条 | `audit_logs` | 自增 id→新 UUID；`entity_kind`→`kind`；details 文本 JSON→jsonb（非 dict/解析失败包 `{"raw":...}`）；created_at 保留原始时间戳；超长字段按列宽截断 |
| idempotency | 2 条 | `idempotency_records` | 新 UUID id；`ON CONFLICT (action,key) DO NOTHING`（Postgres 现有记录优先） |

一次性脚本在临时目录执行、不提交入库。迁移后核对计数（Postgres audit_logs ≈ 迁移前存量 + 3685），随后删除 `data/agent.db.bak`。

## Part 2 · 代码清除

- `agent_hub/agents/global_part_time/repository.py`：删除 `SQLiteRepository`、`Repository = SQLiteRepository` 别名、`sqlite3`/`SCHEMA` 等实现残留；仅保留 `RepositoryProtocol`；更新模块 docstring
- 新增 `tests/inmemory_repo.py`：`InMemoryRepository`（dict 存储）实现完整协议；语义对齐 SQLite 版：存取经 JSON 往返快照（隔离外部突变）、`list` 按 created_at 倒序、`list_by_session` 升序、`audits` 按插入序倒序且 `min(limit,1000)`、`idempotent` 先查后执行；构造函数接受并忽略可选 path 参数（兼容 `Repository(":memory:")` 调用点，测试只需改 import）
- `tests/test_repository_contract.py`：契约测试的内存侧改为针对 `InMemoryRepository`（Postgres 侧不变）
- 波及测试改 import：`test_service`、`test_api`、`test_app_skill_graph_lifecycle`、`test_remotive_fetcher`、`test_remoteok_fetcher`、`test_celery_tasks`（SQLiteRepository→InMemoryRepository）
- `agent_hub/database/config.py`：工厂仅接受 `DATABASE_URL`（参数或环境变量），缺失时 `raise RuntimeError`，删除 `DATABASE_PATH`/SQLite 分支；`tests/test_database_config.py` 相应重写
- `.env`：新增 `DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub`（宿主机裸跑仍可用），删除注释的 `DATABASE_PATH` 行；`.env.example` 同步
- 删除 `scripts/migrate_sqlite_to_pg.py`（历史使命完成）
- `CLAUDE.md` 技术栈表数据库行：`PostgreSQL + pgvector`，删除 SQLite 字样

## 验收

1. `python -m unittest discover -s tests`（不设 TEST_DATABASE_URL、不依赖 Docker）：除既有无关失败（fetcher 国家码、database_models chat 表、Neo4j 连接）外全绿
2. `ruff check src/ tests/` 通过
3. `grep -ri sqlite src/ tests/ scripts/` 除历史文档外零命中
4. compose 栈（api/worker）不受影响，`/api/v1/jobs` 正常
5. Postgres audit_logs 含迁移前全部历史；`data/agent.db.bak` 已删除
