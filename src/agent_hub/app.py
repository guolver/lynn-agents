"""组合平台核心和所有内置 Agent 的 FastAPI 应用。"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from .agents.global_part_time import http_api
from .agents.global_part_time.agent import GlobalPartTimeAgent
from .agents.global_part_time.repository import RepositoryProtocol
from .agents.global_part_time.service import AgentService, NotFoundError, PolicyError
from .api.platform import create_platform_router
from .core.contracts import (
    ActionNotFoundError,
    Agent,
    AgentNotFoundError,
    AuthorizationError,
    DuplicateAgentError,
    InvalidInvocationError,
)
from .core.discovery import discover_agents
from .core.registry import AgentRegistry
from .core.security import IdentityMiddleware, SecuritySettings
from .database.config import create_repository

load_dotenv()

logger = logging.getLogger(__name__)


def create_app(
    repository: RepositoryProtocol | None = None,
    *,
    extra_agents: Iterable[Agent] = (),
    load_plugins: bool = False,
    allowed_plugins: Iterable[str] | None = None,
    security_settings: SecuritySettings | None = None,
) -> FastAPI:
    """创建一个完整应用，并显式组装依赖。

    依赖组装只发生在 composition root。具体 Agent 不需要知道其他 Agent 的存在，
    测试也可以传入内存仓储，避免隐式修改全局数据库。
    """

    settings = security_settings or SecuritySettings.from_env()
    repo = repository or create_repository()
    expand_fn = None
    neo4j_driver = None

    def close_neo4j_driver() -> None:
        nonlocal neo4j_driver
        driver, neo4j_driver = neo4j_driver, None
        if driver is not None:
            try:
                driver.close()
            except Exception:
                logger.warning("Failed to close Neo4j driver", exc_info=True)

    skill_graph_router = None
    neo4j_uri = os.getenv("NEO4J_URI")
    if neo4j_uri:
        try:
            from .skill_graph.config import create_neo4j_driver
            from .skill_graph.service import SkillGraphService

            neo4j_driver = create_neo4j_driver(neo4j_uri)
            skill_graph = SkillGraphService(neo4j_driver)
            skill_graph.seed()
            expand_fn = skill_graph.expand
            logger.info("Skill graph initialized from Neo4j at %s", neo4j_uri)

            from .api.skill_graph import create_skill_graph_router

            skill_graph_router = create_skill_graph_router(skill_graph)
        except Exception:
            logger.warning("Failed to initialize skill graph, continuing without it", exc_info=True)
            close_neo4j_driver()
    embed_fn = None
    if os.getenv("EMBEDDING_ENABLED", "true").lower() == "true":
        try:
            from .agents.global_part_time.embedding import get_embedding

            embed_fn = get_embedding
        except Exception:
            logger.warning(
                "Failed to import embedding module, continuing without it", exc_info=True
            )

    part_time_service = AgentService(repo, expand_fn=expand_fn, embed_fn=embed_fn)

    from .agents.global_part_time.chat_service import ChatService

    chat_service = ChatService(service=part_time_service, repo=repo)

    # --- Chat stream hub (Redis Streams; enables resumable chat streaming) ---
    stream_hub = None
    stream_redis_url = (
        os.getenv("CHAT_STREAM_REDIS_URL")
        or os.getenv("CELERY_BROKER_URL")
        or "redis://localhost:6379/0"
    )
    try:
        from .agents.global_part_time.stream_hub import StreamHub

        stream_hub = StreamHub(stream_redis_url)
        if stream_hub.available():
            logger.info("Chat StreamHub initialized at %s", stream_redis_url)
        else:
            logger.warning(
                "Redis unreachable at %s; chat streaming falls back to inline (non-resumable)",
                stream_redis_url,
            )
    except Exception:
        logger.warning("Failed to initialize chat StreamHub", exc_info=True)
        stream_hub = None

    registry = AgentRegistry()
    registry.register(GlobalPartTimeAgent(part_time_service, repo))
    for agent in extra_agents:
        registry.register(agent)
    if load_plugins:
        discover_agents(registry, allowed_plugins=allowed_plugins)

    # --- Workflow tracker (PostgreSQL only) ---
    workflow_tracker = None
    if hasattr(repo, "_engine"):
        try:
            from .worker.workflow import WorkflowTracker

            workflow_tracker = WorkflowTracker(repo._engine)
            logger.info("WorkflowTracker initialized")
        except Exception:
            logger.warning("Failed to initialize WorkflowTracker", exc_info=True)

    # --- Identity: registration/login (PostgreSQL + AUTH_JWT_SECRET required) ---
    identity_router = None
    if hasattr(repo, "_engine") and settings.auth_jwt_secret:
        try:
            from .identity.http_api import create_identity_router
            from .identity.rate_limiter import RedisLoginRateLimiter
            from .identity.repository import IdentityRepository
            from .identity.service import IdentityService

            identity_repo = IdentityRepository(repo._engine)
            identity_rate_limiter = RedisLoginRateLimiter(stream_redis_url)
            identity_service = IdentityService(
                identity_repo,
                rate_limiter=identity_rate_limiter,
                jwt_secret=settings.auth_jwt_secret,
            )
            identity_router = create_identity_router(identity_service)
            logger.info("Identity service initialized (registration/login enabled)")
        except Exception:
            logger.warning("Failed to initialize identity service", exc_info=True)
    elif hasattr(repo, "_engine"):
        logger.warning("AUTH_JWT_SECRET not set — registration/login endpoints disabled")

    # --- Celery app (optional) ---
    celery_instance = None
    if os.getenv("CELERY_BROKER_URL"):
        try:
            from .worker.celery_app import celery_app as _celery_app

            celery_instance = _celery_app
            logger.info("Celery app attached")
        except Exception:
            logger.warning("Failed to initialize Celery app", exc_info=True)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        try:
            yield
        finally:
            close_neo4j_driver()

    application = FastAPI(
        title="Agent Hub",
        version="0.2.0",
        description="统一发现、治理和调用多个业务 Agent；保留兼职 Agent 的兼容 API。",
        lifespan=lifespan,
    )
    application.add_middleware(
        IdentityMiddleware,
        mode=settings.mode,
        gateway_secret=settings.gateway_secret,
        development_default_roles=settings.development_default_roles,
        auth_jwt_secret=settings.auth_jwt_secret,
    )
    application.state.agent_registry = registry
    application.state.part_time_repository = repo
    application.state.part_time_service = part_time_service
    if workflow_tracker is not None:
        application.state.workflow_tracker = workflow_tracker
    if celery_instance is not None:
        application.state.celery_app = celery_instance
    application.state.chat_service = chat_service
    application.state.stream_hub = stream_hub
    application.include_router(create_platform_router(registry))
    application.include_router(http_api.router)
    if identity_router is not None:
        application.include_router(identity_router)
    if skill_graph_router is not None:
        application.include_router(skill_graph_router)

    @application.get("/health", tags=["platform"])
    def health() -> dict[str, Any]:
        return {"status": "ok", "registered_agents": len(registry.manifests())}

    # --- Workflow management routes ---

    @application.get("/api/v1/workflows", tags=["workflows"])
    def list_workflows(
        status: str | None = Query(None),
        workflow_type: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        if workflow_tracker is None:
            return []
        return workflow_tracker.list_runs(status=status, workflow_type=workflow_type, limit=limit)

    @application.get("/api/v1/workflows/{run_id}", tags=["workflows"])
    def get_workflow(run_id: str) -> dict[str, Any]:
        if workflow_tracker is None:
            return JSONResponse(status_code=404, content={"detail": "workflow tracking disabled"})
        result = workflow_tracker.get_run(run_id)
        if result is None:
            return JSONResponse(
                status_code=404, content={"detail": f"workflow run {run_id} not found"}
            )
        return result

    @application.post("/api/v1/workflows/{run_id}/retry", tags=["workflows"])
    def retry_workflow(run_id: str, request: Request) -> dict[str, Any]:
        if workflow_tracker is None:
            return JSONResponse(status_code=503, content={"detail": "workflow tracking disabled"})
        run = workflow_tracker.get_run(run_id)
        if run is None:
            return JSONResponse(
                status_code=404, content={"detail": f"workflow run {run_id} not found"}
            )
        if run["status"] not in ("failed", "manual_review"):
            return JSONResponse(
                status_code=409, content={"detail": f"cannot retry run in status {run['status']}"}
            )
        if celery_instance is None:
            return JSONResponse(status_code=503, content={"detail": "celery not configured"})
        # Re-dispatch based on workflow type.
        from .worker.tasks import (
            notification_pipeline_task,
            run_matches_task,
            send_notification_task,
            sync_source_task,
        )

        task_map = {
            "source_sync": sync_source_task,
            "matching": run_matches_task,
            "notification": notification_pipeline_task,
            "notification_send": send_notification_task,
        }
        task_fn = task_map.get(run["workflow_type"])
        if task_fn is None:
            return JSONResponse(
                status_code=422,
                content={"detail": f"unknown workflow type: {run['workflow_type']}"},
            )

        # Build kwargs from the original run payload.
        payload = run.get("payload", {})
        kwargs: dict[str, Any] = {"actor": run["actor"]}
        wtype = run["workflow_type"]
        if wtype == "source_sync":
            kwargs["source_id"] = payload.get("source_id", run["target_id"])
            kwargs["jobs"] = payload.get("jobs", [])
        elif wtype == "matching":
            kwargs["candidate_id"] = payload.get("candidate_id", run["target_id"])
        elif wtype == "notification":
            kwargs["candidate_id"] = payload.get("candidate_id", run["target_id"])
            kwargs["match_ids"] = payload.get("match_ids", [])
            kwargs["base_url"] = payload.get("base_url", "")
        elif wtype == "notification_send":
            kwargs["notification_id"] = payload.get("notification_id", run["target_id"])

        async_result = task_fn.delay(**kwargs)
        return {"status": "retried", "new_celery_task_id": async_result.id}

    # --- Exception handlers ---

    @application.exception_handler(AgentNotFoundError)
    @application.exception_handler(ActionNotFoundError)
    def platform_not_found(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(InvalidInvocationError)
    @application.exception_handler(DuplicateAgentError)
    def platform_invalid(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.exception_handler(AuthorizationError)
    def platform_forbidden(_request: Any, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @application.exception_handler(NotFoundError)
    def domain_not_found(_request: Any, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(PolicyError)
    def policy_conflict(_request: Any, exc: PolicyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    return application


app = create_app()
