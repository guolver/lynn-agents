"""Integration tests for WorkflowTracker — requires PostgreSQL.

Run with:
    TEST_DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub_test \
      python -m unittest tests.test_workflow_tracker -v
"""

import os
import unittest

from sqlalchemy import create_engine

from agent_hub.database.models import Base
from tests.factories import ensure_vector_extension

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set — skipping PostgreSQL tests")
class TestWorkflowTracker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(TEST_DATABASE_URL)
        ensure_vector_extension(cls.engine)
        Base.metadata.create_all(cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self):
        from agent_hub.worker.workflow import WorkflowTracker

        self.tracker = WorkflowTracker(self.engine)

    def test_create_run_returns_uuid(self):
        run_id = self.tracker.create_run("source_sync", "src-1", "admin")
        self.assertEqual(len(run_id), 36)

    def test_run_lifecycle(self):
        run_id = self.tracker.create_run("matching", "cand-1", "system")
        run = self.tracker.get_run(run_id)
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["workflow_type"], "matching")
        self.assertEqual(run["actor"], "system")
        self.assertEqual(run["steps"], [])

        self.tracker.complete_run(run_id)
        run = self.tracker.get_run(run_id)
        self.assertEqual(run["status"], "completed")

    def test_fail_run(self):
        run_id = self.tracker.create_run("notification", "notif-1", "admin")
        self.tracker.fail_run(run_id)
        run = self.tracker.get_run(run_id)
        self.assertEqual(run["status"], "failed")

    def test_manual_review(self):
        run_id = self.tracker.create_run("source_sync", "src-2", "admin")
        self.tracker.mark_manual_review(run_id)
        run = self.tracker.get_run(run_id)
        self.assertEqual(run["status"], "manual_review")

    def test_step_lifecycle(self):
        run_id = self.tracker.create_run("source_sync", "src-3", "admin")
        step_id = self.tracker.start_step(run_id, "fetch_data")
        run = self.tracker.get_run(run_id)
        self.assertEqual(len(run["steps"]), 1)
        self.assertEqual(run["steps"][0]["status"], "running")
        self.assertEqual(run["steps"][0]["step_name"], "fetch_data")

        self.tracker.complete_step(step_id, "imported 42 jobs")
        run = self.tracker.get_run(run_id)
        self.assertEqual(run["steps"][0]["status"], "completed")

    def test_fail_step_with_error_info(self):
        run_id = self.tracker.create_run("source_sync", "src-4", "admin")
        step_id = self.tracker.start_step(run_id, "fetch_data")
        self.tracker.fail_step(step_id, "SourceTimeoutError", "timed out after 30s", 2)

        run = self.tracker.get_run(run_id)
        step = run["steps"][0]
        self.assertEqual(step["status"], "failed")
        self.assertEqual(step["error_class"], "SourceTimeoutError")
        self.assertEqual(step["error_detail"], "timed out after 30s")
        self.assertEqual(step["retry_count"], 2)

    def test_celery_task_id_stored(self):
        run_id = self.tracker.create_run("matching", "cand-2", "admin", celery_task_id="abc-123")
        run = self.tracker.get_run(run_id)
        self.assertEqual(run["celery_task_id"], "abc-123")

    def test_get_run_nonexistent_returns_none(self):
        self.assertIsNone(self.tracker.get_run("nonexistent-id"))

    def test_list_runs_filters(self):
        self.tracker.create_run("source_sync", "src-10", "admin")
        run_id = self.tracker.create_run("matching", "cand-10", "admin")
        self.tracker.complete_run(run_id)

        completed = self.tracker.list_runs(status="completed")
        self.assertTrue(any(r["id"] == run_id for r in completed))

        matching = self.tracker.list_runs(workflow_type="matching")
        self.assertTrue(all(r["workflow_type"] == "matching" for r in matching))

    def test_list_runs_respects_limit(self):
        for i in range(5):
            self.tracker.create_run("source_sync", f"limit-{i}", "admin")
        runs = self.tracker.list_runs(limit=2)
        self.assertLessEqual(len(runs), 2)

    def test_payload_preserved(self):
        run_id = self.tracker.create_run(
            "source_sync", "src-5", "admin", payload={"source_url": "https://example.com"}
        )
        run = self.tracker.get_run(run_id)
        self.assertEqual(run["payload"]["source_url"], "https://example.com")

    def test_step_payload_preserved(self):
        run_id = self.tracker.create_run("source_sync", "src-6", "admin")
        self.tracker.start_step(run_id, "fetch", payload={"page": 1})
        run = self.tracker.get_run(run_id)
        self.assertEqual(run["steps"][0]["payload"]["page"], 1)


if __name__ == "__main__":
    unittest.main()
