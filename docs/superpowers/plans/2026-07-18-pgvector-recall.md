# pgvector 向量召回 + SiliconFlow Embedding + 统一 Compose 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把混合推荐引擎的语义层升级为真实的 pgvector 向量召回（SiliconFlow BGE-M3 embedding），检索证据落库，并合并 compose 为一份全栈配置。

**Architecture:** `run_matches` 改为"pgvector top-K 召回 → 规则精筛 → 打分"，semantic 分复用召回相似度；职位向量由 Celery 在同步后批量生成写入 `jobs.embedding vector(1024)`。SQLite / 无 API key 环境自动降级为现有全量扫描（行为不变）。

**Tech Stack:** Python 3.10 / FastAPI / SQLAlchemy 2 / Alembic / pgvector / openai SDK（指向 SiliconFlow）/ Celery / Docker Compose。

**设计文档:** `docs/superpowers/specs/2026-07-18-pgvector-recall-design.md`

**测试约定:** 项目用 unittest（`python -m unittest discover -s tests -v`）；Postgres 相关测试用 `TEST_DATABASE_URL` 环境变量门槛（未设置自动跳过）。提交用 `git commit`（Husky 钩子会跑 lint-staged）。

---

### Task 1: 重写 embedding.py（SiliconFlow via openai SDK）

**Files:**
- Modify: `agent_hub/agents/global_part_time/embedding.py:1-53`（替换头部与 API 调用部分；`build_candidate_text`/`build_job_text`/`cosine_similarity` 保持不变）
- Test: `tests/test_embedding.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_embedding.py`：

```python
"""SiliconFlow embedding 模块单元测试（mock OpenAI client，不发真实请求）。"""

import unittest
from unittest.mock import MagicMock, patch

from agent_hub.agents.global_part_time import embedding


class _FakeItem:
    def __init__(self, vec):
        self.embedding = vec


def _fake_response(vectors):
    return MagicMock(data=[_FakeItem(v) for v in vectors])


class GetEmbeddingsTest(unittest.TestCase):
    def test_returns_none_list_without_api_key(self):
        with patch.object(embedding, "SILICONFLOW_API_KEY", ""):
            self.assertEqual(embedding.get_embeddings(["a", "b"]), [None, None])

    def test_batch_maps_vectors_and_preserves_blanks(self):
        client = MagicMock()
        client.embeddings.create.return_value = _fake_response([[0.1] * 3, [0.2] * 3])
        with (
            patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"),
            patch.object(embedding, "_get_client", return_value=client),
        ):
            result = embedding.get_embeddings(["hello", "  ", "world"])
        self.assertEqual(result, [[0.1] * 3, None, [0.2] * 3])
        client.embeddings.create.assert_called_once_with(
            model=embedding.EMBEDDING_MODEL, input=["hello", "world"]
        )

    def test_api_error_degrades_to_none(self):
        client = MagicMock()
        client.embeddings.create.side_effect = RuntimeError("boom")
        with (
            patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"),
            patch.object(embedding, "_get_client", return_value=client),
        ):
            self.assertEqual(embedding.get_embeddings(["hello"]), [None])

    def test_get_embedding_single(self):
        client = MagicMock()
        client.embeddings.create.return_value = _fake_response([[1.0, 0.0]])
        with (
            patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"),
            patch.object(embedding, "_get_client", return_value=client),
        ):
            self.assertEqual(embedding.get_embedding("hi"), [1.0, 0.0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `source .venv/bin/activate && python -m unittest tests.test_embedding -v`
Expected: FAIL/ERROR（`get_embeddings` 不存在、`SILICONFLOW_API_KEY` 属性不存在）

- [ ] **Step 3: 重写 embedding.py 头部**

把 `agent_hub/agents/global_part_time/embedding.py` 从文件头到 `cosine_similarity` 之前（即原第 1-42 行，含 `get_embedding` 旧实现和 httpx import）替换为：

```python
"""Embedding 生成与余弦相似度计算。

使用 SiliconFlow 的 OpenAI 兼容 embedding 接口（默认 BAAI/bge-m3，1024 维）
为候选人和职位生成向量表示。失败时返回 None，调用方负责降级。
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            api_key=SILICONFLOW_API_KEY, base_url=EMBEDDING_BASE_URL, timeout=15.0
        )
    return _client


def get_embeddings(texts: list[str]) -> list[list[float] | None]:
    """批量获取文本向量。空白文本对应位置返回 None；整批失败返回全 None。"""
    if not SILICONFLOW_API_KEY or not texts:
        return [None] * len(texts)
    cleaned = [t.strip()[:8000] if t and t.strip() else None for t in texts]
    payload = [t for t in cleaned if t is not None]
    if not payload:
        return [None] * len(texts)
    try:
        response = _get_client().embeddings.create(model=EMBEDDING_MODEL, input=payload)
    except Exception as exc:
        logger.warning("Embedding API call failed: %s", exc)
        return [None] * len(texts)
    vectors = iter(item.embedding for item in response.data)
    return [next(vectors) if t is not None else None for t in cleaned]


def get_embedding(text: str) -> list[float] | None:
    """获取单条文本向量。失败返回 None。"""
    return get_embeddings([text])[0]
```

`cosine_similarity`、`build_candidate_text`、`build_job_text` 三个函数原样保留在文件后半部分。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_embedding -v`
Expected: 4 个测试全 PASS

- [ ] **Step 5: 确认无 httpx 残留并跑相关回归**

Run: `grep -n httpx agent_hub/agents/global_part_time/embedding.py`（Expected: 无输出）
Run: `python -m unittest tests.test_domain tests.test_service -v`（Expected: PASS，现有降级行为不受影响）

- [ ] **Step 6: Commit**

```bash
git add agent_hub/agents/global_part_time/embedding.py tests/test_embedding.py
git commit -m "feat(embedding): switch to SiliconFlow BGE-M3 with batch API"
```

---

### Task 2: domain 支持预计算语义相似度

**Files:**
- Modify: `agent_hub/agents/global_part_time/domain.py:213-229`（`_semantic_score`）、`domain.py:259-267`（`score_match` 签名与调用）
- Test: `tests/test_domain.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_domain.py` 末尾（沿用该文件现有 import 与测试类风格）追加一个测试类：

```python
class PrecomputedSemanticScoreTest(unittest.TestCase):
    def test_precomputed_similarity_maps_to_semantic_score(self):
        candidate = candidate_payload()
        job = job_payload()
        # (0.9 - 0.3) / 0.6 = 1.0
        _total, breakdown, _reasons = score_match(candidate, job, semantic_similarity=0.9)
        self.assertEqual(breakdown["semantic"], 1.0)

    def test_precomputed_similarity_clamps_low_values(self):
        candidate = candidate_payload()
        job = job_payload()
        _total, breakdown, _reasons = score_match(candidate, job, semantic_similarity=0.1)
        self.assertEqual(breakdown["semantic"], 0.0)

    def test_without_precomputed_and_without_embed_fn_stays_neutral(self):
        candidate = candidate_payload()
        job = job_payload()
        _total, breakdown, _reasons = score_match(candidate, job)
        self.assertEqual(breakdown["semantic"], 0.5)
```

注意：`tests/factories.py` 提供 `candidate_payload`/`job_payload`；若 `test_domain.py` 尚未 import `score_match` 或 factories，按该文件现有 import 风格补上。

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_domain -v`
Expected: 新增测试 ERROR（`score_match() got an unexpected keyword argument 'semantic_similarity'`）

- [ ] **Step 3: 实现**

`domain.py` 中 `_semantic_score` 改为：

```python
def _semantic_score(
    candidate: dict[str, Any],
    job: dict[str, Any],
    embed_fn: Callable[[str], list[float] | None] | None = None,
    precomputed: float | None = None,
) -> float:
    """通过 embedding 余弦相似度计算候选人与职位的语义匹配度。

    ``precomputed`` 为向量召回阶段带回的相似度；提供时跳过实时 embedding 调用。
    """
    if precomputed is None:
        if embed_fn is None:
            return 0.5
        from .embedding import build_candidate_text, build_job_text, cosine_similarity

        cand_emb = embed_fn(build_candidate_text(candidate))
        job_emb = embed_fn(build_job_text(job))
        if cand_emb is None or job_emb is None:
            return 0.5
        precomputed = cosine_similarity(cand_emb, job_emb)
    return max(0.0, min(1.0, (precomputed - 0.3) / 0.6))  # 线性映射 [0.3, 0.9] → [0, 1]
```

`score_match` 签名加参数并传递：

```python
def score_match(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    semantic_similarity: float | None = None,
) -> tuple[float, dict[str, float], list[str]]:
```

函数体内原 `semantic = _semantic_score(candidate, job, embed_fn)` 改为：

```python
    semantic = _semantic_score(candidate, job, embed_fn, precomputed=semantic_similarity)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_domain -v`
Expected: 全 PASS（含原有测试）

- [ ] **Step 5: Commit**

```bash
git add agent_hub/agents/global_part_time/domain.py tests/test_domain.py
git commit -m "feat(domain): accept precomputed semantic similarity in score_match"
```

---

### Task 3: pgvector 依赖 + Job.embedding 列 + Alembic 迁移 0004

**Files:**
- Modify: `pyproject.toml:11-24`（dependencies）
- Modify: `agent_hub/database/models.py:108-132`（Job 模型）
- Create: `alembic/versions/20260718_0004_job_embedding.py`
- Modify: `tests/test_postgres_repository.py:22-25`、`tests/test_postgres_workflow.py`（setUp 附近）、`tests/test_postgres_concurrency.py`（setUp 附近）——create_all 前建扩展

- [ ] **Step 1: 加依赖**

`pyproject.toml` dependencies 列表中 `"openai>=1.30",` 之后插入一行：

```toml
  "pgvector>=0.3,<1",
```

Run: `pip install -e ".[dev]"`
Expected: 安装成功，含 pgvector

- [ ] **Step 2: Job 模型加 embedding 列**

`agent_hub/database/models.py` 顶部 import 区（`from sqlalchemy.dialects.postgresql import JSONB` 之后）加：

```python
from pgvector.sqlalchemy import Vector
```

`Job` 类中 `risk_score` 字段之后加：

```python
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
```

- [ ] **Step 3: 写迁移**

创建 `alembic/versions/20260718_0004_job_embedding.py`：

```python
"""Add pgvector extension, jobs.embedding column and HNSW index.

Revision ID: 20260718_0004
Revises: 20260718_0003
Create Date: 2026-07-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260718_0004"
down_revision: Union[str, None] = "20260718_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("jobs", sa.Column("embedding", Vector(1024), nullable=True))
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_embedding_hnsw "
        "ON jobs USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_embedding_hnsw")
    op.drop_column("jobs", "embedding")
```

- [ ] **Step 4: 离线校验迁移 SQL**

Run: `DATABASE_URL="postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub" alembic upgrade head --sql | grep -A1 "CREATE EXTENSION"`
Expected: 输出包含 `CREATE EXTENSION IF NOT EXISTS vector` 与 `ALTER TABLE jobs ADD COLUMN embedding VECTOR(1024)`（离线模式不连库；若 env.py 要求连接，改为在 Task 7 起 compose 后执行 `alembic upgrade head` 验证）

- [ ] **Step 5: 现有 Postgres 测试 setUp 建扩展**

三个文件（`tests/test_postgres_repository.py` 的 `create_repository`、`tests/test_postgres_workflow.py` 与 `tests/test_postgres_concurrency.py` 的 `setUp`）中，在 `Base.metadata.drop_all(...)` 之前插入：

```python
        from sqlalchemy import text

        with repo._engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
```

（`test_postgres_workflow.py`/`test_postgres_concurrency.py` 中引擎变量按各自文件实际写法，如 `self.repo.
_engine` 或 `self.repo1._engine`。）

- [ ] **Step 6: 回归**

Run: `python -m unittest tests.test_database_models tests.test_database_config -v`
Expected: PASS（models 可正常 import；SQLite 路径不受影响）

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml agent_hub/database/models.py alembic/versions/20260718_0004_job_embedding.py tests/test_postgres_repository.py tests/test_postgres_workflow.py tests/test_postgres_concurrency.py
git commit -m "feat(db): jobs.embedding vector(1024) column with pgvector migration"
```

---

### Task 4: PostgresRepository 向量方法

**Files:**
- Modify: `agent_hub/database/repository.py`（类末尾追加三个方法）
- Test: `tests/test_postgres_repository.py`（追加测试类）

- [ ] **Step 1: 写失败测试**

`tests/test_postgres_repository.py` 末尾追加：

```python
@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set")
class PostgresVectorSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        from sqlalchemy import text

        from agent_hub.database.models import Base
        from agent_hub.database.repository import PostgresRepository

        self.repo = PostgresRepository(TEST_DATABASE_URL)
        with self.repo._engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.drop_all(self.repo._engine)
        Base.metadata.create_all(self.repo._engine)

    @staticmethod
    def _job(job_id: str, title: str) -> dict:
        return {
            "id": job_id,
            "source_id": "s1",
            "dedup_key": job_id,
            "title_original": title,
            "company_name": "ACME",
            "status": "active",
        }

    def test_search_orders_by_cosine_similarity(self):
        self.repo.put("job", self._job("job-a", "Python Backend"))
        self.repo.put("job", self._job("job-b", "Frontend React"))
        near = [0.0] * 1024
        near[0] = 1.0
        far = [0.0] * 1024
        far[1] = 1.0
        query = [0.0] * 1024
        query[0], query[1] = 0.9, 0.1
        self.assertEqual(self.repo.update_job_embeddings({"job-a": near, "job-b": far}), 2)
        hits = self.repo.search_jobs_by_embedding(query, limit=10)
        self.assertEqual([job["id"] for job, _sim in hits], ["job-a", "job-b"])
        self.assertGreater(hits[0][1], hits[1][1])

    def test_search_excludes_inactive_and_unembedded_jobs(self):
        self.repo.put("job", self._job("job-a", "Active embedded"))
        inactive = self._job("job-b", "Inactive")
        inactive["status"] = "rejected"
        self.repo.put("job", inactive)
        self.repo.put("job", self._job("job-c", "No embedding"))
        vec = [0.5] * 1024
        self.repo.update_job_embeddings({"job-a": vec, "job-b": vec})
        hits = self.repo.search_jobs_by_embedding(vec, limit=10)
        self.assertEqual([job["id"] for job, _sim in hits], ["job-a"])

    def test_put_job_preserves_embedding(self):
        self.repo.put("job", self._job("job-a", "Python Backend"))
        vec = [0.5] * 1024
        self.repo.update_job_embeddings({"job-a": vec})
        self.repo.put("job", self._job("job-a", "Python Backend (updated)"))
        hits = self.repo.search_jobs_by_embedding(vec, limit=10)
        self.assertEqual(hits[0][0]["id"], "job-a")

    def test_list_jobs_missing_embedding(self):
        self.repo.put("job", self._job("job-a", "A"))
        self.repo.put("job", self._job("job-b", "B"))
        self.repo.update_job_embeddings({"job-a": [0.1] * 1024})
        self.assertEqual(self.repo.list_jobs_missing_embedding(), ["job-b"])
```

- [ ] **Step 2: 运行确认失败**

Run: `TEST_DATABASE_URL=<本地或 compose 的 PG 连接串> python -m unittest tests.test_postgres_repository.PostgresVectorSearchTest -v`
Expected: ERROR（`AttributeError: search_jobs_by_embedding`）。没有可用 PG 时该类自动 skip——此时先完成 Step 3，在 Task 7 起 compose 后回来跑通此步与 Step 4。

- [ ] **Step 3: 实现三个方法**

`agent_hub/database/repository.py` 的 `PostgresRepository` 类末尾（`idempotent` 方法之后）追加：

```python
    # ------------------------------------------------------------------
    # Vector search (pgvector)
    # ------------------------------------------------------------------

    def search_jobs_by_embedding(
        self, vec: list[float], limit: int = 200
    ) -> list[tuple[dict[str, Any], float]]:
        """按余弦相似度检索活跃且已向量化的职位，返回 (job_dict, similarity) 降序列表。"""
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            distance = Job.embedding.cosine_distance(vec)
            rows = session.execute(
                select(Job, distance.label("distance"))
                .where(Job.status == "active", Job.embedding.isnot(None))
                .order_by(distance)
                .limit(limit)
            ).all()
            return [
                (self._row_to_dict(row.Job, "job"), 1.0 - float(row.distance)) for row in rows
            ]
        finally:
            if owns_session:
                session.close()

    def update_job_embeddings(self, embeddings: dict[str, list[float]]) -> int:
        """批量写入职位向量，返回实际更新条数。"""
        session = self._session()
        owns_session = not self._is_context_session()
        updated = 0
        try:
            for job_id, vec in embeddings.items():
                if vec is None:
                    continue
                row = session.get(Job, job_id)
                if row is not None:
                    row.embedding = vec
                    updated += 1
            if owns_session:
                session.commit()
            else:
                session.flush()
            return updated
        except Exception:
            if owns_session:
                session.rollback()
            raise
        finally:
            if owns_session:
                session.close()

    def list_jobs_missing_embedding(self, limit: int = 500) -> list[str]:
        """返回缺失向量的活跃职位 id（新职位优先）。"""
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            rows = (
                session.execute(
                    select(Job.id)
                    .where(Job.status == "active", Job.embedding.is_(None))
                    .order_by(Job.created_at.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return list(rows)
        finally:
            if owns_session:
                session.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `TEST_DATABASE_URL=<PG 连接串> python -m unittest tests.test_postgres_repository -v`
Expected: 全 PASS（含原有 contract 测试）

- [ ] **Step 5: Commit**

```bash
git add agent_hub/database/repository.py tests/test_postgres_repository.py
git commit -m "feat(db): pgvector similarity search and embedding batch update"
```

---

### Task 5: service.run_matches 向量召回 + 检索证据落库

**Files:**
- Modify: `agent_hub/agents/global_part_time/service.py:15-25`（import 区）、`service.py:257-315`（run_matches 召回与落库段）
- Test: `tests/test_service.py`（追加测试类）

- [ ] **Step 1: 写失败测试**

`tests/test_service.py` 末尾追加：

```python
class FakeVectorRepo(Repository):
    """SQLite 仓储 + 假 pgvector 检索接口，用于验证召回路径。"""

    def __init__(self):
        super().__init__(":memory:")
        self.search_calls = []
        self.hits = []

    def search_jobs_by_embedding(self, vec, limit=200):
        self.search_calls.append((vec, limit))
        return self.hits


class VectorRecallTest(unittest.TestCase):
    def setUp(self):
        self.repo = FakeVectorRepo()
        self.service = AgentService(self.repo, embed_fn=lambda text: [0.1, 0.2, 0.3])
        source = self.service.create_source(source_payload(), "operator")
        self.service.review_source(source["id"], True, "operator")
        self.service.sync_source(source["id"], [job_payload()], "worker")
        self.job = self.repo.list("job")[0]
        candidate = self.service.create_candidate(candidate_payload(), "candidate")
        self.candidate = self.service.set_consent(candidate["id"], True, "candidate", "mvp-1")

    def test_pgvector_recall_records_retrieval_evidence(self):
        self.repo.hits = [(self.job, 0.9)]
        result = self.service.run_matches(self.candidate["id"], "scheduler")
        self.assertEqual(len(self.repo.search_calls), 1)
        match = result["matches"][0]
        self.assertEqual(match["retrieval"]["method"], "pgvector")
        self.assertEqual(match["retrieval"]["similarity"], 0.9)
        self.assertEqual(match["retrieval"]["rank"], 1)
        self.assertEqual(match["retrieval"]["recall_size"], 1)
        self.assertEqual(match["score_breakdown"]["semantic"], 1.0)

    def test_empty_recall_falls_back_to_full_scan(self):
        self.repo.hits = []
        result = self.service.run_matches(self.candidate["id"], "scheduler")
        match = result["matches"][0]
        self.assertEqual(match["retrieval"]["method"], "full_scan")

    def test_no_embed_fn_never_calls_vector_search(self):
        plain_service = AgentService(self.repo)
        result = plain_service.run_matches(self.candidate["id"], "scheduler")
        self.assertEqual(self.repo.search_calls, [])
        self.assertEqual(result["matches"][0]["retrieval"]["method"], "full_scan")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_service.VectorRecallTest -v`
Expected: FAIL（match 中无 `retrieval` 键；`search_calls` 为空）

- [ ] **Step 3: 实现召回段**

`service.py` import 区加（与现有 domain import 并列）：

```python
from .embedding import build_candidate_text
```

模块级常量（`RULE_VERSION` import 附近或类外顶部）：

```python
RECALL_LIMIT = 200
```

`run_matches` 中，`existing_matches`/`sent_job_ids` 两个赋值之后、原 `for job in self.repo.list("job"):` 循环之前，插入召回段并把循环来源改为 `candidate_jobs`：

```python
        # 召回阶段：优先 pgvector 向量检索；不可用或失败时降级为全量扫描。
        similarities: dict[str, float] = {}
        retrieval_meta: dict[str, dict[str, Any]] = {}
        retrieval_method = "full_scan"
        candidate_jobs: list[dict[str, Any]] | None = None
        if embed_fn is not None and hasattr(self.repo, "search_jobs_by_embedding"):
            candidate_vec = embed_fn(build_candidate_text(candidate))
            if candidate_vec is not None:
                hits = self.repo.search_jobs_by_embedding(candidate_vec, RECALL_LIMIT)
                if hits:
                    retrieval_method = "pgvector"
                    candidate_jobs = []
                    for rank, (job, similarity) in enumerate(hits, start=1):
                        candidate_jobs.append(job)
                        similarities[job["id"]] = similarity
                        retrieval_meta[job["id"]] = {
                            "method": "pgvector",
                            "similarity": round(similarity, 4),
                            "rank": rank,
                            "recall_size": len(hits),
                        }
        if candidate_jobs is None:
            candidate_jobs = self.repo.list("job")

        filtered = []
        eligible_jobs = []
        for job in candidate_jobs:
            failures = hard_filter(candidate, job, job["id"] in sent_job_ids)
            if failures:
                filtered.append({"job_id": job["id"], "reasons": failures})
                continue
            eligible_jobs.append(job)
```

打分段两处 `score_match` 调用都加 `semantic_similarity=similarities.get(job["id"])`：

```python
        scored_jobs = []
        for job in eligible_jobs:
            scored_jobs.append(
                (
                    job,
                    *score_match(
                        candidate,
                        job,
                        expand_fn,
                        embed_fn,
                        semantic_similarity=similarities.get(job["id"]),
                    ),
                )
            )
            if expansion_failed:
                break
        if expansion_failed:
            scored_jobs = [
                (
                    job,
                    *score_match(
                        candidate,
                        job,
                        embed_fn=embed_fn,
                        semantic_similarity=similarities.get(job["id"]),
                    ),
                )
                for job in eligible_jobs
            ]
```

match 字典（`"created_at": utcnow(),` 之前）加一行：

```python
                "retrieval": retrieval_meta.get(job["id"], {"method": "full_scan"}),
```

audit details 加 `"retrieval_method": retrieval_method`：

```python
            {
                "matched": len(results),
                "filtered": len(filtered),
                "rule_version": RULE_VERSION,
                "retrieval_method": retrieval_method,
            },
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_service -v`
Expected: 全 PASS（含原有测试——无向量能力的 `Repository` 走 full_scan，行为不变）

- [ ] **Step 5: Commit**

```bash
git add agent_hub/agents/global_part_time/service.py tests/test_service.py
git commit -m "feat(matching): pgvector recall stage with retrieval evidence"
```

---

### Task 6: worker 接入——embed 步骤、backfill 任务、embed_fn 装配

**Files:**
- Modify: `agent_hub/worker/tasks.py`（`_get_service_and_tracker`、`sync_source_task`、`fetch_and_sync_source_task`，末尾新增 `_embed_jobs`/`embed_jobs_task`/`backfill_embeddings_task`）
- Test: `tests/test_celery_tasks.py`（追加）

- [ ] **Step 1: 写失败测试**

`tests/test_celery_tasks.py` 末尾追加（沿用文件现有 import；另需在文件顶部 import 区加 `from agent_hub.worker.tasks import _embed_jobs`）：

```python
class EmbedJobsTest(unittest.TestCase):
    def test_skips_repo_without_vector_support(self):
        repo = SQLiteRepository(":memory:")
        result = _embed_jobs(repo, ["j1"])
        self.assertEqual(result["embedded"], 0)
        self.assertEqual(result["skipped"], "no_vector_support")

    def test_batches_and_stores_vectors(self):
        class FakeVectorRepo:
            def __init__(self):
                self.jobs = {
                    f"j{i}": {"id": f"j{i}", "title_original": f"Job {i}"} for i in range(3)
                }
                self.stored = {}

            def get(self, kind, job_id):
                return self.jobs.get(job_id)

            def update_job_embeddings(self, embeddings):
                self.stored.update(embeddings)
                return len(embeddings)

        repo = FakeVectorRepo()
        with patch(
            "agent_hub.agents.global_part_time.embedding.get_embeddings",
            side_effect=lambda texts: [[0.1, 0.2]] * len(texts),
        ):
            result = _embed_jobs(repo, list(repo.jobs))
        self.assertEqual(result["embedded"], 3)
        self.assertEqual(set(repo.stored), set(repo.jobs))

    def test_total_api_failure_raises_for_retry(self):
        class FakeVectorRepo:
            def get(self, kind, job_id):
                return {"id": job_id, "title_original": "Job"}

            def update_job_embeddings(self, embeddings):
                return len(embeddings)

        with (
            patch(
                "agent_hub.agents.global_part_time.embedding.get_embeddings",
                side_effect=lambda texts: [None] * len(texts),
            ),
            patch(
                "agent_hub.agents.global_part_time.embedding.SILICONFLOW_API_KEY", "sk-test"
            ),
        ):
            with self.assertRaises(RuntimeError):
                _embed_jobs(FakeVectorRepo(), ["j1"])
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_celery_tasks -v`
Expected: ImportError（`_embed_jobs` 不存在）

- [ ] **Step 3: 实现 _embed_jobs 与两个任务**

`agent_hub/worker/tasks.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# Embedding tasks
# ---------------------------------------------------------------------------

EMBED_BATCH_SIZE = 64


def _embed_jobs(repo: Any, job_ids: list[str]) -> dict[str, Any]:
    """为给定职位批量生成向量并落库。仓储无向量能力时直接跳过。"""
    if not hasattr(repo, "update_job_embeddings"):
        return {"requested": len(job_ids), "embedded": 0, "skipped": "no_vector_support"}
    from agent_hub.agents.global_part_time import embedding as embedding_mod

    jobs = [job for job in (repo.get("job", job_id) for job_id in job_ids) if job]
    embedded = 0
    for start in range(0, len(jobs), EMBED_BATCH_SIZE):
        batch = jobs[start : start + EMBED_BATCH_SIZE]
        vectors = embedding_mod.get_embeddings(
            [embedding_mod.build_job_text(job) for job in batch]
        )
        embeddings = {
            job["id"]: vec for job, vec in zip(batch, vectors) if vec is not None
        }
        if not embeddings and batch and embedding_mod.SILICONFLOW_API_KEY:
            # API key 已配置但整批失败 → 抛错交给错误分类器按可重试处理。
            raise RuntimeError("embedding API returned no vectors for batch")
        if embeddings:
            embedded += repo.update_job_embeddings(embeddings)
    return {"requested": len(job_ids), "embedded": embedded}


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.embed_jobs")
def embed_jobs_task(
    self,
    job_ids: list[str],
    actor: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    _service, repo, _tracker = self._get_service_and_tracker()
    return _run_task(
        self,
        workflow_type="embedding",
        step_name="embed_jobs",
        target_id=job_ids[0] if job_ids else "none",
        actor=actor,
        operation_fn=lambda: _embed_jobs(repo, job_ids),
        workflow_run_id=workflow_run_id,
        payload={"job_count": len(job_ids)},
    )


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.backfill_embeddings")
def backfill_embeddings_task(
    self,
    actor: str = "system",
    limit: int = 500,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """补齐存量活跃职位缺失的向量。"""
    _service, repo, _tracker = self._get_service_and_tracker()
    if not hasattr(repo, "list_jobs_missing_embedding"):
        return {"skipped": True, "reason": "no_vector_support"}
    job_ids = repo.list_jobs_missing_embedding(limit)
    return _run_task(
        self,
        workflow_type="embedding_backfill",
        step_name="backfill_embeddings",
        target_id="jobs",
        actor=actor,
        operation_fn=lambda: _embed_jobs(repo, job_ids),
        workflow_run_id=workflow_run_id,
        payload={"job_count": len(job_ids)},
    )
```

- [ ] **Step 4: worker 装配 embed_fn 并链接同步后 embed**

`_get_service_and_tracker`（`tasks.py:59` 附近）中 `AgentService(repo)` 改为：

```python
            from agent_hub.agents.global_part_time.embedding import get_embedding

            self.__class__._service = AgentService(repo, embed_fn=get_embedding)
```

`sync_source_task` 中 `return _run_task(...)` 改为：

```python
    result = _run_task(
        self,
        workflow_type="source_sync",
        step_name="sync_source",
        target_id=source_id,
        actor=actor,
        operation_fn=lambda: service.sync_source(source_id, jobs, actor),
        workflow_run_id=workflow_run_id,
        payload={"source_id": source_id, "job_count": len(jobs)},
    )
    job_ids = result.get("job_ids") or []
    if job_ids and hasattr(_repo, "update_job_embeddings"):
        embed_jobs_task.delay(job_ids, actor)
    return result
```

`fetch_and_sync_source_task` 同样处理：`return _run_task(...)` 改为先赋值 `result`，然后：

```python
    job_ids = result.get("job_ids") or []
    if job_ids and hasattr(repo, "update_job_embeddings"):
        embed_jobs_task.delay(job_ids, actor)
    return result
```

（注意 `sync_source_task` 中仓储变量名是 `_repo`，`fetch_and_sync_source_task` 中是 `repo`。）

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_celery_tasks -v`
Expected: 全 PASS（现有 SQLite eager 测试因 `hasattr` 门槛不触发 embed 链，行为不变）

- [ ] **Step 6: Commit**

```bash
git add agent_hub/worker/tasks.py tests/test_celery_tasks.py
git commit -m "feat(worker): embed jobs after sync and backfill task"
```

---

### Task 7: 合并 docker-compose、pgvector 镜像、环境变量、文档

**Files:**
- Modify: `docker-compose.yml`（整体重写）
- Delete: `compose.dev.yaml`
- Modify: `CLAUDE.md`、`README.md`、`docs/dev-guide.md`（compose 引用与启动命令）

- [ ] **Step 1: 重写 docker-compose.yml**

用 `compose.dev.yaml` 全部服务 + frontend 覆盖 `docker-compose.yml`，改动点：postgres 镜像换 `pgvector/pgvector:pg16`；api/worker 透传 `SILICONFLOW_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`（保留 `DEEPSEEK_API_KEY`，chat 服务仍在用）；frontend 服务沿用原 docker-compose.yml 写法，`API_BASE_URL` 指向 `http://api:8000`。完整内容：

```yaml
services:
  api:
    build: .
    ports:
      - '127.0.0.1:8000:8000'
    volumes:
      - ./src:/app/src
      - ./alembic:/app/alembic
      - ./alembic.ini:/app/alembic.ini
      - ./scripts:/app/scripts
      - ./data:/app/data
    environment:
      DATABASE_URL: postgresql+psycopg://agent_hub:agent_hub@postgres:5432/agent_hub
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/1
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: agent_hub
      PUBLIC_BASE_URL: http://localhost:8000
      DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}
      SILICONFLOW_API_KEY: ${SILICONFLOW_API_KEY:-}
      EMBEDDING_BASE_URL: ${EMBEDDING_BASE_URL:-https://api.siliconflow.cn/v1}
      EMBEDDING_MODEL: ${EMBEDDING_MODEL:-BAAI/bge-m3}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 5s
      timeout: 5s
      retries: 10

  frontend:
    build: ./frontend
    ports:
      - '3000:3000'
    depends_on:
      - api
    environment:
      - API_BASE_URL=http://api:8000
    volumes:
      - ./frontend:/app
      - /app/node_modules
      - /app/.next

  worker:
    build: .
    command: ["celery", "-A", "agent_hub.worker.celery_app:celery_app", "worker", "--loglevel=info", "--concurrency=2"]
    volumes:
      - ./src:/app/src
    environment:
      DATABASE_URL: postgresql+psycopg://agent_hub:agent_hub@postgres:5432/agent_hub
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/1
      SYNC_INTERVAL_HOURS: "1"
      DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}
      SILICONFLOW_API_KEY: ${SILICONFLOW_API_KEY:-}
      EMBEDDING_BASE_URL: ${EMBEDDING_BASE_URL:-https://api.siliconflow.cn/v1}
      EMBEDDING_MODEL: ${EMBEDDING_MODEL:-BAAI/bge-m3}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  beat:
    build: .
    command: ["celery", "-A", "agent_hub.worker.celery_app:celery_app", "beat", "--loglevel=info"]
    volumes:
      - ./src:/app/src
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/1
      SYNC_INTERVAL_HOURS: "1"
    depends_on:
      redis:
        condition: service_healthy

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: agent_hub
      POSTGRES_PASSWORD: agent_hub
      POSTGRES_DB: agent_hub
    ports:
      - '127.0.0.1:5432:5432'
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent_hub"]
      interval: 3s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7
    ports:
      - '127.0.0.1:6379:6379'
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      timeout: 3s
      retries: 10

  neo4j:
    image: neo4j:5
    environment:
      NEO4J_AUTH: neo4j/agent_hub
    ports:
      - '127.0.0.1:7687:7687'
      - '127.0.0.1:7474:7474'
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p agent_hub 'RETURN 1'"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pg_data:
  redis_data:
  neo4j_data:
```

- [ ] **Step 2: 删除 compose.dev.yaml 并更新引用**

```bash
git rm compose.dev.yaml
grep -rn "compose.dev" README.md CLAUDE.md docs/ Makefile
```

把所有 `compose.dev.yaml` / `docker compose -f compose.dev.yaml` 引用改为 `docker compose`（默认文件）。CLAUDE.md「技术栈」表中数据库一行改为 `PostgreSQL + pgvector（compose 默认），SQLite（本地裸跑 MVP）`；「开发命令」加一行 `docker compose up --build  # 全栈启动（PG+Redis+Neo4j+worker）`。

- [ ] **Step 3: 验证 compose 启动与迁移**

```bash
docker compose down -v   # 旧 postgres:16 卷与 pgvector 镜像不兼容，丢弃 dev 数据
docker compose up -d --build postgres redis
docker compose up -d api worker beat
docker compose logs api | tail -20
```

Expected: api 日志出现 `alembic upgrade` 成功（含 0004）与 uvicorn 启动；`curl -s localhost:8000/health` 返回 200。
再验证扩展：`docker compose exec postgres psql -U agent_hub -c "\dx vector"` Expected: 列出 vector 扩展。
此时回补 Task 4 Step 2/4：`TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub python -m unittest tests.test_postgres_repository -v`

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml CLAUDE.md README.md docs/
git commit -m "chore(compose): merge full stack into docker-compose with pgvector image"
```

---

### Task 8: 全量验证

- [ ] **Step 1: 全量单测**

Run: `python -m unittest discover -s tests -v`
Expected: 全 PASS（无 TEST_DATABASE_URL 时 PG 测试 skip）

- [ ] **Step 2: PG 门槛测试**

Run: `TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub python -m unittest tests.test_postgres_repository tests.test_postgres_workflow tests.test_postgres_concurrency -v`
Expected: 全 PASS

- [ ] **Step 3: Lint**

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: 无错误（有格式问题就 `ruff format src/ tests/` 后重跑）

- [ ] **Step 4: 端到端冒烟（可选但推荐，需 SILICONFLOW_API_KEY）**

```bash
export SILICONFLOW_API_KEY=sk-...
docker compose up -d --build
# 触发一次抓取同步（worker 会链式 embed），然后确认向量落库：
docker compose exec postgres psql -U agent_hub -c \
  "SELECT count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded, count(*) AS total FROM jobs;"
```

Expected: 同步过职位后 embedded > 0；对某候选人跑一次匹配，match payload 中出现 `"retrieval": {"method": "pgvector", ...}`。

- [ ] **Step 5: 最终提交（如有散落改动）**

```bash
git status
git add -A && git commit -m "chore: pgvector recall rollout finishing touches"
```
