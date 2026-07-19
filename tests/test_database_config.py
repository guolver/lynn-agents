"""Tests for repository factory configuration."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent_hub.database.config import create_repository


class DatabaseConfigTest(unittest.TestCase):
    def test_raises_without_database_url(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DATABASE_URL", None)
            with self.assertRaises(RuntimeError):
                create_repository()

    def test_explicit_database_url_selects_postgres(self) -> None:
        from agent_hub.database.repository import PostgresRepository

        with patch.object(PostgresRepository, "__init__", return_value=None):
            repo = create_repository(database_url="postgresql+psycopg://x:x@localhost:5432/test")
            self.assertIsInstance(repo, PostgresRepository)

    def test_env_database_url_selects_postgres(self) -> None:
        from agent_hub.database.repository import PostgresRepository

        with (
            patch.object(PostgresRepository, "__init__", return_value=None),
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql+psycopg://x:x@localhost:5432/test"},
                clear=False,
            ),
        ):
            repo = create_repository()
            self.assertIsInstance(repo, PostgresRepository)


if __name__ == "__main__":
    unittest.main()
