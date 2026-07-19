# Agent Hub 系统架构

> 文档状态：当前实现 + 演进设计  
> 更新日期：2026-07-19  
> 目标读者：平台研发、Agent 开发者、架构师、运维与安全人员

## 1. 架构目标

Agent Hub 的目标是让多个业务 Agent 通过统一方式被发现、治理和调用，同时保持每个 Agent 的领域逻辑与数据边界独立。

当前首个内置 Agent 是“全球兼职职位匹配 Agent”。平台设计不依赖招聘领域，后续可以接入内容处理、数据分析、运营自动化等其他 Agent。

核心原则：

- 平台只负责通用能力，不理解具体业务数据。
- Agent 只暴露声明过的动作，不允许任意方法或脚本执行。
- 领域规则与 HTTP、数据库和模型 SDK 解耦，确保结果可测试、可复现。
- 写动作必须幂等；高风险动作需要人工审批。
- Agent 之间不直接访问彼此的仓储，跨 Agent 流程通过公开动作编排。
- 第三方插件默认不加载，生产环境启用时应经过 allowlist 和安全评估。

## 2. 系统上下文

```text
                    ┌─────────────────────┐
                    │ Web / CLI / 管理后台 │
                    └──────────┬──────────┘
                               │ HTTP
                    ┌──────────▼──────────┐
                    │      Agent Hub       │
                    │ 发现、治理、统一调用  │
                    └──────┬────────┬─────┘
                           │        │
                  标准 Agent 协议   │ 兼容业务 API
                           │        │
             ┌─────────────▼──┐  ┌──▼────────────────┐
             │ 其他业务 Agent │  │ 全球兼职匹配 Agent │
             └───────┬────────┘  └────────┬──────────┘
                     │                    │
             自有服务/数据源       PostgreSQL + pgvector / Neo4j / Redis+Celery
```

外部调用者有两个入口：

- `/platform/v1`：统一 Agent 目录与动作调用接口，新集成优先使用。
- `/api/v1`：兼职 Agent 原有业务 REST API，作为兼容入口继续保留。

## 3. 组件架构

```text
┌──────────────────────────── FastAPI Application ───────────────────────────┐
│                                                                            │
│  Platform API ──▶ AgentRegistry ──▶ GlobalPartTimeAgent                    │
│  /platform/v1     │                  manifest / actions / invoke            │
│                   │ Plugin Discovery                   │                    │
│                   │ ExecutionContext                   │                    │
│                                                         ▼                    │
│  Compatibility API ───────────────────────────▶ Application Service        │
│  /api/v1                                          │              │          │
│                                                   ▼              ▼          │
│                                             Domain Rules     Repository     │
│                                             风险/过滤/评分    实体/审计/幂等  │
│                                                                  │         │
└──────────────────────────────────────────────────────────────────┼─────────┘
                                                                   ▼
                                                     PostgreSQL + pgvector
                                              （另有 Neo4j 技能图谱、Redis/Celery
                                                异步流水线，见部署架构一节）
```

统一平台入口先经过注册表和 Agent 适配器；兼容 REST API 直接调用同一个 Application Service。两条路径最终共享领域规则和仓储，因此业务结果一致，但平台级动作发现只适用于 `/platform/v1`。

## 4. 代码分层与职责

| 层 | 当前实现 | 职责 | 不应承担 |
| --- | --- | --- | --- |
| 应用组装 | `agent_hub/app.py` | 创建依赖、注册 Agent、组合路由和异常映射 | 业务规则 |
| 平台 API | `agent_hub/api/platform.py` | Agent 发现、描述和统一动作调用 | 直接访问 Agent 数据库 |
| 平台契约 | `agent_hub/core/contracts.py` | Manifest、Action、ExecutionContext、Agent Protocol | 具体框架或业务模型 |
| 注册表 | `agent_hub/core/registry.py` | 注册、查找、动作白名单和通用前置校验 | Agent 内部业务校验 |
| 插件发现 | `agent_hub/core/discovery.py` | 可选加载 Python entry point 插件 | 默认执行未知第三方代码 |
| Agent 适配器 | `agents/*/agent.py` | 声明能力，把平台调用映射到业务用例 | 绕过 service 直接拼装复杂业务流程 |
| 应用服务 | `agents/*/service.py` | 编排领域规则、仓储、审批与业务状态 | HTTP 参数和响应格式 |
| 领域规则 | `agents/*/domain.py` | 纯确定性校验、过滤、评分 | 数据库、网络和模型调用 |
| 仓储 | `agents/*/repository.py` | 持久化、审计和幂等边界 | 业务决策 |
| 兼容 API | `agents/*/http_api.py` | 保留 Agent 专属 REST 接口 | 平台注册与插件发现 |
| 数据访问 | `agent_hub/database/` | SQLAlchemy 模型、PostgreSQL 仓储实现、pgvector 检索 | 业务规则 |
| 技能图谱 | `agent_hub/skill_graph/` | Neo4j 别名归一与类别扩展，失败熔断降级 | 阻塞主流程 |
| 后台流水线 | `agent_hub/worker/` | Celery 任务（采集/向量化/匹配/通知）、错误分类与指数退避、workflow 落库追踪 | 绕过 service 直接写业务表 |
| 对话编排 | `agents/*/chat_service.py` + `chat_tools.py` | 会话持久化、LLM function calling 多轮工具调用、SSE 流式（Redis StreamHub 解耦生成与连接） | 让 LLM 绕过工具白名单触达业务能力 |

## 5. Agent 契约

每个 Agent 必须提供三项能力：

```python
class Agent(Protocol):
    @property
    def manifest(self) -> AgentManifest: ...

    def actions(self) -> tuple[ActionDefinition, ...]: ...

    def invoke(
        self,
        action: str,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]: ...
```

### 5.1 Manifest

Manifest 用于目录展示和版本治理，包含：

- `agent_id`：稳定且唯一的机器标识。
- `name`：用户可读名称。
- `version`：Agent 契约或实现版本。
- `description`：能力和边界说明。
- `tags`：用于分类和搜索。
- `owner`：责任团队或插件所有者。

### 5.2 ActionDefinition

Agent 只能执行 `actions()` 中声明的动作。每个动作描述：

- 动作名称和用途。
- `read` 或 `write` 模式。
- 风险级别。
- 是否强制要求 `Idempotency-Key`。
- 可发现的输入 Schema。

### 5.3 ExecutionContext

业务 payload 与调用上下文分开传递。当前上下文包含：

- `actor`：调用者身份；当前来自 `X-Actor` 请求头。
- `request_id`：单次调用追踪 ID，可由调用方传入或由平台生成。
- `idempotency_key`：写动作的幂等键。
- `tenant_id`：为未来多租户预留。
- `metadata`：不属于业务输入的附加上下文。

当前 `X-Actor` 只是身份传递接口，不是完整认证机制。生产环境必须由网关或认证中间件验证 token，并根据 RBAC 生成可信身份与角色。

## 6. 关键运行流程

### 6.1 Agent 发现

```text
Client
  │ GET /platform/v1/agents
  ▼
Platform API
  ▼
AgentRegistry.manifests()
  ▼
返回 Agent ID、版本、描述与标签
```

获取单个 Agent 详情时，注册表还会返回动作白名单、风险等级、幂等要求和输入 Schema。

### 6.2 统一动作调用

```text
Client
  │ POST /platform/v1/agents/{id}/actions/{action}
  │ X-Actor / X-Request-Id / Idempotency-Key
  ▼
Platform API 创建 ExecutionContext
  ▼
AgentRegistry
  ├─ 校验 Agent 是否存在
  ├─ 校验动作是否已声明
  ├─ 校验写动作幂等键
  └─ 校验 Schema 中的必填字段
  ▼
Agent.invoke()
  ├─ 执行 Agent 自己的类型与业务校验
  ├─ 写动作查询/保存幂等结果
  └─ 调用 Application Service
  ▼
Domain Rules + Repository
  ▼
统一响应：agent_id / action / request_id / result
```

### 6.3 兼职职位匹配

```text
批准来源同步
  ▼
URL 规范化 + 风险规则
  ├─ 高风险：拒绝并审计
  ├─ 中风险：暂停并等待审批
  └─ 低风险：进入职位池
  ▼
跨来源去重
  ▼
异步批量向量化（Celery，批 64）
  ▼
候选人授权检查
  ▼
pgvector 余弦召回 top-200（向量层不可用时降级全量扫描）
  ▼
地区/时区/语言/薪资/工时硬过滤
  ▼
确定性加权评分 + 推荐理由（含检索证据落库）
  ▼
通知草稿
  ▼
人工审批 + 发送前再次校验
  ▼
模拟发送 + 审计记录
```

模型未来可以辅助字段抽取、翻译和理由生成，但不能覆盖来源授权、退订、硬过滤、风险规则和发送限制。

## 7. 数据架构与所有权

默认数据库为 PostgreSQL（Alembic 管理迁移，API 启动时自动执行），24 张结构化表按职责分组：

| 分组 | 主要表 | 说明 |
| --- | --- | --- |
| 职位采集 | `job_sources` / `source_sync_runs` / `raw_jobs` / `jobs` / `job_versions` | 来源审批、同步运行、原始与清洗后职位、版本快照 |
| 候选人 | `candidates` / `candidate_experiences` / `candidate_skills` | 画像、经历、技能 |
| 技能 | `skills` / `skill_aliases` / `skill_relations` / `job_skills` | PG 侧技能表（图关系镜像在 Neo4j） |
| 匹配 | `matches` / `match_evidence` / `match_score_items` | 结果、检索证据（召回方式/相似度/排名）、8 维分项得分 |
| 流水线 | `workflow_runs` / `workflow_steps` | Celery 任务状态、重试次数、错误类别 |
| 审批与通知 | `approvals` / `notifications` / `feedback` | 人工审批、通知与用户反馈 |
| 治理 | `audit_logs` / `idempotency_records` | 审计与幂等（`(action, idempotency_key)` 唯一约束 + advisory lock，与业务写同事务提交） |
| 对话 | `chat_sessions` / `chat_messages` | LLM 会话与消息（含 tool_calls/tool 配对） |

向量存储：`jobs.embedding vector(1024)` + HNSW 余弦索引（pgvector），召回查询可直接携带业务条件过滤。

数据所有权规则：

- 每个 Agent 管理自己的业务数据和迁移。
- 平台目录只保存 Agent 元数据，不应保存完整业务 payload。
- Agent 之间通过动作返回必要数据，不共享数据库表。
- 审计日志不记录访问令牌、完整简历或不必要的敏感信息。

## 8. 插件和扩展机制

### 8.1 内置或本地 Agent

应用启动时通过 `create_app(extra_agents=[...])` 注入。适合与平台同仓开发、共享发布周期的 Agent。

### 8.2 外部 Python 插件

独立包可以声明 `agent_hub.agents` entry point。平台只有在 `load_plugins=True` 时才加载，并可通过 `allowed_plugins` 限制名称。

```text
已安装插件包
  ▼
importlib.metadata.entry_points
  ▼
allowlist 检查
  ▼
加载 Agent 实例或工厂
  ▼
Protocol + ID + 动作唯一性检查
  ▼
注册到 AgentRegistry
```

Python 插件与平台运行在同一进程，拥有同等代码权限，因此只能加载可信包。后续接入第三方生态时，应将插件部署到隔离 worker，通过队列或 RPC 调用。

### 8.3 远程 Agent（目标架构）

未来可以实现一个 `RemoteAgentProxy`，继续满足现有 Agent Protocol，但把 `invoke()` 转发到独立服务。平台 API 和上层编排器无需感知本地或远程差异。

## 9. 安全边界

当前已经实现：

- Agent ID 格式和重复注册检查。
- 动作白名单，未声明动作不可执行。
- 写动作强制幂等键。
- 必填字段和 Agent 业务输入校验。
- 第三方插件默认关闭。
- 兼职 Agent 的来源审批、风险规则、候选人授权、人工审批和发送前复检。
- 删除、通知和关键业务操作审计。

生产环境仍需补充：

- OAuth/OIDC 身份认证和租户级 RBAC。
- API 网关限流、请求大小限制和 WAF。
- Agent/插件签名、制品扫描和供应链治理。
- 密钥管理系统与短期凭证。
- Agent worker 的网络、文件系统和资源隔离。
- 审计日志集中存储、防篡改和保留策略。
- 敏感数据加密、数据区域和跨境策略。

## 10. 部署架构演进

### 10.1 当前：Docker Compose 全栈（7 服务）

```text
docker compose up
├── api        FastAPI（启动自动跑 Alembic 迁移）
├── frontend   Next.js 管控台
├── worker     Celery worker（采集/向量化/匹配/通知）
├── beat       Celery beat（定时调度）
├── postgres   PostgreSQL + pgvector（业务库+向量+审计+幂等）
├── redis      Celery broker + 对话流 StreamHub
└── neo4j      技能知识图谱
```

全部服务带 healthcheck 和依赖编排，一条命令起全栈。长任务已经异步化：任务状态、重试与错误类别落 `workflow_runs`/`workflow_steps`，失败可通过 API 重派。限制：API 单副本、注册表在内存中、不受信任插件仍与 API 同进程。

### 10.2 下一阶段：多副本与隔离 Worker

```text
API Gateway / Identity Provider
              │
       Agent Hub API Pods（多副本）
              │
       PostgreSQL + Redis
              │
       Task Queue / Workflow
          ┌───┴─────────┐
          │             │
   Trusted Workers   Isolated Agent Workers
          │             │
        External APIs / Model Providers
```

该阶段应加入任务取消、超时、心跳、集中审批和 OpenTelemetry，并把不受信任插件挪到隔离 worker。

### 10.3 平台化阶段：多租户与远程 Agent

增加持久化 Agent Catalog、版本发布/回滚、租户安装关系、配额计费、远程 Agent Gateway 和策略引擎。注册表由内存实现替换为数据库目录与健康检查缓存，但保留当前 Agent 契约。

## 11. 可观测性与失败处理

每次统一调用都应使用 `request_id` 贯穿平台、Agent、任务和外部 API。目标观测字段包括：

- `request_id`、`tenant_id`、`agent_id`、`agent_version`、`action`。
- 调用者、风险级别、幂等命中状态和审批 ID。
- 执行状态、耗时、重试次数和错误类别。
- 模型名称、提示词版本和结构化输出校验结果（使用模型时）。

建议的失败边界：

| 失败 | 当前行为 | 目标行为 |
| --- | --- | --- |
| Agent 或动作不存在 | 返回 404 | 保持 |
| 缺少幂等键或输入无效 | 返回 422 | 保持并增加错误码 |
| 业务策略冲突 | 返回 409 | 保持 |
| 外部来源超时 | 错误分类 + 指数退避重试，上限后转 manual_review | 增加熔断和告警 |
| Agent 长任务 | Celery 异步执行，状态落 workflow_runs，可查询/重派 | 增加取消与超时 |
| Worker 崩溃 | 独立容器，重启后任务可重试（幂等键保证安全） | 心跳检测与自动接管 |

## 12. 目录结构

```text
src/
├── agent_hub/
│   ├── app.py                    # composition root
│   ├── api/
│   │   ├── platform.py           # 统一 Agent 发现与调用
│   │   └── skill_graph.py
│   ├── core/
│   │   ├── contracts.py
│   │   ├── discovery.py
│   │   └── registry.py
│   ├── database/                 # SQLAlchemy 模型 + PG 仓储 + pgvector 检索
│   ├── skill_graph/              # Neo4j 技能图谱（seed/expand/降级）
│   ├── worker/                   # Celery 任务、错误分类、workflow 追踪
│   └── agents/
│       └── global_part_time/
│           ├── agent.py
│           ├── domain.py
│           ├── service.py
│           ├── repository.py
│           ├── http_api.py
│           ├── chat_service.py   # LLM 对话编排（function calling + SSE）
│           ├── chat_tools.py     # LLM 工具白名单
│           ├── stream_hub.py     # Redis 流式事件中转
│           ├── resume_parser.py / embedding.py / translator.py
│           └── fetchers/         # remoteok / remotive / jobicy / himalayas
```

新增 Agent 的实现步骤和示例见 [接入新的 Agent](adding-agents.md)。兼职招聘业务的产品与规则设计见 [全球兼职职位匹配 Agent](global-part-time-agent.md)。

## 13. 当前架构决策

| 决策 | 原因 | 未来触发调整的条件 |
| --- | --- | --- |
| 使用 Python Protocol 定义 Agent | 核心不依赖具体框架或 SDK | 需要跨语言时增加协议规范和远程代理 |
| 进程内注册表 | MVP 简单、调用开销低 | 多副本、动态安装或远程 Agent |
| 动作白名单 | 限制攻击面并支持能力发现 | 保留，不应移除 |
| Agent 自管幂等 | 不同 Agent 的事务边界不同 | 增加平台执行记录，但业务幂等仍归 Agent |
| 兼容 `/api/v1` | 避免重构破坏现有客户端 | 客户端全部迁移后再版本化下线 |
| PostgreSQL 结构化表 + pgvector 同库 | 向量与业务状态天然一致、幂等有唯一约束和事务锁 | 向量量级触及单库瓶颈时拆独立向量库（检索接口已隔离在仓储层） |
| 插件加载默认关闭 | Python 插件拥有进程级权限 | 隔离 worker 和签名供应链成熟后 |
