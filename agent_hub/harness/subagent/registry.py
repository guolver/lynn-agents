"""子 Agent 注册表"""

import logging
from typing import Any, Callable, Type

from agent_hub.harness.subagent.base import ModelClient, SubAgent, ToolRegistry
from agent_hub.harness.subagent.types import SubResult, SubTask

logger = logging.getLogger(__name__)


class SubAgentRegistry:
    """子 Agent 注册表

    管理子 Agent 的注册、实例化和调用。

    Usage:
        registry = SubAgentRegistry(model_client, tool_registry)

        # 注册子 Agent 类
        registry.register("examiner", ExaminerAgent)
        registry.register("grader", GraderAgent)

        # 或使用装饰器
        @registry.subagent("examiner")
        class ExaminerAgent(SubAgent):
            ...

        # 调用
        result = registry.execute("examiner", SubTask(goal="出一道题"))
    """

    def __init__(
        self,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
    ):
        """
        Args:
            model_client: LLM 客户端（注入到所有子 Agent）
            tool_registry: 工具注册表（注入到所有子 Agent）
        """
        self._model = model_client
        self._tools = tool_registry
        self._classes: dict[str, Type[SubAgent]] = {}
        self._instances: dict[str, SubAgent] = {}
        self._factories: dict[str, Callable[..., SubAgent]] = {}

    def register(
        self,
        name: str,
        agent_class: Type[SubAgent],
        **kwargs,
    ) -> "SubAgentRegistry":
        """
        注册子 Agent 类。

        Args:
            name: 子 Agent 名称
            agent_class: 子 Agent 类
            **kwargs: 实例化参数

        Returns:
            self（支持链式调用）
        """
        self._classes[name] = agent_class

        # 创建工厂函数
        def factory(model=self._model, tools=self._tools, **kw):
            merged_kwargs = {**kwargs, **kw}
            return agent_class(model, tools, **merged_kwargs)

        self._factories[name] = factory
        logger.info("Registered SubAgent: %s -> %s", name, agent_class.__name__)
        return self

    def register_factory(
        self,
        name: str,
        factory: Callable[..., SubAgent],
    ) -> "SubAgentRegistry":
        """
        注册子 Agent 工厂函数。

        Args:
            name: 子 Agent 名称
            factory: 工厂函数

        Returns:
            self
        """
        self._factories[name] = factory
        logger.info("Registered SubAgent factory: %s", name)
        return self

    def subagent(self, name: str, **kwargs) -> Callable[[Type[SubAgent]], Type[SubAgent]]:
        """
        装饰器：注册子 Agent 类。

        Usage:
            @registry.subagent("examiner")
            class ExaminerAgent(SubAgent):
                ...
        """
        def decorator(cls: Type[SubAgent]) -> Type[SubAgent]:
            self.register(name, cls, **kwargs)
            return cls
        return decorator

    def get(self, name: str, **kwargs) -> SubAgent:
        """
        获取子 Agent 实例。

        如果已有实例则返回，否则创建新实例。

        Args:
            name: 子 Agent 名称
            **kwargs: 额外参数

        Returns:
            子 Agent 实例
        """
        if name not in self._factories:
            raise KeyError(f"SubAgent not found: {name}")

        # 如果没有额外参数，使用缓存实例
        if not kwargs:
            if name not in self._instances:
                self._instances[name] = self._factories[name]()
            return self._instances[name]

        # 有额外参数，创建新实例
        return self._factories[name](**kwargs)

    def execute(self, name: str, task: SubTask, **kwargs) -> SubResult:
        """
        执行子 Agent 任务。

        Args:
            name: 子 Agent 名称
            task: 子任务
            **kwargs: 额外参数

        Returns:
            SubResult: 执行结果
        """
        agent = self.get(name, **kwargs)
        return agent.execute(task)

    def list(self) -> list[dict[str, Any]]:
        """列出所有注册的子 Agent"""
        result = []
        for name in self._factories:
            cls = self._classes.get(name)
            result.append({
                "name": name,
                "class": cls.__name__ if cls else "factory",
                "allowed_tools": list(cls.allowed_tools) if cls else [],
                "description": cls.description if cls else "",
            })
        return result

    def has(self, name: str) -> bool:
        """检查子 Agent 是否已注册"""
        return name in self._factories

    def clear(self) -> None:
        """清空注册表"""
        self._classes.clear()
        self._instances.clear()
        self._factories.clear()
