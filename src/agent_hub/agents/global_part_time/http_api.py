"""兼职 Agent 原有 REST API 的兼容路由。

新平台调用统一使用 ``/platform/v1``；这些 ``/api/v1`` 路由继续保留，避免现有
客户端因平台化重构立即迁移。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from ...core.security import Principal, Role, get_principal, require_roles
from .chat_service import ChatService
from .repository import RepositoryProtocol, TenantRepositoryProtocol
from .service import AgentService


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: Literal["api", "rss", "ats", "company_page", "partner_feed"]
    base_url: HttpUrl
    authorization_basis: str = Field(min_length=3)
    allowed_paths: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    rate_limit: str
    retention_policy: str


class ReviewRequest(APIModel):
    approved: bool
    note: str = ""


class JobInput(APIModel):
    source_job_id: str
    canonical_url: HttpUrl
    title_original: str
    title_zh: str | None = None
    company_name: str
    description_original: str
    description_zh: str | None = None
    employment_type: Literal["part_time", "contract", "temporary"] = "part_time"
    work_mode: Literal["remote", "hybrid", "onsite"]
    countries_allowed: list[str] = Field(default_factory=list)
    timezone_requirements: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    hours_per_week_min: int | None = Field(default=None, ge=0, le=168)
    hours_per_week_max: int | None = Field(default=None, ge=0, le=168)
    compensation_min: float | None = Field(default=None, ge=0)
    compensation_max: float | None = Field(default=None, ge=0)
    compensation_currency: str | None = None
    compensation_period: Literal["hour", "day", "month", "project"] | None = None
    application_deadline: str | None = None
    published_at: str | None = None
    quality_score: float = Field(default=0.7, ge=0, le=1)
    extraction_confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_ranges(self) -> "JobInput":
        if (
            self.hours_per_week_min is not None
            and self.hours_per_week_max is not None
            and self.hours_per_week_min > self.hours_per_week_max
        ):
            raise ValueError("hours_per_week_min cannot exceed hours_per_week_max")
        if (
            self.compensation_min is not None
            and self.compensation_max is not None
            and self.compensation_min > self.compensation_max
        ):
            raise ValueError("compensation_min cannot exceed compensation_max")
        return self


class SyncRequest(APIModel):
    jobs: list[JobInput] = Field(max_length=500)


class Language(APIModel):
    code: str
    level: str = "working"


class Skill(APIModel):
    name: str
    level: int = Field(default=3, ge=1, le=5)


class Money(APIModel):
    amount: float = Field(ge=0)
    currency: str


class CandidateCreate(APIModel):
    country: str
    timezone: str
    email: str | None = None
    languages: list[Language] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    desired_roles: list[str] = Field(default_factory=list)
    minimum_hourly_rate: Money | None = None
    availability_hours_per_week: int = Field(ge=0, le=168)
    allowed_work_modes: list[Literal["remote", "hybrid", "onsite"]] = Field(
        default_factory=lambda: ["remote"]
    )
    notification_channels: list[Literal["email", "telegram", "in_app"]] = Field(
        default_factory=lambda: ["email"]
    )
    notification_frequency: Literal["daily", "weekly", "paused"] = "daily"
    excluded_companies: list[str] = Field(default_factory=list)
    resume_summary: str | None = None


class CandidatePreferences(APIModel):
    country: str | None = None
    timezone: str | None = None
    languages: list[Language] | None = None
    skills: list[Skill] | None = None
    desired_roles: list[str] | None = None
    minimum_hourly_rate: Money | None = None
    availability_hours_per_week: int | None = Field(default=None, ge=0, le=168)
    allowed_work_modes: list[Literal["remote", "hybrid", "onsite"]] | None = None
    notification_channels: list[Literal["email", "telegram", "in_app"]] | None = None
    notification_frequency: Literal["daily", "weekly", "paused"] | None = None
    excluded_companies: list[str] | None = None


class ConsentRequest(APIModel):
    opted_in: bool
    policy_version: str = "mvp-1"


class MatchRunRequest(APIModel):
    candidate_id: str
    limit: int = Field(default=50, ge=1, le=100)


class FeedbackRequest(APIModel):
    value: Literal["saved", "not_interested", "clicked", "reported"]


class ReportRequest(APIModel):
    reason: str = Field(min_length=3, max_length=1000)


class DigestPreviewRequest(APIModel):
    candidate_id: str
    match_ids: list[str] = Field(min_length=1, max_length=5)


class NotificationSendRequest(APIModel):
    notification_id: str


class UnsubscribeRequest(APIModel):
    candidate_id: str


IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
Actor = Annotated[str, Header(alias="X-Actor", min_length=1, max_length=200)]
RequestId = Annotated[str | None, Header(alias="X-Request-Id", max_length=200)]

router = APIRouter(prefix="/api/v1", tags=["global-part-time-legacy"])


def get_tenant_repository(
    request: Request, principal: Principal = Depends(get_principal)
) -> TenantRepositoryProtocol:
    """Carve a tenant-scoped view out of the app's root repository for this
    request's Principal. Every route below reads/writes through this scoped
    view rather than the raw root repository, so no route can read or write
    another tenant's data even by accident.
    """
    return request.app.state.part_time_repository.for_tenant(principal.tenant_id)


def get_service(
    request: Request,
    repository: TenantRepositoryProtocol = Depends(get_tenant_repository),
    principal: Principal = Depends(get_principal),
    request_id: RequestId = None,
) -> AgentService:
    """Build a request-scoped AgentService carrying this request's Principal
    (for owner checks and audit enrichment) — replaces the old fixed
    ``request.app.state.part_time_service`` singleton that every request used
    to share regardless of who was calling.
    """
    return AgentService(
        repository,
        expand_fn=getattr(request.app.state, "expand_fn", None),
        embed_fn=getattr(request.app.state, "embed_fn", None),
        principal=principal,
        request_id=request_id or str(uuid.uuid4()),
    )


def get_chat_service(
    request: Request,
    repository: TenantRepositoryProtocol = Depends(get_tenant_repository),
    principal: Principal = Depends(get_principal),
    request_id: RequestId = None,
) -> ChatService:
    """Build a request-scoped ChatService — replaces the old fixed
    ``request.app.state.chat_service`` singleton. Owner checks on chat
    sessions (see ChatService._owned_session) depend on this being scoped to
    the calling Principal.
    """
    service = AgentService(
        repository,
        expand_fn=getattr(request.app.state, "expand_fn", None),
        embed_fn=getattr(request.app.state, "embed_fn", None),
        principal=principal,
        request_id=request_id or str(uuid.uuid4()),
    )
    return ChatService(
        service=service,
        repo=repository,
        tracer=getattr(request.app.state, "chat_tracer", None),
        principal=principal,
    )


RepositoryDep = Annotated[TenantRepositoryProtocol, Depends(get_tenant_repository)]
ServiceDep = Annotated[AgentService, Depends(get_service)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def dump(model: BaseModel, *, exclude_none: bool = False) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=exclude_none)


def once(repository: RepositoryProtocol, action: str, key: str, operation: Any) -> dict[str, Any]:
    return repository.idempotent(action, key, operation)


def _celery_available(request: Request) -> bool:
    return hasattr(request.app.state, "celery_app") and request.app.state.celery_app is not None


@router.post("/sources", status_code=201)
def create_source(
    body: SourceCreate,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> dict[str, Any]:
    return once(repository, "source.create", key, lambda: service.create_source(dump(body), actor))


@router.get("/sources")
def list_sources(
    repository: RepositoryDep, _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN)
) -> list[dict[str, Any]]:
    return repository.list("source")


@router.post("/sources/{source_id}/review")
def review_source(
    source_id: str,
    body: ReviewRequest,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> dict[str, Any]:
    return once(
        repository,
        f"source.review:{source_id}",
        key,
        lambda: service.review_source(source_id, body.approved, actor, body.note),
    )


@router.post("/sources/{source_id}/sync")
def sync_source(
    source_id: str,
    body: SyncRequest,
    key: IdempotencyKey,
    actor: Actor,
    request: Request,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> dict[str, Any]:
    jobs = [dump(job) for job in body.jobs]
    if _celery_available(request):
        from agent_hub.worker.tasks import sync_source_task

        result = sync_source_task.delay(source_id, jobs, actor)
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "celery_task_id": result.id,
                "detail": "task dispatched to worker",
            },
        )
    return once(
        repository,
        f"source.sync:{source_id}",
        key,
        lambda: service.sync_source(source_id, jobs, actor),
    )


@router.get("/candidates")
def list_candidates(
    repository: RepositoryDep, _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN)
) -> list[dict[str, Any]]:
    # Bulk/ops view across every candidate — not a "personal candidate"
    # route, so it's gated by role only (like GET /notifications) rather
    # than owner-scoped like GET /candidates/{id}.
    return repository.list("candidate")


@router.get("/notifications")
def list_notifications(
    repository: RepositoryDep,
    status: str | None = None,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> list[dict[str, Any]]:
    notifications = repository.list("notification")
    if status:
        return [n for n in notifications if n.get("status") == status]
    return notifications


@router.get("/jobs")
def list_jobs(
    repository: RepositoryDep,
    status: str | None = None,
    review_status: str | None = None,
    q: str | None = None,
    work_mode: str | None = None,
    category: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    total, jobs = repository.search_jobs(
        q=q, work_mode=work_mode, category=category, offset=offset, limit=limit
    )
    # Apply legacy filters if provided
    if status or review_status:
        jobs = [
            job
            for job in jobs
            if (not status or job.get("status") == status)
            and (not review_status or job.get("review_status") == review_status)
        ]
    return {"total": total, "offset": offset, "limit": limit, "jobs": jobs}


@router.get("/jobs/categories")
def list_job_categories(
    repository: RepositoryDep,
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    """活跃职位类别聚合，供前端筛选器渲染选项。"""
    return {"categories": repository.list_job_categories(limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, service: ServiceDep) -> dict[str, Any]:
    return service.get_job(job_id)


@router.post("/jobs/{job_id}/review")
def review_job(
    job_id: str,
    body: ReviewRequest,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> dict[str, Any]:
    return once(
        repository,
        f"job.review:{job_id}",
        key,
        lambda: service.review_job(job_id, body.approved, actor, body.note),
    )


@router.post("/jobs/{job_id}/report")
def report_job(
    job_id: str,
    body: ReportRequest,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
) -> dict[str, Any]:
    return once(
        repository,
        f"job.report:{job_id}",
        key,
        lambda: service.report_job(job_id, body.reason, actor),
    )


@router.post("/jobs/{job_id}/translate")
def translate_job_endpoint(
    job_id: str,
    repository: RepositoryDep,
    service: ServiceDep,
) -> dict[str, Any]:
    """按需翻译岗位标题和描述为中文，结果缓存到 payload。"""
    job = service.get_job(job_id)

    # 已有翻译直接返回
    if job.get("title_zh") and job.get("description_zh"):
        return {"title_zh": job["title_zh"], "description_zh": job["description_zh"]}

    # 调用翻译服务
    try:
        from .translator import translate_job
    except ImportError as exc:
        return JSONResponse(status_code=501, content={"detail": f"翻译依赖未安装: {exc}"})

    try:
        result = translate_job(
            job.get("title_original", ""),
            job.get("description_original", ""),
        )
    except ValueError as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    except Exception as exc:
        logging.getLogger(__name__).exception("translation failed")
        return JSONResponse(status_code=502, content={"detail": f"翻译服务异常: {exc}"})

    # 写回缓存
    job["title_zh"] = result["title_zh"]
    job["description_zh"] = result["description_zh"]
    repository.put("job", job)

    return {"title_zh": result["title_zh"], "description_zh": result["description_zh"]}


@router.post("/candidates", status_code=201)
def create_candidate(
    body: CandidateCreate,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    return once(
        repository, "candidate.create", key, lambda: service.create_candidate(dump(body), actor)
    )


@router.get("/candidates/{candidate_id}")
def get_candidate(
    candidate_id: str,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    # service.get_candidate() applies the owner check (404s on cross-owner
    # access) — the role gate alone would let any USER read any candidate.
    return service.get_candidate(candidate_id)


@router.patch("/candidates/{candidate_id}/preferences")
def update_candidate(
    candidate_id: str,
    body: CandidatePreferences,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    changes = body.model_dump(mode="json", exclude_unset=True)
    return once(
        repository,
        f"candidate.update:{candidate_id}",
        key,
        lambda: service.update_candidate(candidate_id, changes, actor),
    )


@router.post("/candidates/{candidate_id}/consent")
def set_consent(
    candidate_id: str,
    body: ConsentRequest,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    return once(
        repository,
        f"candidate.consent:{candidate_id}",
        key,
        lambda: service.set_consent(candidate_id, body.opted_in, actor, body.policy_version),
    )


@router.delete("/candidates/{candidate_id}")
def delete_candidate(
    candidate_id: str,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    return once(
        repository,
        f"candidate.delete:{candidate_id}",
        key,
        lambda: service.delete_candidate(candidate_id, actor),
    )


@router.post("/matches/run")
def run_matches(
    body: MatchRunRequest,
    key: IdempotencyKey,
    actor: Actor,
    request: Request,
    repository: RepositoryDep,
    service: ServiceDep,
    sync: bool = False,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> dict[str, Any]:
    # Ops/bulk matching trigger, not a "personal candidate" route — end
    # users get matches for their own candidate via chat's internal
    # service.run_matches() call, which never goes through this REST route.
    if not sync and _celery_available(request):
        from agent_hub.worker.tasks import run_matches_task

        result = run_matches_task.delay(body.candidate_id, actor, body.limit)
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "celery_task_id": result.id,
                "detail": "task dispatched to worker",
            },
        )
    return once(
        repository,
        f"matches.run:{body.candidate_id}",
        key,
        lambda: service.run_matches(body.candidate_id, actor, body.limit),
    )


@router.get("/candidates/{candidate_id}/matches")
def candidate_matches(
    candidate_id: str,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> list[dict[str, Any]]:
    return service.candidate_matches(candidate_id)


@router.post("/matches/{match_id}/feedback")
def match_feedback(
    match_id: str,
    body: FeedbackRequest,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    return once(
        repository,
        f"match.feedback:{match_id}",
        key,
        lambda: service.feedback(match_id, body.value, actor),
    )


@router.post("/notifications/preview", status_code=201)
def preview_digest(
    body: DigestPreviewRequest,
    key: IdempotencyKey,
    actor: Actor,
    request: Request,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> dict[str, Any]:
    base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    if _celery_available(request):
        from agent_hub.worker.tasks import notification_pipeline_task

        result = notification_pipeline_task.delay(
            body.candidate_id, body.match_ids, actor, base_url
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "celery_task_id": result.id,
                "detail": "task dispatched to worker",
            },
        )
    return once(
        repository,
        f"notification.preview:{body.candidate_id}",
        key,
        lambda: service.preview_digest(body.candidate_id, body.match_ids, actor, base_url),
    )


@router.post("/notifications/{notification_id}/review")
def review_notification(
    notification_id: str,
    body: ReviewRequest,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> dict[str, Any]:
    return once(
        repository,
        f"notification.review:{notification_id}",
        key,
        lambda: service.review_notification(notification_id, body.approved, actor),
    )


@router.post("/notifications/send")
def send_notification(
    body: NotificationSendRequest,
    key: IdempotencyKey,
    actor: Actor,
    request: Request,
    repository: RepositoryDep,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.OPERATOR, Role.ADMIN),
) -> dict[str, Any]:
    if _celery_available(request):
        from agent_hub.worker.tasks import send_notification_task

        result = send_notification_task.delay(body.notification_id, actor)
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "celery_task_id": result.id,
                "detail": "task dispatched to worker",
            },
        )
    return once(
        repository,
        f"notification.send:{body.notification_id}",
        key,
        lambda: service.send_notification(body.notification_id, actor),
    )


@router.post("/unsubscribe")
def unsubscribe(
    body: UnsubscribeRequest,
    key: IdempotencyKey,
    repository: RepositoryDep,
    service: ServiceDep,
    actor: Actor = "self-service",
) -> dict[str, Any]:
    # Public self-service flow (e.g. an unsubscribe link in an email): the
    # caller is intentionally not the candidate's owner, so no extra role
    # requirement and the owner check is explicitly bypassed.
    return once(
        repository,
        f"candidate.unsubscribe:{body.candidate_id}",
        key,
        lambda: service.set_consent(
            body.candidate_id, False, actor, "unsubscribe", enforce_owner=False
        ),
    )


@router.post("/candidates/upload-resume", status_code=201)
def upload_resume(
    file: UploadFile,
    actor: Actor,
    request: Request,
    service: ServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    _logger = logging.getLogger(__name__)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=422, content={"detail": "仅支持 PDF 文件"})

    pdf_bytes = file.file.read()
    if not pdf_bytes:
        return JSONResponse(status_code=422, content={"detail": "文件为空"})

    # Celery 可用时异步执行
    if _celery_available(request):
        from agent_hub.worker.tasks import parse_resume_task

        result = parse_resume_task.delay(pdf_bytes.hex(), actor)
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "celery_task_id": result.id,
                "detail": "简历解析任务已提交，正在后台处理",
            },
        )

    # 同步执行（无 Celery 时的 fallback）
    try:
        from .resume_parser import extract_text_from_pdf, parse_resume
    except ImportError as exc:
        _logger.exception("resume_parser dependencies not installed")
        return JSONResponse(
            status_code=501,
            content={"detail": f"简历解析依赖未安装: {exc}"},
        )

    try:
        text = extract_text_from_pdf(pdf_bytes)
    except Exception as exc:
        _logger.exception("PDF text extraction failed")
        return JSONResponse(
            status_code=422,
            content={"detail": f"PDF 解析失败: {exc}"},
        )

    if not text.strip():
        return JSONResponse(status_code=422, content={"detail": "无法从 PDF 中提取文本"})

    try:
        parsed = parse_resume(text)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:
        _logger.exception("LLM resume parsing failed")
        return JSONResponse(
            status_code=502,
            content={"detail": f"简历解析服务异常: {exc}"},
        )

    _logger.info(
        "Resume parsed: country=%s, skills=%d",
        parsed.get("country"),
        len(parsed.get("skills", [])),
    )

    candidate = service.create_candidate(parsed, actor)
    candidate_id = candidate["id"]

    service.set_consent(candidate_id, True, actor, "resume_upload")

    match_result = service.run_matches(candidate_id, actor)
    matches_count = len(match_result.get("matches", []))

    return {
        "candidate": candidate,
        "matches_count": matches_count,
        "parsed_fields": parsed,
    }


@router.get("/tasks/{task_id}/status")
def get_task_status(task_id: str, request: Request) -> dict[str, Any]:
    """查询 Celery 异步任务的状态和结果。"""
    if not _celery_available(request):
        return JSONResponse(status_code=501, content={"detail": "异步任务不可用"})

    celery_app = request.app.state.celery_app
    result = celery_app.AsyncResult(task_id)

    response: dict[str, Any] = {
        "task_id": task_id,
        "status": result.status,
    }

    if result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["error"] = str(result.result)

    return response


@router.get("/audit")
def audit_log(
    repository: RepositoryDep,
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = require_roles(Role.ADMIN),
) -> list[dict[str, Any]]:
    return repository.audits(limit)


# ---------------------------------------------------------------------------
# Chat endpoints
# ---------------------------------------------------------------------------


class ChatMessageRequest(APIModel):
    content: str = Field(min_length=1, max_length=5000)


@router.post("/chat/sessions", status_code=201)
def create_chat_session(
    actor: Actor,
    chat_svc: ChatServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    return chat_svc.create_session(actor=actor)


@router.get("/chat/sessions")
def list_chat_sessions(
    chat_svc: ChatServiceDep, _principal: Principal = require_roles(Role.USER, Role.ADMIN)
) -> list[dict[str, Any]]:
    # Scoped to the caller's own sessions (ChatService.list_sessions), not a
    # tenant-wide listing — otherwise any USER could enumerate every other
    # user's chat sessions within the tenant.
    return chat_svc.list_sessions()


@router.get("/chat/sessions/{session_id}")
def get_chat_session(
    session_id: str,
    chat_svc: ChatServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
) -> dict[str, Any]:
    result = chat_svc.get_session(session_id)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Session not found"})
    return result


@router.delete("/chat/sessions/{session_id}")
def delete_chat_session(
    session_id: str,
    chat_svc: ChatServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
):
    found = chat_svc.delete_session(session_id)
    if not found:
        return JSONResponse(status_code=404, content={"detail": "Session not found"})
    return {"ok": True}


def _sse_response(events):
    import json as _json

    from fastapi.responses import StreamingResponse

    def event_stream():
        for event in events:
            event_type = event["event"]
            event_data = _json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {event_type}\ndata: {event_data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chat/sessions/{session_id}/messages")
def send_chat_message(
    session_id: str,
    body: ChatMessageRequest,
    request: Request,
    chat_svc: ChatServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
):
    hub = getattr(request.app.state, "stream_hub", None)

    # 生成与连接解耦：后台线程写 StreamHub，本响应只是其中一个消费者。
    # 客户端断开（切页面、刷新）不影响生成，且可通过 GET /stream 重连续传。
    # start_streaming() checks session ownership synchronously before
    # spawning the background thread, so a cross-owner call 404s here
    # instead of silently starting to generate into someone else's session.
    if hub is not None and hub.available():
        stream_id = chat_svc.start_streaming(session_id, body.content, hub)
        return _sse_response(hub.replay_and_follow(stream_id))

    # Redis 不可用时退回原地流式（无恢复能力）。
    return _sse_response(chat_svc.stream_response(session_id, body.content))


@router.get("/chat/sessions/{session_id}/stream")
def resume_chat_stream(
    session_id: str,
    request: Request,
    chat_svc: ChatServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
):
    """重连进行中的回答：从头重放已生成部分并继续跟读；无活跃流返回 204。"""
    from fastapi import Response

    # Raises NotFoundError (-> 404 via the app-level exception handler) if
    # the session doesn't exist or isn't owned by this principal, before we
    # ever touch the stream hub.
    chat_svc._owned_session(session_id)

    hub = getattr(request.app.state, "stream_hub", None)
    if hub is None or not hub.available():
        return Response(status_code=204)
    stream_id = hub.get_active(session_id)
    if not stream_id:
        return Response(status_code=204)
    return _sse_response(hub.replay_and_follow(stream_id))


@router.post("/chat/sessions/{session_id}/upload", status_code=201)
def upload_chat_resume(
    session_id: str,
    file: UploadFile,
    request: Request,
    actor: Actor,
    chat_svc: ChatServiceDep,
    _principal: Principal = require_roles(Role.USER, Role.ADMIN),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=422, content={"detail": "仅支持 PDF 文件"})

    pdf_bytes = file.file.read()
    if not pdf_bytes:
        return JSONResponse(status_code=422, content={"detail": "文件为空"})

    try:
        from .resume_parser import extract_text_from_pdf
    except ImportError as exc:
        return JSONResponse(status_code=501, content={"detail": f"简历解析依赖未安装: {exc}"})

    try:
        text = extract_text_from_pdf(pdf_bytes)
    except Exception as exc:
        return JSONResponse(status_code=422, content={"detail": f"PDF 解析失败: {exc}"})

    if not text.strip():
        return JSONResponse(status_code=422, content={"detail": "无法从 PDF 中提取文本"})

    # Store extracted text as user message for LLM context / later reference.
    # Attachment metadata lets the frontend rebuild the file card on history replay
    # instead of dumping the raw resume text.
    chat_svc.add_message(
        session_id,
        "user",
        f"[简历内容]\n{text}",
        attachment={
            "name": file.filename,
            "size": len(pdf_bytes),
            "type": file.content_type or "application/pdf",
        },
    )

    # Celery 可用时：异步跑「解析 + 匹配」流水线，立刻返回 task_id 供前端轮询。
    if _celery_available(request):
        from agent_hub.worker.tasks import parse_and_match_chat_task

        async_result = parse_and_match_chat_task.delay(session_id, text, actor)
        return JSONResponse(
            status_code=202,
            content={
                "session_id": session_id,
                "task_id": async_result.id,
                "status": "processing",
            },
        )

    # 无 Celery 的同步 fallback：直接跑完流水线再返回结果。
    try:
        result = chat_svc.run_analysis(session_id, text, actor)
    except Exception as exc:  # noqa: BLE001 - surface parse/match failures to the client
        logging.getLogger(__name__).exception("chat resume analysis failed")
        return JSONResponse(status_code=502, content={"detail": f"简历分析失败: {exc}"})

    return {"session_id": session_id, "status": "completed", "result": result}
