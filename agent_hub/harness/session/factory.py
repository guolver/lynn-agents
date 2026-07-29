"""会话工厂"""

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Type

from agent_hub.harness.context.assembler import ContextAssembler
from agent_hub.harness.context.compaction import CompactionPipeline
from agent_hub.harness.loop.machine import HarnessLoop
from agent_hub.harness.loop.planner import Planner, RulePlanner
from agent_hub.harness.loop.types import Bounds, Plan
from agent_hub.harness.loop.verifier import BoundsVerifier, Verifier
from agent_hub.harness.memory.base import MemoryService
from agent_hub.harness.memory.episodic import EpisodicMemory, JsonlEpisodicBackend
from agent_hub.harness.memory.procedural import ProceduralMemory
from agent_hub.harness.memory.semantic import SemanticMemory
from agent_hub.harness.memory.working import WorkingMemory
from agent_hub.harness.subagent.base import SubAgent
from agent_hub.harness.subagent.registry import SubAgentRegistry
from agent_hub.harness.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class SessionConfig:
    """会话配置"""

    bounds: Bounds = field(default_factory=Bounds)
    """执行边界"""

    base_dir: Path = field(default_factory=lambda: Path("./sessions"))
    """会话数据根目录"""

    persist_episodic: bool = True
    """是否持久化情景记忆"""

    system_prompt: str = ""
    """默认系统提示词"""

    rules: list[str] = field(default_factory=list)
    """全局规则"""


class SessionFactory:
    """会话工厂

    为每个会话创建隔离的 Harness 实例。

    Features:
        - 隔离的记忆空间
        - 独立的子 Agent 实例
        - 可配置的规划器和校验器
        - 会话级持久化

    Usage:
        factory = SessionFactory(
            model_client=openai_client,
            tool_registry=tools,
            subagent_classes={"examiner": ExaminerAgent},
        )

        loop = factory.build("session-123", role="backend", difficulty=3)
        result = loop.step({"message": "你好"})
    """

    def __init__(
        self,
        model_client: Any,
        tool_registry: ToolRegistry,
        subagent_classes: dict[str, Type[SubAgent]] | None = None,
        planner_factory: Callable[..., Planner] | None = None,
        verifier_factory: Callable[..., Verifier] | None = None,
        config: SessionConfig | None = None,
    ):
        """
        Args:
            model_client: LLM 客户端
            tool_registry: 工具注册表
            subagent_classes: 子 Agent 类映射
            planner_factory: 规划器工厂函数
            verifier_factory: 校验器工厂函数
            config: 会话配置
        """
        self._model = model_client
        self._tools = tool_registry
        self._subagent_classes = subagent_classes or {}
        self._planner_factory = planner_factory
        self._verifier_factory = verifier_factory
        self._config = config or SessionConfig()

    def build(self, session_id: str | None = None, **kwargs) -> HarnessLoop:
        """
        构建会话实例。

        Args:
            session_id: 会话 ID（可选，自动生成）
            **kwargs: 会话参数

        Returns:
            HarnessLoop: 配置好的状态机实例
        """
        if session_id is None:
            session_id = str(uuid.uuid4())[:8]

        logger.info("Building session: %s", session_id)

        # 创建会话目录
        session_dir = self._config.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # 创建记忆系统
        memory = self._build_memory(session_id, session_dir)

        # 创建子 Agent 注册表
        subagent_registry = self._build_subagent_registry(memory, **kwargs)

        # 创建上下文组装器
        assembler = ContextAssembler(self._config.bounds.token_budget)
        assembler.set_system_prompt(
            kwargs.get("system_prompt", self._config.system_prompt)
        )
        if self._config.rules:
            assembler.set_rules(self._config.rules)

        # 创建压缩管道
        compactor = CompactionPipeline(self._model)

        # 创建规划器
        planner = self._build_planner(memory, subagent_registry, **kwargs)

        # 创建校验器
        verifier = self._build_verifier(**kwargs)

        # 创建执行器
        executor = self._build_executor(
            subagent_registry, memory, assembler, **kwargs
        )

        # Token 计数器
        def token_counter(state):
            return assembler.estimate_tokens()

        # 压缩函数
        def compact_fn(state):
            messages = assembler.assemble()
            target = int(self._config.bounds.token_budget * 0.7)
            result = compactor.compact(messages, target)
            assembler.set_messages(result.messages)
            logger.info(
                "Compacted: %d -> %d tokens, layers=%s",
                result.original_tokens,
                result.compressed_tokens,
                result.layers_applied,
            )

        # 组装状态机
        loop = HarnessLoop(
            planner=planner,
            verifier=verifier,
            executor=executor,
            bounds=self._config.bounds,
            token_counter=token_counter,
            compactor=compact_fn,
            session_id=session_id,
        )

        # 存储元数据
        loop.state.metadata = {
            "session_dir": str(session_dir),
            **kwargs,
        }

        logger.info("Session %s built successfully", session_id)

        return loop

    def _build_memory(self, session_id: str, session_dir: Path) -> MemoryService:
        """构建记忆系统"""
        working = WorkingMemory(max_items=100)

        if self._config.persist_episodic:
            episodic_backend = JsonlEpisodicBackend(session_dir / "episodic.jsonl")
            episodic = EpisodicMemory(session_id, persist_backend=episodic_backend)
        else:
            episodic = EpisodicMemory(session_id)

        semantic = SemanticMemory()
        procedural = ProceduralMemory()

        return MemoryService(
            working=working,
            episodic=episodic,
            semantic=semantic,
            procedural=procedural,
        )

    def _build_subagent_registry(
        self, memory: MemoryService, **kwargs
    ) -> SubAgentRegistry:
        """构建子 Agent 注册表"""
        registry = SubAgentRegistry(self._model, self._tools)

        for name, cls in self._subagent_classes.items():
            registry.register(name, cls)

        return registry

    def _build_planner(
        self,
        memory: MemoryService,
        subagents: SubAgentRegistry,
        **kwargs,
    ) -> Planner:
        """构建规划器"""
        if self._planner_factory:
            return self._planner_factory(memory, subagents, **kwargs)

        # 默认规则规划器
        return RulePlanner(default_intent="process")

    def _build_verifier(self, **kwargs) -> Verifier:
        """构建校验器"""
        if self._verifier_factory:
            return self._verifier_factory(**kwargs)

        # 默认边界校验器
        return BoundsVerifier(
            bounds=self._config.bounds,
            allowed_tools=frozenset(self._tools.names()),
            allowed_subagents=frozenset(self._subagent_classes.keys()),
        )

    def _build_executor(
        self,
        subagents: SubAgentRegistry,
        memory: MemoryService,
        assembler: ContextAssembler,
        **kwargs,
    ) -> Callable:
        """构建执行器"""

        def executor(plan: Plan, state) -> dict[str, Any]:
            result = {"intent": plan.intent}

            # 如果有子 Agent，委托执行
            if plan.subagent and subagents.has(plan.subagent):
                from agent_hub.harness.subagent.types import SubTask

                task = SubTask(
                    goal=plan.intent,
                    inputs=plan.metadata,
                )
                sub_result = subagents.execute(plan.subagent, task)
                result["subagent_result"] = {
                    "summary": sub_result.summary,
                    "structured": sub_result.structured,
                    "success": sub_result.success,
                }

            # 执行工具调用
            if plan.tool_calls:
                tool_results = []
                for tool_name in plan.tool_calls:
                    try:
                        tool_result = self._tools.call(
                            tool_name,
                            **plan.metadata.get("tool_args", {}).get(tool_name, {}),
                        )
                        tool_results.append({
                            "tool": tool_name,
                            "output": tool_result,
                            "success": True,
                        })
                    except Exception as e:
                        tool_results.append({
                            "tool": tool_name,
                            "error": str(e),
                            "success": False,
                        })

                result["tool_results"] = tool_results

            return result

        return executor
