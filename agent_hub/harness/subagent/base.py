"""子 Agent 基类"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from agent_hub.harness.subagent.types import SubResult, SubTask

logger = logging.getLogger(__name__)


class ToolPermissionError(Exception):
    """工具权限错误"""

    def __init__(self, tool_name: str, allowed_tools: frozenset[str]):
        self.tool_name = tool_name
        self.allowed_tools = allowed_tools
        super().__init__(
            f"Tool '{tool_name}' not in allowed_tools: {allowed_tools}"
        )


@runtime_checkable
class ToolRegistry(Protocol):
    """工具注册表协议"""

    def call(self, name: str, **kwargs) -> Any:
        """调用工具"""
        ...


@runtime_checkable
class ModelClient(Protocol):
    """模型客户端协议"""

    def chat(self, messages: list[dict[str, str]]) -> str:
        """发送消息并获取回复"""
        ...


class SubAgent(ABC):
    """子 Agent 基类

    提供权限隔离和上下文隔离能力。

    Features:
        - 工具权限白名单：只能调用 allowed_tools 中的工具
        - 历史隔离：每次执行有独立的 _history，执行后清空
        - 显式输入：通过 SubTask.inputs 传递，非共享内存
        - 摘要输出：只返回 SubResult.summary，不回传完整历史

    Usage:
        class MySubAgent(SubAgent):
            allowed_tools = frozenset(["search", "lookup"])

            def _run(self, task: SubTask) -> SubResult:
                # 使用 _call_tool 和 _ask_model
                result = self._call_tool("search", query=task.inputs["query"])
                ...
                return SubResult(summary="...", structured={...})
    """

    # 子类必须声明允许的工具
    allowed_tools: frozenset[str] = frozenset()

    # 子类可选声明名称和描述
    name: str = "unnamed"
    description: str = ""

    def __init__(
        self,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        system_prompt: str | None = None,
    ):
        """
        Args:
            model_client: LLM 客户端
            tool_registry: 工具注册表
            system_prompt: 系统提示词
        """
        self._model = model_client
        self._tools = tool_registry
        self._system_prompt = system_prompt
        self._history: list[dict[str, str]] = []
        self._tool_calls_count = 0
        self._tokens_used = 0

    def execute(self, task: SubTask) -> SubResult:
        """
        执行子任务。

        执行前清空历史，执行后销毁历史，确保隔离。

        Args:
            task: 子任务

        Returns:
            SubResult: 执行结果
        """
        start_time = time.time()
        self._reset()

        logger.info(
            "SubAgent %s executing task: %s",
            self.name,
            task.goal[:50],
        )

        try:
            result = self._run(task)
            result.tool_calls_made = self._tool_calls_count
            result.tokens_used = self._tokens_used

            elapsed = time.time() - start_time
            logger.info(
                "SubAgent %s completed: success=%s, tools=%d, elapsed=%.2fs",
                self.name,
                result.success,
                result.tool_calls_made,
                elapsed,
            )

            return result

        except ToolPermissionError as e:
            logger.error("SubAgent %s permission error: %s", self.name, e)
            return SubResult.failure(str(e))

        except Exception as e:
            logger.exception("SubAgent %s execution error: %s", self.name, e)
            return SubResult.failure(str(e))

        finally:
            # 确保历史被清空
            self._reset()

    def _reset(self) -> None:
        """重置内部状态"""
        self._history.clear()
        self._tool_calls_count = 0
        self._tokens_used = 0

    @abstractmethod
    def _run(self, task: SubTask) -> SubResult:
        """
        子类实现具体逻辑。

        可使用:
            - self._call_tool(name, **kwargs): 调用工具（会检查权限）
            - self._ask_model(messages): 调用模型（隔离历史）

        Args:
            task: 子任务

        Returns:
            SubResult: 执行结果
        """
        ...

    def _call_tool(self, name: str, **kwargs) -> Any:
        """
        调用工具（权限检查）。

        Args:
            name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果

        Raises:
            ToolPermissionError: 工具不在白名单中
        """
        if name not in self.allowed_tools:
            raise ToolPermissionError(name, self.allowed_tools)

        self._tool_calls_count += 1
        logger.debug("SubAgent %s calling tool: %s", self.name, name)

        return self._tools.call(name, **kwargs)

    def _ask_model(self, messages: list[dict[str, str]]) -> str:
        """
        调用模型（隔离历史）。

        消息会添加到隔离的 _history 中，执行完成后清空。

        Args:
            messages: 消息列表

        Returns:
            模型回复
        """
        # 构建完整消息列表
        full_messages = []

        if self._system_prompt:
            full_messages.append({"role": "system", "content": self._system_prompt})

        full_messages.extend(self._history)
        full_messages.extend(messages)

        # 调用模型
        reply = self._model.chat(full_messages)

        # 记录到隔离历史
        self._history.extend(messages)
        self._history.append({"role": "assistant", "content": reply})

        # 估算 Token（简单按字符估算）
        self._tokens_used += sum(len(m.get("content", "")) for m in messages)
        self._tokens_used += len(reply)

        return reply

    def _parse_json(self, text: str) -> dict[str, Any]:
        """解析 JSON 输出"""
        import json

        # 尝试提取 JSON 块
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()

        return json.loads(text)
