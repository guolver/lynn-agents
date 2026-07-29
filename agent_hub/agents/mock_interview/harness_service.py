"""Harness 版本的模拟面试服务

使用 Harness 框架重新封装面试服务，提供 PEV 循环能力。
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from agent_hub.harness import HarnessLoop
from agent_hub.harness.loop.types import LoopState, Plan
from agent_hub.harness.mixins import HarnessMixin, RetryConfig

from .harness_config import (
    INTENT_ASK_QUESTION,
    INTENT_COMPLETE,
    INTENT_EVALUATE,
    INTENT_FOLLOW_UP,
    INTENT_START_INTERVIEW,
    MOCK_INTERVIEW_BOUNDS,
    MOCK_INTERVIEW_PLANNER,
    MockInterviewVerifier,
    PassthroughVerifier,
)

if TYPE_CHECKING:
    from .service import InterviewService

logger = logging.getLogger(__name__)


class HarnessMockInterviewService(HarnessMixin):
    """使用 Harness 的模拟面试服务

    包装原始 InterviewService，在其之上提供 PEV 循环能力。

    Features:
        - Plan-Execute-Verify 循环
        - 边界约束（最大轮次、Token 预算）
        - 工具注册与调用
        - 重试与重规划

    Usage:
        original_service = InterviewService(repo, embed_fn)
        harness_service = HarnessMockInterviewService(original_service)

        # 使用 Harness 模式处理消息
        for event in harness_service.stream_response(session_id, message):
            yield event
    """

    def __init__(
        self,
        original: "InterviewService",
        *,
        strict_verify: bool = False,
    ):
        """
        Args:
            original: 原始面试服务
            strict_verify: 是否使用严格校验
        """
        self.original = original

        # 初始化 Harness 能力
        self.init_harness(
            bounds=MOCK_INTERVIEW_BOUNDS,
            retry_config=RetryConfig(max_retries=2),
        )

        # 构建 Harness 循环
        verifier = MockInterviewVerifier() if strict_verify else PassthroughVerifier()
        self.loop = HarnessLoop(
            planner=MOCK_INTERVIEW_PLANNER,
            verifier=verifier,
            executor=self._execute,
            bounds=MOCK_INTERVIEW_BOUNDS,
            on_transition=self._on_transition,
            on_error=self._on_error,
        )

        # 注册工具
        self._register_tools()

    def _register_tools(self) -> None:
        """注册面试相关工具"""

        @self.tool_registry.register(
            name="search_knowledge",
            description="从知识库搜索相关内容",
            parameters={
                "query": {"type": "string", "required": True, "description": "搜索关键词"},
                "limit": {"type": "integer", "required": False, "default": 5},
            },
        )
        def search_knowledge(query: str, limit: int = 5) -> list[dict[str, Any]]:
            results = self.original.search_knowledge(query, limit=limit)
            return [{"title": k["title"], "content": k["content"][:200]} for k, _ in results]

        @self.tool_registry.register(
            name="get_session",
            description="获取会话信息",
            parameters={
                "session_id": {"type": "string", "required": True, "description": "会话 ID"},
            },
        )
        def get_session(session_id: str) -> dict[str, Any] | None:
            return self.original.get_session(session_id)

    def _execute(self, plan: Plan, state: LoopState) -> dict[str, Any]:
        """执行计划

        根据意图调用原服务的相应方法。

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
            if intent == INTENT_START_INTERVIEW:
                return self._handle_start(metadata)
            elif intent == INTENT_ASK_QUESTION:
                return self._handle_question(metadata)
            elif intent == INTENT_FOLLOW_UP:
                return self._handle_follow_up(metadata)
            elif intent == INTENT_EVALUATE:
                return self._handle_evaluate(metadata)
            elif intent == INTENT_COMPLETE:
                return self._handle_complete(metadata)
            else:
                return self._handle_process(metadata)
        except Exception as e:
            logger.exception("Execution error: %s", e)
            return {"error": str(e)}

    def _handle_start(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理开始面试"""
        session = self.original.create_session(
            target_role=metadata.get("target_role", "软件工程师"),
            difficulty=metadata.get("difficulty", "medium"),
            actor=metadata.get("actor", "anonymous"),
            category=metadata.get("category"),
        )
        return {
            "action": "start",
            "session_id": session["id"],
            "message": "面试已开始",
        }

    def _handle_question(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理提问"""
        session_id = metadata.get("session_id")
        if not session_id:
            return {"error": "session_id is required"}

        # 从知识库搜索相关内容
        category = metadata.get("category", "")
        context = ""
        if category:
            results = self.original.search_knowledge(category, limit=3)
            if results:
                context = "\n".join(k["content"][:200] for k, _ in results)

        return {
            "action": "question",
            "session_id": session_id,
            "context": context,
        }

    def _handle_follow_up(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理追问"""
        return {
            "action": "follow_up",
            "session_id": metadata.get("session_id"),
            "reason": "需要更详细的回答",
        }

    def _handle_evaluate(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理评估"""
        return {
            "action": "evaluate",
            "session_id": metadata.get("session_id"),
        }

    def _handle_complete(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理完成"""
        session_id = metadata.get("session_id")
        if not session_id:
            return {"error": "session_id is required"}

        session = self.original.end_session(session_id)
        return {
            "action": "complete",
            "session_id": session_id,
            "summary": session.get("summary") if session else None,
        }

    def _handle_process(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """处理普通消息"""
        return {
            "action": "process",
            "session_id": metadata.get("session_id"),
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
        # 将 context 合并到状态元数据
        self.loop.state.metadata.update(context)
        return self.loop.step(context)

    def stream_response(
        self, session_id: str, user_message: str
    ) -> Generator[dict[str, Any], None, None]:
        """使用 Harness 处理用户消息并流式返回

        这个方法包装原始服务的 stream_response，在其之上添加
        PEV 循环的边界检查和状态管理。

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
        }
