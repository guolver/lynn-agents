# MCP Server：把 Agent 平台动作暴露给任意 MCP 客户端

> 模块：`agent_hub/mcp_server.py`。让 Claude Code / Claude Desktop 等支持
> MCP（Model Context Protocol）的客户端，直接调用 Agent Hub 的白名单动作。

## 设计原则：瘦客户端，治理不下放

MCP 层**不复制任何治理逻辑**。它只做两件事：

1. 启动时从 `GET /platform/v1/agents` 动态发现所有 Agent 及其动作定义，生成
   MCP 工具清单（工具名 `{agent_id}__{action}`，描述携带 mode 与 risk_level）；
2. 工具调用转发为 `POST /platform/v1/agents/{id}/actions/{name}`，带上
   `X-Actor`（审计）与自动生成的 `Idempotency-Key`（写动作）。

动作白名单、参数校验、风险分级、人工审批、幂等去重、审计日志——全部仍由
平台层执行。新增 Agent 注册后，MCP 工具清单自动跟进，本模块零改动。

```
Claude Code ──(MCP stdio)──▶ mcp_server.py ──(HTTP + X-Actor)──▶ /platform/v1
                              工具清单动态发现                     治理与审计不变
```

## 安全默认值

| 机制 | 行为 |
|---|---|
| 最小权限 | 默认只暴露 `mode=read` 的动作；`MCP_EXPOSE_WRITE=1` 才暴露写动作 |
| 高风险动作 | 即便暴露，`send_digest` 等仍受平台侧审批流约束（未审批调用会被拒绝） |
| 幂等 | 需要幂等键的动作每次调用自动生成 UUID 键，传输层重试由平台去重 |
| 审计 | 所有调用以 `MCP_ACTOR` 身份进审计日志，与人类操作者可区分 |
| 错误透传 | 平台的拒绝原因（422 详情等）原样返回给模型，便于其自行修正参数 |

## 使用

```bash
pip install -e ".[mcp]"          # 安装 mcp SDK（可选依赖组）
docker compose up api            # 平台 API 需在运行

# 手动启动（stdio）
AGENT_HUB_API_URL=http://localhost:8000 python -m agent_hub.mcp_server
```

Claude Code：仓库根目录已提供 `.mcp.json`，打开本项目即自动发现 `agent-hub`
服务器（默认只读、actor 为 `mcp:claude-code`）。需要写动作时在 `.mcp.json`
的 `env` 中加 `"MCP_EXPOSE_WRITE": "1"`。

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `AGENT_HUB_API_URL` | `http://localhost:8000` | 平台 API 地址 |
| `MCP_ACTOR` | `mcp-client` | 审计日志中的操作者标识 |
| `MCP_EXPOSE_WRITE` | `0` | 设为 `1` 才暴露写动作 |

## 端到端验证（2026-07-19 实测）

- 默认只读：暴露 2 个工具（`list_sources`、`validate_job`）；
- `MCP_EXPOSE_WRITE=1`：7 个工具（补充 `sync_source`、`find_matches`、
  `draft_digest`、`request_approval`、`send_digest`）；
- 通过 MCP 客户端调用 `global-part-time__list_sources` 返回真实数据源列表，
  审计日志记录 actor。

单元测试：`tests/test_mcp_server.py`（16 个用例，覆盖工具名清洗、schema 规整、
读写过滤、HTTP 头与幂等键、错误映射；不依赖 mcp SDK 与真实网络）。

## 面试要点

- **为什么 MCP 层不做校验？** 单一执行点原则：治理逻辑若在 MCP 层复制一份，
  两处就会漂移；MCP 只是平台 API 的又一个客户端，与前端 BFF、Celery 任务
  同级，所有入口共用同一套白名单/审批/审计。
- **动态发现的价值？** 工具清单来自 Agent 注册表而非硬编码——这正是"统一
  Agent 注册"架构的兑现：注册新 Agent，MCP、平台 API、管控台同时获得能力。
- **与 chat_tools.py 的关系？** `chat_tools` 是内置对话 agent 的工具层（走
  进程内 service），MCP 是对外部模型客户端的工具层（走平台 HTTP API + 治理），
  两者暴露同一套业务能力，信任边界不同。
