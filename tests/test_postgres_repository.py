"""PostgreSQL repository contract tests.

Reuses the shared RepositoryContractMixin from test_repository_contract.
Skipped when TEST_DATABASE_URL is not set.
"""

from __future__ import annotations

import os
import unittest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set")
class PostgresRepositoryContractTest(unittest.TestCase):
    """Run the shared repository contract against PostgreSQL."""

    def create_repository(self):
        from agent_hub.database.models import Base
        from agent_hub.database.repository import PostgresRepository

        repo = PostgresRepository(TEST_DATABASE_URL)

        from sqlalchemy import text

        with repo._engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()

        Base.metadata.drop_all(repo._engine)
        Base.metadata.create_all(repo._engine)
        return repo

    def setUp(self) -> None:
        self.repository = self.create_repository()

    # Import mixin methods so unittest discovers them.
    from tests.test_repository_contract import RepositoryContractMixin

    test_round_trip_crud = RepositoryContractMixin.test_round_trip_crud
    test_list_orders_newest_created_first = (
        RepositoryContractMixin.test_list_orders_newest_created_first
    )
    test_audit_reads_are_append_only_and_newest_first = (
        RepositoryContractMixin.test_audit_reads_are_append_only_and_newest_first
    )
    test_failing_operation_is_not_recorded_and_can_be_retried = (
        RepositoryContractMixin.test_failing_operation_is_not_recorded_and_can_be_retried
    )
    test_same_key_idempotency_returns_first_result = (
        RepositoryContractMixin.test_same_key_idempotency_returns_first_result
    )


if __name__ == "__main__":
    unittest.main()
