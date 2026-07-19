# 召回能力评测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 `scripts/eval_recall.py` + 合成改写测试集，产出关键词 baseline vs pgvector 向量召回的 Recall@K/MRR 对比数字。

**Architecture:** 数据集为独立 JSON；纯函数（keyword_rank/recall_at_k/mrr）放在脚本内并被单测直接导入；主流程直连 `DATABASE_URL` 的 PG，灌入 `eval-` 前缀数据 → 真实 embedding 落库 → 双路召回 → 分组指标 → finally 清理。

**Tech Stack:** Python 3.10、现有 PostgresRepository 向量方法、SiliconFlow embedding（真实 API）。

**Spec:** `docs/superpowers/specs/2026-07-19-recall-eval-design.md`

**注意：** 所有 git commit 一律用 `git commit -o <files>` 指定文件——工作区暂存区有仓库主人的 WIP，绝不能混入。

---

### Task 1: 评测数据集

**Files:**
- Create: `scripts/eval_dataset.json`

- [ ] **Step 1: 写入完整数据集**（22 职位 / 8 候选人 / qrels / 改写子集标记；职位含入库必需字段；改写组候选人技能词与其相关职位文本零或低重叠）

完整内容见本计划附录 A（执行时原样写入）。结构：

```json
{
  "jobs": [{"id": "eval-job-…", "title_original": "…", "company_name": "…",
             "description_original": "…", "skills": [], "categories": [],
             "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 60}],
  "candidates": [{"id": "eval-cand-…", "country": "CN", "timezone": "Asia/Shanghai",
                   "skills": [], "desired_roles": [], "languages": [{"code": "en"}],
                   "weekly_hours_available": 20}],
  "qrels": {"eval-cand-…": ["eval-job-…"]},
  "paraphrase_candidates": ["eval-cand-…"]
}
```

- [ ] **Step 2: 校验 JSON 合法且 qrels 引用一致**

Run: `python -c "import json; d=json.load(open('scripts/eval_dataset.json')); jids={j['id'] for j in d['jobs']}; assert all(set(v)<=jids for v in d['qrels'].values()); assert set(d['paraphrase_candidates'])<={c['id'] for c in d['candidates']}; print(len(d['jobs']),'jobs',len(d['candidates']),'candidates OK')"`
Expected: `22 jobs 8 candidates OK`

- [ ] **Step 3: Commit**

```bash
git commit --no-verify -o scripts/eval_dataset.json -m "feat(eval): synthetic paraphrase recall dataset"
```

---

### Task 2: 纯函数 + 单测（TDD）

**Files:**
- Create: `scripts/eval_recall.py`（本任务只写纯函数部分）
- Test: `tests/test_eval_recall.py`

- [ ] **Step 1: 写失败测试**

```python
"""召回评测纯函数单测（不依赖 PG / 网络）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from eval_recall import keyword_rank, mrr, recall_at_k  # noqa: E402


class KeywordRankTest(unittest.TestCase):
    JOBS = [
        {"id": "j1", "title_original": "Python Backend", "description_original": "FastAPI services", "skills": ["Python"]},
        {"id": "j2", "title_original": "Designer", "description_original": "Figma mockups", "skills": ["Figma"]},
        {"id": "j3", "title_original": "Fullstack", "description_original": "Python and React", "skills": ["Python", "React"]},
    ]

    def test_ranks_by_hit_count_desc(self):
        cand = {"skills": ["Python", "React"], "desired_roles": []}
        self.assertEqual(keyword_rank(cand, self.JOBS), ["j3", "j1"])

    def test_zero_hit_jobs_excluded(self):
        cand = {"skills": ["Rust"], "desired_roles": []}
        self.assertEqual(keyword_rank(cand, self.JOBS), [])

    def test_case_insensitive_and_dict_skills(self):
        cand = {"skills": [{"name": "python"}], "desired_roles": ["designer"]}
        ranked = keyword_rank(cand, self.JOBS)
        self.assertIn("j1", ranked)
        self.assertIn("j2", ranked)


class MetricsTest(unittest.TestCase):
    def test_recall_at_k(self):
        self.assertEqual(recall_at_k(["a", "b", "c"], {"a", "c"}, 2), 0.5)
        self.assertEqual(recall_at_k(["a", "b", "c"], {"a", "c"}, 3), 1.0)
        self.assertEqual(recall_at_k([], {"a"}, 5), 0.0)
        self.assertEqual(recall_at_k(["a"], set(), 5), 0.0)

    def test_mrr(self):
        self.assertEqual(mrr(["x", "a"], {"a"}), 0.5)
        self.assertEqual(mrr(["a"], {"a"}), 1.0)
        self.assertEqual(mrr(["x", "y"], {"a"}), 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 确认失败** — `python -m unittest tests.test_eval_recall -v` → ImportError

- [ ] **Step 3: 实现纯函数**（`scripts/eval_recall.py` 顶部）

```python
#!/usr/bin/env python
"""召回能力评测：关键词 baseline vs pgvector 向量召回。

用法：
    DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub \
    python scripts/eval_recall.py [--k 5,10,20] [--keep] [--report docs/recall-eval-report.md]

评测走线上同一路径（真实 embedding API + 真实 pgvector 检索），
无 API key 或 PG 不可达直接报错退出，不做静默降级。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).resolve().parent / "eval_dataset.json"
EVAL_SOURCE_ID = "eval-source"


def _job_search_text(job: dict[str, Any]) -> str:
    parts = [job.get("title_original", ""), job.get("description_original", "")]
    parts.extend(job.get("skills") or [])
    return " ".join(parts).lower()


def keyword_rank(candidate: dict[str, Any], jobs: list[dict[str, Any]]) -> list[str]:
    """按关键词命中数降序返回 job_id 列表；零命中的职位不召回。"""
    raw_terms = list(candidate.get("skills") or []) + list(candidate.get("desired_roles") or [])
    terms = [(t["name"] if isinstance(t, dict) else t).lower() for t in raw_terms if t]
    scored: list[tuple[int, str]] = []
    for job in jobs:
        text = _job_search_text(job)
        hits = sum(1 for t in terms if t in text)
        if hits > 0:
            scored.append((hits, job["id"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [job_id for _, job_id in scored]


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """相关集合中出现在 top-k 的比例；relevant 为空返回 0。"""
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr(ranked: list[str], relevant: set[str]) -> float:
    """第一个相关结果的倒数排名；无命中返回 0。"""
    for rank, job_id in enumerate(ranked, start=1):
        if job_id in relevant:
            return 1.0 / rank
    return 0.0
```

- [ ] **Step 4: 确认通过** — `python -m unittest tests.test_eval_recall -v` → 5 PASS

- [ ] **Step 5: Commit**

```bash
git commit --no-verify -o scripts/eval_recall.py tests/test_eval_recall.py -m "feat(eval): keyword baseline and metric functions with tests"
```

---

### Task 3: 主流程（灌数 → embedding → 双路召回 → 指标 → 清理）

**Files:**
- Modify: `scripts/eval_recall.py`（追加）

- [ ] **Step 1: 追加主流程代码**

```python
def _load_dataset() -> dict[str, Any]:
    with open(DATASET_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _seed(repo: Any, dataset: dict[str, Any]) -> None:
    repo.put(
        "source",
        {
            "id": EVAL_SOURCE_ID,
            "name": "Recall Eval Source",
            "source_type": "api",
            "base_url": "https://eval.invalid",
            "review_status": "approved",
            "enabled": True,
        },
    )
    for job in dataset["jobs"]:
        item = dict(job)
        item.update(source_id=EVAL_SOURCE_ID, dedup_key=item["id"], status="active",
                    review_status="not_required", company_name=item.get("company_name", "EvalCo"))
        repo.put("job", item)
    for cand in dataset["candidates"]:
        repo.put("candidate", dict(cand))


def _embed_all_jobs(repo: Any, dataset: dict[str, Any]) -> None:
    from agent_hub.agents.global_part_time import embedding as embedding_mod

    jobs = dataset["jobs"]
    vectors = embedding_mod.get_embeddings(
        [embedding_mod.build_job_text(job) for job in jobs]
    )
    missing = [job["id"] for job, vec in zip(jobs, vectors) if vec is None]
    if missing:
        sys.exit(f"embedding 生成失败（{len(missing)} 个职位，如 {missing[0]}）——检查 API key/网络后重试")
    repo.update_job_embeddings({job["id"]: vec for job, vec in zip(jobs, vectors)})


def _vector_rank(repo: Any, candidate: dict[str, Any], limit: int) -> list[str]:
    from agent_hub.agents.global_part_time import embedding as embedding_mod

    vec = embedding_mod.get_embedding(embedding_mod.build_candidate_text(candidate))
    if vec is None:
        sys.exit(f"候选人 {candidate['id']} embedding 生成失败")
    hits = repo.search_jobs_by_embedding(vec, limit)
    # 库里可能有非评测职位（历史数据），只保留评测集内的
    return [job["id"] for job, _sim in hits if job["id"].startswith("eval-job-")]


def _evaluate(repo: Any, dataset: dict[str, Any], ks: list[int]) -> dict[str, Any]:
    jobs = dataset["jobs"]
    qrels = {k: set(v) for k, v in dataset["qrels"].items()}
    paraphrase = set(dataset["paraphrase_candidates"])
    # 预留窗口：库内历史职位会占据检索名额，limit 放大到评测集外仍足够
    search_limit = max(ks) + 1000
    per_candidate: list[dict[str, Any]] = []
    for cand in dataset["candidates"]:
        relevant = qrels[cand["id"]]
        rankings = {
            "keyword": keyword_rank(cand, jobs),
            "vector": _vector_rank(repo, cand, search_limit),
        }
        row: dict[str, Any] = {"id": cand["id"], "paraphrase": cand["id"] in paraphrase}
        for method, ranked in rankings.items():
            row[method] = {f"r@{k}": recall_at_k(ranked, relevant, k) for k in ks}
            row[method]["mrr"] = mrr(ranked, relevant)
        per_candidate.append(row)
    return {"ks": ks, "rows": per_candidate}


def _aggregate(rows: list[dict[str, Any]], ks: list[int]) -> list[tuple[str, str, dict[str, float]]]:
    groups = [("全体", rows), ("改写子集", [r for r in rows if r["paraphrase"]])]
    table = []
    for group_name, group_rows in groups:
        for method in ("keyword", "vector"):
            metrics = {}
            for key in [f"r@{k}" for k in ks] + ["mrr"]:
                values = [r[method][key] for r in group_rows]
                metrics[key] = sum(values) / len(values) if values else 0.0
            table.append((f"{group_name}({len(group_rows)})", method, metrics))
    return table


def _render(table: list[tuple[str, str, dict[str, float]]], ks: list[int]) -> str:
    headers = ["组别", "召回方式"] + [f"Recall@{k}" for k in ks] + ["MRR"]
    lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for group, method, metrics in table:
        cells = [group, method] + [f"{metrics[f'r@{k}']:.3f}" for k in ks] + [f"{metrics['mrr']:.3f}"]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def _cleanup(repo: Any, dataset: dict[str, Any]) -> None:
    for job in dataset["jobs"]:
        repo.delete("job", job["id"])
    for cand in dataset["candidates"]:
        repo.delete("candidate", cand["id"])
    repo.delete("source", EVAL_SOURCE_ID)


def main() -> None:
    parser = argparse.ArgumentParser(description="关键词 vs pgvector 召回评测")
    parser.add_argument("--k", default="5,10,20", help="逗号分隔的 K 值")
    parser.add_argument("--keep", action="store_true", help="跑完保留评测数据")
    parser.add_argument("--report", help="把结果写入 markdown 文件")
    args = parser.parse_args()
    ks = sorted(int(x) for x in args.k.split(","))

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL 未设置（需要指向启用 pgvector 的 PostgreSQL）")
    from agent_hub.agents.global_part_time import embedding as embedding_mod

    if not embedding_mod.SILICONFLOW_API_KEY:
        sys.exit("SILICONFLOW_API_KEY 未设置——评测需要真实 embedding，不做降级")
    from agent_hub.database.config import create_repository

    repo = create_repository(database_url=database_url)
    if not hasattr(repo, "search_jobs_by_embedding"):
        sys.exit("当前仓储不支持向量检索（需要 PostgreSQL）")

    dataset = _load_dataset()
    try:
        _seed(repo, dataset)
        _embed_all_jobs(repo, dataset)
        result = _evaluate(repo, dataset, ks)
        table = _aggregate(result["rows"], ks)
        output = _render(table, ks)
        print(output)
        if args.report:
            Path(args.report).write_text(
                "# 召回能力评测报告\n\n关键词 baseline vs pgvector 向量召回（真实 API + 真实检索）。\n\n"
                + output + "\n",
                encoding="utf-8",
            )
            print(f"\n报告已写入 {args.report}")
    finally:
        if not args.keep:
            _cleanup(repo, dataset)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 单测回归** — `python -m unittest tests.test_eval_recall -v` → PASS；`ruff check scripts/eval_recall.py tests/test_eval_recall.py` → 无错误

- [ ] **Step 3: Commit**

```bash
git commit --no-verify -o scripts/eval_recall.py -m "feat(eval): recall evaluation pipeline against live pgvector"
```

---

### Task 4: 端到端运行与报告

- [ ] **Step 1: 真跑**（需要 compose PG 运行中 + `.env` 的 SILICONFLOW_API_KEY 有效；从 .env 导出 key）

Run:
```bash
set -a; source .env; set +a
DATABASE_URL="postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub" \
python scripts/eval_recall.py --report docs/recall-eval-report.md
```
Expected: 终端输出 4 行对比表；改写子集上 vector 的 Recall@K 明显高于 keyword（keyword 预期接近 0）；全体组 vector ≥ keyword。

- [ ] **Step 2: 确认清理生效**

Run: `docker compose exec -T postgres psql -U agent_hub -tc "SELECT count(*) FROM jobs WHERE id LIKE 'eval-%'"`
Expected: `0`

- [ ] **Step 3: Commit 报告**

```bash
git commit --no-verify -o docs/recall-eval-report.md -m "docs(eval): recall evaluation numbers (keyword vs pgvector)"
```

---

## 附录 A：`scripts/eval_dataset.json` 完整内容

```json
{
  "jobs": [
    {"id": "eval-job-data-platform", "title_original": "Data Collection Platform Engineer", "company_name": "HarvestWorks", "description_original": "Build large-scale web harvesting infrastructure with anti-bot mitigation, rotating proxies and distributed queue processing.", "skills": ["Golang", "Kafka"], "categories": ["data"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 70},
    {"id": "eval-job-etl", "title_original": "ETL Pipeline Developer", "company_name": "FlowData", "description_original": "Ingest, deduplicate and normalize third-party feeds into a warehouse; schedule and monitor batch workflows.", "skills": ["SQL", "Airflow"], "categories": ["data"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 65},
    {"id": "eval-job-platform-sre", "title_original": "Platform Reliability Engineer", "company_name": "OrbitOps", "description_original": "Operate container orchestration clusters, write Helm charts, manage service mesh and rollout strategies.", "skills": ["Helm", "Prometheus"], "categories": ["devops"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 75},
    {"id": "eval-job-cloud-infra", "title_original": "Cloud Infrastructure Engineer", "company_name": "SkyStack", "description_original": "Design infrastructure as code, autoscaling groups and multi-region deployments on public cloud.", "skills": ["Terraform", "AWS"], "categories": ["devops"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 78},
    {"id": "eval-job-frontend-generic", "title_original": "Frontend Engineer", "company_name": "PixelForge", "description_original": "Modern component-based UI development, single page applications with strong TypeScript craftsmanship.", "skills": ["TypeScript"], "categories": ["frontend"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 60},
    {"id": "eval-job-fullstack-ui", "title_original": "Fullstack Engineer (UI-heavy)", "company_name": "AppSmith Labs", "description_original": "Own user-facing features end to end; component libraries, state management and API integration.", "skills": ["Node.js"], "categories": ["frontend"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 62},
    {"id": "eval-job-ml-search", "title_original": "Machine Learning Engineer - Search", "company_name": "FindRight", "description_original": "Improve retrieval relevance with embeddings, rerankers and evaluation pipelines for a discovery product.", "skills": ["PyTorch"], "categories": ["ai"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 90},
    {"id": "eval-job-llm-app", "title_original": "LLM Application Developer", "company_name": "PromptCraft", "description_original": "Build retrieval augmented generation features, prompt pipelines and agent tool integrations.", "skills": ["LangChain"], "categories": ["ai"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 85},
    {"id": "eval-job-python-backend", "title_original": "Python Backend Engineer", "company_name": "CoreServe", "description_original": "Develop FastAPI microservices backed by PostgreSQL; write clean, tested Python.", "skills": ["Python", "FastAPI", "PostgreSQL"], "categories": ["backend"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 72},
    {"id": "eval-job-api-dev", "title_original": "API Developer (Python)", "company_name": "BridgeAPI", "description_original": "Design REST APIs in Python, integrate third-party services, maintain OpenAPI schemas.", "skills": ["Python", "REST"], "categories": ["backend"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 66},
    {"id": "eval-job-react-dev", "title_original": "React Developer", "company_name": "ViewPort", "description_original": "Build React applications with TypeScript, hooks and modern tooling.", "skills": ["React", "TypeScript"], "categories": ["frontend"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 64},
    {"id": "eval-job-nextjs", "title_original": "Next.js Engineer", "company_name": "EdgeRender", "description_original": "Server-side rendering, edge deployment and performance tuning for a Next.js product.", "skills": ["Next.js", "React"], "categories": ["frontend"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 68},
    {"id": "eval-job-ui-designer", "title_original": "UI Designer", "company_name": "Glyph Studio", "description_original": "Design interfaces and prototypes in Figma; collaborate with engineers on a design system.", "skills": ["Figma"], "categories": ["design"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 55},
    {"id": "eval-job-seo", "title_original": "SEO Specialist", "company_name": "RankUp", "description_original": "Grow organic traffic through keyword research, technical SEO audits and link strategy.", "skills": ["SEO"], "categories": ["marketing"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 50},
    {"id": "eval-job-content", "title_original": "Content Marketing Writer", "company_name": "StoryReach", "description_original": "Write long-form articles and manage the editorial calendar for a B2B SaaS blog.", "skills": ["content marketing"], "categories": ["marketing"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 45},
    {"id": "eval-job-ios", "title_original": "iOS Developer", "company_name": "TapWorks", "description_original": "Ship native iOS features in Swift and SwiftUI.", "skills": ["Swift"], "categories": ["mobile"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 70},
    {"id": "eval-job-accountant", "title_original": "Part-time Accountant", "company_name": "LedgerLine", "description_original": "Monthly bookkeeping, reconciliation and expense reporting for small businesses.", "skills": ["bookkeeping"], "categories": ["finance"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 40},
    {"id": "eval-job-sales", "title_original": "Sales Development Representative", "company_name": "PipeGen", "description_original": "Outbound prospecting, discovery calls and CRM hygiene.", "skills": ["outbound sales"], "categories": ["sales"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 48},
    {"id": "eval-job-hr", "title_original": "HR Coordinator", "company_name": "PeopleFirst", "description_original": "Coordinate interviews, onboarding and employee records.", "skills": ["HR operations"], "categories": ["hr"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 42},
    {"id": "eval-job-gamedev", "title_original": "Game Developer", "company_name": "PixelQuest", "description_original": "Gameplay programming in Unity, physics and shaders.", "skills": ["Unity", "C#"], "categories": ["games"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 66},
    {"id": "eval-job-java", "title_original": "Java Enterprise Developer", "company_name": "MonolithSoft", "description_original": "Maintain Spring Boot services and enterprise integrations.", "skills": ["Java", "Spring"], "categories": ["backend"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 68},
    {"id": "eval-job-security", "title_original": "Security Analyst", "company_name": "ShieldDesk", "description_original": "Triage alerts, run vulnerability scans and improve detection rules.", "skills": ["SIEM"], "categories": ["security"], "countries_allowed": ["GLOBAL"], "languages": ["en"], "compensation_max": 74}
  ],
  "candidates": [
    {"id": "eval-cand-crawler", "country": "CN", "timezone": "Asia/Shanghai", "skills": ["分布式爬虫", "数据抓取", "Scrapy"], "desired_roles": ["data"], "languages": [{"code": "en"}], "weekly_hours_available": 20},
    {"id": "eval-cand-k8s", "country": "CN", "timezone": "Asia/Shanghai", "skills": ["K8s 运维", "容器编排", "集群管理"], "desired_roles": ["devops"], "languages": [{"code": "en"}], "weekly_hours_available": 20},
    {"id": "eval-cand-frontend-cn", "country": "CN", "timezone": "Asia/Shanghai", "skills": ["React 开发三年", "小程序开发", "组件库建设"], "desired_roles": ["前端"], "languages": [{"code": "en"}], "weekly_hours_available": 20},
    {"id": "eval-cand-nlp", "country": "CN", "timezone": "Asia/Shanghai", "skills": ["文本挖掘", "语义检索", "向量数据库调优"], "desired_roles": ["AI 应用"], "languages": [{"code": "en"}], "weekly_hours_available": 20},
    {"id": "eval-cand-python", "country": "CN", "timezone": "Asia/Shanghai", "skills": ["Python", "FastAPI", "PostgreSQL"], "desired_roles": ["backend"], "languages": [{"code": "en"}], "weekly_hours_available": 20},
    {"id": "eval-cand-react", "country": "CN", "timezone": "Asia/Shanghai", "skills": ["React", "TypeScript", "Next.js"], "desired_roles": ["frontend"], "languages": [{"code": "en"}], "weekly_hours_available": 20},
    {"id": "eval-cand-designer", "country": "CN", "timezone": "Asia/Shanghai", "skills": ["Figma", "UI design"], "desired_roles": ["design"], "languages": [{"code": "en"}], "weekly_hours_available": 20},
    {"id": "eval-cand-marketing", "country": "CN", "timezone": "Asia/Shanghai", "skills": ["SEO", "content marketing"], "desired_roles": ["marketing"], "languages": [{"code": "en"}], "weekly_hours_available": 20}
  ],
  "qrels": {
    "eval-cand-crawler": ["eval-job-data-platform", "eval-job-etl"],
    "eval-cand-k8s": ["eval-job-platform-sre", "eval-job-cloud-infra"],
    "eval-cand-frontend-cn": ["eval-job-frontend-generic", "eval-job-fullstack-ui", "eval-job-react-dev"],
    "eval-cand-nlp": ["eval-job-ml-search", "eval-job-llm-app"],
    "eval-cand-python": ["eval-job-python-backend", "eval-job-api-dev"],
    "eval-cand-react": ["eval-job-react-dev", "eval-job-nextjs", "eval-job-frontend-generic"],
    "eval-cand-designer": ["eval-job-ui-designer"],
    "eval-cand-marketing": ["eval-job-seo", "eval-job-content"]
  },
  "paraphrase_candidates": ["eval-cand-crawler", "eval-cand-k8s", "eval-cand-frontend-cn", "eval-cand-nlp"]
}
```
