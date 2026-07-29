"""Harness 版本的兼职 Agent 聊天服务

使用 Harness 框架重新封装聊天服务，提供 PEV 循环能力。
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from agent_hub.harness import HarnessLoop
from agent_hub.harness.loop.planner import RulePlanner
from agent_hub.harness.loop.types import Bounds, LoopState, Plan, VerifyResult
from agent_hub.harness.loop.verifier import BaseVerifier
from agent_hub.harness.mixins import HarnessMixin, RetryConfig

from .harness_tools import build_tool_registry

if TYPE_CHECKING:
    from .chat_service import ChatService
    from .service import AgentService

logger = logging.getLogger(__name__)


# =============================================================================
# 配置
# =============================================================================

PART_TIME_BOUNDS = Bounds(
    max_turns=50,
    max_replans=3,
    max_tool_calls_per_turn=5,
    token_budget=16000,
    compaction_ratio=0.85,
    single_output_cap=1000,
)

# 意图定义
INTENT_PARSE_RESUME = "parse_resume"
INTENT_RUN_MATCHES = "run_matches"
INTENT_SEARCH_JOBS = "search_jobs"
INTENT_GET_JOB_DETAIL = "get_job_detail"
INTENT_UPDATE_PREFERENCES = "update_preferences"
INTENT_GET_PROFILE = "get_profile"
INTENT_CHAT = "chat"

ALLOWED_INTENTS = frozenset({
    INTENT_PARSE_RESUME,
    INTENT_RUN_MATCHES,
    INTENT_SEARCH_JOBS,
    INTENT_GET_JOB_DETAIL,
    INTENT_UPDATE_PREFERENCES,
    INTENT_GET_PROFILE,
    INTENT_CHAT,
})


# =============================================================================
# 规划器
# =============================================================================


def _is_resume_upload(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是简历上传"""
    return bool(context.get("resume_text") or context.get("attachment"))


def _is_match_request(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是匹配请求"""
    message = (context.get("message") or context.get("user_message") or "").lower()
    keywords = ["推荐", "匹配", "找工作", "职位", "recommend", "match", "job"]
    return any(kw in message for kw in keywords)


def _is_search_request(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是搜索请求"""
    message = (context.get("message") or context.get("user_message") or "").lower()
    keywords = ["搜索", "查找", "有没有", "search", "find", "look for"]
    return any(kw in message for kw in keywords)


def _is_preference_update(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是偏好更新"""
    message = (context.get("message") or context.get("user_message") or "").lower()
    keywords = ["修改", "更新", "设置", "偏好", "update", "change", "preference"]
    return any(kw in message for kw in keywords)


def _is_profile_query(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是档案查询"""
    message = (context.get("message") or context.get("user_message") or "").lower()
    keywords = ["我的", "档案", "资料", "profile", "my"]
    return any(kw in message for kw in keywords)


PART_TIME_PLANNER = RulePlanner(
    rules=[
        (INTENT_PARSE_RESUME, _is_resume_upload),
        (INTENT_RUN_MATCHES, _is_match_request),
        (INTENT_SEARCH_JOBS, _is_search_request),
        (INTENT_UPDATE_PREFERENCES, _is_preference_update),
        (INTENT_GET_PROFILE, _is_profile_query),
    ],
    default_intent=INTENT_CHAT,
)


# =============================================================================
# 校验器
# =============================================================================


class PartTimeVerifier(BaseVerifier):
    """兼职 Agent 校验器"""

    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        """校验计划"""
        if plan.intent not in ALLOWED_INTENTS:
            return VerifyResult.fail(
                f"Unknown intent: {plan.intent}",
                suggestions=[f"Use one of: {list(ALLOWED_INTENTS)}"],
            )

        # 检查需要候选人 ID 的意图
        needs_candidate = {INTENT_RUN_MATCHES, INTENT_UPDATE_PREFERENCES, INTENT_GET_PROFILE}
        if plan.intent in needs_candidate:
            candidate_id = state.metadata.get("candidate_id")
            if not candidate_id:
                return VerifyResult.fail(
                    "candidate_id is required for this action",
                    suggestions=["Please upload a resume first"],
                )

        return VerifyResult.ok()

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        """校验结果"""
        if result.get("error"):
            return VerifyResult.fail(
                f"Execution error: {result['error']}",
                suggestions=["Retry with different parameters"],
            )
        return VerifyResult.ok()


class PassthroughVerifier(BaseVerifier):
    """透传校验器"""

    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        return VerifyResult.ok()

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        return VerifyResult.ok()


# =============================================================================
# Harness 聊天服务
# =============================================================================


class HarnessPartTimeChatService(HarnessMixin):
    """使用 Harness 的兼职 Agent 聊天服务

    包装原始 ChatService，在其之上提供 PEV 循环能力。

    Features:
        - Plan-Execute-Verify 循环
        - 边界约束（最大轮次、Token 预算）
        - 工具注册与调用
        - 分层记忆管理
        - 重试与重规划

    Usage:
        original_service = ChatService(...)
        harness_service = HarnessPartTimeChatService(
            original_service,
            agent_service,
        )

        # 使用 Harness 模式处理消息
        for event in harness_service.stream_response(session_id, message):
            yield event
    """

    def __init__(
        self,
        original: "ChatService",
        agent_service: "AgentService",
        *,
        strict_verify: bool = False,
        actor: str = "anonymous",
    ):
        """
        Args:
            original: 原始聊天服务
            agent_service: Agent 服务
            strict_verify: 是否使用严格校验
            actor: 操作者标识
        """
        self.original = original
        self.agent_service = agent_service
        self.actor = actor

        # 初始化 Harness 能力
        self.init_harness(
            bounds=PART_TIME_BOUNDS,
            retry_config=RetryConfig(max_retries=2),
        )

        # 构建工具注册表
        self.tool_registry = build_tool_registry(agent_service, actor)

        # 构建 Harness 循环
        verifier = PartTimeVerifier() if strict_verify else PassthroughVerifier()
        self.loop = HarnessLoop(
            planner=PART_TIME_PLANNER,
            verifier=verifier,
            executor=self._execute,
            bounds=PART_TIME_BOUNDS,
            on_transition=self._on_transition,
            on_error=self._on_error,
        )

    def _execute(self, plan: Plan, state: LoopState) -> dict[str, Any]:
        """执行计划

        Args:
            plan: 执行计划
            state: 当前状态

        Returns:
            执行结果
        """
        intent = plan.intent
        metadata = state.metadata

        logger.debug("Executing plan: intent=%s, turn=%d", intent, state.turn)

        try:
            if intent == INTENT_PARSE_RESUME:
                return self._handle_parse_resume(metadata)
            elif intent == INTENT_RUN_MATCHES:
                return self._handle_run_matches(metadata)
            elif intent == INTENT_SEARCH_JOBS:
                return self._handle_search_jobs(metadata)
            elif intent == INTENT_GET_JOB_DETAIL:
                return self._handle_get_job_detail(metadata)
            elif intent == INTENT_UPDATE_PREFERENCES:
                return self._handle_update_preferences(metadata)
            elif intent == INTENT_GET_PROFILE:
                return self._handle_get_profile(metadata)
            else:
                return self._handle_chat(metadata)
        except Exception as e:
            logger.exception("Execution error: %s", e)
            return {"error": str(e)}

    def _handle_parse_resume(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理简历解析"""
        resume_text = metadata.get("resume_text", "")
        if not resume_text:
            return {"error": "No resume text provided"}

        result = self.tool_registry.call("parse_resume", pdf_text=resume_text)

        # 更新候选人 ID
        if "candidate" in result:
            metadata["candidate_id"] = result["candidate"]["id"]

        return result

    def _handle_run_matches(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理职位匹配"""
        candidate_id = metadata.get("candidate_id")
        if not candidate_id:
            return {"error": "No candidate_id"}

        limit = metadata.get("limit", 10)
        exclude_job_ids = metadata.get("exclude_job_ids", [])

        return self.tool_registry.call(
            "run_matches",
            candidate_id=candidate_id,
            limit=limit,
            exclude_job_ids=exclude_job_ids,
        )

    def _handle_search_jobs(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理职位搜索"""
        return self.tool_registry.call(
            "search_jobs",
            keyword=metadata.get("keyword"),
            country=metadata.get("country"),
            min_pay=metadata.get("min_pay"),
            work_mode=metadata.get("work_mode"),
        )

    def _handle_get_job_detail(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理获取职位详情"""
        job_id = metadata.get("job_id")
        if not job_id:
            return {"error": "No job_id"}

        return self.tool_registry.call("get_job_detail", job_id=job_id)

    def _handle_update_preferences(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理更新偏好"""
        candidate_id = metadata.get("candidate_id")
        changes = metadata.get("changes", {})

        if not candidate_id:
            return {"error": "No candidate_id"}
        if not changes:
            return {"error": "No changes provided"}

        return self.tool_registry.call(
            "update_preferences",
            candidate_id=candidate_id,
            changes=changes,
        )

    def _handle_get_profile(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理获取档案"""
        candidate_id = metadata.get("candidate_id")
        if not candidate_id:
            return {"error": "No candidate_id"}

        return self.tool_registry.call("get_my_profile", candidate_id=candidate_id)

    def _handle_chat(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理普通聊天"""
        return {
            "action": "chat",
            "message": metadata.get("user_message", ""),
        }

    def _on_transition(self, old_phase: Any, new_phase: Any, state: LoopState) -> None:
        """状态转移回调"""
        logger.debug(
            "Phase transition: %s -> %s (turn=%d)",
            old_phase.name,
            new_phase.name,
            state.turn,
        )

    def _on_error(self, error: str, state: LoopState) -> None:
        """错误回调"""
        logger.warning("Harness error: %s (turn=%d)", error, state.turn)

    def step(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """执行一轮 PEV 循环

        Args:
            context: 执行上下文

        Returns:
            执行结果
        """
        self.loop.state.metadata.update(context)
        return self.loop.step(context)

    def stream_response(
        self, session_id: str, user_message: str
    ) -> Generator[dict[str, Any], None, None]:
        """使用 Harness 处理用户消息并流式返回

        在原有逻辑之上添加 PEV 循环的边界检查和状态管理。

        Args:
            session_id: 会话 ID
            user_message: 用户消息

        Yields:
            事件字典
        """
        # 检查边界
        if not self.check_bounds():
            yield {
                "event": "error",
                "data": {"detail": "Session bounds exceeded"},
            }
            return

        # 更新状态
        self.loop.state.metadata["session_id"] = session_id
        self.loop.state.metadata["user_message"] = user_message

        # 委托给原服务
        try:
            for event in self.original.stream_response(session_id, user_message):
                yield event

            # 成功后增加轮次
            self.increment_turn()

        except Exception as e:
            logger.exception("Stream error: %s", e)
            yield {"event": "error", "data": {"detail": str(e)}}

    def run_analysis(
        self,
        session_id: str,
        resume_text: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """使用 Harness 执行简历分析流程

        Args:
            session_id: 会话 ID
            resume_text: 简历文本
            limit: 匹配数量限制

        Returns:
            分析结果
        """
        # 更新状态
        self.loop.state.metadata["session_id"] = session_id
        self.loop.state.metadata["resume_text"] = resume_text
        self.loop.state.metadata["limit"] = limit

        # 执行 PEV 循环
        context = {
            "action": "analyze",
            "resume_text": resume_text,
            "limit": limit,
        }

        result = self.step(context)

        if result and "candidate" in result:
            # 更新候选人 ID
            candidate_id = result["candidate"]["id"]
            self.loop.state.metadata["candidate_id"] = candidate_id

            # 绑定到会话
            self.original.bind_candidate(session_id, candidate_id)

            # 运行匹配
            match_context = {
                "action": "match",
                "candidate_id": candidate_id,
                "limit": limit,
            }
            match_result = self.step(match_context)

            if match_result:
                result["matches"] = match_result.get("matches", [])
                result["matches_count"] = len(result["matches"])

        return result or {"error": "Analysis failed"}

    def reset(self) -> None:
        """重置 Harness 状态"""
        self.loop.reset()
        self._turn_count = 0
        self._tool_calls_count = 0
        self._token_count = 0

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "harness": self.get_harness_stats(),
            "loop_summary": self.loop.get_summary(),
            "tool_count": len(self.tool_registry),
        }
