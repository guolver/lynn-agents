"""PostgreSQL foundation schema.

Revision ID: 20260717_0001
Revises:
Create Date: 2026-07-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260717_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- job_sources ---
    op.create_table(
        "job_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("payload", postgresql.JSONB, nullable=False),
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
    )
    op.create_index("ix_job_sources_review_status", "job_sources", ["review_status"])

    # --- source_sync_runs ---
    op.create_table(
        "source_sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("job_sources.id"),
            nullable=False,
        ),
        sa.Column("received", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("imported", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("duplicates", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("pending_review", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("rejected", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_source_sync_runs_source_id", "source_sync_runs", ["source_id"])

    # --- raw_jobs ---
    op.create_table(
        "raw_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("job_sources.id"),
            nullable=False,
        ),
        sa.Column("source_job_id", sa.String(255), nullable=False),
        sa.Column("canonical_url", sa.Text, nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_raw_jobs_source_identity", "raw_jobs", ["source_id", "source_job_id"]
    )
    op.create_unique_constraint("uq_raw_jobs_canonical_url", "raw_jobs", ["canonical_url"])
    op.create_unique_constraint(
        "uq_raw_jobs_content_fingerprint", "raw_jobs", ["content_fingerprint"]
    )

    # --- skills (before tables that reference it) ---
    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- skill_aliases ---
    op.create_table(
        "skill_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("alias", sa.String(255), nullable=False, unique=True),
    )
    op.create_index("ix_skill_aliases_skill_id", "skill_aliases", ["skill_id"])

    # --- skill_relations ---
    op.create_table(
        "skill_relations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("from_skill_id", sa.String(36), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("to_skill_id", sa.String(36), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("relation_type", sa.String(50), nullable=False),
    )
    op.create_unique_constraint(
        "uq_skill_relations",
        "skill_relations",
        ["from_skill_id", "to_skill_id", "relation_type"],
    )

    # --- jobs ---
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("title_original", sa.Text, nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="not_required"),
        sa.Column("risk_level", sa.String(10), nullable=False, server_default="low"),
        sa.Column("risk_score", sa.Float, nullable=False, server_default=sa.text("0.0")),
        sa.Column("payload", postgresql.JSONB, nullable=False),
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
    )
    op.create_unique_constraint("uq_jobs_dedup_key", "jobs", ["dedup_key"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_source_id", "jobs", ["source_id"])

    # --- job_versions ---
    op.create_table(
        "job_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_job_versions_job_id", "job_versions", ["job_id"])

    # --- job_skills ---
    op.create_table(
        "job_skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("required", sa.Boolean, nullable=False, server_default=sa.text("true")),
    )
    op.create_unique_constraint("uq_job_skills", "job_skills", ["job_id", "skill_id"])
    op.create_index("ix_job_skills_job_id", "job_skills", ["job_id"])

    # --- candidates ---
    op.create_table(
        "candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("country", sa.String(10), nullable=False),
        sa.Column("timezone", sa.String(50), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("consent_status", sa.String(20), nullable=False, server_default="not_requested"),
        sa.Column("payload", postgresql.JSONB, nullable=False),
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
    )
    op.create_index("ix_candidates_consent_status", "candidates", ["consent_status"])

    # --- candidate_experiences ---
    op.create_table(
        "candidate_experiences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("candidates.id"),
            nullable=False,
        ),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("role", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_candidate_experiences_candidate_id", "candidate_experiences", ["candidate_id"]
    )

    # --- candidate_skills ---
    op.create_table(
        "candidate_skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("candidates.id"),
            nullable=False,
        ),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("level", sa.Integer, nullable=False, server_default=sa.text("1")),
    )
    op.create_unique_constraint(
        "uq_candidate_skills", "candidate_skills", ["candidate_id", "skill_id"]
    )
    op.create_index("ix_candidate_skills_candidate_id", "candidate_skills", ["candidate_id"])

    # --- matches ---
    op.create_table(
        "matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("candidates.id"),
            nullable=False,
        ),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("hard_filter_passed", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_matches_candidate_job", "matches", ["candidate_id", "job_id"])
    op.create_index("ix_matches_candidate_id", "matches", ["candidate_id"])
    op.create_index("ix_matches_job_id", "matches", ["job_id"])

    # --- match_evidence ---
    op.create_table(
        "match_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("match_id", sa.String(36), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_match_evidence_match_id", "match_evidence", ["match_id"])

    # --- match_score_items ---
    op.create_table(
        "match_score_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("match_id", sa.String(36), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("dimension", sa.String(50), nullable=False),
        sa.Column("weight", sa.Float, nullable=False),
        sa.Column("raw_score", sa.Float, nullable=False),
        sa.Column("weighted_score", sa.Float, nullable=False),
    )
    op.create_index("ix_match_score_items_match_id", "match_score_items", ["match_id"])

    # --- workflow_runs ---
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("payload", postgresql.JSONB, nullable=False),
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
    )
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    # --- workflow_steps ---
    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workflow_run_id",
            sa.String(36),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("step_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_workflow_steps_workflow_run_id", "workflow_steps", ["workflow_run_id"])

    # --- approvals ---
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_approvals_status", "approvals", ["status"])

    # --- notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("candidates.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_approval"),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
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
    )
    op.create_unique_constraint(
        "uq_notifications_provider_message_id", "notifications", ["provider_message_id"]
    )
    op.create_index("ix_notifications_candidate_id", "notifications", ["candidate_id"])
    op.create_index("ix_notifications_status", "notifications", ["status"])

    # --- feedback ---
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("match_id", sa.String(36), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("candidates.id"),
            nullable=False,
        ),
        sa.Column("value", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_feedback_match_id", "feedback", ["match_id"])
    op.create_index("ix_feedback_candidate_id", "feedback", ["candidate_id"])

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_logs_entity", "audit_logs", ["kind", "entity_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # --- idempotency_records ---
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("response", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_idempotency_records_action_key", "idempotency_records", ["action", "key"]
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("audit_logs")
    op.drop_table("feedback")
    op.drop_table("notifications")
    op.drop_table("approvals")
    op.drop_table("workflow_steps")
    op.drop_table("workflow_runs")
    op.drop_table("match_score_items")
    op.drop_table("match_evidence")
    op.drop_table("matches")
    op.drop_table("candidate_skills")
    op.drop_table("candidate_experiences")
    op.drop_table("candidates")
    op.drop_table("job_skills")
    op.drop_table("job_versions")
    op.drop_table("jobs")
    op.drop_table("skill_relations")
    op.drop_table("skill_aliases")
    op.drop_table("skills")
    op.drop_table("raw_jobs")
    op.drop_table("source_sync_runs")
    op.drop_table("job_sources")
