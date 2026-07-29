"""Global Part-Time Agent 子 Agent 定义

使用 Harness SubAgent 框架定义专用子 Agent。
"""

from __future__ import annotations

import logging
from typing import Any

from agent_hub.harness import SubAgent, SubResult, SubTask

from .harness_tools import (
    CANDIDATE_MATCH_ALLOWED_TOOLS,
    JOB_SEARCH_ALLOWED_TOOLS,
)

logger = logging.getLogger(__name__)


class JobSearchSubAgent(SubAgent):
    """职位搜索子 Agent

    专门负责职位搜索和过滤任务。

    Features:
        - 权限隔离：只能使用 search_jobs 和 filter_jobs 工具
        - 历史隔离：每次执行有独立历史
        - 显式输入：通过 SubTask.inputs 传递
    """

    name = "job_search"
    description = "搜索和过滤职位"
    allowed_tools = JOB_SEARCH_ALLOWED_TOOLS

    def _run(self, task: SubTask) -> SubResult:
        """执行职位搜索任务

        Args:
            task: 子任务，包含搜索条件

        Returns:
            搜索结果
        """
        inputs = task.inputs
        keyword = inputs.get("keyword")
        country = inputs.get("country")
        min_pay = inputs.get("min_pay")
        work_mode = inputs.get("work_mode")
        candidate_id = inputs.get("candidate_id")

        try:
            # 第一步：搜索职位
            search_args = {}
            if keyword:
                search_args["keyword"] = keyword
            if country:
                search_args["country"] = country
            if min_pay:
                search_args["min_pay"] = min_pay
            if work_mode:
                search_args["work_mode"] = work_mode

            search_result = self._call_tool("search_jobs", **search_args)
            jobs = search_result.get("jobs", [])

            # 第二步：如果有候选人 ID，过滤职位
            if candidate_id and jobs:
                job_ids = [j["id"] for j in jobs]
                filter_result = self._call_tool(
                    "filter_jobs",
                    candidate_id=candidate_id,
                    job_ids=job_ids,
                )
                passed = filter_result.get("passed", [])

                return SubResult(
                    summary=f"找到 {len(passed)} 个符合条件的职位",
                    structured={
                        "jobs": passed,
                        "total": len(passed),
                        "filtered_count": filter_result.get("filtered_count", 0),
                    },
                )

            return SubResult(
                summary=f"找到 {len(jobs)} 个职位",
                structured=search_result,
            )

        except Exception as e:
            logger.exception("Job search error: %s", e)
            return SubResult.failure(str(e))


class CandidateMatchSubAgent(SubAgent):
    """候选人匹配子 Agent

    专门负责候选人与职位的匹配和评分任务。

    Features:
        - 权限隔离：只能使用 match_candidate 和 score_candidate 工具
        - 历史隔离：每次执行有独立历史
        - 批量处理：支持对多个职位进行评分
    """

    name = "candidate_match"
    description = "匹配候选人与职位"
    allowed_tools = CANDIDATE_MATCH_ALLOWED_TOOLS

    def _run(self, task: SubTask) -> SubResult:
        """执行匹配任务

        Args:
            task: 子任务，包含候选人 ID 和职位 ID（列表）

        Returns:
            匹配结果
        """
        inputs = task.inputs
        candidate_id = inputs.get("candidate_id")
        job_ids = inputs.get("job_ids", [])
        detailed = inputs.get("detailed", False)

        if not candidate_id:
            return SubResult.failure("candidate_id is required")

        if not job_ids:
            return SubResult.failure("job_ids is required")

        try:
            matches = []
            for job_id in job_ids:
                if detailed:
                    result = self._call_tool(
                        "score_candidate",
                        candidate_id=candidate_id,
                        job_id=job_id,
                        detailed=True,
                    )
                else:
                    result = self._call_tool(
                        "match_candidate",
                        candidate_id=candidate_id,
                        job_id=job_id,
                    )

                if "error" not in result:
                    matches.append(result)

            # 按分数排序
            matches.sort(key=lambda x: x.get("score", 0), reverse=True)

            return SubResult(
                summary=f"完成 {len(matches)} 个职位的匹配评分",
                structured={
                    "matches": matches,
                    "candidate_id": candidate_id,
                    "total": len(matches),
                },
            )

        except Exception as e:
            logger.exception("Candidate match error: %s", e)
            return SubResult.failure(str(e))


class ResumeAnalysisSubAgent(SubAgent):
    """简历分析子 Agent

    专门负责简历解析和分析任务。
    """

    name = "resume_analysis"
    description = "解析和分析简历"
    allowed_tools = frozenset({"parse_resume", "get_my_profile"})

    def _run(self, task: SubTask) -> SubResult:
        """执行简历分析任务

        Args:
            task: 子任务，包含简历文本或候选人 ID

        Returns:
            分析结果
        """
        inputs = task.inputs
        pdf_text = inputs.get("pdf_text")
        candidate_id = inputs.get("candidate_id")

        try:
            if pdf_text:
                # 解析新简历
                result = self._call_tool("parse_resume", pdf_text=pdf_text)
                candidate = result.get("candidate", {})
                parsed = result.get("parsed_fields", {})

                skills = parsed.get("skills", [])
                languages = parsed.get("languages", [])

                return SubResult(
                    summary=f"简历解析完成，提取了 {len(skills)} 项技能和 {len(languages)} 种语言",
                    structured={
                        "candidate_id": candidate.get("id"),
                        "skills": skills,
                        "languages": languages,
                        "country": parsed.get("country"),
                        "parsed_fields": parsed,
                    },
                )

            elif candidate_id:
                # 获取现有档案
                profile = self._call_tool("get_my_profile", candidate_id=candidate_id)

                if "error" in profile:
                    return SubResult.failure(profile["error"])

                skills = profile.get("skills", [])

                return SubResult(
                    summary=f"获取到候选人档案，包含 {len(skills)} 项技能",
                    structured={
                        "candidate_id": candidate_id,
                        "profile": profile,
                    },
                )

            else:
                return SubResult.failure("需要 pdf_text 或 candidate_id")

        except Exception as e:
            logger.exception("Resume analysis error: %s", e)
            return SubResult.failure(str(e))


class PreferenceUpdateSubAgent(SubAgent):
    """偏好更新子 Agent

    专门负责候选人偏好更新任务。
    """

    name = "preference_update"
    description = "更新候选人偏好"
    allowed_tools = frozenset({"update_preferences", "get_my_profile"})

    def _run(self, task: SubTask) -> SubResult:
        """执行偏好更新任务

        Args:
            task: 子任务，包含候选人 ID 和更新内容

        Returns:
            更新结果
        """
        inputs = task.inputs
        candidate_id = inputs.get("candidate_id")
        changes = inputs.get("changes", {})

        if not candidate_id:
            return SubResult.failure("candidate_id is required")

        if not changes:
            return SubResult.failure("changes is required")

        try:
            # 获取当前档案
            current = self._call_tool("get_my_profile", candidate_id=candidate_id)
            if "error" in current:
                return SubResult.failure(current["error"])

            # 更新偏好
            updated = self._call_tool(
                "update_preferences",
                candidate_id=candidate_id,
                changes=changes,
            )

            if "error" in updated:
                return SubResult.failure(updated["error"])

            # 记录变更
            changed_fields = list(changes.keys())

            return SubResult(
                summary=f"已更新 {len(changed_fields)} 项偏好设置",
                structured={
                    "candidate_id": candidate_id,
                    "changed_fields": changed_fields,
                    "changes": changes,
                },
            )

        except Exception as e:
            logger.exception("Preference update error: %s", e)
            return SubResult.failure(str(e))


# 子 Agent 注册表
SUBAGENT_REGISTRY: dict[str, type[SubAgent]] = {
    "job_search": JobSearchSubAgent,
    "candidate_match": CandidateMatchSubAgent,
    "resume_analysis": ResumeAnalysisSubAgent,
    "preference_update": PreferenceUpdateSubAgent,
}


def get_subagent(name: str) -> type[SubAgent] | None:
    """获取子 Agent 类

    Args:
        name: 子 Agent 名称

    Returns:
        子 Agent 类，未找到则返回 None
    """
    return SUBAGENT_REGISTRY.get(name)


def list_subagents() -> list[dict[str, Any]]:
    """列出所有子 Agent

    Returns:
        子 Agent 信息列表
    """
    return [
        {
            "name": name,
            "description": cls.description,
            "allowed_tools": list(cls.allowed_tools),
        }
        for name, cls in SUBAGENT_REGISTRY.items()
    ]
