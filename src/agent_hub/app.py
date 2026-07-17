"""组合平台核心和所有内置 Agent 的 FastAPI 应用。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .agents.global_part_time import http_api
from .agents.global_part_time.agent import GlobalPartTimeAgent
from .agents.global_part_time.repository import RepositoryProtocol
from .database.config import create_repository
from .agents.global_part_time.service import AgentService, NotFoundError, PolicyError
from .api.platform import create_platform_router
from .core.contracts import (
    ActionNotFoundError,
    AgentNotFoundError,
    DuplicateAgentError,
    InvalidInvocationError,
    Agent,
)
from .core.discovery import discover_agents
from .core.registry import AgentRegistry


def create_app(
    repository: RepositoryProtocol | None = None,
    *,
    extra_agents: Iterable[Agent] = (),
    load_plugins: bool = False,
    allowed_plugins: Iterable[str] | None = None,
) -> FastAPI:
    """创建一个完整应用，并显式组装依赖。

    依赖组装只发生在 composition root。具体 Agent 不需要知道其他 Agent 的存在，
    测试也可以传入内存仓储，避免隐式修改全局数据库。
    """

    repo = repository or create_repository()
    part_time_service = AgentService(repo)
    registry = AgentRegistry()
    registry.register(GlobalPartTimeAgent(part_time_service, repo))
    for agent in extra_agents:
        registry.register(agent)
    if load_plugins:
        discover_agents(registry, allowed_plugins=allowed_plugins)

    application = FastAPI(
        title="Agent Hub",
        version="0.2.0",
        description="统一发现、治理和调用多个业务 Agent；保留兼职 Agent 的兼容 API。",
    )
    application.state.agent_registry = registry
    application.state.part_time_repository = repo
    application.state.part_time_service = part_time_service
    application.include_router(create_platform_router(registry))
    application.include_router(http_api.router)

    @application.get("/health", tags=["platform"])
    def health() -> dict[str, Any]:
        return {"status": "ok", "registered_agents": len(registry.manifests())}

    @application.exception_handler(AgentNotFoundError)
    @application.exception_handler(ActionNotFoundError)
    def platform_not_found(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(InvalidInvocationError)
    @application.exception_handler(DuplicateAgentError)
    def platform_invalid(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.exception_handler(NotFoundError)
    def domain_not_found(_request: Any, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(PolicyError)
    def policy_conflict(_request: Any, exc: PolicyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    return application


app = create_app()
