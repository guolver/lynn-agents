"""Tests for repository factory configuration."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent_hub.agents.global_part_time.repository import SQLiteRepository
from agent_hub.database.config import create_repository


class DatabaseConfigTest(unittest.TestCase):
    def test_defaults_to_sqlite_when_no_url(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DATABASE_URL", None)
            os.environ.pop("DATABASE_PATH", None)
            repo = create_repository()
            self.assertIsInstance(repo, SQLiteRepository)

    def test_explicit_sqlite_path(self) -> None:
        repo = create_repository(sqlite_path=":memory:")
        self.assertIsInstance(repo, SQLiteRepository)

    def test_env_database_path_selects_sqlite(self) -> None:
        with patch.dict(os.environ, {"DATABASE_PATH": ":memory:"}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            repo = create_repository()
            self.assertIsInstance(repo, SQLiteRepository)

    def test_explicit_database_url_selects_postgres(self) -> None:
        # We can't actually connect, but we can verify the type.
        from agent_hub.database.repository import PostgresRepository

        repo = create_repository(database_url="postgresql+psycopg://x:x@localhost:5432/test")
        self.assertIsInstance(repo, PostgresRepository)

    def test_env_database_url_selects_postgres(self) -> None:
        from agent_hub.database.repository import PostgresRepository

        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql+psycopg://x:x@localhost:5432/test"},
            clear=False,
        ):
            repo = create_repository()
            self.assertIsInstance(repo, PostgresRepository)

    def test_explicit_url_takes_priority_over_env(self) -> None:
        from agent_hub.database.repository import PostgresRepository

        with patch.dict(os.environ, {"DATABASE_PATH": ":memory:"}, clear=False):
            repo = create_repository(database_url="postgresql+psycopg://x:x@localhost:5432/test")
            self.assertIsInstance(repo, PostgresRepository)


if __name__ == "__main__":
    unittest.main()
