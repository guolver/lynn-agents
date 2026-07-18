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


def _get_client() -> Any:
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=SILICONFLOW_API_KEY, base_url=EMBEDDING_BASE_URL, timeout=15.0)
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
        logger.warning("Embedding API call failed: %s", exc, exc_info=True)
        return [None] * len(texts)
    data = list(response.data)
    if len(data) != len(payload):
        logger.warning(
            "Embedding API returned %d vectors for %d inputs; discarding batch",
            len(data),
            len(payload),
        )
        return [None] * len(texts)
    vectors = (item.embedding for item in data)
    return [next(vectors) if t is not None else None for t in cleaned]


def get_embedding(text: str) -> list[float] | None:
    """获取单条文本向量。失败返回 None。"""
    return get_embeddings([text])[0]


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
