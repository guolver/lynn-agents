"""Batch LLM summaries layered on top of deterministic match reasons."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

MAX_SUMMARY_JOBS = 5
MAX_SUMMARY_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 1200

SYSTEM_PROMPT = """\
你是职位推荐解释器。请根据候选人画像、岗位事实和确定性匹配依据，为每个岗位生成一句中文推荐总结。
只返回以 job_id 为键、总结字符串为值的 JSON 对象。
每句不超过 120 个中文字符。不得编造输入中没有的经历、技能、薪资或岗位事实。
"""


def _candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    skills = [
        item.get("name") if isinstance(item, dict) else item
        for item in candidate.get("skills") or []
    ]
    return {
        "desired_roles": candidate.get("desired_roles") or [],
        "skills": [skill for skill in skills if skill],
        "resume_summary": candidate.get("resume_summary"),
    }


def generate_recommendation_summaries(
    candidate: dict[str, Any],
    matches: list[dict[str, Any]],
    jobs_by_id: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Generate up to five summaries in one request; failures return an empty mapping."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    selected = [match for match in matches if match.get("job_id") in jobs_by_id][:MAX_SUMMARY_JOBS]
    if not api_key or not selected:
        return {}

    allowed_ids = {str(match["job_id"]) for match in selected}
    jobs = []
    for match in selected:
        job_id = str(match["job_id"])
        job = jobs_by_id[job_id]
        jobs.append(
            {
                "job_id": job_id,
                "title": job.get("title_original", ""),
                "company": job.get("company_name", ""),
                "description": str(job.get("description_original") or "")[:MAX_DESCRIPTION_LENGTH],
                "reasons": match.get("reasons") or [],
            }
        )

    request_payload = {"candidate": _candidate_payload(candidate), "jobs": jobs}
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout=15.0,
        )
        response = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(request_payload, ensure_ascii=False),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return {}
    except Exception as exc:  # noqa: BLE001 - explanations must never break matching
        logger.warning("Recommendation summary generation failed: %s", exc)
        return {}

    summaries: dict[str, str] = {}
    for job_id, value in parsed.items():
        if job_id not in allowed_ids or not isinstance(value, str):
            continue
        summary = value.strip()
        if not summary or len(summary) > MAX_SUMMARY_LENGTH:
            continue
        summaries[job_id] = summary
    return summaries
