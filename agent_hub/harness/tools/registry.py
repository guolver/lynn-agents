"""工具注册表"""

import logging
from typing import Any, Callable

from agent_hub.harness.tools.spec import Tool, ToolSpec

logger = logging.getLogger(__name__)


class ToolNotFoundError(Exception):
    """工具未找到"""

    def __init__(self, name: str, available: list[str]):
        self.name = name
        self.available = available
        super().__init__(f"Tool '{name}' not found. Available: {available}")


class ToolRegistry:
    """工具注册表

    管理工具的注册、查询和调用。

    Usage:
        registry = ToolRegistry()

        # 装饰器注册
        @registry.register(
            name="search",
            description="搜索知识库",
            parameters={
                "query": {"type": "str", "required": True, "description": "搜索词"},
                "limit": {"type": "int", "required": False, "default": 10}
            }
        )
        def search(query: str, limit: int = 10):
            ...

        # 调用
        result = registry.call("search", query="redis")

        # 获取所有工具规约（用于 LLM）
        specs = registry.specs()
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, dict[str, Any]] | None = None,
        returns: str = "",
        examples: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
    ) -> Callable[[Callable], Callable]:
        """
        装饰器：注册工具。

        Args:
            name: 工具名称
            description: 工具描述
            parameters: 参数定义
            returns: 返回值描述
            examples: 使用示例
            tags: 标签

        Returns:
            装饰器函数
        """
        def decorator(func: Callable) -> Callable:
            spec = ToolSpec(
                name=name,
                description=description,
                parameters=parameters or {},
                returns=returns,
                examples=examples or [],
                tags=tags or [],
            )
            self._tools[name] = Tool(spec, func)
            logger.debug("Registered tool: %s", name)
            return func

        return decorator

    def register_tool(self, tool: Tool) -> "ToolRegistry":
        """
        直接注册工具实例。

        Args:
            tool: 工具实例

        Returns:
            self（支持链式调用）
        """
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)
        return self

    def register_function(
        self,
        name: str,
        func: Callable,
        description: str = "",
        parameters: dict[str, dict[str, Any]] | None = None,
    ) -> "ToolRegistry":
        """
        注册函数为工具。

        Args:
            name: 工具名称
            func: 函数
            description: 描述
            parameters: 参数定义

        Returns:
            self
        """
        spec = ToolSpec(
            name=name,
            description=description or func.__doc__ or "",
            parameters=parameters or {},
        )
        self._tools[name] = Tool(spec, func)
        return self

    def call(self, name: str, **kwargs) -> Any:
        """
        调用工具。

        Args:
            name: 工具名称
            **kwargs: 参数

        Returns:
            工具执行结果

        Raises:
            ToolNotFoundError: 工具未找到
        """
        if name not in self._tools:
            raise ToolNotFoundError(name, list(self._tools.keys()))

        tool = self._tools[name]
        logger.debug("Calling tool: %s with %s", name, kwargs)

        result = tool(**kwargs)
        logger.debug("Tool %s returned: %s", name, type(result).__name__)

        return result

    def get(self, name: str) -> Tool | None:
        """获取工具实例"""
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        """获取所有工具规约"""
        return [tool.spec for tool in self._tools.values()]

    def to_openai_functions(self) -> list[dict[str, Any]]:
        """转换为 OpenAI Function Calling 格式"""
        return [tool.spec.to_openai_function() for tool in self._tools.values()]

    def names(self) -> list[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        """检查工具是否存在"""
        return name in self._tools

    def remove(self, name: str) -> bool:
        """移除工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def clear(self) -> None:
        """清空所有工具"""
        self._tools.clear()

    def merge(self, other: "ToolRegistry") -> "ToolRegistry":
        """合并另一个注册表"""
        for tool in other._tools.values():
            self._tools[tool.name] = tool
        return self

    def filter_by_tags(self, tags: list[str]) -> list[ToolSpec]:
        """按标签过滤工具"""
        return [
            tool.spec for tool in self._tools.values()
            if any(tag in tool.spec.tags for tag in tags)
        ]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self):
        return iter(self._tools.values())
