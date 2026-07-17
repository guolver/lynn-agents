"""兼职 Agent 原有 REST API 的兼容路由。

新平台调用统一使用 ``/platform/v1``；这些 ``/api/v1`` 路由继续保留，避免现有
客户端因平台化重构立即迁移。
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from .repository import RepositoryProtocol
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

router = APIRouter(prefix="/api/v1", tags=["global-part-time-legacy"])


def get_repository(request: Request) -> RepositoryProtocol:
    """从当前应用读取仓储，避免多个 app/测试实例共享模块级可变状态。"""
    return request.app.state.part_time_repository


def get_service(request: Request) -> AgentService:
    return request.app.state.part_time_service


RepositoryDep = Annotated[RepositoryProtocol, Depends(get_repository)]
ServiceDep = Annotated[AgentService, Depends(get_service)]


def dump(model: BaseModel, *, exclude_none: bool = False) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=exclude_none)


def once(repository: RepositoryProtocol, action: str, key: str, operation: Any) -> dict[str, Any]:
    return repository.idempotent(action, key, operation)


@router.post("/sources", status_code=201)
def create_source(
    body: SourceCreate,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
) -> dict[str, Any]:
    return once(repository, "source.create", key, lambda: service.create_source(dump(body), actor))


@router.get("/sources")
def list_sources(repository: RepositoryDep) -> list[dict[str, Any]]:
    return repository.list("source")


@router.post("/sources/{source_id}/review")
def review_source(
    source_id: str,
    body: ReviewRequest,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
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
    repository: RepositoryDep,
    service: ServiceDep,
) -> dict[str, Any]:
    jobs = [dump(job) for job in body.jobs]
    return once(
        repository,
        f"source.sync:{source_id}",
        key,
        lambda: service.sync_source(source_id, jobs, actor),
    )


@router.get("/jobs")
def list_jobs(
    repository: RepositoryDep, status: str | None = None, review_status: str | None = None
) -> list[dict[str, Any]]:
    jobs = repository.list("job")
    return [
        job
        for job in jobs
        if (not status or job.get("status") == status)
        and (not review_status or job.get("review_status") == review_status)
    ]


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


@router.post("/candidates", status_code=201)
def create_candidate(
    body: CandidateCreate,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
) -> dict[str, Any]:
    return once(
        repository, "candidate.create", key, lambda: service.create_candidate(dump(body), actor)
    )


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: str, service: ServiceDep) -> dict[str, Any]:
    return service.get_candidate(candidate_id)


@router.patch("/candidates/{candidate_id}/preferences")
def update_candidate(
    candidate_id: str,
    body: CandidatePreferences,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
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
    repository: RepositoryDep,
    service: ServiceDep,
) -> dict[str, Any]:
    return once(
        repository,
        f"matches.run:{body.candidate_id}",
        key,
        lambda: service.run_matches(body.candidate_id, actor, body.limit),
    )


@router.get("/candidates/{candidate_id}/matches")
def candidate_matches(candidate_id: str, service: ServiceDep) -> list[dict[str, Any]]:
    return service.candidate_matches(candidate_id)


@router.post("/matches/{match_id}/feedback")
def match_feedback(
    match_id: str,
    body: FeedbackRequest,
    key: IdempotencyKey,
    actor: Actor,
    repository: RepositoryDep,
    service: ServiceDep,
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
    repository: RepositoryDep,
    service: ServiceDep,
) -> dict[str, Any]:
    base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
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
    repository: RepositoryDep,
    service: ServiceDep,
) -> dict[str, Any]:
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
    return once(
        repository,
        f"candidate.unsubscribe:{body.candidate_id}",
        key,
        lambda: service.set_consent(body.candidate_id, False, actor, "unsubscribe"),
    )


@router.get("/audit")
def audit_log(
    repository: RepositoryDep, limit: int = Query(default=100, ge=1, le=1000)
) -> list[dict[str, Any]]:
    return repository.audits(limit)
