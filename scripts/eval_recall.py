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
