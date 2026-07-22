"""merge pgvector and identity heads

Revision ID: 19f8c54c3bbb
Revises: 20260719_0008, 20260719_0009
Create Date: 2026-07-20 20:05:25.761863
"""

from __future__ import annotations

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "19f8c54c3bbb"
down_revision: Union[str, None] = ("20260719_0008", "20260719_0009")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
