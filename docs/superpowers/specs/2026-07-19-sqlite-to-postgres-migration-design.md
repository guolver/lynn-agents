# SQLite → PostgreSQL 全量数据迁移

日期：2026-07-19
状态：已确认

## 背景

应用已整体切到 docker compose（api/worker 连 Postgres），但历史数据（3634 岗位、9 源、3 候选人、123 匹配、聊天记录）在本地 SQLite `data/agent.db` 里，导致岗位大厅只剩 2 个 e2e 测试岗位。

## 方案

一次性迁移脚本 `scripts/migrate_sqlite_to_pg.py`，利用现有 Repository 抽象（两实现受 `tests/test_repository_contract.py` 契约保障）：

- 源：`SQLiteRepository`（默认 `data/agent.db`，`SQLITE_PATH` 可覆盖）
- 目标：`PostgresRepository`（默认 `postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub`，`DATABASE_URL` 可覆盖）
- 迁移顺序（外键安全）：`source → job → candidate → match → chat_session → chat_message`
- 幂等：`put` 按 id upsert，可重复执行
- 容错：单条失败记录 id + 异常并继续，结束打印每类「迁移数/失败数」及失败明细
- audit_logs 不迁移（append-only 历史，保留在备份文件中）

## 迁移后操作

1. 清理 e2e 假数据：删除 Postgres 中 `canonical_url` 含 `e2e.example.com` 的岗位及名为 e2e 的测试源
2. 验证：Postgres 岗位数 ≥ 3634；`/api/v1/jobs` 返回真实岗位；聊天会话可见；匹配记录保留
3. SQLite 退役：`data/agent.db` → `data/agent.db.bak`（保留备份）；`.env` 中 `DATABASE_PATH` 注释掉
4. 代码中的 SQLite 实现保留（单元测试基座），不删除

## 已知限制

- 迁移岗位的 `embedding` 列为 null；SiliconFlow 余额解决后运行 `backfill_embeddings` 任务补齐
- 个别老记录字段缺失时会进失败清单，人工处理，不中断整体
