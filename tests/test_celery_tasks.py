"""Celery task tests using task.apply() — no Redis required.

These tests use the in-memory SQLite repository (the default when no
DATABASE_URL is set) and execute tasks synchronously via ``task.apply()``.
"""

import unittest
from unittest.mock import patch

from agent_hub.agents.global_part_time.repository import SQLiteRepository
from agent_hub.agents.global_part_time.service import AgentService
from agent_hub.worker.celery_app import celery_app
from agent_hub.worker.tasks import (
    WorkflowTask,
    _embed_jobs,
    _make_idempotency_key,
    notification_pipeline_task,
    run_matches_task,
    send_notification_task,
    sync_source_task,
)


# Force Celery to execute tasks eagerly (synchronously, in-process).
celery_app.conf.update(
    task_always_eager=True,
    task_eager_propagates=True,
)


def _make_service():
    """Create a service with an in-memory SQLite repo."""
    repo = SQLiteRepository(":memory:")
    return AgentService(repo), repo


def _seed_source(service, repo):
    """Create and approve a source for sync tests."""
    source = service.create_source(
        {"name": "TestFeed", "source_type": "api", "base_url": "https://example.com"},
        "admin",
    )
    service.review_source(source["id"], True, "admin")
    return source


def _seed_candidate(service):
    """Create a candidate with consent for notification tests."""
    candidate = service.create_candidate(
        {
            "country": "US",
            "timezone": "America/New_York",
            "email": "test@example.com",
            "preferred_roles": ["engineer"],
            "preferred_countries": ["US"],
            "available_hours_per_week": 20,
            "skills": ["python"],
        },
        "admin",
    )
    service.set_consent(candidate["id"], True, "admin", "v1")
    return candidate


class TestIdempotencyKey(unittest.TestCase):
    def test_deterministic(self):
        a = _make_idempotency_key("run-1", "sync")
        b = _make_idempotency_key("run-1", "sync")
        self.assertEqual(a, b)

    def test_different_inputs(self):
        a = _make_idempotency_key("run-1", "sync")
        b = _make_idempotency_key("run-2", "sync")
        self.assertNotEqual(a, b)


class TestSyncSourceTask(unittest.TestCase):
    def setUp(self):
        self.service, self.repo = _make_service()
        self.source = _seed_source(self.service, self.repo)
        # Patch the lazy init to use our in-memory service.
        self._patch = patch.object(
            WorkflowTask,
            "_get_service_and_tracker",
            return_value=(self.service, self.repo, None),
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_sync_source_success(self):
        jobs = [
            {
                "title_original": "Remote Engineer",
                "company_name": "TestCo",
                "canonical_url": "https://example.com/job/1",
                "source_job_id": "ext-1",
                "country": "US",
                "employment_type": "part_time",
                "is_remote": True,
            }
        ]
        result = sync_source_task.apply(args=[self.source["id"], jobs, "admin"]).get()
        self.assertEqual(result["received"], 1)
        self.assertEqual(result["imported"], 1)

    def test_sync_source_bad_source_raises(self):
        """Syncing a non-existent source should raise (permanent error)."""
        with self.assertRaises(Exception):
            sync_source_task.apply(args=["nonexistent", [], "admin"]).get()


class TestRunMatchesTask(unittest.TestCase):
    def setUp(self):
        self.service, self.repo = _make_service()
        self._patch = patch.object(
            WorkflowTask,
            "_get_service_and_tracker",
            return_value=(self.service, self.repo, None),
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_run_matches_success(self):
        candidate = _seed_candidate(self.service)
        source = _seed_source(self.service, self.repo)
        self.service.sync_source(
            source["id"],
            [
                {
                    "title_original": "Python Dev",
                    "company_name": "DevCo",
                    "canonical_url": "https://example.com/j/1",
                    "source_job_id": "ext-1",
                    "country": "US",
                    "employment_type": "part_time",
                    "is_remote": True,
                }
            ],
            "admin",
        )
        result = run_matches_task.apply(args=[candidate["id"], "admin"]).get()
        self.assertIn("matches", result)

    def test_run_matches_nonexistent_candidate(self):
        with self.assertRaises(Exception):
            run_matches_task.apply(args=["nonexistent", "admin"]).get()


class TestNotificationPipelineTask(unittest.TestCase):
    def setUp(self):
        self.service, self.repo = _make_service()
        self._patch = patch.object(
            WorkflowTask,
            "_get_service_and_tracker",
            return_value=(self.service, self.repo, None),
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_preview_returns_awaiting_approval(self):
        candidate = _seed_candidate(self.service)
        source = _seed_source(self.service, self.repo)
        self.service.sync_source(
            source["id"],
            [
                {
                    "title_original": "Python Dev",
                    "company_name": "Co",
                    "canonical_url": "https://example.com/j/2",
                    "source_job_id": "ext-2",
                    "country": "US",
                    "employment_type": "part_time",
                    "is_remote": True,
                }
            ],
            "admin",
        )
        matches = self.service.run_matches(candidate["id"], "admin")
        match_ids = [m["id"] for m in matches["matches"][:1]]

        result = notification_pipeline_task.apply(
            args=[candidate["id"], match_ids, "admin", "http://localhost:8000"]
        ).get()
        self.assertEqual(result["status"], "awaiting_approval")


class TestSendNotificationTask(unittest.TestCase):
    def setUp(self):
        self.service, self.repo = _make_service()
        self._patch = patch.object(
            WorkflowTask,
            "_get_service_and_tracker",
            return_value=(self.service, self.repo, None),
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_send_approved_notification(self):
        candidate = _seed_candidate(self.service)
        source = _seed_source(self.service, self.repo)
        self.service.sync_source(
            source["id"],
            [
                {
                    "title_original": "Dev",
                    "company_name": "Co",
                    "canonical_url": "https://example.com/j/3",
                    "source_job_id": "ext-3",
                    "country": "US",
                    "employment_type": "part_time",
                    "is_remote": True,
                }
            ],
            "admin",
        )
        matches = self.service.run_matches(candidate["id"], "admin")
        match_ids = [m["id"] for m in matches["matches"][:1]]
        draft = self.service.preview_digest(
            candidate["id"], match_ids, "admin", "http://localhost:8000"
        )
        self.service.review_notification(draft["id"], True, "admin")

        result = send_notification_task.apply(args=[draft["id"], "admin"]).get()
        self.assertEqual(result["status"], "sent")

    def test_send_unapproved_raises(self):
        """Sending a notification that hasn't been approved should fail."""
        candidate = _seed_candidate(self.service)
        source = _seed_source(self.service, self.repo)
        self.service.sync_source(
            source["id"],
            [
                {
                    "title_original": "Dev",
                    "company_name": "Co",
                    "canonical_url": "https://example.com/j/4",
                    "source_job_id": "ext-4",
                    "country": "US",
                    "employment_type": "part_time",
                    "is_remote": True,
                }
            ],
            "admin",
        )
        matches = self.service.run_matches(candidate["id"], "admin")
        match_ids = [m["id"] for m in matches["matches"][:1]]
        draft = self.service.preview_digest(
            candidate["id"], match_ids, "admin", "http://localhost:8000"
        )
        # Not reviewed/approved — should raise PolicyError (permanent).
        with self.assertRaises(Exception):
            send_notification_task.apply(args=[draft["id"], "admin"]).get()


class TestRetryBehavior(unittest.TestCase):
    """Verify that retryable errors trigger retries and permanent ones do not."""

    def setUp(self):
        self.service, self.repo = _make_service()
        self._patch = patch.object(
            WorkflowTask,
            "_get_service_and_tracker",
            return_value=(self.service, self.repo, None),
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_permanent_error_does_not_retry(self):
        """A PolicyError (permanent) should propagate immediately."""
        # Trying to sync a disabled source triggers PolicyError.
        source = self.service.create_source(
            {"name": "Disabled", "source_type": "api", "base_url": "https://x.com"},
            "admin",
        )
        # Source is not approved/enabled — sync will raise PolicyError.
        with self.assertRaises(Exception) as ctx:
            sync_source_task.apply(args=[source["id"], [], "admin"]).get()
        self.assertIn("approved", str(ctx.exception).lower())


class EmbedJobsTest(unittest.TestCase):
    def test_skips_repo_without_vector_support(self):
        repo = SQLiteRepository(":memory:")
        result = _embed_jobs(repo, ["j1"])
        self.assertEqual(result["embedded"], 0)
        self.assertEqual(result["skipped"], "no_vector_support")

    def test_batches_and_stores_vectors(self):
        class FakeVectorRepo:
            def __init__(self):
                self.jobs = {
                    f"j{i}": {"id": f"j{i}", "title_original": f"Job {i}"} for i in range(3)
                }
                self.stored = {}

            def get(self, kind, job_id):
                return self.jobs.get(job_id)

            def update_job_embeddings(self, embeddings):
                self.stored.update(embeddings)
                return len(embeddings)

        repo = FakeVectorRepo()
        with patch(
            "agent_hub.agents.global_part_time.embedding.get_embeddings",
            side_effect=lambda texts: [[0.1, 0.2]] * len(texts),
        ):
            result = _embed_jobs(repo, list(repo.jobs))
        self.assertEqual(result["embedded"], 3)
        self.assertEqual(set(repo.stored), set(repo.jobs))

    def test_total_api_failure_raises_for_retry(self):
        class FakeVectorRepo:
            def get(self, kind, job_id):
                return {"id": job_id, "title_original": "Job"}

            def update_job_embeddings(self, embeddings):
                return len(embeddings)

        with (
            patch(
                "agent_hub.agents.global_part_time.embedding.get_embeddings",
                side_effect=lambda texts: [None] * len(texts),
            ),
            patch("agent_hub.agents.global_part_time.embedding.SILICONFLOW_API_KEY", "sk-test"),
        ):
            with self.assertRaises(RuntimeError):
                _embed_jobs(FakeVectorRepo(), ["j1"])


if __name__ == "__main__":
    unittest.main()
