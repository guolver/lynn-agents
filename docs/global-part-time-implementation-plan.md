# AI 驱动的全球兼职职位匹配与 Agent 管理平台实施计划

> 文档状态：V1 实施规划  
> 更新日期：2026-07-17  
> 适用范围：个人项目，前端 + 后端 + AI 应用

## 1. 项目目标

在现有 Agent Hub 和全球兼职职位 Agent MVP 的基础上，建设一条真实、可解释、可恢复、可审计的业务闭环：

```text
职位来源
  → 采集
  → 清洗去重
  → 信息抽取
  → 规则过滤
  → 向量召回
  → 技能图谱扩展
  → 匹配评分
  → 人工审批
  → 邮件通知
  → 全链路审计
```

V1 重点证明以下能力：

- 使用 Python、FastAPI、Next.js 和 PostgreSQL 完成全栈业务闭环。
- 使用“确定性规则过滤 + pgvector 语义召回”实现混合推荐。
- 使用技能别名和技能关系解决简历与职位描述表达不一致的问题。
- 通过动作白名单、输入校验、风险等级和幂等键约束 Agent 行为。
- 为采集、匹配、审批和通知保存版本、证据、状态与操作审计。

## 2. V1 范围

### 2.1 包含范围

- 软件开发类全球远程兼职职位。
- 中文和英文两种语言。
- 2～3 个明确允许使用的 RSS、ATS API 或合作方 Feed。
- 候选人技能、项目经历、地区、时区、语言、薪资和工时偏好。
- PostgreSQL 16 和 pgvector。
- 一个可替换的 Embedding Provider。
- PostgreSQL 技能知识图谱。
- Redis + Celery 异步任务。
- 人工审批后的邮件通知。
- 管理后台和完整操作审计。

### 2.2 非目标

- 绕过登录、验证码、反爬机制或平台访问控制。
- 自动操作 LinkedIn、BOSS 直聘等第三方招聘平台。
- 未经候选人授权采集简历或发送消息。
- 自动代表候选人提交敏感材料、接受合同或承诺入职。
- V1 同时覆盖所有行业、语言、国家和通知渠道。
- 一开始引入 Kafka、Kubernetes 等非必要基础设施。

## 3. 当前基线

当前仓库已经具备：

- FastAPI 后端与 Next.js 管控台。
- Agent 注册、发现和统一调用接口。
- Agent 动作白名单、风险等级、参数校验和写动作幂等要求。
- 来源登记、审核、结构化 Feed 同步和跨来源去重。
- 地区、时区、语言、薪资、工时等确定性硬过滤。
- 确定性加权评分和基础推荐理由。
- 人工审批、模拟通知、退订和审计。
- SQLite MVP Repository。
- **PostgreSQL 16 数据层**（Phase 0 + Phase 1 已完成）：
  - 21 表 SQLAlchemy ORM 模型 + Alembic 迁移。
  - `PostgresRepository` 实现（CRUD / 审计 / 事务性幂等 / 并发安全）。
  - `RepositoryProtocol` 抽象 + `create_repository` 配置工厂。
  - Docker Compose 本地开发基础设施。
  - Repository 契约测试、PostgreSQL 集成测试和工作流 E2E 测试。
- **RemoteOK 职位连接器**：首个真实职位来源，CLI 脚本完成采集到同步全流程。
- 40+ 个通过的 Python 自动化测试。

V1 主要缺口：

- pgvector、Embedding 和 RAG 语义检索。
- 招聘技能知识图谱（Neo4j，进行中）。
- 异步任务、失败重试和运行状态。
- 真实邮件 Provider。
- 前端真实业务操作闭环。

## 4. 技术方案

| 领域 | V1 方案 |
| --- | --- |
| 后端 | FastAPI、Pydantic |
| 数据访问 | SQLAlchemy 2、Alembic、psycopg |
| 数据库 | PostgreSQL 16、pgvector |
| 异步任务 | Celery、Redis |
| 前端 | 现有 Next.js 管控台 |
| 语义检索 | pgvector cosine distance |
| 技能图谱 | Neo4j 5.x（Docker），`neo4j` Python driver |
| 信息抽取 | LLM 结构化输出 + Pydantic 校验 |
| 通知 | 邮件 Provider；开发环境模拟发送 |
| 可观测性 | 结构化日志、trace_id、workflow_run_id |
| 测试 | 单元、PostgreSQL 集成、API 和 E2E 测试 |

核心约束：

1. 硬过滤必须由确定性代码执行，模型不得覆盖。
2. LLM 和 Embedding 必须通过接口封装，可替换、可模拟。
3. 所有会产生副作用的动作必须具备持久化幂等。
4. 高风险动作必须经过人工审批。
5. 推荐必须保存检索和评分证据，不能只保存最终分数。

## 5. 目标架构

```text
Next.js Console
      │
      ▼
FastAPI / Agent Hub
      │
      ├── Agent Registry / Action Policy / Idempotency
      ├── Global Part-time Application Service
      ├── Matching Service
      ├── Skill Graph Service
      ├── Embedding Provider
      └── Notification Provider
      │
      ├───────────────┬───────────────┐
      ▼               ▼               ▼
PostgreSQL         Neo4j 5.x       Redis / Celery
+ pgvector         Skill Graph     Workflow Workers
```

## 6. 分阶段实施计划

### Phase 0：冻结基线 ✅

目标：保证后续重构不破坏当前功能。

任务：

- 补充硬过滤、风险判断、去重、审批和幂等边界测试。
- 固定现有 REST API 和平台 API 的关键响应契约。
- 建立职位、候选人、技能和匹配测试数据工厂。
- 为数据库、任务队列和模型 Provider 决策添加 ADR。
- 确认现有 SQLite 数据是否需要迁移。

验收标准：

- 当前 21 个测试继续通过。
- 核心领域行为有明确自动化测试保护。
- V1 范围和非目标得到确认。

### Phase 1：PostgreSQL 数据层 ✅

目标：用结构化 PostgreSQL 模型替换通用 JSON 实体存储。

建议核心表：

```text
job_sources
source_sync_runs
raw_jobs
jobs
job_versions

candidates
candidate_experiences
candidate_skills

skills
skill_aliases
skill_relations
job_skills

matches
match_evidence
match_score_items

workflow_runs
workflow_steps
approvals
notifications
audit_logs
idempotency_records
```

任务：

- 引入 SQLAlchemy、Alembic 和 psycopg。
- 添加 PostgreSQL 与 Redis 本地开发配置。
- 创建领域表、外键、索引和迁移脚本。
- 抽象 Repository 协议并实现 `PostgresRepository`。
- 为幂等键增加唯一约束和事务保护。
- 为来源职位 ID、规范 URL 和内容指纹增加去重约束。
- 将审计日志设计为只追加记录。
- 增加 PostgreSQL Repository 集成测试。

验收标准：

- API 能在 PostgreSQL 上完成现有全流程。
- Alembic 可以从空数据库完整升级。
- 并发调用不会创建重复职位、匹配或通知。
- SQLite 明确保留为轻量测试实现或进入废弃流程。

### Phase 2：技能知识图谱

目标：统一技能表达，并在受控范围内扩展相关技能。

技术方案：使用 **Neo4j 5.x**（Docker 部署）作为图数据库，通过 `neo4j` Python driver 访问。图谱包含 `Category`、`Skill` 节点和 `ALIAS_OF`、`CHILD_OF`、`RELATED_TO`、`REQUIRES` 关系。

关系示例（Cypher）：

```text
(:Skill {name: "K8s"})-[:ALIAS_OF]->(:Skill {name: "Kubernetes"})
(:Skill {name: "Kubernetes"})-[:RELATED_TO]->(:Skill {name: "Docker"})
(:Skill {name: "Kubernetes"})-[:REQUIRES]->(:Skill {name: "Linux"})
(:Skill {name: "FastAPI"})-[:CHILD_OF]->(:Category {name: "后端开发"})
```

任务：

- 引入 `neo4j` 运行时依赖和 `testcontainers[neo4j]` 测试依赖。
- 在 Docker Compose 中添加 Neo4j 5.x 服务。
- 创建 `SkillGraphService`，提供 `seed()`、`resolve()` 和 `expand()` 方法。
- 使用 `MERGE` 保证种子数据幂等写入。
- `resolve()` 将别名规范化为标准技能名（大小写、缩写、中英文）。
- `expand()` 批量解析别名并扩展到父级 Category，返回标准技能名 + Category 集合。
- 实现最大深度为 1～2 的图谱扩展（通过 Cypher 查询控制跳数）。
- 为图谱循环、重复路径和弱关联扩散增加保护。
- 在 `domain.py` 的 `_skill_score` 和 `score_match` 中增加可选 `expand_fn` 参数。
- 在 `app.py` 启动时检测 `NEO4J_URI` 环境变量，有则初始化 `SkillGraphService` 并注入。
- 初始种子数据覆盖 6 个类别约 45 个软件开发技能及其别名。

建议初始权重：

| 命中方式 | 权重 |
| --- | ---: |
| 直接命中 | 1.00 |
| `ALIAS_OF` | 1.00 |
| `REQUIRES` | 0.75 |
| `CHILD_OF` | 0.65 |
| `RELATED_TO` | 0.40 |
| 二跳关联 | 一跳权重 × 0.50 |

验收标准：

- `K8s` 与 `Kubernetes` 被 `resolve()` 规范为同一技能。
- `expand(["React"])` 返回 `{"React", "前端开发"}`。
- 没有 Neo4j 时（`NEO4J_URI` 未设置），系统降级为无扩展模式，不影响现有功能。
- 种子数据可以重复执行（`MERGE` 幂等）。
- 每个扩展技能都能解释关系路径。
- 图谱不会无限递归或通过弱关联产生过高分数。
- 测试使用 `testcontainers[neo4j]` 自动启动临时 Neo4j 实例。

### Phase 3：Embedding 与 RAG 检索

目标：在确定性硬过滤之后实现语义召回。

推荐链路：

```text
全部有效职位
  → 地区/时区/语言/薪资/工时过滤
  → pgvector Top 100
  → 技能图谱重排
  → 综合评分
  → Top 10 推荐
```

任务：

- 启用 pgvector 扩展并为职位增加向量列。
- 定义稳定的职位 Embedding 文本模板。
- 定义候选人技能和项目经历查询模板。
- 创建 `EmbeddingProvider` 接口。
- 实现生产 Provider 和确定性测试 Provider。
- 在职位新增或实质更新后异步生成向量。
- 使用 SQL 先执行硬过滤，再执行向量 Top-K 检索。
- 保存模型版本、相似度、召回排名和查询摘要。
- 实现失败补偿和模型升级后的批量重建任务。

验收标准：

- 非关键词但语义相近的职位能够被召回。
- 不符合硬条件的职位不会被语义相似度重新纳入。
- 测试不依赖真实模型和外部网络。
- 更换模型后可以安全重建向量索引。

### Phase 4：混合评分与可解释证据

目标：生成可复现、可解释的推荐结果。

建议初始公式：

```text
final_score =
    0.35 × semantic_similarity
  + 0.25 × skill_score
  + 0.15 × preference_score
  + 0.10 × compensation_score
  + 0.10 × freshness_quality
  + 0.05 × graph_relation_score
```

每次匹配保存：

- 规则版本和职位版本。
- 候选人偏好版本。
- Embedding 模型及版本。
- 检索排名和语义相似度。
- 直接命中技能。
- 扩展技能及知识图谱关系路径。
- 各维度原始分、权重和加权分。
- 硬过滤结果和过滤原因。
- 推荐理由及其证据引用。
- 创建任务、执行 Agent 和操作人员。

推荐理由采用“确定性证据模板 + 可选 LLM 润色”：

```text
证据：
- 直接匹配 Python、FastAPI
- Kubernetes 通过 K8s 别名命中
- 工作时区与 Asia/Shanghai 重叠 4 小时
- 时薪上限高于候选人最低要求 20%

理由：
你的 Python/FastAPI 经验与岗位核心要求直接匹配；
简历中的 K8s 已规范化为 Kubernetes，满足其容器编排要求。
```

验收标准：

- 关闭 LLM 后仍能生成确定性推荐理由。
- LLM 不得创造证据库中不存在的技能、薪资或工作条件。
- 相同版本输入可以重现评分结果。
- 管理后台可以查看完整评分拆解。

### Phase 5：任务编排与失败重试

目标：把采集、抽取、Embedding、匹配和通知变成可恢复任务。

任务状态：

```text
pending → running → succeeded
              │
              ├──→ retry_scheduled → running
              └──→ failed → manual_review
```

任务：

- 接入 Celery 和 Redis。
- 建立工作流运行与步骤记录。
- 为每个步骤生成稳定幂等键。
- 实现指数退避、最大重试次数和任务超时。
- 区分可重试错误与永久业务错误。
- 支持后台人工重试和从指定步骤重新运行。
- 防止过期或重复任务发送通知。
- 保存输入输出摘要、错误分类和 trace 信息。

可自动重试：

- 来源超时。
- 模型限流或暂时不可用。
- 邮件服务暂时不可用。
- 数据库短暂连接失败。

不可盲目重试：

- 来源未授权。
- 输入 Schema 错误。
- 人工拒绝。
- 候选人已经退订。
- 职位被确定性规则判定为高风险。

验收标准：

- Worker 中断后任务可以安全恢复。
- 重试不会产生重复职位或重复通知。
- 后台可以查看失败步骤、尝试次数和错误原因。

### Phase 6：审批与真实通知

目标：在安全边界内完成真实业务闭环。

任务：

- 为审批增加清晰的状态机、权限和版本检查。
- 将通知草稿、审批和发送记录分离。
- 发送前再次检查候选人授权和退订状态。
- 发送前再次检查职位有效性。
- 接入真实邮件 Provider。
- 开发和测试环境强制使用模拟 Provider。
- 增加退订链接、发送回执、退信和投诉处理。
- 保存邮件 Provider 消息 ID。

验收标准：

- 未审批通知不能发送。
- 已退订候选人不能收到通知。
- 相同幂等键不会发送两次。
- 所有审批和发送动作都有 actor、时间与关联实体。

### Phase 7：前端真实业务闭环

目标：可以只通过管理后台完成主要业务流程。

页面范围：

- 数据源管理与同步记录。
- 职位列表、详情和职位版本。
- 候选人资料与偏好。
- 技能知识图谱管理。
- 匹配结果、检索证据和评分拆解。
- 审批队列。
- 工作流运行中心。
- 通知记录。
- Agent 管理和动作调用。
- 审计中心。

任务：

- 关闭默认演示数据回退，连接真实 BFF/API。
- 建立统一、类型安全的 API 客户端。
- 增加加载、空数据、失败和权限不足状态。
- 为高风险操作增加二次确认。
- 为所有写请求生成幂等键。
- 支持通过 actor、实体、事件和时间筛选审计日志。

验收标准：

- 网页可以完成来源同步、匹配、审批和通知流程。
- 页面刷新后状态不会丢失。
- 后端异常不会静默回退为演示数据。
- 关键业务记录可以跳转到对应审计事件。

## 7. 建议迭代安排

按个人项目、兼职开发估算：

| 周期 | 交付内容 | 状态 |
| --- | --- | --- |
| 第 1 周 | 基线、ADR、PostgreSQL 环境与数据模型 | ✅ 已完成 |
| 第 2 周 | Repository 迁移、事务幂等与集成测试 | ✅ 已完成 |
| 第 3 周 | Neo4j 技能知识图谱（`SkillGraphService`） | 🔄 进行中 |
| 第 4 周 | Embedding、pgvector 和语义召回 | |
| 第 5 周 | 混合评分、证据和推荐理由 | |
| 第 6 周 | Celery、Redis、任务状态和失败重试 | |
| 第 7 周 | 审批、邮件 Provider 和前端真实数据 | |
| 第 8 周 | E2E、可观测性、安全加固和演示数据 | |

如果时间有限，可以将复杂采集连接器和多通知渠道放入 V1.1，但不应省略持久化幂等、匹配证据和任务状态。

## 8. 测试策略

每个小任务遵循：

```text
先写失败测试
  → 实现最小功能
  → 测试通过
  → 重构
  → 阶段验收
```

测试层次：

- 领域单元测试：过滤、风险、评分、技能规范化和图谱扩展。
- Repository 集成测试：事务、唯一约束、并发和幂等。
- pgvector 检索测试：召回、排序和硬过滤边界。
- Worker 测试：重试、恢复、超时和重复执行。
- API 测试：身份、参数、权限、状态码和错误契约。
- 前端测试：真实 API、加载、空状态和错误状态。
- E2E 测试：来源同步到通知发送完整链路。

外部模型和通知服务在自动化测试中使用可预测的 Fake Provider；少量独立的 Provider 合约测试验证真实适配器。

## 9. V1 完成标准

满足以下条件后，项目介绍中的目标能力才算真正完成：

- PostgreSQL 是主要业务数据库。
- pgvector 用于真实语义召回。
- 技能别名和关系实际参与匹配。
- 硬规则在语义检索前执行。
- 推荐结果保存完整检索和评分证据。
- 异步工作流支持失败重试与人工恢复。
- 通知只有审批通过后才能发送。
- 写动作具有持久化、并发安全的幂等约束。
- 前端使用真实后端数据完成业务流程。
- 从职位采集到通知发送具有统一 trace。
- 自动化测试覆盖完整主流程。

## 10. 实施进度

### 第一批次（已完成）

Phase 0 + Phase 1 + RemoteOK 连接器：

1. ✅ 固定当前测试基线和 API 契约。
2. ✅ 确定 PostgreSQL 数据模型（21 表）。
3. ✅ 引入 SQLAlchemy、Alembic 和 psycopg。
4. ✅ 创建首版数据库迁移。
5. ✅ 抽象 Repository（`RepositoryProtocol`），并实现 `PostgresRepository`。
6. ✅ 通过 `create_repository` 工厂按环境变量切换存储后端。
7. ✅ 增加事务、并发去重和幂等集成测试。
8. ✅ 实现 RemoteOK 职位连接器（首个真实来源）。

### 当前批次

- Phase 2（Neo4j 技能知识图谱）：另一 Agent 独立进行。
- Phase 5（Celery + Redis 任务编排）：可并行推进，不依赖技能图谱。
- Phase 3（pgvector + Embedding）：pgvector 基础设施可独立搭建，完整召回链路需等 Phase 2。
