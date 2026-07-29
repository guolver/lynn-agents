"""Global Part-Time Agent Harness 工具定义

使用 ToolRegistry 注册兼职 Agent 的工具，支持 Harness 框架。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_hub.harness import ToolRegistry

if TYPE_CHECKING:
    from .service import AgentService

logger = logging.getLogger(__name__)

# 限制常量
RESUME_TEXT_STORE_LIMIT = 20000
RESUME_TEXT_PROFILE_LIMIT = 6000


def build_tool_registry(service: "AgentService", actor: str) -> ToolRegistry:
    """构建工具注册表

    将 AgentService 的方法注册为 Harness 工具。

    Args:
        service: Agent 服务实例
        actor: 操作者标识

    Returns:
        ToolRegistry 实例
    """
    registry = ToolRegistry()

    # =========================================================================
    # 简历解析
    # =========================================================================

    @registry.register(
        name="parse_resume",
        description="解析简历文本，提取技能、语言、国家等结构化数据",
        parameters={
            "pdf_text": {
                "type": "string",
                "required": True,
                "description": "从 PDF 提取的简历全文",
            },
        },
        returns="包含 candidate 和 parsed_fields 的字典",
        tags=["resume", "parse"],
    )
    def parse_resume(pdf_text: str) -> dict[str, Any]:
        from .resume_parser import parse_resume as do_parse

        parsed = do_parse(pdf_text)
        candidate = service.create_candidate(
            {**parsed, "resume_text": pdf_text[:RESUME_TEXT_STORE_LIMIT]},
            actor,
        )
        service.set_consent(candidate["id"], True, actor, "chat_upload")
        # 剔除原文，避免进入 LLM 上下文
        candidate_public = {k: v for k, v in candidate.items() if k != "resume_text"}
        return {"candidate": candidate_public, "parsed_fields": parsed}

    # =========================================================================
    # 职位匹配
    # =========================================================================

    @registry.register(
        name="run_matches",
        description="运行硬过滤和评分，为候选人匹配职位",
        parameters={
            "candidate_id": {
                "type": "string",
                "required": True,
                "description": "候选人 ID",
            },
            "limit": {
                "type": "integer",
                "required": False,
                "default": 10,
                "description": "最大返回数量",
            },
            "exclude_job_ids": {
                "type": "array",
                "required": False,
                "description": "要排除的职位 ID 列表",
            },
        },
        returns="匹配结果，包含 matches 和 filtered",
        tags=["match", "job"],
    )
    def run_matches(
        candidate_id: str,
        limit: int = 10,
        exclude_job_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from .recommendation_explainer import generate_recommendation_summaries

        result = service.run_matches(
            candidate_id, actor, limit, exclude_job_ids=exclude_job_ids
        )

        # 富化匹配结果
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

        # 生成推荐摘要
        try:
            summaries = generate_recommendation_summaries(
                service.get_candidate(candidate_id),
                result.get("matches", []),
                jobs_by_id,
            )
            for match in result.get("matches", []):
                summary = summaries.get(match.get("job_id"))
                if summary:
                    match["recommendation_summary"] = summary
                    service.repo.put("match", match)
        except Exception:
            logger.warning(
                "Recommendation summary generation failed for candidate %s",
                candidate_id,
                exc_info=True,
            )

        return result

    # =========================================================================
    # 职位搜索
    # =========================================================================

    @registry.register(
        name="search_jobs",
        description="按关键词、国家、薪资或工作模式搜索职位",
        parameters={
            "keyword": {
                "type": "string",
                "required": False,
                "description": "搜索关键词",
            },
            "country": {
                "type": "string",
                "required": False,
                "description": "ISO 国家代码（如 US, CN）或 GLOBAL",
            },
            "min_pay": {
                "type": "number",
                "required": False,
                "description": "最低时薪（USD）",
            },
            "work_mode": {
                "type": "string",
                "required": False,
                "description": "工作模式：remote/hybrid/onsite",
                "enum": ["remote", "hybrid", "onsite"],
            },
        },
        returns="职位列表",
        tags=["search", "job"],
    )
    def search_jobs(
        keyword: str | None = None,
        country: str | None = None,
        min_pay: float | None = None,
        work_mode: str | None = None,
    ) -> dict[str, Any]:
        keyword_lower = (keyword or "").lower()
        jobs = service.repo.list("job")
        results = []

        for job in jobs:
            if job.get("status") != "active":
                continue

            # 关键词过滤
            if keyword_lower:
                searchable = (
                    job.get("title_original", "") + " " + job.get("description_original", "")
                ).lower()
                if keyword_lower not in searchable:
                    continue

            # 国家过滤
            if country:
                allowed = job.get("countries_allowed") or []
                if "GLOBAL" not in allowed and country not in allowed:
                    continue

            # 薪资过滤
            if min_pay and (job.get("compensation_max") or 0) < min_pay:
                continue

            # 工作模式过滤
            if work_mode and job.get("work_mode") != work_mode:
                continue

            results.append({
                "id": job["id"],
                "title": job.get("title_original", ""),
                "company": job.get("company_name", ""),
                "country": job.get("countries_allowed", []),
                "compensation_max": job.get("compensation_max"),
                "work_mode": job.get("work_mode"),
            })

            if len(results) >= 20:
                break

        return {"jobs": results, "total": len(results)}

    # =========================================================================
    # 职位详情
    # =========================================================================

    @registry.register(
        name="get_job_detail",
        description="获取职位详情，包括描述、要求和薪资",
        parameters={
            "job_id": {
                "type": "string",
                "required": True,
                "description": "职位 ID",
            },
        },
        returns="职位详情字典",
        tags=["job", "detail"],
    )
    def get_job_detail(job_id: str) -> dict[str, Any]:
        job = service.repo.get("job", job_id)
        if job is None:
            return {"error": f"Job {job_id} not found"}
        return job

    # =========================================================================
    # 更新偏好
    # =========================================================================

    @registry.register(
        name="update_preferences",
        description="更新候选人偏好，如最低时薪、工作模式、国家等",
        parameters={
            "candidate_id": {
                "type": "string",
                "required": True,
                "description": "候选人 ID",
            },
            "changes": {
                "type": "object",
                "required": True,
                "description": "要更新的字段",
            },
        },
        returns="更新后的候选人信息",
        tags=["candidate", "preferences"],
    )
    def update_preferences(candidate_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        return service.update_candidate(candidate_id, changes, actor)

    # =========================================================================
    # 获取档案
    # =========================================================================

    @registry.register(
        name="get_my_profile",
        description="获取候选人档案，包括技能、偏好和授权状态",
        parameters={
            "candidate_id": {
                "type": "string",
                "required": True,
                "description": "候选人 ID",
            },
        },
        returns="候选人档案",
        tags=["candidate", "profile"],
    )
    def get_my_profile(candidate_id: str) -> dict[str, Any]:
        candidate = service.get_candidate(candidate_id)
        resume_text = candidate.get("resume_text")
        if resume_text and len(resume_text) > RESUME_TEXT_PROFILE_LIMIT:
            candidate = {
                **candidate,
                "resume_text": resume_text[:RESUME_TEXT_PROFILE_LIMIT] + "...(truncated)",
            }
        return candidate

    # =========================================================================
    # 候选人匹配（用于子 Agent）
    # =========================================================================

    @registry.register(
        name="match_candidate",
        description="为特定候选人和职位计算匹配分数",
        parameters={
            "candidate_id": {
                "type": "string",
                "required": True,
                "description": "候选人 ID",
            },
            "job_id": {
                "type": "string",
                "required": True,
                "description": "职位 ID",
            },
        },
        returns="匹配分数和原因",
        tags=["match", "subagent"],
    )
    def match_candidate(candidate_id: str, job_id: str) -> dict[str, Any]:
        # 获取候选人和职位
        candidate = service.get_candidate(candidate_id)
        job = service.repo.get("job", job_id)

        if not job:
            return {"error": f"Job {job_id} not found"}

        from .domain import score_match_with_evidence

        score, breakdown, reasons, evidence = score_match_with_evidence(
            candidate, job, None, None, None
        )

        return {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "score": score,
            "breakdown": breakdown,
            "reasons": reasons,
            "evidence": evidence,
        }

    # =========================================================================
    # 职位过滤（用于子 Agent）
    # =========================================================================

    @registry.register(
        name="filter_jobs",
        description="根据候选人条件过滤职位列表",
        parameters={
            "candidate_id": {
                "type": "string",
                "required": True,
                "description": "候选人 ID",
            },
            "job_ids": {
                "type": "array",
                "required": False,
                "description": "要过滤的职位 ID 列表（为空则过滤所有）",
            },
        },
        returns="通过过滤的职位列表",
        tags=["filter", "subagent"],
    )
    def filter_jobs(
        candidate_id: str,
        job_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from .domain import hard_filter

        candidate = service.get_candidate(candidate_id)

        if job_ids:
            jobs = [service.repo.get("job", jid) for jid in job_ids]
            jobs = [j for j in jobs if j is not None]
        else:
            jobs = service.repo.list("job")

        passed = []
        filtered = []

        for job in jobs:
            failures = hard_filter(candidate, job)
            if failures:
                filtered.append({"job_id": job["id"], "reasons": failures})
            else:
                passed.append({
                    "job_id": job["id"],
                    "title": job.get("title_original", ""),
                    "company": job.get("company_name", ""),
                })

        return {
            "passed": passed,
            "filtered": filtered,
            "passed_count": len(passed),
            "filtered_count": len(filtered),
        }

    # =========================================================================
    # 候选人评分（用于子 Agent）
    # =========================================================================

    @registry.register(
        name="score_candidate",
        description="计算候选人与职位的详细匹配评分",
        parameters={
            "candidate_id": {
                "type": "string",
                "required": True,
                "description": "候选人 ID",
            },
            "job_id": {
                "type": "string",
                "required": True,
                "description": "职位 ID",
            },
            "detailed": {
                "type": "boolean",
                "required": False,
                "default": False,
                "description": "是否返回详细评分",
            },
        },
        returns="评分结果",
        tags=["score", "subagent"],
    )
    def score_candidate(
        candidate_id: str,
        job_id: str,
        detailed: bool = False,
    ) -> dict[str, Any]:
        candidate = service.get_candidate(candidate_id)
        job = service.repo.get("job", job_id)

        if not job:
            return {"error": f"Job {job_id} not found"}

        from .domain import score_match_with_evidence

        score, breakdown, reasons, evidence = score_match_with_evidence(
            candidate, job, None, None, None
        )

        result = {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "score": score,
            "reasons": reasons,
        }

        if detailed:
            result["breakdown"] = breakdown
            result["evidence"] = evidence

        return result

    return registry


# 工具名称常量
TOOL_SEARCH_JOBS = "search_jobs"
TOOL_RUN_MATCHES = "run_matches"
TOOL_GET_JOB_DETAIL = "get_job_detail"
TOOL_UPDATE_PREFERENCES = "update_preferences"
TOOL_GET_MY_PROFILE = "get_my_profile"
TOOL_PARSE_RESUME = "parse_resume"
TOOL_MATCH_CANDIDATE = "match_candidate"
TOOL_FILTER_JOBS = "filter_jobs"
TOOL_SCORE_CANDIDATE = "score_candidate"

# 用户可见工具
USER_FACING_TOOLS = frozenset({
    TOOL_SEARCH_JOBS,
    TOOL_RUN_MATCHES,
    TOOL_GET_JOB_DETAIL,
    TOOL_UPDATE_PREFERENCES,
    TOOL_GET_MY_PROFILE,
    TOOL_PARSE_RESUME,
})

# 子 Agent 专用工具
SUBAGENT_TOOLS = frozenset({
    TOOL_MATCH_CANDIDATE,
    TOOL_FILTER_JOBS,
    TOOL_SCORE_CANDIDATE,
})

# 职位搜索子 Agent 允许的工具
JOB_SEARCH_ALLOWED_TOOLS = frozenset({
    TOOL_SEARCH_JOBS,
    TOOL_FILTER_JOBS,
})

# 候选人匹配子 Agent 允许的工具
CANDIDATE_MATCH_ALLOWED_TOOLS = frozenset({
    TOOL_MATCH_CANDIDATE,
    TOOL_SCORE_CANDIDATE,
})
