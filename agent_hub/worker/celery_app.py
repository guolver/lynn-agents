"""Celery application factory and configuration.

The module-level ``celery_app`` instance is used by the ``celery`` CLI worker
process.  Configuration is driven by environment variables so that the same
image works across dev / staging / production.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab


def create_celery_app() -> Celery:
    """Build a Celery application with production-safe defaults."""
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")

    sync_interval = int(os.getenv("SYNC_INTERVAL_HOURS", "4"))

    app = Celery("agent_hub")
    app.conf.update(
        broker_url=broker_url,
        result_backend=result_backend,
        # Worker picks up the task only after completing the current one.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        # Time limits.
        task_soft_time_limit=300,
        task_time_limit=360,
        # Serialisation.
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Timezone.
        timezone="UTC",
        enable_utc=True,
        # Beat schedule — periodic source sync.
        beat_schedule={
            "periodic-sync-all-sources": {
                "task": "agent_hub.worker.periodic_sync_all",
                "schedule": crontab(minute=0, hour=f"*/{sync_interval}"),
            },
        },
    )
    app.autodiscover_tasks(["agent_hub.worker"])
    return app


celery_app = create_celery_app()
