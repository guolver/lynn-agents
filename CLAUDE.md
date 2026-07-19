# Agent Hub

可扩展的 Agent 平台底座，提供统一的 Agent 注册、发现、调用和审计能力。

## 架构概览

```
Browser / API Client
        │
        ▼
  FastAPI (Python)          ← 后端：Agent 平台 + 业务 Agent
  localhost:8000
        │
        ▼
  PostgreSQL + pgvector     ← 默认数据库

  Next.js (frontend/)       ← 前端：可视化管控台
  localhost:3000
```

## 项目结构

```
src/agent_hub/
├── core/                         # 平台契约和注册表
├── api/platform.py               # Agent 发现与统一调用 API
├── app.py                        # 依赖组装入口
└── agents/global_part_time/      # 全球兼职职位匹配 Agent
    ├── agent.py                  # manifest、动作白名单
    ├── domain.py                 # 纯确定性规则
    ├── repository.py             # 持久化与审计边界
    ├── service.py                # 业务用例
    └── http_api.py               # REST API 兼容路由

frontend/                         # Next.js + React + Cloudflare Workers
├── app/(console)/                # 管控台页面
├── app/api/                      # BFF 层
├── components/                   # 共享 UI 组件
├── lib/                          # API 客户端与演示数据
└── db/                           # Drizzle ORM schema

tests/                            # Python 单元测试
docs/                             # 架构文档
```

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.10+, FastAPI, Pydantic, Uvicorn |
| 前端 | Next.js 16, React 19, Tailwind CSS 4, Drizzle ORM |
| 数据库 | PostgreSQL + pgvector |
| 部署 | Cloudflare Workers（前端） |

## 开发命令

```bash
# 后端
source .venv/bin/activate
uvicorn agent_hub.app:app --reload        # 启动后端
python -m unittest discover -s tests -v   # 运行测试
ruff check src/ tests/                    # 代码检查
ruff format src/ tests/                   # 代码格式化

# 前端
cd frontend
pnpm dev                                  # 启动前端
pnpm lint                                 # ESLint 检查
pnpm build                                # 构建

# 全栈
docker compose up --build                 # 全栈启动（api+worker+beat+PG+Redis+Neo4j+frontend）
```

## 代码规范

- **Python**: ruff lint + format，行宽 100，目标版本 py310
- **TypeScript/JS**: ESLint (flat config v9) + Prettier
- **Prettier**: 分号，单引号，2 空格缩进，行尾逗号 es5，行宽 120
- **Pre-commit**: Husky + lint-staged（Python → ruff, 前端 → eslint）

## 平台 API

```
GET  /platform/v1/agents                           # Agent 列表
GET  /platform/v1/agents/{agent_id}                # Agent 详情
POST /platform/v1/agents/{agent_id}/actions/{name} # 调用动作
```

必须包含 `X-Actor` 头。写动作需要 `Idempotency-Key`。

## 文档索引

- [系统架构](docs/system-architecture.md)
- [新增 Agent 指南](docs/adding-agents.md)
- [兼职 Agent 设计](docs/global-part-time-agent.md)
- [MCP Server](docs/mcp-server.md)
- [LLM 可观测性](docs/observability.md)
- [开发环境搭建](docs/dev-guide.md)
