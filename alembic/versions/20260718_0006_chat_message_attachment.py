"""Add chat_messages.attachment column (file metadata for uploaded resumes).

Revision ID: 20260718_0006
Revises: 20260718_0005
Create Date: 2026-07-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260718_0006"
down_revision: Union[str, None] = "20260718_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("attachment", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "attachment")
