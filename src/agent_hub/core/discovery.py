"""从 Python entry point 可选加载第三方 Agent 插件。"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Iterable

from .contracts import Agent, InvalidInvocationError
from .registry import AgentRegistry


ENTRY_POINT_GROUP = "agent_hub.agents"


def discover_agents(
    registry: AgentRegistry,
    *,
    allowed_plugins: Iterable[str] | None = None,
) -> list[str]:
    """加载并注册已安装的 Agent 插件，返回 entry point 名称。

    加载插件会执行第三方 Python 代码，所以应用默认不会自动调用本函数。
    生产环境应传入 allowlist，并在隔离 worker 中运行不受信任的 Agent。
    Entry point 可以直接导出 Agent 实例，也可以导出一个无参数工厂。
    """

    allowlist = set(allowed_plugins) if allowed_plugins is not None else None
    selected = entry_points().select(group=ENTRY_POINT_GROUP)
    loaded_names: list[str] = []
    for entry_point in selected:
        if allowlist is not None and entry_point.name not in allowlist:
            continue
        exported = entry_point.load()
        candidate = exported if isinstance(exported, Agent) else exported()
        if not isinstance(candidate, Agent):
            raise InvalidInvocationError(
                f"plugin {entry_point.name} does not implement the Agent protocol"
            )
        registry.register(candidate)
        loaded_names.append(entry_point.name)
    return loaded_names

