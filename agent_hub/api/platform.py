"""统一的 Agent 发现和调用 API。"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from ..core.contracts import ExecutionContext
from ..core.registry import AgentRegistry
from ..core.security import Principal, get_principal


class InvokeRequest(BaseModel):
    """统一调用包；具体 payload 结构可从 Agent action 的 input_schema 发现。"""

    model_config = ConfigDict(extra="forbid")
    payload: dict[str, Any] = Field(default_factory=dict)


IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", min_length=8, max_length=200)
]
RequestId = Annotated[str | None, Header(alias="X-Request-Id", max_length=200)]


def create_platform_router(registry: AgentRegistry) -> APIRouter:
    """为一个注册表创建路由，测试和多租户部署可注入各自的注册表。"""

    router = APIRouter(prefix="/platform/v1", tags=["agent-platform"])

    @router.get("/agents")
    def list_agents() -> list[dict[str, Any]]:
        return [manifest.to_dict() for manifest in registry.manifests()]

    @router.get("/agents/{agent_id}")
    def describe_agent(agent_id: str) -> dict[str, Any]:
        return registry.describe(agent_id)

    @router.post("/agents/{agent_id}/actions/{action_name}")
    def invoke_agent(
        agent_id: str,
        action_name: str,
        body: InvokeRequest,
        principal: Principal = Depends(get_principal),
        idempotency_key: IdempotencyKey = None,
        request_id: RequestId = None,
    ) -> dict[str, Any]:
        context = ExecutionContext(
            principal=principal,
            request_id=request_id or str(uuid.uuid4()),
            idempotency_key=idempotency_key,
        )
        result = registry.invoke(agent_id, action_name, body.payload, context)
        return {
            "agent_id": agent_id,
            "action": action_name,
            "request_id": context.request_id,
            "result": result,
        }

    return router
