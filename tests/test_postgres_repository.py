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

        from tests.factories import ensure_vector_extension

        repo = PostgresRepository(TEST_DATABASE_URL)

        ensure_vector_extension(repo._engine)

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


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set")
class PostgresVectorSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        from agent_hub.database.models import Base
        from agent_hub.database.repository import PostgresRepository

        from tests.factories import ensure_vector_extension

        self.repo = PostgresRepository(TEST_DATABASE_URL)
        ensure_vector_extension(self.repo._engine)
        Base.metadata.drop_all(self.repo._engine)
        Base.metadata.create_all(self.repo._engine)

    @staticmethod
    def _job(job_id: str, title: str) -> dict:
        return {
            "id": job_id,
            "source_id": "s1",
            "dedup_key": job_id,
            "title_original": title,
            "company_name": "ACME",
            "status": "active",
        }

    def test_search_orders_by_cosine_similarity(self):
        self.repo.put("job", self._job("job-a", "Python Backend"))
        self.repo.put("job", self._job("job-b", "Frontend React"))
        near = [0.0] * 1024
        near[0] = 1.0
        far = [0.0] * 1024
        far[1] = 1.0
        query = [0.0] * 1024
        query[0], query[1] = 0.9, 0.1
        self.assertEqual(self.repo.update_job_embeddings({"job-a": near, "job-b": far}), 2)
        hits = self.repo.search_jobs_by_embedding(query, limit=10)
        self.assertEqual([job["id"] for job, _sim in hits], ["job-a", "job-b"])
        self.assertGreater(hits[0][1], hits[1][1])

    def test_search_excludes_inactive_and_unembedded_jobs(self):
        self.repo.put("job", self._job("job-a", "Active embedded"))
        inactive = self._job("job-b", "Inactive")
        inactive["status"] = "rejected"
        self.repo.put("job", inactive)
        self.repo.put("job", self._job("job-c", "No embedding"))
        vec = [0.5] * 1024
        self.repo.update_job_embeddings({"job-a": vec, "job-b": vec})
        hits = self.repo.search_jobs_by_embedding(vec, limit=10)
        self.assertEqual([job["id"] for job, _sim in hits], ["job-a"])

    def test_put_job_preserves_embedding(self):
        self.repo.put("job", self._job("job-a", "Python Backend"))
        vec = [0.5] * 1024
        self.repo.update_job_embeddings({"job-a": vec})
        self.repo.put("job", self._job("job-a", "Python Backend (updated)"))
        hits = self.repo.search_jobs_by_embedding(vec, limit=10)
        self.assertEqual(hits[0][0]["id"], "job-a")

    def test_list_jobs_missing_embedding(self):
        self.repo.put("job", self._job("job-a", "A"))
        self.repo.put("job", self._job("job-b", "B"))
        self.repo.update_job_embeddings({"job-a": [0.1] * 1024})
        self.assertEqual(self.repo.list_jobs_missing_embedding(), ["job-b"])


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set")
class PostgresCategoryFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        from agent_hub.database.models import Base
        from agent_hub.database.repository import PostgresRepository

        from tests.factories import ensure_vector_extension

        self.repo = PostgresRepository(TEST_DATABASE_URL)
        ensure_vector_extension(self.repo._engine)
        Base.metadata.drop_all(self.repo._engine)
        Base.metadata.create_all(self.repo._engine)

    @staticmethod
    def _job(job_id: str, title: str, categories: list[str]) -> dict:
        return {
            "id": job_id,
            "source_id": "s1",
            "dedup_key": job_id,
            "title_original": title,
            "company_name": "ACME",
            "status": "active",
            "categories": categories,
        }

    def test_search_jobs_filters_by_category(self):
        self.repo.put("job", self._job("job-a", "Backend Dev", ["Developer", "Backend"]))
        self.repo.put("job", self._job("job-b", "Sales Rep", ["Sales"]))
        self.repo.put("job", self._job("job-c", "Fullstack", ["Developer"]))

        total, jobs = self.repo.search_jobs(category="Developer")
        self.assertEqual(total, 2)
        self.assertEqual({j["id"] for j in jobs}, {"job-a", "job-c"})

    def test_search_jobs_combines_category_with_keyword(self):
        self.repo.put("job", self._job("job-a", "Backend Dev", ["Developer"]))
        self.repo.put("job", self._job("job-b", "Frontend Dev", ["Developer"]))

        total, jobs = self.repo.search_jobs(q="Backend", category="Developer")
        self.assertEqual(total, 1)
        self.assertEqual(jobs[0]["id"], "job-a")

    def test_list_job_categories_aggregates_active_only(self):
        self.repo.put("job", self._job("job-a", "A", ["Developer", "Backend"]))
        self.repo.put("job", self._job("job-b", "B", ["Developer"]))
        inactive = self._job("job-c", "C", ["Sales"])
        inactive["status"] = "pending_review"
        self.repo.put("job", inactive)

        cats = self.repo.list_job_categories()
        self.assertEqual(cats[0], {"name": "Developer", "count": 2})
        self.assertIn({"name": "Backend", "count": 1}, cats)
        self.assertNotIn({"name": "Sales", "count": 1}, cats)


if __name__ == "__main__":
    unittest.main()
