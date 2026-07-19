"""Repository factory: PostgreSQL only.

``DATABASE_URL``（参数或环境变量）必须提供，形如
``postgresql+psycopg://user:pass@host:5432/dbname``。
"""

from __future__ import annotations

import os

from agent_hub.agents.global_part_time.repository import RepositoryProtocol


def create_repository(database_url: str | None = None) -> RepositoryProtocol:
    """Return a configured PostgreSQL repository instance."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required (e.g. postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub)"
        )
    from agent_hub.database.repository import PostgresRepository

    return PostgresRepository(url)
