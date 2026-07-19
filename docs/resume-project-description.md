# 简历项目描述：AI 驱动的全球兼职职位匹配与 Agent 管理平台

> 2026-07-19 整理。所有描述均与代码库实际实现对齐，量化数字见 `docs/recall-eval-report.md`。

## 精简版（推荐直接使用）

**AI 驱动的全球兼职职位匹配与 Agent 管理平台（个人项目）**
Python · FastAPI · Next.js · PostgreSQL/pgvector · Neo4j · Celery · Docker

1. 独立开发全球兼职匹配平台，覆盖职位采集、智能匹配、人工审批、通知与审计全流程，Docker Compose 编排 7 个服务一键部署。
2. 构建"pgvector 向量召回 + 规则精筛"混合推荐引擎，自建评测集验证：非关键词场景 Recall@5 从 0 提升至 1.0，整体从 0.47 提升至 1.0。
3. 基于 Neo4j 构建技能知识图谱，归一技能别名（K8s/Kubernetes）、按上下位类别扩展候选人技能，生成带依据的可解释推荐理由。
4. 设计统一 Agent 注册与受控工具调用机制，以动作白名单、参数校验、风险分级、幂等键约束执行范围，调用全程可审计。
5. 构建采集→去重→向量化→匹配→审批→通知的 Celery 流水线，落库规则版本、检索证据与评分明细，支持错误分类与指数退避重试。

## 详细版（篇幅充裕时使用）

1. 设计并开发全球兼职职位匹配平台，基于 Python、FastAPI、Next.js 和 PostgreSQL，覆盖职位来源管理、候选人偏好、智能匹配、人工审批、通知发送与操作审计全流程；Docker Compose 一键编排 API、Celery worker、PostgreSQL、Redis、Neo4j、前端共 7 个服务。
2. 构建"向量语义召回 + 规则精筛"的混合推荐引擎：先通过 pgvector 余弦相似度检索（HNSW 索引，1024 维 embedding）召回与候选人技能及经历语义相关的职位，再按地区、时区、薪资、语言、工时等硬性条件精筛。自建同义改写评测集离线验证：非关键词场景下 Recall@5 由关键词匹配的 0 提升至 1.0，整体 Recall@5 由 0.47 提升至 1.0。
3. 构建招聘技能知识图谱（Neo4j），统一技能别名（如 K8s/Kubernetes）、维护技能上下位类别关系，匹配时自动扩展候选人相关技能，并生成带匹配依据（命中技能、语义相似度、检索排名）的可解释推荐理由。
4. 设计统一 Agent 注册与工具调用机制，将职位检索、技能查询、匹配评分、审批和通知封装为受控动作，通过动作白名单、参数校验、风险分级和幂等键约束 Agent 执行范围，所有调用全程可审计。
5. 构建"职位采集（4 个数据源）—清洗去重—结构化抽取—向量化—匹配推荐—人工审批—通知发送"全链路 Celery 任务流水线，持久化每次匹配的规则版本、检索证据（召回方式/相似度/排名）、分项评分与操作人员，支持错误分类、指数退避重试与结果追溯。

## 面试要点

**一句话讲召回评测**：
"我用合成改写测试集 + 与线上完全相同的检索路径做了离线召回评测：关键词匹配在跨语言/同义改写场景（'分布式爬虫'↔'Web Harvesting Platform'）Recall@5 是 0，向量召回拉到满召回。"

**主动交代的局限性（加分项）**：
评测集 30 职位 / 8 候选人，向量召回触及天花板（全项 1.0）；可靠结论是相对差距的方向与量级，不是绝对数值。局限性已写在评测报告里。

**可能被追问的点与答法**：
- 为什么先召回后规则精筛？——召回是为了从全量里缩小候选集（top-200），规则精筛是硬性资格约束；顺序反了就变成重排序，提升不了召回。
- 通知的真实渠道？——渠道抽象为 provider（当前 simulation），审批流、频控、资格复核、发送状态机均为真实实现；接 SMTP/webhook 是配置级工作。
- 知识图谱的"上下位"？——别名边（ALIAS_OF）+ 技能到类别的上下位边（CHILD_OF），间接命中的技能会写进可解释理由；技能间横向关联边（RELATED_TO）是规划中的下一步。
- 信息抽取用 LLM 吗？——采集侧是规则映射 + 抽取置信度标注（4 个数据源统一 schema）；简历解析侧（候选人）有独立的 PDF 解析。

## 证据索引（面试现场可演示）

| 主张 | 代码/文档位置 |
|---|---|
| 召回评测数字 | `docs/recall-eval-report.md` + `scripts/eval_recall.py`（可复现） |
| pgvector 召回 | `src/agent_hub/agents/global_part_time/service.py` run_matches；`src/agent_hub/database/repository.py` search_jobs_by_embedding |
| 向量列与索引 | `alembic/versions/20260718_0004_job_embedding.py`（vector(1024) + HNSW） |
| 检索证据落库 | match 记录 `retrieval` 字段（method/similarity/rank/recall_size） |
| 技能图谱 | `src/agent_hub/skill_graph/`（Neo4j，ALIAS_OF/CHILD_OF/expand） |
| Agent 受控调用 | `src/agent_hub/core/contracts.py`（RiskLevel/幂等键）、`api/platform.py` |
| 流水线与重试 | `src/agent_hub/worker/`（错误分类、指数退避、workflow 追踪） |
| 混合引擎设计 | `docs/superpowers/specs/2026-07-18-pgvector-recall-design.md` |
