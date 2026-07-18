"""Embedding 生成与余弦相似度计算。

使用 DeepSeek embedding API 为候选人和职位生成向量表示，
用于语义相似度评分。失败时返回 None，调用方负责降级。
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "deepseek-chat")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def get_embedding(text: str) -> list[float] | None:
    """调用 DeepSeek embedding 端点获取文本向量。失败返回 None。"""
    if not DEEPSEEK_API_KEY:
        return None
    if not text.strip():
        return None
    try:
        response = httpx.post(
            f"{DEEPSEEK_BASE_URL}/v1/embeddings",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={"model": EMBEDDING_MODEL, "input": text[:8000]},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
    except Exception as exc:
        logger.warning("Embedding API call failed: %s", exc)
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_candidate_text(candidate: dict[str, Any]) -> str:
    """将候选人的技能和期望角色组合为一段用于 embedding 的文本。"""
    parts: list[str] = []
    skills = candidate.get("skills") or []
    skill_names = [s["name"] if isinstance(s, dict) else s for s in skills]
    if skill_names:
        parts.append("Skills: " + ", ".join(skill_names))
    desired_roles = candidate.get("desired_roles") or []
    if desired_roles:
        parts.append("Desired roles: " + ", ".join(desired_roles))
    return ". ".join(parts)


def build_job_text(job: dict[str, Any]) -> str:
    """将职位的关键字段组合为一段用于 embedding 的文本。"""
    parts: list[str] = []
    title = job.get("title_original", "")
    if title:
        parts.append(f"Title: {title}")
    skills = job.get("skills") or []
    if skills:
        parts.append("Skills: " + ", ".join(skills))
    categories = job.get("categories") or []
    if categories:
        parts.append("Categories: " + ", ".join(categories))
    description = job.get("description_original", "")
    if description:
        parts.append("Description: " + description[:500])
    return ". ".join(parts)
