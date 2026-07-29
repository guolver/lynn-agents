"""
Harness - Agent 执行框架

提供 PEV 状态机、子 Agent 隔离、分层记忆和上下文压缩等能力。
"""

from __future__ import annotations

from agent_hub.harness.adapter import (
    DualModeAdapter,
    HarnessAdapter,
    PassthroughAdapter,
)
from agent_hub.harness.loop.machine import HarnessLoop
from agent_hub.harness.loop.types import Bounds, LoopState, Phase, Plan
from agent_hub.harness.memory.base import MemoryService
from agent_hub.harness.memory.types import MemoryItem, MemoryKind, RecallQuery
from agent_hub.harness.mixins import (
    BoundsMixin,
    HarnessMixin,
    MemoryMixin,
    RetryConfig,
    RetryMixin,
    ToolRegistryMixin,
)
from agent_hub.harness.session.factory import SessionFactory
from agent_hub.harness.session.store import SessionStore
from agent_hub.harness.subagent.base import SubAgent, ToolPermissionError
from agent_hub.harness.subagent.types import SubResult, SubTask
from agent_hub.harness.tools.registry import ToolRegistry
from agent_hub.harness.tools.spec import Tool, ToolSpec

__all__ = [
    # Loop
    "HarnessLoop",
    "Phase",
    "LoopState",
    "Plan",
    "Bounds",
    # Adapter
    "HarnessAdapter",
    "PassthroughAdapter",
    "DualModeAdapter",
    # Mixins
    "HarnessMixin",
    "ToolRegistryMixin",
    "RetryMixin",
    "RetryConfig",
    "BoundsMixin",
    "MemoryMixin",
    # SubAgent
    "SubAgent",
    "SubTask",
    "SubResult",
    "ToolPermissionError",
    # Memory
    "MemoryService",
    "MemoryItem",
    "MemoryKind",
    "RecallQuery",
    # Tools
    "ToolRegistry",
    "ToolSpec",
    "Tool",
    # Session
    "SessionFactory",
    "SessionStore",
]
