"""Make jobs.embedding HNSW index partial on status = 'active'.

search_jobs_by_embedding() filters on status = 'active' in addition to
ordering by embedding distance. The old full-table index required the
planner to prove the predicate via hnsw.iterative_scan, which it never did
(verified with enable_seqscan/enable_bitmapscan off: it fell back to
ix_jobs_status + sort instead). Scoping the index to the same predicate lets
the planner match it directly with no iterative scan needed, confirmed by
temporarily dropping ix_jobs_status in a rolled-back transaction: the query
then picks ix_jobs_embedding_hnsw straight away.

This does NOT make the planner pick the index today. At ~11k active jobs,
the cost estimate for the HNSW ordered scan still loses to
ix_jobs_status + sort (a plain seq scan costs ~1700 vs. ~2200-47700 for the
HNSW path), so search_jobs_by_embedding() keeps sorting the full active-job
set (~100-150ms) until the table grows enough to flip that cost comparison.
That's expected and fine at current volume — this migration just removes
the predicate-matching blocker so the index is ready to be picked up once
the table is large enough for a sequential scan to be the more expensive
option.

Also note for whenever the planner does start using it: pgvector's default
hnsw.ef_search is 40, below RECALL_LIMIT (200, see service.py). Once this
index scan path becomes live, the caller must SET hnsw.ef_search >= 200 for
the session or run_matches() will silently recall fewer candidates than
requested.

Revision ID: 20260719_0008
Revises: 20260719_0007
Create Date: 2026-07-19
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260719_0008"
down_revision: Union[str, None] = "20260719_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_embedding_hnsw")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_embedding_hnsw "
        "ON jobs USING hnsw (embedding vector_cosine_ops) "
        "WHERE status = 'active'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_embedding_hnsw")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_embedding_hnsw "
        "ON jobs USING hnsw (embedding vector_cosine_ops)"
    )
