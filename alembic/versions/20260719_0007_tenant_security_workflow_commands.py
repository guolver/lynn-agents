"""Add tenant isolation and workflow command persistence.

Revision ID: 20260719_0007
Revises: 20260718_0006
Create Date: 2026-07-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260719_0007"
down_revision: Union[str, None] = "20260718_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = (
    "job_sources",
    "jobs",
    "candidates",
    "matches",
    "approvals",
    "notifications",
    "feedback",
    "audit_logs",
    "idempotency_records",
    "workflow_runs",
    "chat_sessions",
)

DOWNGRADE_DUPLICATE_QUERIES = (
    (
        "jobs.dedup_key",
        "SELECT dedup_key FROM jobs GROUP BY dedup_key "
        "HAVING COUNT(DISTINCT tenant_id) > 1 LIMIT 1",
    ),
    (
        "matches.(candidate_id, job_id)",
        "SELECT candidate_id, job_id FROM matches GROUP BY candidate_id, job_id "
        "HAVING COUNT(DISTINCT tenant_id) > 1 LIMIT 1",
    ),
    (
        "idempotency_records.(action, key)",
        "SELECT action, key FROM idempotency_records GROUP BY action, key "
        "HAVING COUNT(DISTINCT tenant_id) > 1 LIMIT 1",
    ),
)


def upgrade() -> None:
    for table_name in TENANT_TABLES:
        op.add_column(table_name, sa.Column("tenant_id", sa.String(100), nullable=True))
    op.add_column("candidates", sa.Column("owner_actor_id", sa.String(255), nullable=True))

    for table_name in TENANT_TABLES:
        op.execute(f"UPDATE {table_name} SET tenant_id = 'default' WHERE tenant_id IS NULL")
    op.execute("UPDATE candidates SET owner_actor_id = 'legacy-owner' WHERE owner_actor_id IS NULL")

    op.drop_constraint("uq_jobs_dedup_key", "jobs", type_="unique")
    op.create_unique_constraint("uq_jobs_tenant_dedup_key", "jobs", ["tenant_id", "dedup_key"])
    op.drop_constraint("uq_matches_candidate_job", "matches", type_="unique")
    op.create_unique_constraint(
        "uq_matches_tenant_candidate_job",
        "matches",
        ["tenant_id", "candidate_id", "job_id"],
    )
    op.drop_constraint("uq_idempotency_records_action_key", "idempotency_records", type_="unique")
    op.create_unique_constraint(
        "uq_idempotency_tenant_action_key",
        "idempotency_records",
        ["tenant_id", "action", "key"],
    )

    for table_name in TENANT_TABLES:
        op.alter_column(table_name, "tenant_id", nullable=False)
    op.alter_column("candidates", "owner_actor_id", nullable=False)

    op.create_table(
        "workflow_commands",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "workflow_run_id",
            sa.String(36),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending_dispatch",
        ),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "action",
            "idempotency_key",
            name="uq_workflow_commands_request",
        ),
    )
    op.create_table(
        "workflow_command_payloads",
        sa.Column(
            "command_id",
            sa.String(36),
            sa.ForeignKey("workflow_commands.id"),
            primary_key=True,
        ),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for key_name, query in DOWNGRADE_DUPLICATE_QUERIES:
        if connection.execute(sa.text(query)).first() is not None:
            raise RuntimeError(
                f"Cannot downgrade tenant schema: cross-tenant duplicates exist for {key_name}"
            )

    op.drop_table("workflow_command_payloads")
    op.drop_table("workflow_commands")

    op.drop_constraint("uq_jobs_tenant_dedup_key", "jobs", type_="unique")
    op.create_unique_constraint("uq_jobs_dedup_key", "jobs", ["dedup_key"])
    op.drop_constraint("uq_matches_tenant_candidate_job", "matches", type_="unique")
    op.create_unique_constraint("uq_matches_candidate_job", "matches", ["candidate_id", "job_id"])
    op.drop_constraint("uq_idempotency_tenant_action_key", "idempotency_records", type_="unique")
    op.create_unique_constraint(
        "uq_idempotency_records_action_key", "idempotency_records", ["action", "key"]
    )

    op.drop_column("candidates", "owner_actor_id")
    for table_name in reversed(TENANT_TABLES):
        op.drop_column(table_name, "tenant_id")
