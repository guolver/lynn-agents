"""校验器协议与实现"""

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from agent_hub.harness.loop.types import Bounds, LoopState, Plan, VerifyResult


@runtime_checkable
class Verifier(Protocol):
    """校验器协议"""

    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        """
        校验执行计划是否合法。

        Args:
            plan: 待校验的计划
            state: 当前状态

        Returns:
            VerifyResult: 校验结果
        """
        ...

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        """
        校验执行结果是否合法。

        Args:
            result: 执行结果
            plan: 执行的计划
            state: 当前状态

        Returns:
            VerifyResult: 校验结果
        """
        ...


class BaseVerifier(ABC):
    """校验器基类"""

    @abstractmethod
    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        """校验计划"""
        ...

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        """校验结果，默认通过"""
        return VerifyResult.ok()


class BoundsVerifier(BaseVerifier):
    """边界约束校验器

    检查计划是否符合边界约束。
    """

    def __init__(
        self,
        bounds: Bounds,
        allowed_tools: frozenset[str] | None = None,
        allowed_subagents: frozenset[str] | None = None,
        allowed_intents: frozenset[str] | None = None,
    ):
        """
        Args:
            bounds: 边界约束
            allowed_tools: 允许的工具集
            allowed_subagents: 允许的子 Agent 集
            allowed_intents: 允许的意图集
        """
        self._bounds = bounds
        self._allowed_tools = allowed_tools
        self._allowed_subagents = allowed_subagents
        self._allowed_intents = allowed_intents

    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        """校验计划是否符合边界约束"""
        # 检查工具调用数量
        if len(plan.tool_calls) > self._bounds.max_tool_calls_per_turn:
            return VerifyResult.fail(
                f"Tool calls ({len(plan.tool_calls)}) exceed limit "
                f"({self._bounds.max_tool_calls_per_turn})",
                suggestions=["减少工具调用数量", "分多轮执行"],
            )

        # 检查工具白名单
        if self._allowed_tools is not None:
            disallowed = set(plan.tool_calls) - self._allowed_tools
            if disallowed:
                return VerifyResult.fail(
                    f"Disallowed tools: {disallowed}",
                    suggestions=[f"使用允许的工具: {self._allowed_tools}"],
                )

        # 检查子 Agent 白名单
        if plan.subagent and self._allowed_subagents is not None:
            if plan.subagent not in self._allowed_subagents:
                return VerifyResult.fail(
                    f"Disallowed subagent: {plan.subagent}",
                    suggestions=[f"使用允许的子Agent: {self._allowed_subagents}"],
                )

        # 检查意图白名单
        if self._allowed_intents is not None:
            if plan.intent not in self._allowed_intents:
                return VerifyResult.fail(
                    f"Disallowed intent: {plan.intent}",
                    suggestions=[f"使用允许的意图: {self._allowed_intents}"],
                )

        return VerifyResult.ok()

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        """校验结果"""
        # 检查是否有错误
        if result.get("error"):
            return VerifyResult.fail(
                f"Execution error: {result['error']}",
                suggestions=["检查输入参数", "重试执行"],
            )

        return VerifyResult.ok()


class CompositeVerifier(BaseVerifier):
    """组合校验器

    按顺序执行多个校验器，任一失败则返回失败。
    """

    def __init__(self, verifiers: list[Verifier]):
        self._verifiers = verifiers

    def add(self, verifier: Verifier) -> "CompositeVerifier":
        """添加校验器"""
        self._verifiers.append(verifier)
        return self

    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        """依次校验计划"""
        for verifier in self._verifiers:
            result = verifier.verify_plan(plan, state)
            if not result.passed:
                return result
        return VerifyResult.ok()

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        """依次校验结果"""
        for verifier in self._verifiers:
            verify_result = verifier.verify_result(result, plan, state)
            if not verify_result.passed:
                return verify_result
        return VerifyResult.ok()


class SchemaVerifier(BaseVerifier):
    """Schema 校验器

    校验结果是否符合预期 Schema。
    """

    def __init__(self, result_schemas: dict[str, dict[str, Any]] | None = None):
        """
        Args:
            result_schemas: 意图到结果 Schema 的映射
        """
        self._schemas = result_schemas or {}

    def verify_plan(self, plan: Plan, state: LoopState) -> VerifyResult:
        """计划校验，默认通过"""
        return VerifyResult.ok()

    def verify_result(
        self, result: dict[str, Any], plan: Plan, state: LoopState
    ) -> VerifyResult:
        """校验结果是否符合 Schema"""
        schema = self._schemas.get(plan.intent)
        if schema is None:
            return VerifyResult.ok()

        # 检查必填字段
        required = schema.get("required", [])
        missing = [f for f in required if f not in result]
        if missing:
            return VerifyResult.fail(
                f"Missing required fields: {missing}",
                suggestions=[f"确保返回以下字段: {required}"],
            )

        return VerifyResult.ok()
