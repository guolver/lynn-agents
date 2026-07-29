"""Harness Mixins

提供可组合的 Harness 能力，允许现有 Agent 选择性地使用。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from agent_hub.harness.loop.types import Bounds, LoopState
from agent_hub.harness.memory.base import MemoryService
from agent_hub.harness.memory.types import MemoryItem, MemoryKind, RecallQuery
from agent_hub.harness.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Tool Registry Mixin
# =============================================================================


class ToolRegistryMixin:
    """工具注册能力 Mixin

    为 Agent 提供工具注册和调用能力。

    Usage:
        class MyAgent(ToolRegistryMixin):
            def __init__(self):
                self.init_tool_registry()
                self.register_tools()

            def register_tools(self):
                @self.tool_registry.register(
                    name="search",
                    description="搜索",
                    parameters={"query": {"type": "string"}}
                )
                def search(query: str):
                    return {"results": [...]}
    """

    tool_registry: ToolRegistry

    def init_tool_registry(self) -> None:
        """初始化工具注册表"""
        self.tool_registry = ToolRegistry()

    def call_tool(self, name: str, **kwargs) -> Any:
        """调用已注册的工具

        Args:
            name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果
        """
        return self.tool_registry.call(name, **kwargs)

    def get_tool_specs(self) -> list[dict[str, Any]]:
        """获取所有工具的 OpenAI Function Calling 格式规约"""
        return self.tool_registry.to_openai_functions()

    def get_tool_names(self) -> list[str]:
        """获取所有工具名称"""
        return self.tool_registry.names()


# =============================================================================
# Retry Mixin
# =============================================================================


@dataclass
class RetryConfig:
    """重试配置"""

    max_retries: int = 3
    """最大重试次数"""

    backoff_factor: float = 1.5
    """退避因子"""

    initial_delay: float = 0.5
    """初始延迟（秒）"""

    max_delay: float = 30.0
    """最大延迟（秒）"""

    retryable_errors: tuple[type[Exception], ...] = (Exception,)
    """可重试的异常类型"""


class RetryMixin:
    """重试与重规划能力 Mixin

    提供带退避的重试机制和重规划能力。

    Usage:
        class MyAgent(RetryMixin):
            def __init__(self):
                self.init_retry(RetryConfig(max_retries=3))

            def execute(self, context):
                return self.with_retry(self._do_work, context)
    """

    _retry_config: RetryConfig
    _retry_count: int = 0
    _replan_count: int = 0

    def init_retry(self, config: RetryConfig | None = None) -> None:
        """初始化重试配置"""
        self._retry_config = config or RetryConfig()
        self._retry_count = 0
        self._replan_count = 0

    def with_retry(
        self,
        fn: Callable[..., T],
        *args,
        on_retry: Callable[[Exception, int], None] | None = None,
        **kwargs,
    ) -> T:
        """带重试执行函数

        Args:
            fn: 要执行的函数
            *args: 函数参数
            on_retry: 重试回调
            **kwargs: 函数关键字参数

        Returns:
            函数执行结果
        """
        last_error: Exception | None = None
        delay = self._retry_config.initial_delay

        for attempt in range(self._retry_config.max_retries + 1):
            try:
                result = fn(*args, **kwargs)
                self._retry_count = 0  # 成功后重置
                return result
            except self._retry_config.retryable_errors as e:
                last_error = e
                self._retry_count = attempt + 1

                if attempt < self._retry_config.max_retries:
                    logger.warning(
                        "Attempt %d failed, retrying in %.1fs: %s",
                        attempt + 1,
                        delay,
                        e,
                    )

                    if on_retry:
                        on_retry(e, attempt + 1)

                    time.sleep(delay)
                    delay = min(
                        delay * self._retry_config.backoff_factor,
                        self._retry_config.max_delay,
                    )

        logger.error("All %d retries exhausted", self._retry_config.max_retries)
        raise last_error  # type: ignore[misc]

    def should_replan(self, error: Exception, state: LoopState) -> bool:
        """判断是否应该重规划

        Args:
            error: 发生的错误
            state: 当前状态

        Returns:
            是否应该重规划
        """
        # 默认策略：未超过最大重规划次数时重规划
        return state.replan_count < 3

    def get_retry_stats(self) -> dict[str, int]:
        """获取重试统计"""
        return {
            "retry_count": self._retry_count,
            "replan_count": self._replan_count,
        }


# =============================================================================
# Bounds Mixin
# =============================================================================


class BoundsMixin:
    """边界约束能力 Mixin

    提供执行边界检查和约束管理。

    Usage:
        class MyAgent(BoundsMixin):
            def __init__(self):
                self.init_bounds(Bounds(max_turns=20))

            def step(self, context):
                if not self.check_bounds():
                    return {"error": "Bounds exceeded"}
                ...
    """

    _bounds: Bounds
    _turn_count: int = 0
    _tool_calls_count: int = 0
    _token_count: int = 0

    def init_bounds(self, bounds: Bounds | None = None) -> None:
        """初始化边界约束"""
        self._bounds = bounds or Bounds()
        self._turn_count = 0
        self._tool_calls_count = 0
        self._token_count = 0

    @property
    def bounds(self) -> Bounds:
        """获取边界配置"""
        return self._bounds

    def check_bounds(self) -> bool:
        """检查是否在边界内

        Returns:
            是否在边界内
        """
        if self._turn_count >= self._bounds.max_turns:
            logger.warning("Max turns (%d) reached", self._bounds.max_turns)
            return False

        if self._token_count >= self._bounds.token_budget:
            logger.warning("Token budget (%d) exceeded", self._bounds.token_budget)
            return False

        return True

    def check_tool_calls(self) -> bool:
        """检查工具调用次数是否在限制内"""
        return self._tool_calls_count < self._bounds.max_tool_calls_per_turn

    def increment_turn(self) -> None:
        """增加轮次计数"""
        self._turn_count += 1
        self._tool_calls_count = 0  # 新轮次重置工具调用计数

    def increment_tool_calls(self) -> None:
        """增加工具调用计数"""
        self._tool_calls_count += 1

    def add_tokens(self, count: int) -> None:
        """增加 Token 计数"""
        self._token_count += count

    def should_compact(self) -> bool:
        """检查是否应该压缩上下文"""
        threshold = int(self._bounds.token_budget * self._bounds.compaction_ratio)
        return self._token_count > threshold

    def get_bounds_stats(self) -> dict[str, Any]:
        """获取边界统计"""
        return {
            "turn_count": self._turn_count,
            "max_turns": self._bounds.max_turns,
            "tool_calls_count": self._tool_calls_count,
            "max_tool_calls_per_turn": self._bounds.max_tool_calls_per_turn,
            "token_count": self._token_count,
            "token_budget": self._bounds.token_budget,
        }


# =============================================================================
# Memory Mixin
# =============================================================================


class MemoryMixin:
    """分层记忆能力 Mixin

    提供四层记忆管理能力。

    Usage:
        class MyAgent(MemoryMixin):
            def __init__(self, memory_service: MemoryService):
                self.init_memory(memory_service)

            def process(self, context):
                # 存储到工作记忆
                self.remember_working({"action": "search", "query": "..."})

                # 召回相关记忆
                memories = self.recall_all(tags=["search"])
    """

    _memory: MemoryService | None = None

    def init_memory(self, memory: MemoryService) -> None:
        """初始化记忆服务"""
        self._memory = memory

    @property
    def memory(self) -> MemoryService | None:
        """获取记忆服务"""
        return self._memory

    def remember_working(
        self,
        content: dict[str, Any],
        salience: float = 0.5,
        tags: list[str] | None = None,
    ) -> None:
        """存储到工作记忆

        Args:
            content: 记忆内容
            salience: 显著性
            tags: 标签
        """
        if self._memory is None:
            return

        item = MemoryItem(
            kind=MemoryKind.WORKING,
            content=content,
            salience=salience,
            tags=tags or [],
        )
        self._memory.remember(item)

    def remember_episodic(
        self,
        content: dict[str, Any],
        salience: float = 0.7,
        tags: list[str] | None = None,
    ) -> None:
        """存储到情景记忆

        Args:
            content: 记忆内容
            salience: 显著性
            tags: 标签
        """
        if self._memory is None:
            return

        item = MemoryItem(
            kind=MemoryKind.EPISODIC,
            content=content,
            salience=salience,
            tags=tags or [],
        )
        self._memory.remember(item)

    def remember_semantic(
        self,
        content: dict[str, Any],
        salience: float = 0.9,
        tags: list[str] | None = None,
    ) -> None:
        """存储到语义记忆

        Args:
            content: 记忆内容
            salience: 显著性
            tags: 标签
        """
        if self._memory is None:
            return

        item = MemoryItem(
            kind=MemoryKind.SEMANTIC,
            content=content,
            salience=salience,
            tags=tags or [],
        )
        self._memory.remember(item)

    def recall_working(
        self,
        limit: int = 10,
        tags: list[str] | None = None,
    ) -> list[MemoryItem]:
        """召回工作记忆

        Args:
            limit: 最大数量
            tags: 过滤标签

        Returns:
            记忆条目列表
        """
        if self._memory is None:
            return []

        query = RecallQuery(
            kinds=[MemoryKind.WORKING],
            limit=limit,
            tags=tags or [],
        )
        return self._memory.recall(query)

    def recall_all(
        self,
        limit: int = 20,
        tags: list[str] | None = None,
        min_salience: float = 0.3,
    ) -> list[MemoryItem]:
        """召回所有层级的记忆

        Args:
            limit: 最大数量
            tags: 过滤标签
            min_salience: 最小显著性

        Returns:
            记忆条目列表
        """
        if self._memory is None:
            return []

        query = RecallQuery(
            kinds=[
                MemoryKind.WORKING,
                MemoryKind.EPISODIC,
                MemoryKind.SEMANTIC,
                MemoryKind.PROCEDURAL,
            ],
            limit=limit,
            tags=tags or [],
            min_salience=min_salience,
        )
        return self._memory.recall(query)

    def clear_working_memory(self) -> None:
        """清空工作记忆"""
        if self._memory is not None:
            self._memory.clear_working()

    def promote_to_episodic(self, item: MemoryItem) -> MemoryItem | None:
        """将工作记忆提升到情景记忆

        Args:
            item: 待提升的记忆

        Returns:
            新创建的记忆条目
        """
        if self._memory is None:
            return None
        return self._memory.promote(item, MemoryKind.EPISODIC)


# =============================================================================
# Composite Mixin
# =============================================================================


class HarnessMixin(ToolRegistryMixin, RetryMixin, BoundsMixin, MemoryMixin):
    """组合 Mixin

    包含所有 Harness 能力的组合 Mixin。

    Usage:
        class MyAgent(HarnessMixin):
            def __init__(self, memory_service: MemoryService):
                self.init_harness(
                    bounds=Bounds(max_turns=20),
                    retry_config=RetryConfig(max_retries=3),
                    memory=memory_service,
                )
    """

    def init_harness(
        self,
        bounds: Bounds | None = None,
        retry_config: RetryConfig | None = None,
        memory: MemoryService | None = None,
    ) -> None:
        """初始化所有 Harness 能力

        Args:
            bounds: 边界约束
            retry_config: 重试配置
            memory: 记忆服务
        """
        self.init_tool_registry()
        self.init_retry(retry_config)
        self.init_bounds(bounds)
        if memory:
            self.init_memory(memory)

    def get_harness_stats(self) -> dict[str, Any]:
        """获取 Harness 统计"""
        return {
            **self.get_bounds_stats(),
            **self.get_retry_stats(),
            "memory_summary": self._memory.summarize() if self._memory else None,
        }
