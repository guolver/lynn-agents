"""Celery tasks — thin wrappers around AgentService methods.

Each task follows the same pattern:
1. Create/reuse a ``WorkflowRun``.
2. Record a ``WorkflowStep`` (status=running).
3. Execute the business operation via ``repo.idempotent()``.
4. On success → ``complete_step`` + ``complete_run``.
5. On failure → classify the error, then retry or fail permanently.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from celery import Task

from .celery_app import celery_app
from .errors import classify

logger = logging.getLogger(__name__)

# Maximum retries before escalating to manual review.
MAX_RETRIES = 5

# Exponential backoff base (seconds): 30, 60, 120, 240, 480.
BACKOFF_BASE = 30


def _make_idempotency_key(workflow_run_id: str, step_name: str) -> str:
    """Deterministic key so that retries within the same run/step are idempotent."""
    raw = f"{workflow_run_id}:{step_name}"
    return hashlib.sha256(raw.encode()).hexdigest()


class WorkflowTask(Task):
    """Base task class with lazy initialisation of service and tracker.

    Heavy objects (DB connections, service instances) are created once per
    worker process — not at import time — via ``_get_service_and_tracker()``.
    """

    abstract = True

    _service = None
    _repo = None
    _tracker = None

    def _get_service_and_tracker(self):
        if self._service is None:
            from agent_hub.database.config import create_repository
            from agent_hub.agents.global_part_time.service import AgentService

            database_url = os.environ.get("DATABASE_URL")
            repo = create_repository(database_url=database_url)
            self.__class__._repo = repo
            from agent_hub.agents.global_part_time.embedding import get_embedding

            self.__class__._service = AgentService(repo, embed_fn=get_embedding)

            # WorkflowTracker needs the SQLAlchemy engine (PostgreSQL only).
            if hasattr(repo, "_engine"):
                from agent_hub.worker.workflow import WorkflowTracker

                self.__class__._tracker = WorkflowTracker(repo._engine)
            else:
                logger.warning("Repository has no _engine attribute; workflow tracking disabled")

        return self._service, self._repo, self._tracker


def _run_task(
    task: WorkflowTask,
    workflow_type: str,
    step_name: str,
    target_id: str,
    actor: str,
    operation_fn,
    *,
    workflow_run_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared execution flow for all workflow tasks."""
    service, repo, tracker = task._get_service_and_tracker()

    # 1. Create or reuse workflow run.
    if tracker is not None:
        if workflow_run_id is None:
            workflow_run_id = tracker.create_run(
                workflow_type,
                target_id,
                actor,
                payload=payload,
                celery_task_id=task.request.id,
            )
        step_id = tracker.start_step(workflow_run_id, step_name, payload=payload)
    else:
        step_id = None

    # 2. Execute.
    idem_key = _make_idempotency_key(workflow_run_id or "no-run", step_name)

    try:
        if hasattr(repo, "idempotent"):
            result = repo.idempotent(f"task.{step_name}", idem_key, operation_fn)
        else:
            result = operation_fn()

        # 3. Success.
        if tracker is not None:
            tracker.complete_step(step_id, str(result)[:500])
            tracker.complete_run(workflow_run_id)

        return result

    except Exception as exc:
        classified = classify(exc)
        retry_count = task.request.retries or 0

        if tracker is not None:
            tracker.fail_step(step_id, classified.error_class, classified.message, retry_count)

        if classified.category == "permanent":
            logger.error("Permanent error in %s: %s", step_name, classified.message, exc_info=True)
            if tracker is not None:
                tracker.fail_run(workflow_run_id)
            raise

        # Retryable.
        if retry_count < MAX_RETRIES:
            countdown = BACKOFF_BASE * (2**retry_count)
            logger.warning(
                "Retryable error in %s (attempt %d/%d): %s — retrying in %ds",
                step_name,
                retry_count + 1,
                MAX_RETRIES,
                classified.message,
                countdown,
            )
            raise task.retry(
                exc=exc,
                countdown=countdown,
                max_retries=MAX_RETRIES,
                kwargs={
                    **(task.request.kwargs or {}),
                    "workflow_run_id": workflow_run_id,
                },
            )
        else:
            logger.error(
                "Max retries exhausted for %s: %s", step_name, classified.message, exc_info=True
            )
            if tracker is not None:
                tracker.mark_manual_review(workflow_run_id)
            raise


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.sync_source")
def sync_source_task(
    self,
    source_id: str,
    jobs: list[dict[str, Any]],
    actor: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    service, _repo, _tracker = self._get_service_and_tracker()
    result = _run_task(
        self,
        workflow_type="source_sync",
        step_name="sync_source",
        target_id=source_id,
        actor=actor,
        operation_fn=lambda: service.sync_source(source_id, jobs, actor),
        workflow_run_id=workflow_run_id,
        payload={"source_id": source_id, "job_count": len(jobs)},
    )
    job_ids = result.get("job_ids") or []
    if job_ids and hasattr(_repo, "update_job_embeddings"):
        embed_jobs_task.delay(job_ids, actor)
    return result


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.run_matches")
def run_matches_task(
    self,
    candidate_id: str,
    actor: str,
    limit: int = 50,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    service, _repo, _tracker = self._get_service_and_tracker()
    return _run_task(
        self,
        workflow_type="matching",
        step_name="run_matches",
        target_id=candidate_id,
        actor=actor,
        operation_fn=lambda: service.run_matches(candidate_id, actor, limit),
        workflow_run_id=workflow_run_id,
        payload={"candidate_id": candidate_id, "limit": limit},
    )


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.notification_pipeline")
def notification_pipeline_task(
    self,
    candidate_id: str,
    match_ids: list[str],
    actor: str,
    base_url: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute preview_digest only. The actual send requires human approval."""
    service, _repo, _tracker = self._get_service_and_tracker()

    def _preview():
        result = service.preview_digest(candidate_id, match_ids, actor, base_url)
        return {**result, "status": "awaiting_approval"}

    return _run_task(
        self,
        workflow_type="notification",
        step_name="preview_digest",
        target_id=candidate_id,
        actor=actor,
        operation_fn=_preview,
        workflow_run_id=workflow_run_id,
        payload={"candidate_id": candidate_id, "match_ids": match_ids},
    )


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.send_notification")
def send_notification_task(
    self,
    notification_id: str,
    actor: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    service, _repo, _tracker = self._get_service_and_tracker()
    return _run_task(
        self,
        workflow_type="notification_send",
        step_name="send_notification",
        target_id=notification_id,
        actor=actor,
        operation_fn=lambda: service.send_notification(notification_id, actor),
        workflow_run_id=workflow_run_id,
        payload={"notification_id": notification_id},
    )


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.fetch_and_sync_source")
def fetch_and_sync_source_task(
    self,
    source_id: str,
    actor: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """Fetch jobs from a single source, map them, and sync into the database."""
    from agent_hub.agents.global_part_time.fetchers import get_fetcher

    service, repo, _tracker = self._get_service_and_tracker()

    source = repo.get("source", source_id)
    if not source:
        logger.info("Source %s not found, skipping", source_id)
        return {"skipped": True, "reason": "source_not_found"}
    if source.get("review_status") != "approved" or not source.get("enabled"):
        logger.info("Source %s not approved/enabled, skipping", source_id)
        return {"skipped": True, "reason": "not_approved_or_enabled"}

    base_url = source.get("base_url", "")
    fetcher = get_fetcher(base_url)
    if fetcher is None:
        logger.info("No fetcher for source %s (base_url=%s), skipping", source_id, base_url)
        return {"skipped": True, "reason": "no_fetcher"}

    fetch_fn, map_fn = fetcher

    def _fetch_and_sync():
        raw_jobs = fetch_fn()
        mapped = [map_fn(raw) for raw in raw_jobs]
        return service.sync_source(source_id, mapped, actor)

    result = _run_task(
        self,
        workflow_type="source_fetch_sync",
        step_name="fetch_and_sync_source",
        target_id=source_id,
        actor=actor,
        operation_fn=_fetch_and_sync,
        workflow_run_id=workflow_run_id,
        payload={"source_id": source_id, "base_url": base_url},
    )
    job_ids = result.get("job_ids") or []
    if job_ids and hasattr(repo, "update_job_embeddings"):
        embed_jobs_task.delay(job_ids, actor)
    return result


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.parse_resume")
def parse_resume_task(
    self,
    pdf_bytes_hex: str,
    actor: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """解析简历 PDF → 创建候选人 → 自动 opt-in → 触发匹配。"""
    from agent_hub.agents.global_part_time.resume_parser import extract_text_from_pdf, parse_resume

    service, _repo, _tracker = self._get_service_and_tracker()

    def _parse_and_create():
        pdf_bytes = bytes.fromhex(pdf_bytes_hex)
        text = extract_text_from_pdf(pdf_bytes)
        if not text.strip():
            raise ValueError("无法从 PDF 中提取文本")

        parsed = parse_resume(text)
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

    return _run_task(
        self,
        workflow_type="resume_parsing",
        step_name="parse_resume",
        target_id="resume",
        actor=actor,
        operation_fn=_parse_and_create,
        workflow_run_id=workflow_run_id,
        payload={"actor": actor},
    )


@celery_app.task(name="agent_hub.worker.periodic_sync_all")
def periodic_sync_all_task() -> dict[str, Any]:
    """Coordinator: dispatch fetch_and_sync_source_task for every eligible source."""
    from agent_hub.agents.global_part_time.fetchers import get_fetcher
    from agent_hub.database.config import create_repository

    database_url = os.environ.get("DATABASE_URL")
    repo = create_repository(database_url=database_url)

    sources = repo.list("source")
    dispatched_ids = []
    skipped = 0

    for source in sources:
        if source.get("review_status") != "approved" or not source.get("enabled"):
            skipped += 1
            continue
        base_url = source.get("base_url", "")
        if get_fetcher(base_url) is None:
            skipped += 1
            continue
        fetch_and_sync_source_task.delay(source["id"], "beat:periodic_sync")
        dispatched_ids.append(source["id"])

    logger.info("periodic_sync_all: dispatched=%d skipped=%d", len(dispatched_ids), skipped)
    return {
        "dispatched": len(dispatched_ids),
        "skipped": skipped,
        "source_ids": dispatched_ids,
    }


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.chat_parse_and_match")
def parse_and_match_chat_task(
    self,
    session_id: str,
    resume_text: str,
    actor: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Chat 简历流水线：解析简历 → 建候选人 → opt-in → 绑定会话 → 匹配。

    确定性地一次跑完，不依赖 LLM 决定是否调用工具。业务逻辑委托给
    ``ChatService.run_analysis``，与同步 fallback 共用同一实现。
    """
    from agent_hub.agents.global_part_time.chat_service import ChatService

    service, repo, _tracker = self._get_service_and_tracker()
    chat = ChatService(service=service, repo=repo)
    return chat.run_analysis(session_id, resume_text, actor, limit)


# ---------------------------------------------------------------------------
# Embedding tasks
# ---------------------------------------------------------------------------

EMBED_BATCH_SIZE = 64


def _embed_jobs(repo: Any, job_ids: list[str]) -> dict[str, Any]:
    """为给定职位批量生成向量并落库。仓储无向量能力时直接跳过。"""
    if not hasattr(repo, "update_job_embeddings"):
        return {"requested": len(job_ids), "embedded": 0, "skipped": "no_vector_support"}
    from agent_hub.agents.global_part_time import embedding as embedding_mod

    jobs = [job for job in (repo.get("job", job_id) for job_id in job_ids) if job]
    embedded = 0
    for start in range(0, len(jobs), EMBED_BATCH_SIZE):
        batch = jobs[start : start + EMBED_BATCH_SIZE]
        vectors = embedding_mod.get_embeddings([embedding_mod.build_job_text(job) for job in batch])
        embeddings = {job["id"]: vec for job, vec in zip(batch, vectors) if vec is not None}
        if not embeddings and batch and embedding_mod.SILICONFLOW_API_KEY:
            # API key 已配置但整批失败 → 抛错交给错误分类器按可重试处理。
            raise RuntimeError("embedding API returned no vectors for batch")
        if embeddings:
            embedded += repo.update_job_embeddings(embeddings)
    return {"requested": len(job_ids), "embedded": embedded}


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.embed_jobs")
def embed_jobs_task(
    self,
    job_ids: list[str],
    actor: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    _service, repo, _tracker = self._get_service_and_tracker()
    return _run_task(
        self,
        workflow_type="embedding",
        step_name="embed_jobs",
        target_id=job_ids[0] if job_ids else "none",
        actor=actor,
        operation_fn=lambda: _embed_jobs(repo, job_ids),
        workflow_run_id=workflow_run_id,
        payload={"job_count": len(job_ids)},
    )


@celery_app.task(base=WorkflowTask, bind=True, name="agent_hub.worker.backfill_embeddings")
def backfill_embeddings_task(
    self,
    actor: str = "system",
    limit: int = 500,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """补齐存量活跃职位缺失的向量。"""
    _service, repo, _tracker = self._get_service_and_tracker()
    if not hasattr(repo, "list_jobs_missing_embedding"):
        return {"skipped": True, "reason": "no_vector_support"}
    job_ids = repo.list_jobs_missing_embedding(limit)
    return _run_task(
        self,
        workflow_type="embedding_backfill",
        step_name="backfill_embeddings",
        target_id="jobs",
        actor=actor,
        operation_fn=lambda: _embed_jobs(repo, job_ids),
        workflow_run_id=workflow_run_id,
        payload={"job_count": len(job_ids)},
    )
