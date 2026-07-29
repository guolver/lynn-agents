"""Mock Interview Agent Harness 配置

定义模拟面试 Agent 的 Harness 配置，包括边界约束和规划器。
"""

from __future__ import annotations

from typing import Any

from agent_hub.harness.loop.planner import RulePlanner
from agent_hub.harness.loop.types import Bounds, LoopState, Plan, VerifyResult
from agent_hub.harness.loop.verifier import BaseVerifier

# =============================================================================
# 边界约束
# =============================================================================

MOCK_INTERVIEW_BOUNDS = Bounds(
    max_turns=20,
    max_replans=3,
    max_tool_calls_per_turn=3,
    token_budget=8000,
    compaction_ratio=0.85,
    single_output_cap=500,
)

# =============================================================================
# 意图定义
# =============================================================================

# 面试流程意图
INTENT_START_INTERVIEW = "start_interview"
INTENT_ASK_QUESTION = "ask_question"
INTENT_FOLLOW_UP = "follow_up"
INTENT_EVALUATE = "evaluate"
INTENT_COMPLETE = "complete"
INTENT_PROCESS = "process"

ALLOWED_INTENTS = frozenset({
    INTENT_START_INTERVIEW,
    INTENT_ASK_QUESTION,
    INTENT_FOLLOW_UP,
    INTENT_EVALUATE,
    INTENT_COMPLETE,
    INTENT_PROCESS,
})


# =============================================================================
# 规划器
# =============================================================================


def _is_start_action(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是开始面试动作"""
    return context.get("action") == "start" or context.get("intent") == "start_interview"


def _is_question_action(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是提问动作"""
    return context.get("action") == "question" or context.get("intent") == "ask_question"


def _is_evaluate_action(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是评估动作"""
    return context.get("action") == "evaluate" or context.get("intent") == "evaluate"


def _is_complete_action(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否是完成动作"""
    action = context.get("action")
    intent = context.get("intent")
    return action == "complete" or intent == "complete" or action == "end"


def _is_follow_up_needed(state: LoopState, context: dict[str, Any]) -> bool:
    """判断是否需要追问"""
    # 基于之前的回答质量判断
    last_result = context.get("last_result", {})
    answer_quality = last_result.get("answer_quality", 1.0)
    return answer_quality < 0.6 and state.turn < 5


MOCK_INTERVIEW_PLANNER = RulePlanner(
    rules=[
        (INTENT_START_INTERVIEW, _is_start_action),
        (INTENT_COMPLETE, _is_complete_action),
        (INTENT_EVALUATE, _is_evaluate_action),
        (INTENT_FOLLOW_UP, _is_follow_up_needed),
        (INTENT_ASK_QUESTION, _is_question_action),
    ],
    default_intent=INTENT_PROCESS,
)


# =============================================================================
# 校验器
# =============================================================================


class MockInterviewVerifier(BaseVerifier):
    """模拟面试校验器

    校验面试流程的合法性。
    """

    def __init__(self, max_questions: int = 10):
        """
        Args:
            max_questions: 最大问题数
        """
        self._max_questions = max_questions

    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        """校验计划合法性"""
        # 检查意图是否允许
        if plan.intent not in ALLOWED_INTENTS:
            return VerifyResult.fail(
                f"Unknown intent: {plan.intent}",
                suggestions=[f"Use one of: {list(ALLOWED_INTENTS)}"],
            )

        # 检查完成前是否至少问了一个问题
        if plan.intent == INTENT_COMPLETE and state.turn < 1:
            return VerifyResult.fail(
                "Cannot complete interview without asking any questions",
                suggestions=["Ask at least one question first"],
            )

        return VerifyResult.ok()

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        """校验执行结果"""
        # 检查结果是否包含错误
        if result.get("error"):
            return VerifyResult.fail(
                f"Execution error: {result['error']}",
                suggestions=["Retry with different parameters"],
            )

        # 检查生成的内容是否为空
        if plan.intent == INTENT_ASK_QUESTION:
            question = result.get("question", "")
            if not question:
                return VerifyResult.fail(
                    "Generated question is empty",
                    suggestions=["Regenerate question with more context"],
                )

        return VerifyResult.ok()


class PassthroughVerifier(BaseVerifier):
    """透传校验器

    始终通过，用于逐步迁移阶段。
    """

    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        """始终通过"""
        return VerifyResult.ok()

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        """始终通过"""
        return VerifyResult.ok()


# =============================================================================
# 工具定义
# =============================================================================

MOCK_INTERVIEW_TOOLS = [
    {
        "name": "search_knowledge",
        "description": "从知识库搜索相关内容",
        "parameters": {
            "query": {"type": "string", "required": True, "description": "搜索关键词"},
            "limit": {"type": "integer", "required": False, "default": 5},
        },
    },
    {
        "name": "generate_question",
        "description": "生成面试问题",
        "parameters": {
            "category": {"type": "string", "required": True, "description": "问题类别"},
            "difficulty": {"type": "string", "required": False, "default": "medium"},
            "context": {"type": "string", "required": False, "description": "上下文信息"},
        },
    },
    {
        "name": "evaluate_answer",
        "description": "评估候选人回答",
        "parameters": {
            "question": {"type": "string", "required": True, "description": "问题"},
            "answer": {"type": "string", "required": True, "description": "回答"},
            "reference": {"type": "string", "required": False, "description": "参考答案"},
        },
    },
    {
        "name": "generate_summary",
        "description": "生成面试总结",
        "parameters": {
            "session_id": {"type": "string", "required": True, "description": "会话 ID"},
        },
    },
]

ALLOWED_TOOLS = frozenset(t["name"] for t in MOCK_INTERVIEW_TOOLS)
