"""Harness 适配器

将现有 Agent 包装为 Harness 兼容格式，允许渐进式迁移。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, TypeVar, runtime_checkable

from agent_hub.harness.loop.machine import HarnessLoop
from agent_hub.harness.loop.types import LoopState, Plan

logger = logging.getLogger(__name__)

T = TypeVar("T")


@runtime_checkable
class AgentProtocol(Protocol):
    """Agent 协议

    现有 Agent 只需实现 execute 方法即可被适配。
    """

    def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """执行 Agent 逻辑"""
        ...


class HarnessAdapter:
    """适配器：将现有 Agent 包装为 Harness 兼容格式

    支持两种模式：
    1. 包装模式：将现有 Agent 的 execute 作为 Harness executor
    2. 委托模式：在 Harness 循环中调用原 Agent 方法

    Usage:
        # 包装现有 Agent
        adapter = HarnessAdapter(existing_agent, harness_loop)
        result = adapter.execute(context)

        # 或者使用工厂方法
        adapter = HarnessAdapter.wrap(existing_agent, planner, verifier, bounds)
    """

    def __init__(
        self,
        agent: AgentProtocol | Any,
        loop: HarnessLoop,
        *,
        pre_hook: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        post_hook: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ):
        """
        Args:
            agent: 原 Agent 实例
            loop: Harness 循环
            pre_hook: 执行前钩子，可修改上下文
            post_hook: 执行后钩子，可修改结果
        """
        self.agent = agent
        self.loop = loop
        self._pre_hook = pre_hook
        self._post_hook = post_hook

    def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """执行一轮 PEV 循环

        Args:
            context: 执行上下文

        Returns:
            执行结果
        """
        # 应用前置钩子
        if self._pre_hook:
            context = self._pre_hook(context)

        # 执行 Harness 循环
        result = self.loop.step(context)

        if result is None:
            result = {
                "error": "Loop halted",
                "summary": self.loop.get_summary(),
            }

        # 应用后置钩子
        if self._post_hook:
            result = self._post_hook(context, result)

        return result

    def run_until_halt(
        self,
        initial_context: dict[str, Any],
        input_fn: Callable[[], dict[str, Any] | None],
    ) -> list[dict[str, Any]]:
        """运行直到终止

        Args:
            initial_context: 初始上下文
            input_fn: 获取下一轮输入的函数

        Returns:
            所有轮次的结果列表
        """
        results: list[dict[str, Any]] = []
        context = initial_context

        while not self.loop.state.is_halted():
            result = self.execute(context)
            results.append(result)

            next_input = input_fn()
            if next_input is None:
                break

            context = {**context, **next_input}

        return results

    def get_state(self) -> LoopState:
        """获取当前状态"""
        return self.loop.state

    def reset(self) -> None:
        """重置状态机"""
        self.loop.reset()

    @classmethod
    def wrap(
        cls,
        agent: AgentProtocol | Any,
        planner: Any,
        verifier: Any,
        bounds: Any | None = None,
        executor_method: str = "execute",
    ) -> "HarnessAdapter":
        """工厂方法：快速包装现有 Agent

        自动将 Agent 的指定方法包装为 Harness executor。

        Args:
            agent: 原 Agent 实例
            planner: 规划器
            verifier: 校验器
            bounds: 边界约束
            executor_method: 用作 executor 的方法名

        Returns:
            HarnessAdapter 实例
        """

        def executor(plan: Plan, state: LoopState) -> dict[str, Any]:
            # 将 plan 信息注入到 context
            method = getattr(agent, executor_method)
            context = {
                "plan": plan,
                "state": state,
                "intent": plan.intent,
                "tool_calls": plan.tool_calls,
            }
            return method(context)

        loop = HarnessLoop(
            planner=planner,
            verifier=verifier,
            executor=executor,
            bounds=bounds,
        )

        return cls(agent, loop)


class PassthroughAdapter(HarnessAdapter):
    """透传适配器

    直接调用原 Agent 的 execute 方法，不经过 PEV 循环。
    用于需要逐步迁移的场景。
    """

    def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """直接执行原 Agent 逻辑"""
        if hasattr(self.agent, "execute"):
            return self.agent.execute(context)
        raise NotImplementedError("Agent must implement execute method")


class DualModeAdapter(HarnessAdapter):
    """双模适配器

    支持在 Harness 模式和直接模式之间切换。
    """

    def __init__(
        self,
        agent: AgentProtocol | Any,
        loop: HarnessLoop,
        *,
        use_harness: bool = True,
        fallback_method: str = "execute",
        **kwargs,
    ):
        super().__init__(agent, loop, **kwargs)
        self._use_harness = use_harness
        self._fallback_method = fallback_method

    @property
    def use_harness(self) -> bool:
        """是否使用 Harness 模式"""
        return self._use_harness

    @use_harness.setter
    def use_harness(self, value: bool) -> None:
        self._use_harness = value
        if value:
            logger.info("Switched to Harness mode")
        else:
            logger.info("Switched to direct mode")

    def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """根据模式选择执行方式"""
        if self._use_harness:
            return super().execute(context)
        else:
            method = getattr(self.agent, self._fallback_method)
            return method(context)
