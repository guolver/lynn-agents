"""规划器协议与实现"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from agent_hub.harness.loop.types import LoopState, Plan


@runtime_checkable
class Planner(Protocol):
    """规划器协议"""

    def plan(self, state: LoopState, context: dict[str, Any]) -> Plan:
        """
        根据当前状态和上下文生成执行计划。

        Args:
            state: 当前状态机状态
            context: 执行上下文（包含用户输入、记忆等）

        Returns:
            Plan: 执行计划
        """
        ...


class BasePlanner(ABC):
    """规划器基类"""

    @abstractmethod
    def plan(self, state: LoopState, context: dict[str, Any]) -> Plan:
        """生成执行计划"""
        ...


class RulePlanner(BasePlanner):
    """基于规则的规划器

    根据预定义规则生成计划，不依赖 LLM。
    适用于流程固定的场景。
    """

    def __init__(
        self,
        rules: list[tuple[str, callable]] | None = None,
        default_intent: str = "process",
    ):
        """
        Args:
            rules: 规则列表，每个规则为 (intent, condition_fn) 元组
            default_intent: 默认意图
        """
        self._rules = rules or []
        self._default_intent = default_intent

    def add_rule(self, intent: str, condition: callable) -> "RulePlanner":
        """添加规则"""
        self._rules.append((intent, condition))
        return self

    def plan(self, state: LoopState, context: dict[str, Any]) -> Plan:
        """根据规则生成计划"""
        for intent, condition in self._rules:
            if condition(state, context):
                return Plan(
                    intent=intent,
                    metadata={"source": "rule", "turn": state.turn},
                )

        return Plan(
            intent=self._default_intent,
            metadata={"source": "default", "turn": state.turn},
        )


class LLMPlanner(BasePlanner):
    """基于 LLM 的规划器

    使用大语言模型生成执行计划。
    适用于需要理解复杂意图的场景。
    """

    def __init__(
        self,
        model_client: Any,
        system_prompt: str | None = None,
        available_intents: list[str] | None = None,
        available_tools: list[str] | None = None,
        available_subagents: list[str] | None = None,
    ):
        """
        Args:
            model_client: LLM 客户端
            system_prompt: 系统提示词
            available_intents: 可用意图列表
            available_tools: 可用工具列表
            available_subagents: 可用子 Agent 列表
        """
        self._model = model_client
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._available_intents = available_intents or []
        self._available_tools = available_tools or []
        self._available_subagents = available_subagents or []

    def _default_system_prompt(self) -> str:
        return """你是一个任务规划器。根据当前状态和用户输入，生成执行计划。

输出 JSON 格式：
{
    "intent": "意图标识",
    "tool_calls": ["工具1", "工具2"],
    "subagent": "子Agent名称或null",
    "query": "检索query或null"
}
"""

    def plan(self, state: LoopState, context: dict[str, Any]) -> Plan:
        """使用 LLM 生成计划"""
        import json

        prompt = self._build_prompt(state, context)

        response = self._model.chat([
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": prompt},
        ])

        try:
            data = json.loads(response)
            return Plan(
                intent=data.get("intent", "unknown"),
                tool_calls=data.get("tool_calls", []),
                subagent=data.get("subagent"),
                query=data.get("query"),
                metadata={"source": "llm", "turn": state.turn},
            )
        except json.JSONDecodeError:
            # 解析失败，返回默认计划
            return Plan(
                intent="error",
                metadata={"source": "llm_parse_error", "raw": response},
            )

    def _build_prompt(self, state: LoopState, context: dict[str, Any]) -> str:
        parts = [
            f"当前轮次: {state.turn}",
            f"可用意图: {self._available_intents}",
            f"可用工具: {self._available_tools}",
            f"可用子Agent: {self._available_subagents}",
        ]

        if "message" in context:
            parts.append(f"用户输入: {context['message']}")

        if state.errors:
            parts.append(f"历史错误: {state.errors[-3:]}")

        return "\n".join(parts)
