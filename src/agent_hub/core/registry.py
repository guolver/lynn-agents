"""线程安全的进程内 Agent 注册表。

本地注册表适合 MVP 和单进程部署。未来若 Agent 分布在不同服务中，可以保留
同一查询/调用接口，把实现替换成数据库目录与 RPC 客户端。
"""

from __future__ import annotations

import re
from threading import RLock
from typing import Any

from .contracts import (
    ActionDefinition,
    ActionNotFoundError,
    Agent,
    AgentManifest,
    AgentNotFoundError,
    DuplicateAgentError,
    ExecutionContext,
    InvalidInvocationError,
)


AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")


class AgentRegistry:
    """管理 Agent 生命周期，并在调用前统一执行平台级约束。"""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._lock = RLock()

    def register(self, agent: Agent, *, replace: bool = False) -> None:
        manifest = agent.manifest
        if not AGENT_ID_PATTERN.fullmatch(manifest.agent_id):
            raise InvalidInvocationError(
                "agent_id must be 3-64 lowercase letters, digits, dots, dashes or underscores"
            )
        action_names = [action.name for action in agent.actions()]
        if len(action_names) != len(set(action_names)):
            raise InvalidInvocationError(f"agent {manifest.agent_id} declares duplicate actions")
        with self._lock:
            if manifest.agent_id in self._agents and not replace:
                raise DuplicateAgentError(f"agent {manifest.agent_id} is already registered")
            self._agents[manifest.agent_id] = agent

    def unregister(self, agent_id: str) -> None:
        with self._lock:
            if self._agents.pop(agent_id, None) is None:
                raise AgentNotFoundError(f"agent {agent_id} not found")

    def get(self, agent_id: str) -> Agent:
        with self._lock:
            agent = self._agents.get(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"agent {agent_id} not found")
        return agent

    def manifests(self) -> list[AgentManifest]:
        with self._lock:
            manifests = [agent.manifest for agent in self._agents.values()]
        return sorted(manifests, key=lambda item: item.agent_id)

    def describe(self, agent_id: str) -> dict[str, Any]:
        agent = self.get(agent_id)
        return {
            **agent.manifest.to_dict(),
            "actions": [action.to_dict() for action in agent.actions()],
        }

    def invoke(
        self,
        agent_id: str,
        action_name: str,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        agent = self.get(agent_id)
        action = self._find_action(agent.actions(), action_name)
        if action.requires_idempotency_key and not context.idempotency_key:
            raise InvalidInvocationError(
                f"action {action_name} requires an Idempotency-Key header"
            )
        self._validate_required_fields(action, payload)
        # Registry 只允许 manifest 中声明的动作，避免把 Agent 变成任意代码执行入口。
        return agent.invoke(action_name, payload, context)

    @staticmethod
    def _find_action(
        actions: tuple[ActionDefinition, ...], action_name: str
    ) -> ActionDefinition:
        for action in actions:
            if action.name == action_name:
                return action
        raise ActionNotFoundError(f"action {action_name} is not exposed by this agent")

    @staticmethod
    def _validate_required_fields(
        action: ActionDefinition, payload: dict[str, Any]
    ) -> None:
        """执行平台能可靠完成的最小 Schema 校验。

        完整类型和业务约束仍由 Agent 负责；平台只统一处理 manifest 中的
        ``required`` 字段，确保缺参不会变成内部 500 错误。
        """
        required = action.input_schema.get("required", [])
        missing = [field for field in required if payload.get(field) is None]
        if missing:
            raise InvalidInvocationError(
                f"missing required payload fields: {', '.join(sorted(missing))}"
            )

