"""Chat tool definitions and executor for DeepSeek function calling.

Each tool wraps an existing AgentService method. The TOOL_DEFINITIONS list
provides OpenAI-compatible function schemas. execute_tool() dispatches a
tool call to the correct service method and returns the result as a dict.
"""

from __future__ import annotations

import logging
from typing import Any

from .recommendation_explainer import generate_recommendation_summaries
from .service import AgentService

logger = logging.getLogger(__name__)

# 简历原文入库上限：防止超大 PDF 撑爆 candidate payload（会随多个接口返回）。
RESUME_TEXT_STORE_LIMIT = 20000

# get_my_profile 返回给 LLM 的原文截断长度。
RESUME_TEXT_PROFILE_LIMIT = 6000

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "parse_resume",
            "description": "Parse resume text extracted from a PDF into structured candidate data (skills, languages, country, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_text": {
                        "type": "string",
                        "description": "The full text extracted from the resume PDF",
                    },
                },
                "required": ["pdf_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_matches",
            "description": "Run hard-filter and scoring to find matching jobs for a candidate. Returns ranked job matches with scores and reasons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "The candidate ID to match jobs for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of matches to return (default 10)",
                        "default": 10,
                    },
                },
                "required": ["candidate_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Search jobs by keyword, country, minimum pay, or work mode. Use this when the user wants to browse jobs without candidate-specific scoring.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Search keyword to match against job title or description",
                    },
                    "country": {
                        "type": "string",
                        "description": "ISO country code (e.g. US, CN) or GLOBAL",
                    },
                    "min_pay": {
                        "type": "number",
                        "description": "Minimum hourly pay in USD",
                    },
                    "work_mode": {
                        "type": "string",
                        "enum": ["remote", "hybrid", "onsite"],
                        "description": "Work mode filter",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_job_detail",
            "description": "Get full details of a specific job including description, requirements, and compensation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The job ID to look up",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_preferences",
            "description": "Update candidate preferences like minimum hourly rate, work modes, country, or skills. After updating, suggest re-running matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "The candidate ID to update",
                    },
                    "changes": {
                        "type": "object",
                        "description": "Fields to update. Supports: minimum_hourly_rate ({amount, currency}), allowed_work_modes, country, timezone, skills, languages, desired_roles, excluded_companies",
                    },
                },
                "required": ["candidate_id", "changes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_profile",
            "description": "Get the current candidate profile including skills, preferences, and consent status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "The candidate ID to look up",
                    },
                },
                "required": ["candidate_id"],
            },
        },
    },
]


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    service: AgentService,
    actor: str,
) -> dict[str, Any]:
    """Execute a tool call and return the result as a JSON-serializable dict."""
    try:
        if name == "parse_resume":
            from .resume_parser import parse_resume

            parsed = parse_resume(arguments["pdf_text"])
            candidate = service.create_candidate(
                {**parsed, "resume_text": arguments["pdf_text"][:RESUME_TEXT_STORE_LIMIT]},
                actor,
            )
            service.set_consent(candidate["id"], True, actor, "chat_upload")
            # 原文已入库，工具返回值剔除它：避免整份简历进入 LLM 上下文和 tool 消息。
            candidate_public = {k: v for k, v in candidate.items() if k != "resume_text"}
            return {"candidate": candidate_public, "parsed_fields": parsed}

        if name == "run_matches":
            candidate_id = arguments["candidate_id"]
            limit = arguments.get("limit", 10)
            result = service.run_matches(
                candidate_id, actor, limit, exclude_job_ids=arguments.get("exclude_job_ids")
            )
            # Enrich matches with job details
            jobs_by_id = {j["id"]: j for j in service.repo.list("job")}
            for match in result.get("matches", []):
                job = jobs_by_id.get(match.get("job_id"))
                if job:
                    match["job_title"] = job.get("title_original", "")
                    match["company_name"] = job.get("company_name", "")
                    match["compensation_min"] = job.get("compensation_min")
                    match["compensation_max"] = job.get("compensation_max")
                    match["compensation_currency"] = job.get("compensation_currency", "USD")
                    match["work_mode"] = job.get("work_mode", "remote")
            try:
                summaries = generate_recommendation_summaries(
                    service.get_candidate(candidate_id),
                    result.get("matches", []),
                    jobs_by_id,
                )
            except Exception:
                logger.warning(
                    "Recommendation summary generation failed for candidate %s",
                    candidate_id,
                    exc_info=True,
                )
                summaries = {}
            for match in result.get("matches", []):
                summary = summaries.get(match.get("job_id"))
                if summary:
                    match["recommendation_summary"] = summary
                    service.repo.put("match", match)
            return result

        if name == "search_jobs":
            keyword = (arguments.get("keyword") or "").lower()
            country = arguments.get("country")
            min_pay = arguments.get("min_pay")
            work_mode = arguments.get("work_mode")
            jobs = service.repo.list("job")
            results = []
            for job in jobs:
                if job.get("status") != "active":
                    continue
                if (
                    keyword
                    and keyword
                    not in (
                        job.get("title_original", "") + " " + job.get("description_original", "")
                    ).lower()
                ):
                    continue
                if country:
                    allowed = job.get("countries_allowed") or []
                    if "GLOBAL" not in allowed and country not in allowed:
                        continue
                if min_pay and (job.get("compensation_max") or 0) < min_pay:
                    continue
                if work_mode and job.get("work_mode") != work_mode:
                    continue
                results.append(
                    {
                        "id": job["id"],
                        "title": job.get("title_original", ""),
                        "company": job.get("company_name", ""),
                        "country": job.get("countries_allowed", []),
                        "compensation_max": job.get("compensation_max"),
                        "work_mode": job.get("work_mode"),
                    }
                )
                if len(results) >= 20:
                    break
            return {"jobs": results, "total": len(results)}

        if name == "get_job_detail":
            job = service.repo.get("job", arguments["job_id"])
            if job is None:
                return {"error": f"Job {arguments['job_id']} not found"}
            return job

        if name == "update_preferences":
            candidate_id = arguments["candidate_id"]
            changes = arguments["changes"]
            updated = service.update_candidate(candidate_id, changes, actor)
            return updated

        if name == "get_my_profile":
            candidate = service.get_candidate(arguments["candidate_id"])
            resume_text = candidate.get("resume_text")
            if resume_text and len(resume_text) > RESUME_TEXT_PROFILE_LIMIT:
                candidate = {
                    **candidate,
                    "resume_text": resume_text[:RESUME_TEXT_PROFILE_LIMIT] + "...(truncated)",
                }
            return candidate

        return {"error": f"Unknown tool: {name}"}

    except Exception as exc:
        logger.exception("Tool %s execution failed", name)
        return {"error": str(exc)}
