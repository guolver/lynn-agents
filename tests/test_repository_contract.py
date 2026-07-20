"""Shared dictionary repository contract tests."""

from __future__ import annotations

import os
import unittest
from typing import Any

from tests.factories import candidate_payload, job_payload, source_payload
from tests.inmemory_repo import InMemoryRepository

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


class PayloadFactoryTest(unittest.TestCase):
    def test_factories_return_fresh_nested_dictionaries(self) -> None:
        source = source_payload()
        source["allowed_paths"].append("/mutated")
        self.assertEqual(source_payload()["allowed_paths"], ["/jobs"])

        job = job_payload()
        job["skills"].append("mutated")
        self.assertEqual(job_payload()["skills"], ["python", "data_annotation"])

        candidate = candidate_payload()
        candidate["languages"][0]["code"] = "mutated"
        self.assertEqual(candidate_payload()["languages"][0]["code"], "zh-CN")


class RepositoryContractMixin:
    """Contract shared by the in-memory fake and the PostgreSQL repository."""

    repository: Any

    def create_repository(self) -> Any:
        self.fail("wire a repository fixture")

    def setUp(self) -> None:
        self.repository = self.create_repository()

    def test_round_trip_crud(self) -> None:
        item = {"id": "job-1", "name": "Initial"}

        stored = self.repository.put("job", item)
        self.assertEqual(self.repository.get("job", "job-1"), stored)
        self.assertEqual(self.repository.list("job"), [stored])

        stored["name"] = "Updated"
        updated = self.repository.put("job", stored)
        self.assertEqual(self.repository.get("job", "job-1"), updated)

        self.repository.delete("job", "job-1")
        self.assertIsNone(self.repository.get("job", "job-1"))
        self.assertEqual(self.repository.list("job"), [])

    def test_list_orders_newest_created_first(self) -> None:
        older = {"id": "older", "created_at": "2026-07-16T00:00:00+00:00"}
        newer = {"id": "newer", "created_at": "2026-07-17T00:00:00+00:00"}
        self.repository.put("job", older)
        self.repository.put("job", newer)

        self.assertEqual([item["id"] for item in self.repository.list("job")], ["newer", "older"])

    def test_audit_reads_are_append_only_and_newest_first(self) -> None:
        self.repository.audit("job.created", "job", "job-1", "operator", {"sequence": 1})
        self.repository.audit("job.reviewed", "job", "job-1", "reviewer", {"sequence": 2})

        audits = self.repository.audits()
        self.assertEqual([item["event"] for item in audits], ["job.reviewed", "job.created"])
        self.assertEqual([item["details"] for item in audits], [{"sequence": 2}, {"sequence": 1}])
        self.assertEqual(len(self.repository.audits(limit=1)), 1)

    def test_failing_operation_is_not_recorded_and_can_be_retried(self) -> None:
        calls = 0

        def operation() -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("operation failed")
            return {"id": "stable"}

        with self.assertRaisesRegex(RuntimeError, "operation failed"):
            self.repository.idempotent("job.create", "same-key", operation)

        self.assertEqual(
            self.repository.idempotent("job.create", "same-key", operation), {"id": "stable"}
        )
        self.assertEqual(calls, 2)

    def test_same_key_idempotency_returns_first_result(self) -> None:
        calls = 0

        def operation() -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return {"call": calls}

        first = self.repository.idempotent("job.create", "same-key", operation)
        second = self.repository.idempotent("job.create", "same-key", operation)

        self.assertEqual(first, {"call": 1})
        self.assertEqual(second, first)
        self.assertEqual(calls, 1)


class InMemoryRepositoryContractTest(RepositoryContractMixin, unittest.TestCase):
    def create_repository(self) -> InMemoryRepository:
        return InMemoryRepository(":memory:")


class TenantScopedInMemoryRepositoryContractTest(RepositoryContractMixin, unittest.TestCase):
    """A repository obtained via for_tenant() must satisfy the full contract too."""

    def create_repository(self) -> Any:
        return InMemoryRepository(":memory:").for_tenant("acme")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set")
class TenantScopedPostgresRepositoryContractTest(RepositoryContractMixin, unittest.TestCase):
    """A PostgresRepository.for_tenant() view must satisfy the full contract too."""

    def create_repository(self) -> Any:
        from agent_hub.database.models import Base
        from agent_hub.database.repository import PostgresRepository

        from tests.factories import ensure_vector_extension

        repo = PostgresRepository(TEST_DATABASE_URL)
        ensure_vector_extension(repo._engine)
        Base.metadata.drop_all(repo._engine)
        Base.metadata.create_all(repo._engine)
        return repo.for_tenant("acme")


if __name__ == "__main__":
    unittest.main()
