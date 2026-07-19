# 设计：pgvector 向量召回 + SiliconFlow embedding + 统一 compose

日期：2026-07-18
状态：已确认

## 背景与目标

当前"混合推荐引擎"的语义层与描述不符：

1. embedding 调用指向 DeepSeek（无 embedding 端点），一直静默失败并降级为固定分 0.5——语义评分从未真正生效。
2. 语义相似度在 Python 内存中对规则过滤后的职位逐个计算，是"重排序"而非"向量检索召回"，数据库中没有任何向量列。
3. 根目录 `docker-compose.yml` 只有 backend + frontend（SQLite），完整服务栈在 `compose.dev.yaml`，且 postgres 镜像不带 pgvector 扩展。

目标：实现真实的 pgvector 向量召回、接入可用的 embedding 服务（SiliconFlow BGE-M3）、合并 compose 为一份可一键启动的全栈配置，并把检索证据落库。

## 决策记录

| 决策点 | 结论 |
|---|---|
| embedding 服务 | SiliconFlow，模型 `BAAI/bge-m3`（1024 维），OpenAI 兼容接口 |
| 召回架构 | 方案 A：向量召回前置（top-K 召回 → 规则精筛 → 打分） |
| SQLite / 无 key 环境 | 自动降级为现有全量扫描 + semantic=0.5，行为不变 |
| compose | 合并为一份 `docker-compose.yml` 全套服务，删除 `compose.dev.yaml` |
| postgres 镜像 | `pgvector/pgvector:pg16`（dev 数据卷可丢弃重建） |

## 数据流（匹配主链路）

```
run_matches(candidate_id)
  │ build_candidate_text → SiliconFlow BGE-M3（1 次 API 调用）
  ▼
Postgres: SELECT ..., 1 - (embedding <=> :vec) AS similarity
          FROM jobs WHERE status='active' AND embedding IS NOT NULL
          ORDER BY embedding <=> :vec LIMIT 200        ← 向量召回
  ▼
Python: hard_filter 硬性规则精筛（地区/时区/薪资/语言/工时，逻辑不变）
  ▼
score_match：semantic 分 = 召回带回的 similarity（沿用现有 [0.3, 0.9] → [0, 1] 线性映射）
  ▼
match 落库，payload 新增检索证据：
  "retrieval": {"method": "pgvector", "similarity": 0.83, "rank": 5, "recall_size": 200}
```

降级路径（满足任一条件即触发：仓储无向量能力 / 无 API key / 候选人向量生成失败 / 召回结果为空）：
`repo.list("job")` 全量扫描 + semantic=0.5，`retrieval.method = "full_scan"`，与现状行为一致。

## 组件改动

### embedding.py（重写）

- 改用项目已有的 `openai` SDK，指向 SiliconFlow。
- 环境变量：`SILICONFLOW_API_KEY`、`EMBEDDING_BASE_URL`（默认 `https://api.siliconflow.cn/v1`）、`EMBEDDING_MODEL`（默认 `BAAI/bge-m3`）。
- 新增 `get_embeddings(texts: list[str]) -> list[list[float] | None]` 批量接口。
- 保留 `get_embedding`、`build_candidate_text`、`build_job_text`、`cosine_similarity` 签名不变。
- 失败一律返回 `None` 并记 warning（沿用现有约定），调用方负责降级。
- 顺带消除 prod 代码对 dev-only `httpx` 的直接依赖。

### 模型与迁移

- `Job` 模型加 `embedding: Vector(1024)`（`pgvector` python 包，新增 pyproject 依赖 `pgvector>=0.3,<1`）。
- Alembic 迁移 0004：`CREATE EXTENSION IF NOT EXISTS vector` + `jobs.embedding vector(1024)` 列 + HNSW 索引（`vector_cosine_ops`）。

### PostgresRepository

- 新增 `search_jobs_by_embedding(vec: list[float], limit: int = 200) -> list[tuple[dict, float]]`：按余弦距离排序返回 (job_dict, similarity)，只含 `status='active' AND embedding IS NOT NULL`。
- 新增 `update_job_embeddings(embeddings: dict[str, list[float]]) -> int`：批量写入向量列。
- `put("job")` 不得清空已有 embedding 列（payload 更新与向量列独立）。
- `SQLiteRepository` 不实现这两个方法；service 用 `hasattr` 探测能力决定是否走向量召回。

### service.run_matches

- 召回段按上述数据流重构；打分段接口不变。
- `domain._semantic_score` 增加 `precomputed: float | None` 参数：传入时直接用该相似度做线性映射，不再调 embed_fn。
- 检索证据写入每条 match 的 payload。

### worker

- `sync_source` 任务在导入成功后追加 "embed" 步骤：对本次新增/更新的职位批量调 `get_embeddings` 并落库。失败按现有错误分类走重试，不回滚已完成的导入。
- 新增 `backfill_embeddings` Celery 任务：扫 `embedding IS NULL` 的活跃职位，分批（每批 ≤64）补齐。

### compose 合并

- `compose.dev.yaml` 的 api、worker、beat、postgres、redis、neo4j 并入 `docker-compose.yml`，加上 frontend。
- postgres 镜像换 `pgvector/pgvector:pg16`，卷名不变（本地旧卷需 `docker compose down -v` 重建，dev 数据可丢弃）。
- api / worker 透传 `SILICONFLOW_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`。
- 删除 `compose.dev.yaml`；更新 CLAUDE.md、README、docs 中的启动命令。

## 错误处理

- embedding API 任何失败 → `None` + warning → 触发降级路径；匹配功能在任何环境都不因向量层不可用而失败。
- 批量 embed：单批失败整批按 Celery 指数退避重试（复用现有错误分类器）。

## 测试

- `tests/test_embedding.py`（新增）：mock OpenAI client——批量、单条、无 key 降级、API 异常降级。
- `tests/test_domain.py`（补充）：`_semantic_score` 的 `precomputed` 路径。
- `tests/test_service.py`（补充）：仓储有向量能力时走召回并落检索证据；无能力时降级全扫描且行为与现状一致。
- `tests/test_postgres_repository.py`（补充）：向量写入、`<=>` 检索排序、`put("job")` 不清空向量列（沿用现有 `DATABASE_URL` 环境门槛模式）。

## 不做的事（YAGNI）

- 候选人向量不落库（每次 run_matches 现算一次，成本一次 API 调用）。
- 不做双路召回、不做向量列的自动失效/重算策略（职位更新时由 sync 的 embed 步骤覆盖写入）。
- 不改通知发送（simulation provider）——不在次范围。

## 已知行为变化（实现后补记）

- pgvector 召回把候选集限定为 top-200：召回窗口之外的职位不再被重新打分，早期 full_scan 生成的旧 match 行会带着旧分数与旧检索证据保留在库中。活跃职位少于 200 时召回覆盖全集、无差异；超过后如需清理可加 prune-on-run 或 TTL（暂不实现）。
