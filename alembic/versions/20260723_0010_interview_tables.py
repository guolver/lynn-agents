"""Add interview_knowledge, interview_sessions, and interview_messages tables.

Revision ID: 20260723_0010
Revises: 19f8c54c3bbb
Create Date: 2026-07-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0010"
down_revision: Union[str, None] = "19f8c54c3bbb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_knowledge",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source_file", sa.String(255), nullable=True),
        sa.Column("source_format", sa.String(20), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("extra_data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_interview_knowledge_tenant_id", "interview_knowledge", ["tenant_id"])
    op.create_index("ix_interview_knowledge_category", "interview_knowledge", ["category"])

    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
        sa.Column("actor", sa.String(255), nullable=False, server_default="anonymous"),
        sa.Column("target_role", sa.String(100), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("summary", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_interview_sessions_tenant_id", "interview_sessions", ["tenant_id"])
    op.create_index("ix_interview_sessions_status", "interview_sessions", ["status"])

    op.create_table(
        "interview_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id", sa.String(36), sa.ForeignKey("interview_sessions.id"), nullable=False
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("evaluation", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_interview_messages_session_id", "interview_messages", ["session_id"])


def downgrade() -> None:
    op.drop_table("interview_messages")
    op.drop_table("interview_sessions")
    op.drop_table("interview_knowledge")
