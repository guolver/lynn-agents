# ADR 0004: 不自动迁移现有 SQLite 数据

- 状态：已接受
- 日期：2026-07-17

## 背景

本地可能已有 `data/agent.db`，其中的载荷来自不同开发版本，缺少 PostgreSQL 新约束所需的完整字段。应用启动或 Alembic upgrade 时自动读取并写入这些数据，会造成不可见的数据修改、部分迁移、重复记录和难以恢复的失败。

## 决策

PostgreSQL 配置和 schema 迁移绝不删除、修改或自动导入现有 SQLite 文件。启用 `DATABASE_URL` 后，应用使用对应 PostgreSQL 数据库；SQLite 文件原样保留，并仍可通过 `DATABASE_PATH` 作为 fallback 显式选择。

如需迁移历史数据，必须使用未来单独提供的、人工触发的一次性工具。该流程应先备份 SQLite，执行只读导出、字段转换、约束预检和数量/校验和核对，再由操作者确认写入；失败时回滚 PostgreSQL 导入，不改动源文件。

## 后果

- 切换 PostgreSQL 时不会意外破坏现有本地数据，但新数据库默认是空的。
- 操作者必须明确选择继续使用 SQLite、从空 PostgreSQL 开始，或单独执行受控迁移。
- Alembic 只管理 PostgreSQL schema，不承担跨数据库数据搬运。
- 项目文档和发布检查必须持续说明该决定，避免把配置切换误解为自动迁移。
