# 第一阶段：身份隔离、异步幂等与工作流恢复设计

> 状态：已确认设计
> 日期：2026-07-19
> 范围：Agent Hub 模块化单体的第一阶段架构加固

## 1. 背景与目标

Agent Hub 已具备平台动作调用、兼容业务 API、PostgreSQL 持久化、Celery 工作流、
聊天会话和审计能力，但三个边界仍停留在单用户原型阶段：

1. `X-Actor` 由调用方直接提供，租户和角色没有形成可信安全上下文；聊天等资源也未
   强制执行租户与所有者隔离。
2. HTTP 异步分支直接派发 Celery 任务，忽略请求的 `Idempotency-Key`，重复请求可能
   生成多个独立工作流。
3. 人工重试由 API 手写任务映射并猜测参数，保存的 workflow payload 与任务签名不完全
   对称，部分工作流无法可靠恢复。

本阶段在保持模块化单体和现有领域规则的前提下，建立可信身份、租户隔离、两层幂等和
声明式工作流恢复机制。不会在应用内实现完整 OAuth/OIDC 服务，也不会拆分独立 IAM、
命令总线或 Outbox 服务。

## 2. 已确认决策

- 身份由外部网关完成认证，FastAPI 验证网关注入的安全头。
- 历史数据和开发兼容请求统一归入 `default` 租户。
- 第一阶段角色为 `admin`、`operator`、`user`。
- 生产环境不信任裸 `X-Actor`；开发环境通过显式模式兼容旧调用。
- API 请求幂等与 Worker 步骤幂等是两个独立层次。
- 人工重试与首次派发使用同一个工作流定义和 payload 契约。
- 第一阶段采用“数据库先提交、派发失败可补偿”的轻量命令提交方式，暂不实现
  transactional outbox publisher。

## 3. 安全上下文

### 3.1 Principal

平台核心新增不可变 `Principal`：

```python
@dataclass(frozen=True)
class Principal:
    actor_id: str
    tenant_id: str
    roles: frozenset[Role]
    trusted: bool
```

`Role` 仅允许 `admin`、`operator`、`user`。Principal 由统一身份组件创建，业务 payload
不能覆盖这些字段。现有 `ExecutionContext` 改为携带 Principal，同时保留 `actor` 和
`tenant_id` 兼容属性，降低 Agent 插件迁移成本。

### 3.2 请求身份解析

生产网关传递：

- `X-Actor`
- `X-Tenant-Id`
- `X-Roles`，逗号分隔
- `X-Gateway-Token`

运行模式：

- `SECURITY_MODE=trusted_gateway`：要求以上头完整，使用
  `hmac.compare_digest` 将 token 与 `TRUSTED_GATEWAY_SECRET` 比较。缺失或无效返回
  `401`；未知或空角色返回 `403`。
- `SECURITY_MODE=development`：允许现有 `X-Actor`，租户缺省为 `default`。兼容身份
  标记为 `trusted=False`。可通过 `X-Roles` 缩小角色；未提供时使用
  `DEVELOPMENT_DEFAULT_ROLES`，其缺省值为 `admin,operator,user`，以保持现有本地调用和
  测试兼容。该配置在 `trusted_gateway` 模式下完全无效。

`trusted_gateway` 模式缺少 `TRUSTED_GATEWAY_SECRET` 时应用拒绝启动，避免静默降级。

### 3.3 RBAC

权限矩阵：

| 能力 | admin | operator | user |
| --- | --- | --- | --- |
| Agent 目录与只读职位 | 是 | 是 | 是 |
| 平台治理、审计、插件管理 | 是 | 否 | 否 |
| 来源、职位审核、同步、匹配运营 | 是 | 是 | 否 |
| 通知审批与发送 | 是 | 是 | 否 |
| 全租户工作流查看与重试 | 是 | 否 | 否 |
| 本租户运营工作流查看与重试 | 是 | 是 | 否 |
| 自己的聊天、简历和候选人操作 | 是 | 否 | 是 |

跨租户或跨所有者访问统一返回 `404`，避免泄露资源是否存在。角色不足且资源无需查询时
返回 `403`。

### 3.4 非 HTTP 入口

Service 的受保护用例接收 Principal 或显式的 tenant/actor 上下文，不能只依赖路由校验。
Celery payload 保存 Principal 的非敏感快照（actor、tenant、roles），Worker 重建可信的
内部 Principal。MCP 客户端在生产写模式下必须配置 tenant、roles 和 gateway token。

## 4. 数据隔离

### 4.1 租户列与所有者

以下聚合根和治理记录增加非空 `tenant_id`：来源、职位、候选人、匹配、审批、通知、
反馈、审计、幂等、工作流和聊天会话。依赖这些聚合根的明细表通过外键继承隔离边界，
必要时同时存 tenant 以支持数据库级复合约束。

候选人增加 `owner_actor_id`。聊天会话规范现有 `actor` 为所有者，并在服务与查询方法中
统一使用 `owner_actor_id` 语义。历史候选人所有者回填为 `legacy-owner`；历史聊天会话
保留已有 actor，空值回填为 `legacy-owner`。

### 4.2 唯一性

以下唯一约束加入 tenant：

- 职位：`(tenant_id, dedup_key)`
- 匹配：`(tenant_id, candidate_id, job_id)`
- 幂等：`(tenant_id, action, key)`
- 其他面向业务的自然键按相同原则处理

### 4.3 Repository 规则

Repository 的业务查询必须显式接收 `tenant_id`，默认不提供跨租户查询。跨租户管理查询
使用带 `admin_` 前缀的独立方法，并要求调用层先验证 admin 角色。

聊天查询增加 owner 条件。列表、详情、删除、消息、流恢复和简历上传在进入业务逻辑前
都验证 `(tenant_id, owner_actor_id)`。

## 5. 异步提交幂等

### 5.1 两层幂等

1. 请求层：防止相同 HTTP 命令创建多个 workflow。
2. 执行层：防止 Celery 重投或自动重试重复执行同一步骤。

请求层唯一键为 `(tenant_id, action, idempotency_key)`；执行层继续使用
`(workflow_run_id, step_name)` 生成确定性 key。

### 5.2 WorkflowCommand

新增 `workflow_commands` 表：

| 字段 | 说明 |
| --- | --- |
| id | 命令 ID |
| tenant_id | 租户 |
| action | 稳定动作名 |
| idempotency_key | 调用方 key |
| request_hash | 规范化 payload 的 SHA-256 |
| workflow_run_id | 关联运行 |
| celery_task_id | 成功派发后的任务 ID |
| status | pending_dispatch / dispatched / dispatch_failed |
| last_error | 截断且脱敏的派发错误 |
| created_at / updated_at | 时间戳 |

命令创建和 WorkflowRun 创建在同一数据库事务中完成。相同 key 与相同 request hash 返回
已有 command/run；相同 key 与不同 hash 返回 `409`。

数据库提交后调用 Celery。成功时记录 task ID 和 `dispatched`；失败时记录
`dispatch_failed`。人工重试或补偿任务可以重新派发同一 command，而不会新建 workflow。

大型或敏感输入不写入普通 workflow JSON。新增受租户保护的
`workflow_command_payloads` 表，保存来源同步的职位批次等可恢复输入，并通过 command ID
一对一引用；终态保留 7 天后可清理。简历正文不复制到该表，workflow 只引用已经保存该
正文的 chat message ID。WorkflowRun 只保存 command/payload 引用和非敏感摘要。

## 6. 声明式工作流与恢复

### 6.1 WorkflowDefinition

新增统一注册表：

```python
class WorkflowDefinition(Protocol):
    workflow_type: str
    task_name: str
    payload_model: type[BaseModel]
    allowed_roles: frozenset[Role]
    retryable: bool
    sensitive_fields: frozenset[str]

    def build_task_kwargs(self, payload, principal, workflow_run_id): ...
```

所有会创建 WorkflowRun 的任务都必须注册。测试比较 Celery workflow 类型集合与注册表，
防止新增任务遗漏恢复定义。

### 6.2 派发与重试

首次派发和人工重试都调用统一 dispatcher：

```text
dispatch(workflow_type, payload_ref, principal, workflow_run_id)
```

允许人工重试的状态仅为 `failed`、`manual_review`、`dispatch_failed`。重试沿用原
workflow_run_id，创建新的 attempt/step，并更新 celery task ID。不会创建逻辑上无关的
新 WorkflowRun。

权限：

- admin 可重试任意本租户工作流；
- operator 可重试本租户运营工作流；
- user 只能重试自己发起的简历或聊天工作流；
- 未注册或不可重试的类型返回 `422`。

Celery 自动重试仍处理瞬时错误；人工重试处理重试耗尽、外部条件修复和派发失败。

## 7. API 与前端兼容

异步接口继续返回 `202`，响应统一为：

```json
{
  "status": "accepted",
  "workflow_run_id": "...",
  "celery_task_id": "...",
  "replayed": false
}
```

重复请求返回相同 ID，并将 `replayed` 设为 `true`。

前端 BFF 新增统一 Agent Hub 客户端，集中转发身份头、超时和错误。删除各 route 中硬编码
的 `chat-user`。本阶段不实现前端登录页面；生产部署由上游认证层向 BFF 提供已验证身份。

## 8. 错误处理与审计

- `401`：生产模式缺失或网关凭据无效。
- `403`：角色不足。
- `404`：资源不存在、跨租户或跨所有者。
- `409`：幂等 key 与 payload 冲突，或当前 workflow 状态不可重试。
- `422`：workflow 未注册、不可重试或 payload 不符合定义。

审计记录增加 tenant、actor、roles、request_id 和 workflow_run_id。日志、审计和 workflow
payload 不保存 gateway token、完整简历或其他非必要个人信息。

## 9. 数据迁移

Alembic 迁移按以下顺序执行：

1. 新增可空 tenant/owner 列和 workflow command 表。
2. 历史 tenant 回填为 `default`；历史 owner 按第 4.1 节规则回填。
3. 删除旧唯一约束，建立 tenant 复合唯一约束和查询索引。
4. 将 tenant/必要 owner 列改为非空。
5. 增加外键与一致性约束。

迁移不删除现有业务记录。回滚只恢复旧约束和列，不尝试合并迁移后不同租户产生的相同
自然键；在存在冲突数据时 downgrade 必须明确失败。

## 10. 测试策略

实施遵循测试驱动开发，覆盖：

- 身份解析：有效/无效 token、缺头、角色、两种安全模式。
- RBAC：角色允许与拒绝矩阵。
- 数据隔离：两个 tenant 的实体 ID、自然键和幂等 key 互不影响。
- 所有权：用户不能读取、删除、发消息或上传到他人的聊天会话。
- 请求幂等：重复异步请求只派发一次；相同 key 不同 payload 返回 `409`。
- Worker 幂等：Celery 重投不重复执行步骤。
- 工作流恢复：每种定义都能从持久化 payload 引用重建参数。
- 重试权限与状态机。
- 迁移：历史数据进入 `default`，owner 回填、索引和约束正确。
- 现有领域规则回归测试。

质量门禁统一以 pytest 为主，并修复当前 `tests` 包收集路径和 Neo4j Testcontainers 凭据
漂移。CI 后续至少分为纯单元、PostgreSQL/Redis、Neo4j 和前端 lint/build 四组。

## 11. 非目标

- 在应用内实现 OAuth/OIDC 登录与 token 签发。
- 引入独立 IAM 服务。
- 拆分微服务。
- 本阶段实现 Kafka 或完整 transactional outbox publisher。
- 重写匹配、风险、推荐或 LLM 业务规则。
- 建设前端登录和租户管理 UI。

## 12. 完成标准

1. 生产模式无法使用伪造的裸身份头调用 API。
2. 所有受保护数据查询均受 tenant 限制，个人数据同时受 owner 限制。
3. 每个异步写入口使用请求幂等 key，同一请求只产生一个 workflow。
4. 所有记录型 workflow 都有声明式定义并能可靠人工重试。
5. 历史数据无损迁移到 `default`。
6. 新增安全、隔离、幂等、恢复和迁移测试通过，既有领域测试无回归。
