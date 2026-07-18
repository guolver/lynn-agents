"""Add retry/error columns to workflow_steps and actor/celery columns to workflow_runs.

Revision ID: 20260717_0002
Revises: 20260717_0001
Create Date: 2026-07-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260717_0002"
down_revision: Union[str, None] = "20260717_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- workflow_runs: add actor and celery_task_id ---
    op.add_column(
        "workflow_runs",
        sa.Column("actor", sa.String(255), nullable=False, server_default="system"),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("celery_task_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_workflow_runs_celery_task_id", "workflow_runs", ["celery_task_id"])

    # --- workflow_steps: add retry_count, error_class, error_detail ---
    op.add_column(
        "workflow_steps",
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "workflow_steps",
        sa.Column("error_class", sa.String(20), nullable=True),
    )
    op.add_column(
        "workflow_steps",
        sa.Column("error_detail", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_steps", "error_detail")
    op.drop_column("workflow_steps", "error_class")
    op.drop_column("workflow_steps", "retry_count")
    op.drop_index("ix_workflow_runs_celery_task_id", table_name="workflow_runs")
    op.drop_column("workflow_runs", "celery_task_id")
    op.drop_column("workflow_runs", "actor")
