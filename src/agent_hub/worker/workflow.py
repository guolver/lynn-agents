"""WorkflowTracker — records workflow runs and steps in PostgreSQL.

Key design decision: WorkflowTracker owns an **independent sessionmaker** that
does NOT use the ``_active_session`` context variable from the main repository.
This ensures that workflow step records survive even when the business operation
rolls back (e.g. a failed ``sync_source`` should still record the failure step).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from agent_hub.database.models import WorkflowRun, WorkflowStep


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class WorkflowTracker:
    """Audit-oriented tracker for asynchronous workflow runs and their steps."""

    def __init__(self, engine: Engine):
        self._session_factory = sessionmaker(bind=engine)

    def _session(self) -> Session:
        return self._session_factory()

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def create_run(
        self,
        workflow_type: str,
        target_id: str,
        actor: str,
        payload: dict[str, Any] | None = None,
        celery_task_id: str | None = None,
    ) -> str:
        """Create a new workflow run and return its id."""
        run_id = _new_id()
        session = self._session()
        try:
            run = WorkflowRun(
                id=run_id,
                workflow_type=workflow_type,
                target_id=target_id,
                status="running",
                actor=actor,
                celery_task_id=celery_task_id,
                payload=payload or {},
            )
            session.add(run)
            session.commit()
            return run_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def complete_run(self, run_id: str) -> None:
        self._update_run_status(run_id, "completed")

    def fail_run(self, run_id: str) -> None:
        self._update_run_status(run_id, "failed")

    def mark_manual_review(self, run_id: str) -> None:
        self._update_run_status(run_id, "manual_review")

    def _update_run_status(self, run_id: str, status: str) -> None:
        session = self._session()
        try:
            session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id)
                .values(status=status, updated_at=_utcnow())
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Step lifecycle
    # ------------------------------------------------------------------

    def start_step(
        self,
        workflow_run_id: str,
        step_name: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Create a new step in *running* status and return its id."""
        step_id = _new_id()
        session = self._session()
        try:
            step = WorkflowStep(
                id=step_id,
                workflow_run_id=workflow_run_id,
                step_name=step_name,
                status="running",
                retry_count=0,
                payload=payload or {},
            )
            session.add(step)
            session.commit()
            return step_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def complete_step(self, step_id: str, output_summary: str | None = None) -> None:
        session = self._session()
        try:
            values: dict[str, Any] = {"status": "completed"}
            if output_summary is not None:
                values["payload"] = {"output_summary": output_summary}
            session.execute(update(WorkflowStep).where(WorkflowStep.id == step_id).values(**values))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def fail_step(
        self,
        step_id: str,
        error_class: str,
        error_detail: str,
        retry_count: int,
    ) -> None:
        session = self._session()
        try:
            session.execute(
                update(WorkflowStep)
                .where(WorkflowStep.id == step_id)
                .values(
                    status="failed",
                    error_class=error_class[:20],
                    error_detail=error_detail[:2000],
                    retry_count=retry_count,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a run with all its steps, or ``None``."""
        session = self._session()
        try:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                return None
            steps = (
                session.execute(
                    select(WorkflowStep)
                    .where(WorkflowStep.workflow_run_id == run_id)
                    .order_by(WorkflowStep.created_at)
                )
                .scalars()
                .all()
            )
            return {
                "id": run.id,
                "workflow_type": run.workflow_type,
                "target_id": run.target_id,
                "status": run.status,
                "actor": run.actor,
                "celery_task_id": run.celery_task_id,
                "payload": run.payload,
                "created_at": run.created_at.isoformat() if run.created_at else "",
                "updated_at": run.updated_at.isoformat() if run.updated_at else "",
                "steps": [
                    {
                        "id": s.id,
                        "step_name": s.step_name,
                        "status": s.status,
                        "retry_count": s.retry_count,
                        "error_class": s.error_class,
                        "error_detail": s.error_detail,
                        "payload": s.payload,
                        "created_at": s.created_at.isoformat() if s.created_at else "",
                    }
                    for s in steps
                ],
            }
        finally:
            session.close()

    def list_runs(
        self,
        status: str | None = None,
        workflow_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return a summary list of runs (without steps)."""
        session = self._session()
        try:
            stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc())
            if status:
                stmt = stmt.where(WorkflowRun.status == status)
            if workflow_type:
                stmt = stmt.where(WorkflowRun.workflow_type == workflow_type)
            stmt = stmt.limit(min(limit, 200))
            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "id": r.id,
                    "workflow_type": r.workflow_type,
                    "target_id": r.target_id,
                    "status": r.status,
                    "actor": r.actor,
                    "celery_task_id": r.celery_task_id,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                    "updated_at": r.updated_at.isoformat() if r.updated_at else "",
                }
                for r in rows
            ]
        finally:
            session.close()
