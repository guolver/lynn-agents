# 技术细节深度知识库（面试准备）

> 生成于 2026-07-20，通过对当前代码库（含未提交的 `alembic/versions/20260719_0008_partial_hnsw_index.py`）的直接代码走读整理，每条结论都标注了文件路径与行号。目的是把 `docs/resume-project-description.md` 里"结论性"的简历表述，展开成可以被追问到任意深度都答得上来的实现细节。

## 使用方式

`docs/resume-project-description.md` 已经覆盖了简历措辞、24 道高频问答的应答要点和白话解读——那是"答题框架"。本文档是"答题弹药库"：面试官往深了追问一句，答案在这里都能查到具体代码。建议顺序：先看 resume 文档建立框架和"为什么"，被追问"具体怎么实现的"时再回到本文档定位对应小节。

## ⚠️ 先读这一节：文档与实现的已知落差

这些落差本身是很好的面试素材（"你怎么知道自己方案的边界"是诚实题的核心），逐条记下来，别被面试官问住：

1. **技能图谱的 `RELATED_TO`/`REQUIRES` 关系尚未合并进 main**。main 分支的 Neo4j 图谱只有 `ALIAS_OF`（别名）和 `CHILD_OF`（上下位类别）两种关系；横向关联边（如"Vue 经验部分命中 React 职位"）的设计和实现在独立分支 `feat/skill-graph-phase2-completion` 上，尚未合入。如果面试官追问"技能之间的横向关联具体怎么做的"，如实说"这是我下一步要合并的设计，当前 main 只做了别名归一和类别扩展"，不要把分支上的东西当成已上线能力来讲。
2. **`docs/hybrid-recommendation-engine.md` 里的流程图顺序与实际代码相反**。该文档写的是"先规则过滤再向量检索"，但 `service.py::run_matches` 和 `docs/superpowers/specs/2026-07-18-pgvector-recall-design.md` 明确的实际顺序是**先 pgvector 召回 Top-200，再对这 200 条跑硬过滤**。这份文档是早期面向非技术读者的概念图解，没有跟着代码演进更新。回答面试问题一律以代码为准。
3. **`docs/chat-agent-loop-explained.md` 已过期**：该文档的行号是针对 RBAC 改造前约 450 行的 `chat_service.py` 写的，现在文件已经涨到 634 行；文档里列的"已知弱点"包含"没有 agent 级评测"，但这个评测（`scripts/eval_agent_tools.py`）后来已经补上了。
4. **`MatchEvidence`/`MatchScoreItem` 两张表建了但没被写入**。`database/models.py` 里为"结构化可解释性"预留了这两张细粒度表（按证据类别、按打分维度分别建行），但当前 `run_matches` 实现里没有任何地方构造这两个 ORM 对象——所有打分明细实际上整体塞进 `Match.payload` 这个 JSONB 字段里。如果被问"你们的评分明细是怎么存的"，答案是 JSONB payload，不是这两张规范化表。
5. **PostgreSQL 里的 `skills`/`skill_aliases`/`skill_relations` 关系表建而未用**。这套关系型 schema 完整存在（迁移已跑、ORM 模型已声明），但代码库里没有任何仓储/服务逻辑读写它们——候选人和职位的技能实际上是以 JSON 数组形式直接存在 `candidates`/`jobs` 表的字段里，技能归一化和扩展全部发生在 Neo4j 一侧。这是一套"建而未用"的平行方案，不是当前实际查询路径。
6. **`embedding.py` 里的默认模型常量还是 `BAAI/bge-m3`，但真实部署已切到 `Qwen3-Embedding-0.6B`**——`.env` 和 `docker-compose.yml` 通过环境变量覆盖了代码里的默认值。两者都是 1024 维，所以切换没有触发数据库迁移，这也是能悄悄换模型而不用碰 schema 的原因。
7. **`backfill_embeddings_task`（补齐历史缺失向量的任务）没有被 Celery beat 自动调度**，也没有任何 HTTP 路由触发它——它是一个写好了但只能手动 `.delay()` 触发的运维工具，不属于自动化流水线的一环。
8. **`ChatSession.owner_actor_id` 在业务代码里被设置，但没有对应的数据库列**——仓储层的 `chat_session` 字段映射只持久化 `candidate_id`/`title`/`actor`/`status`，`owner_actor_id` 写入内存 dict 后在落库时被静默丢弃，所有权检查实际上永远走 `.get("actor")` 兜底分支。今天恰好因为 HTTP 层总是把调用者的 `X-Actor` 同时赋给 `actor` 和 `owner_actor_id` 而"碰巧正确"，但这跟 `candidates` 表真正拥有独立 `owner_actor_id` 列的严谨程度不是一回事。

---

## 目录

1. [混合推荐引擎](#1-混合推荐引擎)
2. [技能知识图谱](#2-技能知识图谱)
3. [LLM 对话 Agent](#3-llm-对话-agent)
4. [Agent 平台治理与 MCP](#4-agent-平台治理与-mcp)
5. [Celery 异步流水线](#5-celery-异步流水线)
6. [多租户 RBAC 与资源归属](#6-多租户-rbac-与资源归属)
7. [数据库 Schema 与部署架构](#7-数据库-schema-与部署架构)

---

## 1. 混合推荐引擎

### 1.1 Embedding 生成

**模型与配置** — `agent_hub/agents/global_part_time/embedding.py:16-19`：

```python
EMBEDDING_DIM = 1024
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
```

代码默认值是 `BAAI/bge-m3`（早期选型，见 `docs/superpowers/specs/2026-07-18-pgvector-recall-design.md`），**实际部署已切到 `Qwen3-Embedding-0.6B`**：`.env` 写死 `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`，`docker-compose.yml` 用 `${EMBEDDING_MODEL:-BAAI/bge-m3}` 透传。两个模型都是 1024 维，所以切换没有触发迁移变更。

**调用方式**：用 `openai` SDK 指向 SiliconFlow 的 OpenAI 兼容端点，`_get_client()`（`embedding.py:24-30`）懒加载单例 `OpenAI(api_key=..., base_url=..., timeout=15.0)`。整个模块是**同步**调用，异步/批处理靠 Celery 任务包一层。

**批量接口** — `get_embeddings(texts: list[str])`（`embedding.py:33-55`）：先清洗文本（`t.strip()[:8000]`，空白记为 `None` 占位），过滤出非空 payload 调一次 API，再按原始位置映射回去。批大小常量在调用方 `agent_hub/worker/tasks.py:413`：

```python
EMBED_BATCH_SIZE = 64
```

`_embed_jobs()`（`tasks.py:416-434`）按 64 条切分，每批单独调 API，成功的立刻 `repo.update_job_embeddings()` 落库，失败的整批跳过——不会因为一条文本失败拖累整批 64 条。

**触发链路**：`sync_source_task`/`fetch_and_sync_source_task` 在导入成功后，对新增/更新的 `job_ids` 异步 `embed_jobs_task.delay(job_ids, actor)`——导入和向量化解耦。在线匹配路径里**候选人向量是同步实时算的**（每次调用一次 API，不落库），**职位向量完全离线预计算好**存在 `jobs.embedding` 列，匹配时只做 pgvector 检索。

**存量补齐**：`backfill_embeddings_task`（`tasks.py:457-478`）扫 `list_jobs_missing_embedding()`（按 `created_at desc`，新职位优先）分批补齐，但**没有被 Celery beat 调度**，代码库里也没有 HTTP 路由触发它——是手动运维工具，不是自动化的一环（见开篇落差 7）。

**失败处理**：`get_embeddings` 任何异常都被捕获、`logger.warning` 后返回全 `None`，从不抛出到调用方；`_embed_jobs` 在"API key 已配置、有非空文本、但整批返回空"时主动 `raise RuntimeError`，交给 Celery 错误分类器走指数退避重试——区分"配置齐全但服务真挂了该重试"和"压根没配 key 就该静默跳过"两种情况。

### 1.2 pgvector 向量召回

**Schema / 索引演进（两次迁移）**：

`alembic/versions/20260718_0004_job_embedding.py`：

```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
op.add_column("jobs", sa.Column("embedding", Vector(1024), nullable=True))
op.execute(
    "CREATE INDEX IF NOT EXISTS ix_jobs_embedding_hnsw "
    "ON jobs USING hnsw (embedding vector_cosine_ops)"
)
```

未提交的新迁移 `20260719_0008_partial_hnsw_index.py` 把这个全表 HNSW 索引改成**局部索引**（`WHERE status = 'active'`）。迁移注释解释了三层事实：

1. 查询同时带 `status='active'` 谓词和向量排序，旧的全表索引无法证明谓词满足，Planner 从不选它（用 `enable_seqscan/enable_bitmapscan off` 验证过，退化为 `ix_jobs_status` + 排序）；把索引本身限定在同一谓词上，Planner 就能直接匹配。
2. **即便加了局部索引，当前数据量下 Planner 依然不会选择它**：约 1.1 万条 active 职位时，顺序扫描成本约 1700，HNSW 有序扫描成本约 2200~47700，顺序扫描仍更便宜。所以 `search_jobs_by_embedding()` 目前实际执行路径是「过滤 active + 内存排序」（约 100~150ms）。这次迁移只是「拆掉未来会挡路的谓词匹配障碍」，等表长大到顺序扫描更贵时索引才会被自动捡起来，不需要再改代码。
3. 埋了一个前瞻性告警：pgvector 的 `hnsw.ef_search` 默认是 40，低于代码里的 `RECALL_LIMIT=200`；一旦 Planner 真的开始走 HNSW 索引扫描，调用方必须 `SET hnsw.ef_search >= 200`，否则 `run_matches()` 会**静默召回不到 200 条**——一枚还没触发但已写好文档的隐患。

**查询本体** — `agent_hub/database/repository.py:699-712`：

```python
def _search_jobs_by_embedding(
    self, vec: list[float], limit: int = 200, *, tenant_id: str | None = None
) -> list[tuple[dict[str, Any], float]]:
    session = self._session()
    owns_session = not self._is_context_session()
    try:
        distance = Job.embedding.cosine_distance(vec)
        stmt = select(Job, distance.label("distance")).where(
            Job.status == "active", Job.embedding.isnot(None)
        )
        if tenant_id is not None:
            stmt = stmt.where(Job.tenant_id == tenant_id)
        rows = session.execute(stmt.order_by(distance).limit(limit)).all()
        return [(self._row_to_dict(row.Job, "job"), 1.0 - float(row.distance)) for row in rows]
    finally:
        if owns_session:
            session.close()
```

用 pgvector SQLAlchemy 扩展的 `.cosine_distance()`（对应 SQL `<=>` 余弦距离操作符），`ORDER BY distance ASC LIMIT limit`，再把距离转成相似度 `1.0 - distance`。WHERE 固定两条：`status='active'`、`embedding IS NOT NULL`（未向量化的职位天然被排除）。多租户版本额外加 `tenant_id` 过滤，复用同一份底层实现。

**Top-K=200** 定义在业务层：`service.py:29`：`RECALL_LIMIT = 200`。

### 1.3 硬过滤（hard_filter）

`domain.py:165-202`，纯函数、无副作用，返回失败原因列表：

| 检查 | 逻辑 |
|---|---|
| `candidate_not_opted_in` | `candidate.consent_status != "opted_in"` |
| `job_not_active` | `job.status != "active"` |
| `risk_not_approved` | 风险分 ≥0.25 且未 `review_status == "approved"` |
| `company_excluded` | 职位公司名在候选人 `excluded_companies` 黑名单里 |
| `work_mode_mismatch` | 候选人 `allowed_work_modes` 非空且不含职位 `work_mode` |
| `language_mismatch` | 职位要求语言集合不是候选人语言集合的子集（`issubset`） |
| `compensation_currency_mismatch` / `compensation_below_minimum` | 候选人最低时薪 vs 职位 `compensation_max`，先比币种再比金额 |
| `insufficient_availability` | 候选人每周可用工时 < 职位 `hours_per_week_min` |
| `already_sent` | 调用方传入的标记，避免重复推送 |

薪资比较用候选人下限 vs 职位**上限**；语言用**子集关系**（职位要求的每种语言候选人都必须具备）。**地区/时区不在硬过滤里**，只出现在打分阶段——刻意的软过滤设计，地区不满足不会被硬性淘汰，只会拉低分数。

### 1.4 加权打分

**权重表** — `domain.py:19-28`：

```python
SCORE_WEIGHTS = {
    "skills": 0.32, "semantic": 0.18, "language": 0.11,
    "location_timezone": 0.11, "compensation": 0.11,
    "availability": 0.06, "preference": 0.05, "freshness_quality": 0.06,
}
COMPLETENESS_FLOOR = 0.5
```

`skills` 权重最高（0.32），`semantic`（向量相似度）第二（0.18）——语义分不只是用来"找候选集"，也直接参与最终排序。

**完备度加权**（`score_match`，`domain.py:279-345`）是核心机制：每个维度带 `informative` 标志（该维度是否有信息），无信息的维度**从加权分母里剔除**而非硬记 0 分：

```python
active_weight = sum(SCORE_WEIGHTS[k] for k, v in informative.items() if v)
base = sum(breakdown[k] * SCORE_WEIGHTS[k] for k, v in informative.items() if v) / active_weight
factor = COMPLETENESS_FLOOR + (1 - COMPLETENESS_FLOOR) * active_weight
total = round(base * factor, 4)
```

`factor` 是完备度惩罚系数（`[0.5, 1.0]`），信息越不完整惩罚越重，但有 `COMPLETENESS_FLOOR=0.5` 兜底。`completeness < 0.7` 时会在 `reasons` 里追加"信息不完整，评分仅供参考"提示。

**语义相似度线性映射** — `_semantic_score`（`domain.py:228-248`）：

```python
return max(0.0, min(1.0, (precomputed - 0.3) / 0.6)), True  # [0.3, 0.9] → [0, 1]
```

余弦相似度天然聚集在 0.3~0.9 区间，不映射的话 `semantic` 维度长期"缩"在窄区间、区分度不够。`precomputed` 就是 pgvector 召回阶段带回的相似度——打分阶段**不重复调 embedding API**，只有降级为全量扫描时才用 `embed_fn` 现算。

**技能匹配 + 图谱间接命中折扣** — `_skill_score`（`domain.py:251-276`）：

```python
score = (len(direct) + len(indirect) * 0.6) / len(required)
```

`direct` 是归一化后的直接交集；`indirect` 是通过 `expand_fn`（技能图谱扩展）间接命中、但不在直接交集里的技能。**折扣系数 0.6**——图谱扩展关系是"相关"而非"等同"，需要打折避免虚高（详见第 2 节）。

`location_timezone` 内部子权重（`domain.py:306`）：`0.7 * location + 0.3 * timezone`。

### 1.5 匹配结果持久化

`run_matches`（`service.py:454-470`）落库的 payload：

```python
match = {
    "candidate_id": candidate_id, "job_id": job["id"],
    "hard_filter_passed": True, "score": score,
    "score_breakdown": breakdown, "reasons": reasons,
    "rule_version": RULE_VERSION,          # "2026-07-19.2"
    "job_version": job["updated_at"],
    "retrieval": retrieval_meta.get(job["id"], {"method": "full_scan"}),
    "created_at": utcnow(),
}
```

`retrieval` 字段（检索证据）来自 `service.py:406-411`：`{"method": "pgvector", "similarity": ..., "rank": ..., "recall_size": len(hits)}`。数据库层 `Match` 模型（`models.py:272-294`）只有 `score`/`hard_filter_passed` 是独立列，其余整体塞进 `payload: JSONB`（见开篇落差 4，`MatchEvidence`/`MatchScoreItem` 两张细粒度表建而未用）。

### 1.6 降级路径

`run_matches`（`service.py:391-413`）的降级判断：

```python
retrieval_method = "full_scan"
candidate_jobs = None
if embed_fn is not None and hasattr(self.repo, "search_jobs_by_embedding"):
    candidate_vec = embed_fn(build_candidate_text(candidate))
    if candidate_vec is not None:
        hits = self.repo.search_jobs_by_embedding(candidate_vec, RECALL_LIMIT)
        if hits:
            retrieval_method = "pgvector"
            candidate_jobs = [...]
if candidate_jobs is None:
    candidate_jobs = self.repo.list("job")
```

降级触发条件（任一满足即走全量扫描）：仓储不支持向量能力（如 SQLite）；未配置 `embed_fn`；候选人 embedding 生成失败；召回结果为空。`safe_embed` 包装器（`service.py:362-375`）额外兜底：一旦某次调用中途失败，`embedding_failed=True` 被记住，同一次 `run_matches` 内后续调用直接短路返回 `None`，不会对每个职位反复重试同一个已知会失败的 API。设计原则（`pgvector-recall-design.md`）："匹配功能在任何环境都不因向量层不可用而失败"。

### 1.7 召回效果评测

`docs/recall-eval-report.md`（30 职位 / 8 候选人，4 个是"同义改写"样本，技能表述与相关职位文本零关键词重叠）：

| 组别 | 召回方式 | Recall@5 | MRR |
|---|---|---|---|
| 全体(8) | keyword | 0.469 | 0.500 |
| 全体(8) | vector | 1.000 | 1.000 |
| 改写子集(4) | keyword | 0.000 | 0.000 |
| 改写子集(4) | vector | 1.000 | 1.000 |

**防泄漏设计**：① 向量检索窗口 `search_limit = len(repo.list("job")) + max(ks)`，覆盖库内全部职位，不受 `RECALL_LIMIT` 截断影响；② 只保留 `job["id"].startswith("eval-job-")` 的职位，历史真实数据不污染评测集；③ 评测数据临时写入再清理，开头先跑一次 `_cleanup` 清掉上次异常退出的残留；④ 脚本拒绝静默降级——没有 `DATABASE_URL`/`SILICONFLOW_API_KEY`/`search_jobs_by_embedding` 支持均直接 `sys.exit`，必须走真实 API + 真实 pgvector。

**局限性（报告原文明确写出）**：30 职位的小数据集上向量已触及天花板（全项 1.000），绝对数值不可外推；可靠的是相对差距的方向与量级（改写场景从 0 到满召回）。这是诚实披露评测局限性的例子，面试时可直接引用。

---

## 2. 技能知识图谱

### 2.1 数据模型（main 分支实际实现）

`SkillGraphService`（`agent_hub/skill_graph/service.py:10-14`）只接受一个 `neo4j.Driver`。节点标签只有两种：`Skill` 和 `Category`；关系只有两种（**不是三种或四种**，见开篇落差 1）：

- `ALIAS_OF`：别名节点 → 规范节点
- `CHILD_OF`：规范技能节点 → 分类节点

`seed()`（`service.py:16-46`）全部用 `MERGE` 保证幂等：

```cypher
MERGE (c:Category {name: $name})
MERGE (s:Skill {name: $name})
MATCH (s:Skill {name: $skill}), (c:Category {name: $cat})
MERGE (s)-[:CHILD_OF]->(c)
```

别名和规范技能用**同一个 `Skill` 标签**，靠是否有 `ALIAS_OF` 出边区分身份，不是单独的 `Alias` 标签。

### 2.2 别名归一化查询

`resolve()`（`service.py:48-64`）：

```cypher
MATCH (s:Skill {name: $name})
OPTIONAL MATCH (s)-[:ALIAS_OF]->(canonical:Skill)
RETURN coalesce(canonical.name, s.name) AS resolved
```

`OPTIONAL MATCH` + `coalesce`：是别名就返回指向的规范名，是规范技能本身就返回自身，节点不存在返回 `None`。

### 2.3 类别扩展查询（`expand`）

`service.py:66-87`，批量版本：

```cypher
UNWIND $names AS input
MATCH (s:Skill {name: input})
OPTIONAL MATCH (s)-[:ALIAS_OF]->(canonical:Skill)
WITH coalesce(canonical, s) AS resolved
OPTIONAL MATCH (resolved)-[:CHILD_OF]->(cat:Category)
RETURN collect(DISTINCT resolved.name) + collect(DISTINCT cat.name) AS expanded
```

未知名字被 `MATCH` 静默丢弃（`expand_unknown_skill_ignored` 测试验证）。`expand` 本身**不区分 direct/indirect**——它只是把技能字符串"翻译"成一组等价的规范名+分类名，返回一个扁平 `set[str]`；direct/indirect 的区分是调用方 `domain.py` 做的。

### 2.4 direct/indirect 打分算法

`_skill_score`（`domain.py:251-276`）：

```python
direct_set = required & owned                       # 归一化后直接交集
indirect_set = set()
if expand_fn:
    expanded_owned = owned | {_norm(x) for x in expand_fn(raw_owned)}
    for raw_skill in raw_required:
        normalized = _norm(raw_skill)
        if normalized in direct_set:
            continue
        expanded_required = {normalized} | {_norm(x) for x in expand_fn([raw_skill])}
        if expanded_owned & expanded_required:
            indirect_set.add(normalized)
score = (len(direct) + len(indirect) * 0.6) / len(required)
```

例：职位要求"前端开发"，候选人拥有"React"，`expand(["React"])` 返回 `{"React", "前端开发"}`，与要求集合相交 → indirect 命中。

**0.6 折扣验证**：`tests/test_skill_graph.py::test_direct_match_scores_higher_than_indirect` 用具体数字验证：候选人有 Python（直接）和 React（间接命中"前端开发"），职位要求 `["Python", "前端开发"]` → `Direct(Python)=1.0 + Indirect(前端开发)=0.6` → 平均 0.8，断言 `assertAlmostEqual(breakdown["skills"], 0.8, places=1)`。

### 2.5 可解释性：两层设计

`recommendation_explainer.py` **不是**规则化 reason-string 生成器，而是"在确定性理由之上叠加的 LLM 批量总结层"（文件顶部注释原文）。它调用 DeepSeek，system prompt 明确约束：

> 只返回以 job_id 为键、总结字符串为值的 JSON 对象。每句不超过 120 个中文字符。**不得编造输入中没有的经历、技能、薪资或岗位事实**。

传入的 `reasons`（确定性理由列表）作为 LLM 的输入依据，防止 LLM 凭空编造。**真正的确定性 reason** 在 `domain.py:347-379` 的 `score_match` 里拼出：

```python
if direct_skills:
    positive_reasons.append(f"技能{', '.join(direct_skills)}与职位要求直接匹配")
if indirect_skills:
    positive_reasons.append(f"候选人技能通过类别扩展与职位要求的{', '.join(indirect_skills)}相关")
```

### 2.6 熔断/降级机制

进程内单次调用的**布尔标志位**（不是重试计数、不是超时器），`service.py:321` 的 `run_matches` 方法体内定义为闭包变量：

```python
expansion_failed = False
def expand_skills(names):
    nonlocal expansion_failed
    if self.expand_fn is None or expansion_failed:
        return set()
    try:
        return self.expand_fn(names)
    except Exception as exc:
        expansion_failed = True
        logger.warning("Skill graph expansion failed; using direct skill matching: %s", exc, exc_info=True)
        return set()
```

关键行为是**全批次作废而非单条降级**：打分循环里一旦某职位触发异常就立刻 `break`，然后**整批 `eligible_jobs` 用不带 `expand_fn` 的 `score_match` 重新算一遍**，丢弃本轮所有已算出的图谱加分。测试 `test_batch_discards_all_graph_scores_when_later_job_expansion_fails` 用正序、倒序两种职位顺序验证：不管失败发生在第几个职位，整批结果都退化为纯字符串匹配，不存在"前面几个保留图谱加分、后面几个降级"的不一致状态。

应用层面还有"启动期熔断"（`app.py:66-83`）：`skill_graph.seed()` 在应用创建阶段失败会关闭驱动、让 `expand_fn` 永久保持 `None`，整个服务生命周期内都不用图谱，而不是每次请求都尝试连接失败。

### 2.7 PostgreSQL 平行表：建而未用

`alembic/versions/20260717_0001_postgresql_foundation.py` 建了 `skills`/`skill_aliases`/`skill_relations`/`job_skills`/`candidate_skills` 五张关系表，ORM 模型齐全（`models.py:217-264`），但搜索整个代码库**没有任何仓储/服务代码引用这些 ORM 类做查询或写入**——候选人/职位的 `skills` 字段实际是 JSON 数组直接存在 `candidates`/`jobs` 表字段里读写。`SkillRelation.relation_type` 没有任何地方写入过 `RELATED_TO` 之类的值，印证 Phase 2 的关系类型设计还停留在文档/未合并分支阶段。

### 2.8 种子数据规模

`SKILL_GRAPH_SEED` 实测统计：6 个 `Category`，45 个规范 `Skill`，66 个别名 `Skill`，图中 `Skill` 标签节点总数 111 个。`seed()` 每次应用启动都会执行，全部用 `MERGE`，测试验证重复调用不产生副作用。

| 分类 | 规范技能数 | 别名数 |
|---|---|---|
| 前端开发 | 9 | 17 |
| 后端开发 | 9 | 11 |
| 数据库 | 7 | 11 |
| 容器与云 | 7 | 11 |
| 移动开发 | 6 | 7 |
| 数据与AI | 7 | 9 |

### 2.9 测试覆盖

`tests/test_skill_graph.py` 用 `testcontainers.neo4j.Neo4jContainer` 起真实 Neo4j 容器（Docker 不可用时整体跳过），覆盖：别名全局唯一性静态校验（不需要容器）、`K8s→Kubernetes`/`ReactJS→React`/`Golang→Go` 三个具体断言、未知技能静默丢弃、贯穿 seed→expand→score_match 全链路的端到端验证。

---

## 3. LLM 对话 Agent

源文件：`chat_service.py`（634 行）、`chat_tools.py`（276 行）、`stream_hub.py`（111 行）、`resume_parser.py`、`scripts/eval_agent_tools.py`（265 行）+ `docs/agent-tool-eval-report.md`。

### 3.1 多轮 function calling 循环

没有用 LangChain/LangGraph——手写循环，用 `openai` SDK 指向 DeepSeek 的 OpenAI 兼容端点：

```python
from openai import OpenAI
client = OpenAI(api_key=api_key, base_url=base_url)   # base_url = https://api.deepseek.com
```

**白名单 6 个工具**（`chat_tools.py:24-148`，按名字精确匹配分发，`execute_tool()`）：

| 工具 | 用途 |
|---|---|
| `parse_resume` | LLM 解析简历原文为结构化字段，创建候选人，自动授权同意 |
| `run_matches` | 硬过滤+打分，返回带分数/理由的排序职位列表 |
| `search_jobs` | 关键词/国家/薪资/工作模式检索职位（非候选人专属打分） |
| `get_job_detail` | 按 id 取完整职位详情 |
| `update_preferences` | 更新候选人偏好（时薪/工作模式/国家/技能等） |
| `get_my_profile` | 返回候选人已存档的简历/画像 |

不在这 6 个之内的一律返回 `{"error": f"Unknown tool: {name}"}`——模型永远无法触达 `AgentService` 的任意方法，只能调这 6 个显式包装过的。

**循环骨架**（`chat_service.py:391-634`，`stream_response`）：

```python
max_rounds = 5
for round_index in range(max_rounds):
    response = client.chat.completions.create(
        model=model, messages=llm_messages, tools=TOOL_DEFINITIONS,
        stream=True, stream_options={"include_usage": True},
        temperature=0.7, max_tokens=2048,
    )
    # 收集流式 delta 到 collected_content / collected_tool_calls
    if collected_tool_calls:
        # 落库 assistant(tool_calls) 消息，追加到 llm_messages
        # 逐个执行工具，把结果追加到 llm_messages
        continue   # 进入下一轮让 LLM 消化工具结果
    else:
        # 无工具调用 → 最终答案，落库，yield "done"，return
```

**终止条件**：流式响应中没有 `tool_calls`——模型给出了纯文本最终答案。**最大轮数保护**：`max_rounds = 5`，硬编码熔断，无配置开关。到第 5 轮仍未自然终止，循环跳出 `for`，把该轮已收集到的 `collected_content`（可能是空的/不完整的）原样落库返回——不会强制发起一次不带工具的收尾请求。

**流式工具调用的重组**：API 会把工具调用参数也按 token 逐块流式吐出，代码按 `index` 跨 chunk 重组每个工具调用：

```python
if delta.tool_calls:
    for tc_delta in delta.tool_calls:
        if tc_delta.index is not None:
            while len(collected_tool_calls) <= tc_delta.index:
                collected_tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
            current_tool_call = collected_tool_calls[tc_delta.index]
        if tc_delta.id:
            current_tool_call["id"] = tc_delta.id
        if tc_delta.function:
            if tc_delta.function.name:
                current_tool_call["function"]["name"] += tc_delta.function.name
            if tc_delta.function.arguments:
                current_tool_call["function"]["arguments"] += tc_delta.function.arguments
```

参数 JSON 只有在该轮流式结束后才保证完整；`json.loads` 包在 try/except 里，解析失败降级为 `{}` 而不是让循环崩溃。工具执行是同步顺序循环，不是并发/异步——每个结果先落库再进下一轮。

### 3.2 流式 SSE

两层：`stream_response()` 是产出类型化事件字典的 Python 生成器；`_sse_response()`（`http_api.py:866-877`）把生成器转成 FastAPI `StreamingResponse`：

```python
def event_stream():
    for event in events:
        yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False, default=str)}\n\n"
return StreamingResponse(event_stream(), media_type="text/event-stream")
```

5 种事件类型：`delta`（内容片段）、`tool_call`（完整解码后、执行前）、`tool_result`（执行后）、`done`（终态）、`error`（终态）。内容 delta 和工具调用 delta 靠 OpenAI 格式的 `delta.content` vs `delta.tool_calls` 哪个非空来区分——内容逐块立刻转发，工具调用则缓冲重组，只在该轮流式结束后才作为一个完整 `tool_call` 事件抛出（前端永远看不到半截的工具调用 JSON，只看到半截文本）。

### 3.3 Redis Streams 断线续传

实现在 `stream_hub.py`。每个会话两个 Redis 结构：`chat:stream:{stream_id}`（Redis Stream，TTL 1800s，真正的事件日志）、`chat:active:{session_id}`（普通字符串 key，映射会话→当前活跃 `stream_id`，同样 TTL，避免进程崩溃留下幽灵"进行中"会话）。

**生成与 HTTP 连接解耦**（`chat_service.py:360-389`，`start_streaming`）：后台守护线程跑 `stream_response()` 并把每个事件发布进 hub；发起请求的 HTTP handler 只是*第一个*消费者，不是数据源头：

```python
def run():
    terminal_seen = False
    try:
        for event in self.stream_response(session_id, user_message):
            hub.publish(stream_id, event["event"], event["data"])
            if event["event"] in ("done", "error"):
                terminal_seen = True
    except Exception as exc:
        hub.publish(stream_id, "error", {"detail": f"生成中断: {exc}"})
        terminal_seen = True
    finally:
        if not terminal_seen:
            hub.publish(stream_id, "done", {})
        hub.clear_active(session_id)
threading.Thread(target=run, daemon=True, name=f"chat-stream-{stream_id[:8]}").start()
```

发布（`stream_hub.py:59-65`）：

```python
def publish(self, stream_id, event, data):
    pipe = self._redis.pipeline()
    pipe.xadd(key, {"event": event, "data": json.dumps(data or {}, ensure_ascii=False, default=str)})
    pipe.expire(key, STREAM_TTL_SECONDS)
    pipe.execute()
```

重连/重放（`stream_hub.py:69-94`）：

```python
def replay_and_follow(self, stream_id, timeout=600):
    last_id = "0-0"
    idle_deadline = time.monotonic() + timeout
    while time.monotonic() < idle_deadline:
        resp = self._redis.xread({key: last_id}, block=BLOCK_MS, count=100)
        if not resp:
            continue
        for _key, entries in resp:
            for entry_id, fields in entries:
                last_id = entry_id
                event = fields.get("event", "")
                yield {"event": event, "data": json.loads(fields.get("data", "{}"))}
                if event in TERMINAL_EVENTS:
                    return
                idle_deadline = time.monotonic() + timeout
```

**关键精确点**：这**不是**消费组机制（没有 `XGROUP CREATE`/`XREADGROUP`，Redis 侧没有按消费者的 offset 追踪）。每次调用 `replay_and_follow` 都从 `last_id="0-0"` 开始——即永远重放整个流从头开始，再阻塞（`XREAD ... BLOCK`）等新条目。所以"续传"本质是"把目前为止发布的全部事件重放一遍，然后继续跟随"——之所以便宜，是因为一个流只服务一轮对话（长度有界）且 1800s 后自动 TTL 过期。

**端到端重连流程**：① `POST /chat/sessions/{id}/messages` → `start_streaming` 起后台线程，`set_active` 注册 `chat:active:{session_id}=stream_id`，HTTP 响应本身就是 `_sse_response(hub.replay_and_follow(stream_id))`。② 客户端断连（切页、刷新），生成不受影响——它在守护线程里持续写 Redis。③ 客户端通过 `GET /chat/sessions/{id}/stream` 重连：查 `hub.get_active(session_id)` 恢复活跃 `stream_id`，再调 `replay_and_follow`——重放本轮已发布的全部 delta，再继续跟随直到 `done`/`error`。没有活跃流或 Redis 不可用返回 204。④ Redis 整体不可用时，`send_chat_message` 退化为进程内直接调 `stream_response()`——该降级模式下没有续传能力。

### 3.4 协议级历史清洗

`ChatService._sanitize_history`（`chat_service.py:318-358`），在 `build_llm_messages` 截断历史到最近 `MAX_HISTORY_MESSAGES=40` 条之后立刻调用。

**要防的具体协议 bug**：OpenAI/DeepSeek chat-completions 协议要求每条 `role:"tool"` 消息必须紧跟在携带匹配 `tool_calls[].id` 的 `role:"assistant"` 消息之后。如果历史窗口截断到最近 40 条时，截断点恰好落在 `assistant(tool_calls=...)` 和它的 `tool` 回复之间（或多工具调用轮次的多条回复之间），截断后的数组里就会出现一条孤儿 `tool` 消息、前面没有匹配的 `tool_calls`——API 直接拒绝**整个请求**（400），这是真实遇到过的失败模式。

```python
@staticmethod
def _sanitize_history(history):
    result, i = [], 0
    while i < len(history):
        msg = history[i]
        if msg["role"] == "tool":
            i += 1; continue      # 孤儿 tool 消息直接丢弃
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            call_ids = {tc["id"] for tc in msg["tool_calls"]}
            j = i + 1; responses = []
            while (j < len(history) and history[j]["role"] == "tool"
                   and history[j].get("tool_call_id") in call_ids):
                responses.append(history[j]); j += 1
            if len(responses) == len(call_ids):
                result.append(msg); result.extend(responses)
            elif msg.get("content"):
                result.append({k: v for k, v in msg.items() if k != "tool_calls"})
            i = j; continue
        result.append(msg); i += 1
    return result
```

两种情况：① 前面没有匹配 `assistant` 的孤儿 `tool` 消息直接丢弃；② `tool_calls` 未被完整应答的 `assistant` 消息，剥掉 `tool_calls` 字段只保留文本内容（如果有），而不是带着未应答的工具调用一起发送。

### 3.5 简历解析→建档流水线

两层设计：**编排是确定性的，编排内部的字段抽取本身是一次 LLM 调用**。

`ChatService.run_analysis()`（`chat_service.py:209-290`）是确定性外层流水线——由简历上传接口触发，不依赖对话式 LLM 自主决定是否调工具，固定顺序执行：`parse_resume` → `run_matches` → 落库合成的 `assistant/tool` 消息对 → 返回带匹配结果的增强响应。文档字符串原文："不依赖 LLM 决定是否调用工具"。

`execute_tool("parse_resume", ...)` 内部，真正的"文本→结构化字段"这一步委托给 `resume_parser.parse_resume()`——**这一步是 LLM 调用**：DeepSeek `chat.completions.create`，`response_format={"type": "json_object"}`，`temperature=0.1`（低温保证抽取稳定性），system prompt 指示抽取 `country`/`timezone`/`email`/`languages`/`skills`/`desired_roles`/`minimum_hourly_rate`/`availability_hours_per_week`/`allowed_work_modes`/`resume_summary`。PDF→文本抽取本身非 LLM（`pypdf.PdfReader`）。

工具返回值主动剥离 `resume_text`（`chat_tools.py:169-171`），完整简历不会重新进入对话上下文——只有后续调用 `get_my_profile` 才会返回它（截断到 6000 字符）。

### 3.6 消息持久化

`ChatSession`/`ChatMessage`（`models.py:522-559`）。`ChatMessage` 存原始协议形状（`role`/`content`/`tool_calls`/`tool_call_id`），`get_session()` 直接返回存储的消息列表，`build_llm_messages` 从这些行原样重建出 DeepSeek API 期望的数组格式——刷新后的会话可以逐字节从 Postgres 重建，不依赖 Redis 流缓冲（后者明确只是"断连窗口期的重放缓冲"，不是数据源头）。

### 3.7 工具选择评测

**方法论**：只评测*第一次*工具调用决策，直接从 `chat_service.py`/`chat_tools.py` 导入真实 `SYSTEM_PROMPT` 和 `TOOL_DEFINITIONS`（不重新声明），同生产环境的 DeepSeek 模型/温度（`0.7`）。不执行工具、不跑后续轮次——零副作用，不需要数据库。30 个手写用例（`scripts/agent_tool_eval_cases.json`），覆盖 `search_jobs`/`run_matches`/`update_preferences`/`get_job_detail`/`get_my_profile`/`no_tool`/`edge` 七类，`--trials 3` → 90 样本，`ThreadPoolExecutor(max_workers=8)` 并行。

**最终数字**（`docs/agent-tool-eval-report.md`）：
- 30 用例 × 3 trials = 90 样本
- 工具选择正确率：**92.2%**
- `no_tool` 误触发率：**0.0%**
- 参数正确率（工具选对的前提下）：**100.0%**
- 分类表现：`get_job_detail`/`get_my_profile`/`no_tool`/`parse_resume`/`search_jobs`/`update_preferences` 均 100%；`edge` 77.8%；`run_matches` 58.3%（最弱项）

**提示词迭代历史**：

| 版本 | 改动 | 正确率 |
|---|---|---|
| v0 | 原始提示词 | 68.9% |
| v1 | +"候选人 ID 已给定→直接调 `run_matches`/`update_preferences`，不要先查 profile"；+"问某类岗位→先用 `search_jobs` 查真实数据" | 86.7% |
| v2 | +"'根据我的简历/技能推荐'也应直接走 `run_matches`（匹配内部会读 profile）；`get_my_profile` 仅用于查看画像内容" | 92.2% |

**v0 失败模式**：即使候选人已绑定会话，模型仍会先调 `get_my_profile` "确认一下资料"再行动——`run_matches` 类别正确率 v0 时只有 8.3%；部分岗位是否存在的问题被模型凭自己的印象回答，而不是查 `search_jobs`。两条追加规则分别修复了这两点，把 `update_preferences` 和 `search_jobs` 都推到 100%。

**为什么卡在 92.2%**（报告自己的诚实分析）：剩余失败集中在"根据我的简历/技能推荐"这类措辞仍会先触发 profile 查询——报告认为这在完整多轮循环里并不真正有害（模型通常之后仍会调 `run_matches`，只是多花一轮），但在这个"只评第一次决策"的指标下算错。报告明确放弃继续逐case调提示词（担心对评测集过拟合），把进一步提升留给扩充用例多样性。

---

## 4. Agent 平台治理与 MCP

### 4.1 核心契约

`core/contracts.py` 刻意不依赖任何 Web 框架或 LLM SDK。`mode`/`risk_level` 是 `Literal` 而非独立 `Enum`：

```python
ActionMode = Literal["read", "write"]
RiskLevel = Literal["low", "medium", "high"]
```

`ActionDefinition`（frozen dataclass）：

```python
@dataclass(frozen=True)
class ActionDefinition:
    name: str
    description: str
    mode: ActionMode = "read"
    risk_level: RiskLevel = "low"
    requires_idempotency_key: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)
    allowed_roles: frozenset[Role] = frozenset({Role.ADMIN, Role.OPERATOR, Role.USER})
```

**`allowed_roles` 默认放开给全部三个角色**——一处需要主动指出的设计陷阱：如果某个 Agent 声明动作时忘记显式收窄 `allowed_roles`，注册表的角色检查就会变成静默的空操作。`global_part_time/agent.py` 的注释原文承认了这一点（并解释了为什么手工加了 `_OPS_ROLES`）。

`Agent` 协议是 `@runtime_checkable Protocol`，只要求三样：只读属性 `manifest`、`actions()` 返回白名单动作元组、统一入口 `invoke(action, payload, context)`。没有基类可继承，鸭子类型即可通过 `isinstance` 检查。

五个语义化异常全部继承自 `AgentPlatformError(ValueError)`：`AgentNotFoundError`、`ActionNotFoundError`、`DuplicateAgentError`、`InvalidInvocationError`、`AuthorizationError`——平台错误处理的唯一真源。

### 4.2 注册表调度流程

`AgentRegistry.invoke()`（`registry.py:74-89`），五步顺序有意义（先鉴权后校验，避免把"字段缺失"这类信息泄露给未授权调用者）：

```python
def invoke(self, agent_id, action_name, payload, context):
    agent = self.get(agent_id)                                    # 1. Agent 存在？→404
    action = self._find_action(agent.actions(), action_name)      # 2. 动作在白名单？→404
    if not context.principal.roles.intersection(action.allowed_roles):
        raise AuthorizationError(...)                              # 3. 角色检查 →403
    if action.requires_idempotency_key and not context.idempotency_key:
        raise InvalidInvocationError(...)                          # 4. 幂等键存在性 →422
    self._validate_required_fields(action, payload)                # 5. 必填字段 →422
    return agent.invoke(action_name, payload, context)
```

`invoke()` 永远不会把 `action_name` 传给 `getattr`——只传给 Agent 自己实现的 `invoke(action, payload, context)`，由 Agent 内部二次分发（如 `handlers` 字典）。`_validate_required_fields` 只读取 `input_schema.get("required", [])` 做存在性检查，完整的类型/业务约束下放给 Agent 自己。

### 4.3 幂等实现

幂等不在平台核心里，下放到各 Agent 自选的存储。`global-part-time` 用 `RootRepository._idempotent()`（`repository.py:620-687`）：

```python
def _idempotent(self, action, key, operation, *, tenant_id=None):
    session = self._session_factory()
    session.begin()
    existing = session.execute(select(IdempotencyRecord).filter_by(action=action, key=key)).scalar_one_or_none()
    if existing is not None:
        session.rollback(); return dict(existing.response)

    lock_key = int.from_bytes(hashlib.sha256(f"{tenant_id}:{action}:{key}".encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    existing = session.execute(select(IdempotencyRecord).filter_by(action=action, key=key)).scalar_one_or_none()
    if existing is not None:
        session.rollback(); return dict(existing.response)

    token = _active_session.set(session)
    result = operation()          # 业务逻辑在同一 session/事务里跑
    _active_session.reset(token)

    session.add(IdempotencyRecord(action=action, key=key, response=result, tenant_id=tenant_id))
    session.commit()
    return result
```

**双重检查锁定（check-lock-check）**：先无锁查询快速短路已完成的调用；再用 `pg_advisory_xact_lock`（事务级 advisory lock）防止并发重复执行；拿到锁后再查一次，防止等锁期间另一个并发请求已写完结果。锁 key 用 `sha256(f"{tenant_id}:{action}:{key}")` 取前 8 字节转有符号 64 位整数（Postgres advisory lock 要求 `bigint` 参数）。

**同事务保证**：业务逻辑 `operation()` 通过 `_active_session` contextvar 传递当前 session，内部所有仓储写操作复用同一事务——业务写入与 `IdempotencyRecord` 插入要么一起提交要么一起回滚，不存在"业务写成功但幂等记录没落盘导致重放"的窗口。`IdempotencyRecord` 还有 `UniqueConstraint(tenant_id, action, key)` 作为数据库层最后一道防线。

幂等键语义粒度是 `agent:{agent_id}:{action}`——同一个幂等键在不同 action 下是相互独立的记录。

### 4.4 平台 API

`create_platform_router(registry)`（`api/platform.py:29-64`），前缀 `/platform/v1`：

- `GET /agents` → manifest 列表
- `GET /agents/{agent_id}` → manifest + `actions: [action.to_dict()...]`（MCP 服务器发现动作 schema 的唯一数据源）
- `POST /agents/{agent_id}/actions/{action_name}` → 调用入口

请求体只有 `payload: dict[str, Any]`（`ConfigDict(extra="forbid")`）。两个受控 Header：

```python
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
RequestId = Annotated[str | None, Header(alias="X-Request-Id", max_length=200)]
```

`Idempotency-Key` 是否*必需*由 `registry.invoke()` 依据 `action.requires_idempotency_key` 动态决定，路由层只校验长度。`X-Request-Id` 未提供时服务端 `uuid.uuid4()` 兜底生成并原样写回响应体，配合审计日志形成端到端可追踪链路。

平台的 5 个语义异常在 `app.py` 被统一映射为 HTTP 状态码：`AgentNotFoundError`/`ActionNotFoundError`→404，`InvalidInvocationError`/`DuplicateAgentError`→422，`AuthorizationError`→403。

### 4.5 entry-point 插件发现

`core/discovery.py`：`ENTRY_POINT_GROUP = "agent_hub.agents"`，`discover_agents()` 用标准库 `importlib.metadata.entry_points().select(group=...)` 枚举已安装包里声明该分组的 entry point，逐个 `load()`。加载出来的对象可以是 `Agent` 实例或无参工厂函数。docstring 明确警告：加载插件会执行第三方代码，生产环境应传 allowlist，并在隔离 worker 中运行不受信任的 Agent。

`create_app()` 默认 `load_plugins=False`——生产部署默认关闭第三方插件发现。`pyproject.toml` 里没有任何 `[project.entry-points."agent_hub.agents"]` 声明，说明这套机制目前是"已实现但尚未被真实插件使用"的扩展点，为未来多 Agent 业务线接入预留。

### 4.6 `global-part-time` 的 7 个动作

| 动作 | mode | risk_level | 需幂等键 | allowed_roles | 必填字段 |
|---|---|---|---|---|---|
| `list_sources` | read | low | 否 | OPERATOR/ADMIN | — |
| `sync_source` | write | medium | 是 | OPERATOR/ADMIN | `source_id`, `jobs` |
| `validate_job` | read | low | 否 | 全角色（默认） | `job_id` |
| `find_matches` | write | low | 是 | 全角色（默认） | `candidate_id` |
| `draft_digest` | write | medium | 是 | OPERATOR/ADMIN | `candidate_id`, `match_ids` |
| `request_approval` | write | high | 是 | OPERATOR/ADMIN | `action`, `target_id` |
| `send_digest` | write | high | 是 | OPERATOR/ADMIN | `notification_id` |

`validate_job`/`find_matches` 两处保留默认角色是有意的：`validate_job` 镜像未加限制的只读职位查询路由；`find_matches` 允许 USER 为**自己**的 candidate 跑匹配，真正的越权防护下放到 `AgentService.run_matches()` 内部的 owner 检查（OPERATOR/ADMIN 可绕过），而不是在角色层一刀切拒绝 USER。

**`send_digest` 是唯一强制人在回路的点**：`draft_digest`（`preview_digest()`）生成的通知草稿状态固定为 `pending_approval`；把它推进到 `approved` 的 `review_notification()` **没有被注册为任何 Agent 动作**，只能通过 REST 兼容层 `POST /notifications/{id}/review` 调用（要求 OPERATOR/ADMIN）——这条审批路径完全绕开 Agent Hub 统一调用入口，模型/Agent 侧无法自我批准自己的动作。`send_digest` 真正发送前会重新校验 `status == "approved"`，未审批直接调用会被 `PolicyError` 拦截（→409），并且重新校验候选人的授权状态/频控，防止"审批通过之后、发送之前"状态变化（TOCTOU 防护）。

### 4.7 MCP Server

模块 docstring 原文："本模块是平台 API 的瘦客户端，不复制任何治理逻辑——白名单、参数校验、风险分级、审批与审计全部仍由平台层执行。"

**动态发现**：启动时调 `list_agent_ids()` → `describe_agent(agent_id)`，拿到的 manifest+actions 直接喂给 `build_tool_specs()`。新 Agent 注册到平台后，MCP 工具清单无需改代码即可跟进。

**只读默认怎么强制**：`build_tool_specs(agents, *, expose_write=False)` 遍历时过滤：

```python
mode = action.get("mode", "read")
if mode == "write" and not expose_write:
    continue
```

`expose_write` 来自环境变量 `MCP_EXPOSE_WRITE`（默认关闭）。"只读默认"不是协议层拦截，而是**根本不把 write 动作放进 `list_tools()` 返回的清单里**——模型连工具名都看不到。即便打开 `MCP_EXPOSE_WRITE=1`，`send_digest` 这类 high risk 动作仍要过平台侧 `status=="approved"` 检查——MCP 层完全不做也无法绕过这层业务闸门。

**自动幂等键**：只要 `requires_idempotency_key` 为真，每次工具调用都生成新的 `uuid4()`：

```python
idempotency_key = str(uuid.uuid4()) if spec.requires_idempotency_key else None
result = await asyncio.to_thread(client.invoke, spec.agent_id, spec.action, arguments or {}, idempotency_key)
```

代码注释解释设计取舍："每次调用生成新幂等键：MCP 客户端的一次工具调用就是一次业务意图，传输层重试由平台幂等记录去重"——MCP 层不做应用层重试去重，信任底层传输层的偶发重试落到平台侧的 advisory lock + 唯一约束上被吸收。

`docs/mcp-server.md` 记录了一次端到端实测：默认只读模式暴露 2 个工具（`list_sources`、`validate_job`），`MCP_EXPOSE_WRITE=1` 后补齐到 7 个（全部 action）。

### 4.8 审计日志

`AuditLog`（`models.py:480-497`）：`event`/`kind`/`entity_id`/`actor`/`details`(JSONB)/`created_at`，索引 `(kind, entity_id)` 和 `created_at`。写入统一走 `RootRepository._audit()`，与业务写入、幂等记录在同一事务里提交——不存在"业务成功但审计漏记"的情况。`_audit()` 本身不知道调用方是走平台统一入口还是 REST 兼容层——两条入口最终都汇聚到同一个 `AgentService` 方法，审计完整性不依赖调用方式。

---

## 5. Celery 异步流水线

### 5.1 任务链拓扑

`worker/tasks.py` 定义的任务共享 `_run_task` 执行助手。**没有** `celery.chain()`/`chord()`——链式调用靠任务成功路径里显式 `.delay()`（信号式扇出，非声明式链）：

- `sync_source_task`/`fetch_and_sync_source_task` 导入成功后，若产生了 `job_ids` 且仓储支持向量，自行入队 `embed_jobs_task.delay(job_ids, actor)`。
- `embed_jobs_task` 批量生成 embedding，批大小 `EMBED_BATCH_SIZE = 64`。
- `run_matches_task`/`notification_pipeline_task`（只跑 `preview_digest`，**实际发送需人工审批**，返回 `awaiting_approval`）/`send_notification_task` 是独立触发的，不是从 embedding 自动链下来。
- `periodic_sync_all_task` 是 Celery beat 入口：遍历所有 `approved`+`enabled` 且有注册 fetcher 的数据源，逐个 `.delay()`。

真实流水线：**beat → fetch_and_sync_source_task → (内部去重/upsert) → embed_jobs_task(批64) → [独立触发] run_matches_task → notification_pipeline_task(仅预览) → [人工审批] → send_notification_task**。

### 5.2 错误分类器

`worker/errors.py`。两个基类 `RetryableError`/`PermanentError`，带具名子类型：

- Retryable：`SourceTimeoutError`、`RateLimitError`、`EmailServiceTemporaryError`、`TransientDatabaseError`
- Permanent：`SourceUnauthorizedError`、`InputSchemaError`、`CandidateUnsubscribedError`、`HighRiskFlaggedError`

```python
def classify(exc):
    if isinstance(exc, PermanentError): return ClassifiedError(..., "permanent", ...)
    if isinstance(exc, RetryableError): return ClassifiedError(..., "retryable", ...)
    domain_permanent = _domain_permanent_types()   # 懒加载 NotFoundError, PolicyError
    if domain_permanent and isinstance(exc, domain_permanent): return ClassifiedError(..., "permanent", ...)
    if isinstance(exc, _PERMANENT_BUILTINS): return ClassifiedError(..., "permanent", ...)   # ValueError, TypeError
    if isinstance(exc, _RETRYABLE_BUILTINS): return ClassifiedError(..., "retryable", ...)   # ConnectionError, TimeoutError, OSError
    return ClassifiedError(..., "retryable", ...)  # 未知类型 → 默认重试，MAX_RETRIES 兜底
```

`NotFoundError`/`PolicyError` 懒加载导入避免循环依赖，归为 permanent。**未知异常默认归为可重试**是刻意设计——`MAX_RETRIES` 是安全网，宁可多试一次也不要误判一个未识别的瞬时错误为永久失败。

### 5.3 指数退避

```python
MAX_RETRIES = 5
BACKOFF_BASE = 30  # 30, 60, 120, 240, 480 秒
```

```python
if retry_count < MAX_RETRIES:
    countdown = BACKOFF_BASE * (2 ** retry_count)
    raise task.retry(exc=exc, countdown=countdown, max_retries=MAX_RETRIES,
                      kwargs={**task.request.kwargs, "workflow_run_id": workflow_run_id})
else:
    tracker.mark_manual_review(workflow_run_id)
    raise
```

`workflow_run_id` 被穿透进重试的 kwargs，让重试复用同一个 `WorkflowRun` 行而不是新建。每次重试尝试都带幂等键（`sha256(workflow_run_id + step_name)`）。**永久错误不重试**——`tracker.fail_run()` 后立即重新抛出。重试耗尽后标记 `manual_review`（不是 `failed`）。

### 5.4 `workflow_runs`/`workflow_steps` schema

`WorkflowRun`：`id`/`tenant_id`（默认 `"default"`）/`workflow_type`/`target_id`/`status`（pending→running→completed/failed/manual_review）/`actor`/`celery_task_id`/`payload`(JSONB)，索引 `status`、`celery_task_id`。

`WorkflowStep`：`id`/`workflow_run_id`(FK)/`step_name`/`status`/`retry_count`(int)/`error_class`(String20,截断)/`error_detail`(Text,截断2000字符)/`payload`(JSONB)。

`WorkflowTracker` 拥有**独立的 `sessionmaker`**，不复用仓储的 `_active_session` context var——步骤失败记录即使在业务事务回滚时也能存活（docstring 明确写了这个设计理由）。

### 5.5 职位源 fetcher

`fetchers/` 目录恰好 7 个模块：`arbeitnow`/`himalayas`/`jobicy`/`remoteok`/`remotive`/`weworkremotely`/`workingnomads`，按域名匹配注册。共享工具（`fetchers/__init__.py`）：

- `_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())`，`certifi` 缺失时优雅降级为 `None` 而非崩溃全部 fetcher。
- `strip_html()`（纯文本抽取）和 `sanitize_html()`（基于允许列表的 `_HtmlSanitizer`，只保留固定结构标签，剥离 `script/style/iframe/object/embed/form`，强制给所有 `<a>` 注入 `rel="noopener noreferrer" target="_blank"`）。
- 一套手写的 `_COUNTRY_ALIASES`/`_CITY_TO_COUNTRY`/`_REGION_KEYWORDS` 查表和 `normalize_countries()`，把各数据源不同格式的地点字符串归一化成 ISO 3166-1 alpha-2 代码，无法匹配时 fallback 到 `"GLOBAL"`（"remote 职位给个善意假设"）。

### 5.6 LLM 可观测性（Langfuse）

一条 chat 轮次对应一个 `chat-turn` 根 span，子 span 是 `llm-round-N`（model/输入消息/输出/token 用量）和 `tool:<name>`（参数、输出截断到 2000 字符）。

三层降级，每层都退化到全部方法都是空操作的 `NoopTracer`/`NoopTurn`/`NoopHandle`：

1. **未配置 key**：`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` 未设置直接返回 `NoopTracer()`，零开销，甚至不 import `langfuse` 包。
2. **SDK 缺失或 client 初始化失败**：`try/except Exception` 包裹 `Langfuse(...)` 构造，失败则 `logger.warning` 后退回 `NoopTracer()`。
3. **单次调用失败**：每个 `generation()`/`tool()`/`end()` 方法各自 `try/except Exception: logger.warning(...)`——Langfuse 侧中途故障降级为记日志，从不打断对话响应。

Tracer 是进程级单例，`reset_tracer()` 仅供测试隔离使用。

---

## 6. 多租户 RBAC 与资源归属

### 6.1 `IdentityMiddleware` 分发逻辑

`Role` 是 3 值 `str, Enum`：`ADMIN`、`OPERATOR`、`USER`。`Principal` 是 frozen dataclass：`actor_id`/`tenant_id`/`roles: frozenset[Role]`/`trusted: bool`。

`IdentityMiddleware.dispatch` 对 `/health`/`/live`/`/ready`/`/docs`/`/openapi.json`/`/redoc` 直接放行，其余按 `self.mode` 分支：

```python
actor = request.headers.get("X-Actor")
tenant_id = request.headers.get("X-Tenant-Id")
roles = request.headers.get("X-Roles")

if self.mode == "development":
    if not actor: return self._unauthorized()
    parsed_roles = parse_roles(roles) if roles is not None else self.development_default_roles
    request.state.principal = Principal(actor, tenant_id or "default", parsed_roles, trusted=False)
    return await call_next(request)

token = request.headers.get("X-Gateway-Token")
if not all((actor, tenant_id, roles, token)) or not hmac.compare_digest(token or "", self.gateway_secret or ""):
    return self._unauthorized()
request.state.principal = Principal(actor, tenant_id, parse_roles(roles), trusted=True)
return await call_next(request)
```

`get_principal(request)` 读 `request.state.principal`，中间件从未设置过则抛 `HTTPException(401)`。

### 6.2 网关信任：两种模式

`SecuritySettings.from_env()` 读 `SECURITY_MODE`（默认 `development`），`trusted_gateway` 模式下若缺 `TRUSTED_GATEWAY_SECRET` 直接 `RuntimeError`——**在启动时 fail closed，而不是等到请求时才发现配置缺失**。

- **`development` 模式**：只要求 `X-Actor`；`X-Tenant-Id` 默认 `"default"`；`X-Roles` 缺省取 `DEVELOPMENT_DEFAULT_ROLES`（默认三个角色全给）。`trusted=False`。无 token 校验——任何调用方可声称任意 actor/角色。
- **`trusted_gateway` 模式**：四个头全部必需，`X-Gateway-Token` 用 `hmac.compare_digest` 做**常数时间比较**（防时序攻击）校验共享密钥——是"共享密钥 bearer token 常数时间比较"，不是对整个请求做 HMAC 签名。`trusted=True`。用于已认证终端用户身份、通过 Header 断言身份的上游网关。

### 6.3 `require_roles` 依赖

```python
def require_roles(*allowed: Role):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.roles.intersection(allowed):
            raise HTTPException(status_code=403, detail="insufficient role")
        return principal
    return Depends(dependency)
```

用作路由参数默认值，贯穿 `http_api.py`：数据源管理、批量候选人视图、通知列表用 `require_roles(OPERATOR, ADMIN)`；个人候选人路由（获取/更新/授权/删除/匹配）和聊天路由用 `require_roles(USER, ADMIN)`；审计/工作流管理路由单独用 `require_roles(ADMIN)`。

### 6.4 归属校验实例

`AgentService._check_candidate_owner`（`service.py:111-136`）：

```python
_OWNER_CHECK_BYPASS_ROLES = frozenset({Role.ADMIN, Role.OPERATOR})

def _check_candidate_owner(self, candidate):
    if self.principal is None or self.principal.roles & self._OWNER_CHECK_BYPASS_ROLES:
        return
    owner = candidate.get("owner_actor_id")
    if owner is not None and owner != self.principal.actor_id:
        raise NotFoundError(f"candidate {candidate.get('id')} not found")
```

跨所有者访问抛 `NotFoundError`→404（不是 403），**刻意不向非所有者确认该候选人 ID 是否存在**。`ChatService._owned_session` 同样的 404-not-403 模式，向后兼容旧行 `session.get("owner_actor_id", session.get("actor"))`。

`get_tenant_repository`（commit `1bc04ff` 新增）为每个请求构建按租户过滤的仓储：`repository.for_tenant(principal.tenant_id)`；`get_service`/`get_chat_service` 构建**请求级**的 `AgentService`/`ChatService`，携带该请求的 `principal`——替代此前所有请求共用一个不携带身份信息的应用级单例。

### 6.5 漏洞发现与修复：commit `1bc04ff` → `de8bd8f`

**`1bc04ff`（初始 RBAC 上线）之前的状态**：`/api/v1` 路由共用一个固定的 `app.state.part_time_service`/`chat_service` 单例，完全没有 `Principal` 概念——无租户隔离、无角色门禁、无归属校验，任何带任意 actor id 的调用方都能读写任意租户/任意用户的候选人和聊天会话。`1bc04ff` 把 `Principal` 接入每条路由（新增 `get_service`/`get_chat_service`/`get_tenant_repository` 依赖），按敏感度加了 `require_roles(...)` 门禁，并加了上面的 `_owned_candidate`/`_owned_session` 404 校验。

**`1bc04ff` 留下的缺口，由 `de8bd8f` 补上**：`1bc04ff` 的修复只作用于 **REST 路由层**（`http_api.py`）和两个具体的 service 方法，但平台的*通用* Agent Action API——`POST /platform/v1/agents/{agent_id}/actions/{name}`——通过完全独立的路径调用同一套业务逻辑：`GlobalPartTimeAgent.invoke()` → `registry.invoke()`，后者只检查 `ActionDefinition.allowed_roles`。由于 `ActionDefinition` 默认放开全部角色，而 `GlobalPartTimeAgent` 的多个 `ActionDefinition` 从未被显式设过 `allowed_roles`，**平台动作端点悄悄绕过了 `1bc04ff` 刚建好的整套 OPERATOR/ADMIN 路由矩阵**——一个 USER 角色的调用方可以直接命中 `POST /platform/v1/agents/global-part-time/actions/sync_source`，触达 REST 路由本应限制为 OPERATOR/ADMIN 的同一个 `service.sync_source()`。

雪上加霜的是：`run_matches()`/`preview_digest()` 在 `de8bd8f` 之前**完全没有 owner 检查**（不同于其他"个人候选人"方法）——即便通过 REST 层（`find_matches`/`draft_digest` 平台动作故意保留角色不受限，镜像 USER 对自己 `find_matches` 的正常用法），一个 USER 角色的调用方也能传入**任意 `candidate_id`**，对别人的候选人跑匹配或起草通知摘要——无论是通过 Platform Action API 还是通过聊天的 LLM 工具调用（同样走 `AgentService`）。

同一个 commit 里还有第三个更隐蔽的 bug：旧版 `_check_candidate_owner` 用哨兵值兜底：`candidate.get("owner_actor_id", "legacy-owner")`，本意是处理没有记录 owner 的候选人；但 `"legacy-owner"` 不可能等于任何真实 `actor_id`，导致任何通过无 `Principal` 路径创建的候选人（例如 Celery 简历上传任务，构造 `AgentService` 时不带 `Principal`）**永久锁死了它自己合法所有者的访问权**——只有 ADMIN 能碰。

**修复内容**：① 给 `sync_source`/`draft_digest`/`request_approval`/`send_digest`/`list_sources` 显式加 `allowed_roles=_OPS_ROLES`，与 `http_api.py` 的矩阵完全对齐，同时刻意保留 `find_matches`/`validate_job` 不受限（对应 REST 路由本身也不受限），因为它们现在靠 owner 检查保护而非角色层一刀切；② 在 `run_matches`/`preview_digest` 顶部加 `_owned_candidate(candidate_id)` 调用，新增 `_OWNER_CHECK_BYPASS_ROLES` 让 OPERATOR 触发的批量操作仍能工作；③ 把无法匹配的哨兵值换成 `owner is not None and owner != principal.actor_id`（未认领的候选人视为"任何已认证 principal 均可通过"，而非"被一个打不着的哨兵值占有"）；④ 加了公开的 `ChatService.assert_session_owned()` 包装，路由代码不再直接伸手进私有 `_owned_session`；⑤ 在旧的无租户单例上加警告注释，告诫未来的开发者永远不要给新路由接这两个单例。测试覆盖在 `tests/test_chat_ownership.py` 的 `MatchFeedbackOwnershipTest` 里端到端驱动了整个 owner/role 矩阵（owner 成功、跨用户 404、OPERATOR 在个人路由上 403、ADMIN 处处成功）。

**面试讲法**：这是一个"通过代码评审发现真实安全 bug，而非靠测试跑出来"的好故事。核心机制是：一个平台通过两个独立入口（REST 路由和通用 Agent Action API）暴露同一个业务能力，安全控制被正确加到了一个入口却没有传播到另一个入口——因为这两条路径只共享 service 层，不共享授权层。可推广的经验：授权检查应该尽量下沉到离被保护资源最近的地方（service 方法内部），而不是只依赖路由/边缘层这一道防线。

---

## 7. 数据库 Schema 与部署架构

### 7.1 核心表

`database/models.py`（560 行）几乎每张聚合根表都保留 `payload: JSONB` 做向后兼容响应体，同时把需要约束/索引的字段单独提出为强类型列。所有主键 `String(36)`（UUID 字符串）。

**`jobs`**：`tenant_id`、`source_id`、`dedup_key`、`title_original`、`company_name`、`status`(默认active)、`review_status`(默认not_required)、`risk_level`(默认low)、`risk_score`(Float)、`embedding: Vector(1024)`、`payload: JSONB`。唯一约束 `(tenant_id, dedup_key)`，索引 `status`、`source_id`。

**`candidates`**：`tenant_id`、`owner_actor_id`(默认`"legacy-owner"`，租户/RBAC 迁移遗留字段)、`country`、`timezone`、`email`、`consent_status`(默认not_requested) + `payload`。索引 `consent_status`。

**`matches`**：`candidate_id`(FK)、`job_id`(FK)、`score`(Float)、`hard_filter_passed`(Boolean)、`payload`(JSONB)。唯一约束 `(tenant_id, candidate_id, job_id)`。检索证据和分维度分数拆到两张关联表（**建而未被写入**，见开篇落差 4）：`match_evidence`（`match_id`+`category`+`detail`+`payload`）、`match_score_items`（`match_id`+`dimension`+`weight`+`raw_score`+`weighted_score`）。

**技能图谱镜像表**（**建而未使用**，见开篇落差 5）：`skills`/`skill_aliases`/`skill_relations`/`job_skills`/`candidate_skills`。

**审计与幂等**：`audit_logs`（`event`/`kind`/`entity_id`/`actor`/`details`JSONB，复合索引 `(kind, entity_id)` + `created_at`）；`idempotency_records`（`action`/`key`/`response`JSONB，唯一约束 `(tenant_id, action, key)`）。

**工作流**：`workflow_runs`（`workflow_type`/`target_id`/`status`/`actor`/`celery_task_id`/`payload`）、`workflow_steps`（`workflow_run_id`FK/`step_name`/`status`/`retry_count`/`error_class`/`error_detail`）、`workflow_commands`+`workflow_command_payloads`（命令级幂等，`idempotency_key`+`request_hash`+`(tenant_id, action, idempotency_key)`唯一约束，`payload`拆到独立表带`expires_at`TTL设计）。

其余：`job_sources`/`source_sync_runs`/`raw_jobs`（三个唯一约束防重复：`(source_id, source_job_id)`、`canonical_url`、`content_fingerprint`）、`job_versions`、`candidate_experiences`、`approvals`、`notifications`、`feedback`、`chat_sessions`/`chat_messages`（含 `tool_calls`JSONB、`attachment`JSONB）。

### 7.2 Alembic 迁移时间线

| 文件 | 摘要 |
|---|---|
| `20260717_0001_postgresql_foundation.py`（495行） | 初始 schema：全部基础表，此时唯一约束均**无租户前缀** |
| `20260717_0002_workflow_retry_columns.py` | `workflow_runs`加`actor`/`celery_task_id`；`workflow_steps`加`retry_count`/`error_class`/`error_detail` |
| `20260718_0003_chat_tables.py` | 新建 `chat_sessions`/`chat_messages` |
| `20260718_0004_job_embedding.py` | pgvector 扩展 + `jobs.embedding` 向量列 + HNSW 索引 |
| `20260718_0005_chat_session_title.py` | `chat_sessions`加`title` |
| `20260718_0006_chat_message_attachment.py` | `chat_messages`加`attachment`JSONB |
| `20260719_0007_tenant_security_workflow_commands.py`（158行） | 给 11 张表加 `tenant_id`，`candidates`加`owner_actor_id`；旧的无租户唯一约束替换为 `(tenant_id,...)` 复合约束；新建 `workflow_commands`/`workflow_command_payloads`。`downgrade()`回滚前会先跑 `GROUP BY...HAVING COUNT(DISTINCT tenant_id)>1` 查询防止跨租户数据被误合并 |
| `20260719_0008_partial_hnsw_index.py`（未提交） | `ix_jobs_embedding_hnsw` 改为对 `status='active'` 的部分索引（详见第 1.2 节） |

### 7.3 `docker-compose.yml`：7 个服务

| 服务 | 镜像/构建 | 关键配置 | 依赖 |
|---|---|---|---|
| `api` | `build: .` | `DATABASE_URL`、`CELERY_BROKER_URL=redis://redis:6379/0`、`NEO4J_URI`、`EMBEDDING_BASE_URL`/`EMBEDDING_MODEL` | postgres/redis/neo4j 均 `service_healthy` |
| `frontend` | `build: ./frontend` | `AGENT_HUB_API_URL=http://host.docker.internal:8000` | api（顺序依赖） |
| `worker` | `build: .` | 同 api 子集 + `SYNC_INTERVAL_HOURS=1` | postgres/redis `service_healthy` |
| `beat` | `build: .` | `CELERY_BROKER_URL`、`SYNC_INTERVAL_HOURS` | redis `service_healthy` |
| `postgres` | `pgvector/pgvector:pg16` | `POSTGRES_DB=agent_hub` | — |
| `redis` | `redis:7` | — | — |
| `neo4j` | `neo4j:5` | `NEO4J_AUTH=neo4j/agent_hub` | — |

`postgres` healthcheck：`pg_isready -U agent_hub`，`interval 3s / timeout 3s / retries 10`。`api` healthcheck：`python -c "urllib.request.urlopen('http://localhost:8000/health')"`，`interval 5s / retries 10`。命名卷 `pg_data`/`redis_data`/`neo4j_data` 均绑定 `127.0.0.1`（不暴露到局域网）。`api`/`worker`/`beat` 用 bind mount 挂源码，配合 `uvicorn --reload` 热重载。

### 7.4 启动自动迁移

Alembic 不在 FastAPI 代码里调用，而是在容器 `CMD` 里：

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && uvicorn agent_hub.app:app --host 0.0.0.0 --reload --reload-dir src"]
```

`&&` 短路——迁移失败容器直接退出，FastAPI 进程根本不会启动。

### 7.5 组合根模式

`create_app()`（`app.py:38-327`）是唯一的依赖装配入口："依赖组装只发生在 composition root，具体 Agent 不需要知道其他 Agent 的存在，测试也可以传入内存仓储"。三个可选依赖都是函数端口（function-based port）：

**Neo4j/`expand_fn`**：只有设了 `NEO4J_URI` 才尝试连接；连接或 seed 失败捕获异常、关闭驱动、`expand_fn`留`None`，应用仍正常启动。

**Embedding/`embed_fn`**：默认开启（`EMBEDDING_ENABLED`默认`"true"`），导入失败同样静默降级为`None`。

**Celery**：只有设了 `CELERY_BROKER_URL` 才导入 `celery_app`，否则相关路由运行时返回 503。

两个函数端口同时传给"legacy 单例"`AgentService`和实际注册到 registry 的 Agent 实例，但源码注释强调这两个单例**不**用于处理 HTTP 请求——`http_api.py`每个路由都通过`Depends(get_service)`基于调用方`Principal`现造一个 request-scoped `AgentService`，单例只留给 worker 里的旧调用点和少数测试。

**测试替换依赖**：`RepositoryProtocol` 是 `typing.Protocol`，`create_app(repository=...)` 接受任意满足协议的对象；测试用 `InMemoryRepository` 代替 `PostgresRepository`；`expand_fn`/`embed_fn` 用 `unittest.mock.patch` 或直接传 lambda 替换，完全绕开真实 Neo4j/SiliconFlow 网络调用。

### 7.6 前端部署：Cloudflare Workers

不是裸 `wrangler.toml`，而是通过 `vinext`（Next-on-Workers 适配框架）+ `@cloudflare/vite-plugin`。`vite.config.ts` 声明 `main: "./worker/index.ts"`、`compatibility_flags: ["nodejs_compat"]`，可选 D1/R2 绑定（当前均为 `null`）。`frontend/worker/index.ts` 是 Worker fetch 入口，处理图片优化路径后其余请求转给 `vinext` 的 app-router handler。`frontend/db/schema.ts` 目前是空的（Drizzle/D1 是模板脚手架预留，当前项目未真正使用前端数据库层）。

**BFF 层**（`frontend/app/api/`）：Next.js Route Handler 反向代理到 FastAPI 后端，10 秒超时，后端不可用返回 503（不让异常冒泡到客户端）。`AGENT_HUB_API_URL` 在 compose 里是 `http://host.docker.internal:8000`，本地开发默认 `http://127.0.0.1:8000`。浏览器只跟 Next.js/Worker 通信，不直接跨域打后端。

---

## 证据索引

| 主张 | 代码位置 |
|---|---|
| Embedding 生成/批处理 | `agent_hub/agents/global_part_time/embedding.py`；批大小 `worker/tasks.py:413` |
| pgvector 召回 | `database/repository.py:699-712`（`_search_jobs_by_embedding`）；`service.py:29`（`RECALL_LIMIT`） |
| HNSW 索引演进 | `alembic/versions/20260718_0004_job_embedding.py`、`20260719_0008_partial_hnsw_index.py` |
| 硬过滤 | `agents/global_part_time/domain.py:165-202`（`hard_filter`） |
| 加权打分/完备度机制 | `domain.py:19-28`（`SCORE_WEIGHTS`）、`domain.py:279-345`（`score_match`） |
| 语义分映射/技能折扣 | `domain.py:228-248`（`_semantic_score`）、`domain.py:251-276`（`_skill_score`） |
| 召回评测 | `docs/recall-eval-report.md` + `scripts/eval_recall.py` |
| 技能图谱 Cypher | `agent_hub/skill_graph/service.py`（`resolve`/`expand`/`seed`） |
| 图谱熔断降级 | `service.py:321`（`expand_skills`闭包）、`service.py:424-452`（全批次重算） |
| 图谱种子数据 | `agent_hub/skill_graph/seed.py` |
| LLM 循环骨架 | `chat_service.py:391-634`（`stream_response`） |
| 工具白名单 | `chat_tools.py:24-148`（`TOOL_DEFINITIONS`）、`151-276`（`execute_tool`） |
| SSE 流式响应 | `http_api.py:866-877`（`_sse_response`） |
| Redis Streams 续传 | `stream_hub.py`（`publish`/`replay_and_follow`） |
| 历史清洗 | `chat_service.py:318-358`（`_sanitize_history`） |
| 简历解析流水线 | `chat_service.py:209-290`（`run_analysis`）、`resume_parser.py` |
| Agent 工具选择评测 | `scripts/eval_agent_tools.py` + `docs/agent-tool-eval-report.md` |
| Agent 契约 | `core/contracts.py`（`ActionDefinition`/`RiskLevel`/`Agent` Protocol） |
| 注册表调度 | `core/registry.py:74-89`（`invoke`） |
| 幂等实现 | `database/repository.py:620-687`（`_idempotent`） |
| 平台 API | `api/platform.py` |
| MCP Server | `agent_hub/mcp_server.py` + `docs/mcp-server.md` |
| Agent 7 个动作声明 | `agents/global_part_time/agent.py` |
| Celery 错误分类/重试 | `worker/errors.py`（`classify`）、`worker/tasks.py`（`_run_task`） |
| workflow 追踪 | `worker/workflow.py`（`WorkflowTracker`） |
| 职位源 fetcher | `agents/global_part_time/fetchers/` |
| LLM 可观测性 | `agent_hub/observability.py` + `docs/observability.md` |
| RBAC 中间件 | `core/security.py`（`IdentityMiddleware`/`Principal`/`require_roles`） |
| 归属校验 | `service.py:111-136`（`_check_candidate_owner`）、`chat_service.py:79-95`（`_owned_session`） |
| RBAC 漏洞修复 | commit `1bc04ff`、`de8bd8f`；测试 `tests/test_chat_ownership.py` |
| 数据库模型 | `database/models.py` |
| 组合根 | `app.py:38-327`（`create_app`） |
| 部署 | `docker-compose.yml`、`Dockerfile` |
| 前端 Cloudflare 部署 | `frontend/vite.config.ts`、`frontend/worker/index.ts` |
