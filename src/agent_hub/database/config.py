"""Repository factory: select SQLite or PostgreSQL based on configuration.

Selection order:
1. Explicit ``database_url`` parameter
2. ``DATABASE_URL`` environment variable
3. Explicit ``sqlite_path`` parameter
4. ``DATABASE_PATH`` environment variable
5. ``./data/agent.db`` (default SQLite)
"""

from __future__ import annotations

import os

from agent_hub.agents.global_part_time.repository import RepositoryProtocol, SQLiteRepository


def create_repository(
    database_url: str | None = None,
    sqlite_path: str | None = None,
) -> RepositoryProtocol:
    """Return a configured repository instance."""
    url = database_url or os.environ.get("DATABASE_URL")
    if url:
        from agent_hub.database.repository import PostgresRepository

        return PostgresRepository(url)

    path = sqlite_path or os.environ.get("DATABASE_PATH", "./data/agent.db")
    return SQLiteRepository(path)
