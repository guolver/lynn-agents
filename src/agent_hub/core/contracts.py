"""所有业务 Agent 必须遵守的最小协议。

协议使用标准库 ``Protocol`` 和 dataclass，避免平台核心依赖某个 Web 框架或
LLM SDK。将来 Agent 可以运行在 FastAPI、任务队列或独立 worker 中。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from .security import Principal, Role


ActionMode = Literal["read", "write"]
RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class AgentManifest:
    """用于发现、展示和版本治理的 Agent 元数据。"""

    agent_id: str
    name: str
    version: str
    description: str
    tags: tuple[str, ...] = ()
    owner: str = "local"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        # JSON 没有 tuple；显式转换可让 API 契约更直观。
        value["tags"] = list(self.tags)
        return value


@dataclass(frozen=True)
class ActionDefinition:
    """一个 Agent 对平台公开的白名单动作，而不是任意方法调用。"""

    name: str
    description: str
    mode: ActionMode = "read"
    risk_level: RiskLevel = "low"
    requires_idempotency_key: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)
    allowed_roles: frozenset[Role] = frozenset({Role.ADMIN, Role.OPERATOR, Role.USER})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionContext:
    """平台传给 Agent 的调用身份和追踪信息。

    这里不存放数据库密码或模型密钥。后续接入 OAuth/RBAC 后，可继续增加
    tenant_id、roles 和 trace 信息，而无需改变各动作的业务输入。
    """

    principal: Principal
    request_id: str
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def actor(self) -> str:
        return self.principal.actor_id

    @property
    def tenant_id(self) -> str:
        return self.principal.tenant_id


@runtime_checkable
class Agent(Protocol):
    """业务 Agent 的运行时协议。"""

    @property
    def manifest(self) -> AgentManifest: ...

    def actions(self) -> tuple[ActionDefinition, ...]: ...

    def invoke(
        self, action: str, payload: dict[str, Any], context: ExecutionContext
    ) -> dict[str, Any]: ...


class AgentPlatformError(ValueError):
    """平台层可安全映射为客户端错误的基类。"""


class AgentNotFoundError(AgentPlatformError):
    pass


class ActionNotFoundError(AgentPlatformError):
    pass


class DuplicateAgentError(AgentPlatformError):
    pass


class InvalidInvocationError(AgentPlatformError):
    pass


class AuthorizationError(AgentPlatformError):
    pass
