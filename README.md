# Agent Hub + 全球兼职职位匹配 Agent

这是一个可扩展的 Agent 平台底座，全球兼职职位匹配是首个内置 Agent。平台提供统一的 Agent 注册、发现、动作白名单、调用上下文和幂等约束；业务 Agent 独立维护自己的领域规则、仓储和兼容 API。

兼职 Agent 实现了已授权来源登记、结构化 Feed 同步、跨来源去重、风险审核、候选人授权、确定性匹配、通知审批、限频、反馈、退订和审计。

本项目**不会**登录或抓取第三方招聘平台。`/api/v1/sources/{id}/sync` 只接受来自已批准连接器的结构化职位；真实连接器需要在确认授权条款后单独实现。通知发送目前是可审计的模拟投递，避免开发环境误发邮件。

## 启动

### Docker Compose（推荐）

```bash
docker compose up --build
```

前后端一键启动，支持热重载——修改本地代码后容器内自动生效。

| 服务 | 地址 |
|------|------|
| 前端（Next.js） | http://localhost:3000 |
| 后端（FastAPI） | http://localhost:8000 |

### 本地启动

推荐 Python 3.12（最低兼容 3.10）：

```bash
# 后端
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn agent_hub.app:app --reload

# 前端
cd frontend
pnpm install
pnpm dev
```

打开 `http://localhost:8000/docs` 使用交互式 API。旧启动命令 `part_time_agent.api:app` 和原有 `/api/v1` 路由仍然兼容。

## 项目结构

```text
src/agent_hub/
├── core/                         # 稳定平台契约和注册表
├── api/platform.py               # Agent 发现与统一调用 API
├── app.py                        # 唯一依赖组装入口
└── agents/global_part_time/      # 独立业务 Agent
    ├── agent.py                  # manifest、动作白名单和平台适配
    ├── domain.py                 # 纯确定性规则
    ├── repository.py             # 持久化与审计边界
    ├── service.py                # 业务用例
    └── http_api.py               # 原 REST API 兼容路由
```

完整文档：

- [`docs/system-architecture.md`](docs/system-architecture.md)：系统分层、组件职责、调用链、安全边界和部署演进。
- [`docs/adding-agents.md`](docs/adding-agents.md)：新增 Agent 的契约、示例和检查清单。
- [`docs/global-part-time-agent.md`](docs/global-part-time-agent.md)：兼职职位 Agent 的产品与规则设计。

## 平台接口

```text
GET  /platform/v1/agents
GET  /platform/v1/agents/{agent_id}
POST /platform/v1/agents/{agent_id}/actions/{action_name}
```

统一调用请求：

```json
{
  "payload": {}
}
```

请求必须包含 `X-Actor`。写动作还必须包含唯一的 `Idempotency-Key`；同一动作复用该键会返回首次结果。

## 核心流程

1. `POST /api/v1/sources` 登记来源，再由运营调用 `POST /api/v1/sources/{id}/review` 批准。
2. `POST /api/v1/sources/{id}/sync` 提交结构化 Feed。中风险职位进入审核，高风险职位被拒绝。
3. `POST /api/v1/candidates` 创建候选人，`POST /api/v1/candidates/{id}/consent` 明确订阅。
4. `POST /api/v1/matches/run` 执行硬过滤和可解释加权评分。
5. `POST /api/v1/notifications/preview` 生成草稿，批准后调用 `/api/v1/notifications/send` 模拟发送。
6. `/api/v1/unsubscribe` 立即退订；`/api/v1/audit` 可追踪关键处理记录。

## 验证

```bash
python -m unittest discover -s tests -v
```

默认数据库是 `./data/agent.db`。当前 Agent 注册表和 SQLite 适合本地或单进程 MVP；生产扩展平台还应接入持久化目录、PostgreSQL、隔离 worker、任务队列、RBAC、密钥管理、集中审批和可观测性。
