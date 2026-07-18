"""Add pgvector extension, jobs.embedding column and HNSW index.

Revision ID: 20260718_0004
Revises: 20260718_0003
Create Date: 2026-07-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260718_0004"
down_revision: Union[str, None] = "20260718_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("jobs", sa.Column("embedding", Vector(1024), nullable=True))
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_embedding_hnsw "
        "ON jobs USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_embedding_hnsw")
    op.drop_column("jobs", "embedding")
