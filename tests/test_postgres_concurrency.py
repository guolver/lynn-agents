"""PostgreSQL concurrency and transactional idempotency tests.

Skipped when TEST_DATABASE_URL is not set.
"""

from __future__ import annotations

import os
import threading
import unittest
from typing import Any

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set")
class PostgresConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        from agent_hub.database.models import Base
        from agent_hub.database.repository import PostgresRepository

        self.repo1 = PostgresRepository(TEST_DATABASE_URL)
        self.repo2 = PostgresRepository(TEST_DATABASE_URL)
        Base.metadata.drop_all(self.repo1._engine)
        Base.metadata.create_all(self.repo1._engine)

    def test_concurrent_idempotent_produces_one_entity_and_identical_responses(self) -> None:
        results: list[dict[str, Any]] = [None, None]  # type: ignore[list-item]
        errors: list[Exception | None] = [None, None]
        barrier = threading.Barrier(2)

        def run(idx: int, repo: Any) -> None:
            try:
                barrier.wait(timeout=5)
                results[idx] = repo.idempotent(
                    "test.concurrent",
                    "same-key",
                    lambda: repo.put(
                        "job",
                        {
                            "id": f"job-from-thread-{idx}",
                            "source_id": "s1",
                            "dedup_key": f"dk-{idx}",
                            "title_original": f"Job {idx}",
                            "company_name": "TestCo",
                            "status": "active",
                            "review_status": "not_required",
                            "risk_level": "low",
                            "risk_score": 0.0,
                        },
                    ),
                )
            except Exception as exc:
                errors[idx] = exc

        t1 = threading.Thread(target=run, args=(0, self.repo1))
        t2 = threading.Thread(target=run, args=(1, self.repo2))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        for i, err in enumerate(errors):
            self.assertIsNone(err, f"thread {i} raised: {err}")

        # Both threads got the same result.
        self.assertEqual(results[0], results[1])

        # Only one job entity exists.
        jobs = self.repo1.list("job")
        self.assertEqual(len(jobs), 1)

    def test_operation_exception_rolls_back_entity_and_idempotency_record(self) -> None:
        with self.assertRaises(RuntimeError):
            self.repo1.idempotent(
                "test.rollback",
                "fail-key",
                lambda: self._failing_operation(),
            )

        # Neither entity nor idempotency record should exist.
        self.assertIsNone(self.repo1.get("job", "should-not-persist"))
        # Second call with same key should execute the operation again.
        result = self.repo1.idempotent(
            "test.rollback",
            "fail-key",
            lambda: {"recovered": True},
        )
        self.assertEqual(result, {"recovered": True})

    def _failing_operation(self) -> dict[str, Any]:
        self.repo1.put(
            "job",
            {
                "id": "should-not-persist",
                "source_id": "s1",
                "dedup_key": "dk-fail",
                "title_original": "Fail",
                "company_name": "FailCo",
                "status": "active",
                "review_status": "not_required",
                "risk_level": "low",
                "risk_score": 0.0,
            },
        )
        raise RuntimeError("intentional failure")


if __name__ == "__main__":
    unittest.main()
