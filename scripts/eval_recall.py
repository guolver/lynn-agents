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
    extracted = [(t["name"] if isinstance(t, dict) else t) for t in raw_terms]
    terms = [t.lower() for t in extracted if t and t.strip()]
    scored: list[tuple[int, str]] = []
    for job in jobs:
        text = _job_search_text(job)
        # 刻意采用整条词条的子串匹配（如真实系统的技能标签），不做分词
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
        item.update(
            source_id=EVAL_SOURCE_ID,
            dedup_key=item["id"],
            status="active",
            review_status="not_required",
            company_name=item.get("company_name", "EvalCo"),
        )
        repo.put("job", item)
    for cand in dataset["candidates"]:
        repo.put("candidate", dict(cand))


def _embed_all_jobs(repo: Any, dataset: dict[str, Any]) -> None:
    from agent_hub.agents.global_part_time import embedding as embedding_mod

    jobs = dataset["jobs"]
    vectors = embedding_mod.get_embeddings([embedding_mod.build_job_text(job) for job in jobs])
    missing = [job["id"] for job, vec in zip(jobs, vectors) if vec is None]
    if missing:
        sys.exit(
            f"embedding 生成失败（{len(missing)} 个职位，如 {missing[0]}）——检查 API key/网络后重试"
        )
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


def _aggregate(
    rows: list[dict[str, Any]], ks: list[int]
) -> list[tuple[str, str, dict[str, float]]]:
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
        cells = (
            [group, method] + [f"{metrics[f'r@{k}']:.3f}" for k in ks] + [f"{metrics['mrr']:.3f}"]
        )
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
                + output
                + "\n",
                encoding="utf-8",
            )
            print(f"\n报告已写入 {args.report}")
    finally:
        if not args.keep:
            _cleanup(repo, dataset)


if __name__ == "__main__":
    main()
