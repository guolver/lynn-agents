# ADR 0001: PostgreSQL 作为生产主数据库

- 状态：已接受
- 日期：2026-07-17

## 背景

当前 `Repository` 使用 SQLite 和字典载荷，适合单进程 MVP 与自动化测试，但无法可靠支撑多实例并发、事务型幂等、结构化约束和后续向量检索。现有服务和两套 HTTP 入口已经依赖稳定的字典仓储契约，迁移不能改变响应形状或确定性业务规则。

## 决策

生产环境以 PostgreSQL 16 为主数据库，并通过 `DATABASE_URL` 显式启用。PostgreSQL 使用领域专用表、外键、唯一约束和索引；完整字典载荷保存在 JSONB 中，以维持现有 Repository 与 API 形状。业务写入、审计和幂等记录必须能够共享事务。

SQLite 继续作为轻量本地开发和单元测试 fallback，通过 `DATABASE_PATH` 选择。没有 `DATABASE_URL` 时仍可使用 SQLite；该 fallback 不代表支持多实例生产部署。

## 后果

- 应用层保留 `put`、`get`、`list`、`delete`、`audit`、`audits` 和 `idempotent` 字典契约。
- PostgreSQL 可提供并发控制、原子幂等和数据库级数据完整性。
- 需要 SQLAlchemy 模型、Alembic 迁移、PostgreSQL 集成测试和运维备份方案。
- SQLite 与 PostgreSQL 必须复用同一仓储契约测试；SQLite 的并发能力限制继续存在。
