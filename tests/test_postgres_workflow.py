"""PostgreSQL full-workflow integration test.

Exercises the entire source → job → candidate → match → notification pipeline
against a real PostgreSQL database. Skipped when TEST_DATABASE_URL is not set.
"""

from __future__ import annotations

import os
import unittest

from tests.factories import candidate_payload, job_payload, source_payload

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set")
class PostgresWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        from agent_hub.database.models import Base
        from agent_hub.database.repository import PostgresRepository
        from agent_hub.agents.global_part_time.service import AgentService

        self.repo = PostgresRepository(TEST_DATABASE_URL)

        from sqlalchemy import text

        with self.repo._engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()

        Base.metadata.drop_all(self.repo._engine)
        Base.metadata.create_all(self.repo._engine)
        self.service = AgentService(self.repo)

    def test_full_workflow_source_to_notification(self) -> None:
        actor = "test-operator"

        # 1. Create and approve a source.
        source = self.service.create_source(source_payload(), actor)
        source = self.service.review_source(source["id"], True, actor)
        self.assertEqual(source["review_status"], "approved")

        # 2. Sync jobs.
        job = job_payload()
        result = self.service.sync_source(source["id"], [job], actor)
        self.assertEqual(result["imported"], 1)
        job_id = result["job_ids"][0]

        # 3. Create candidate and set consent.
        candidate = self.service.create_candidate(candidate_payload(), actor)
        candidate = self.service.set_consent(candidate["id"], True, actor, "v1")
        self.assertEqual(candidate["consent_status"], "opted_in")

        # 4. Run matches.
        match_result = self.service.run_matches(candidate["id"], actor)
        self.assertGreater(len(match_result["matches"]), 0)
        match = match_result["matches"][0]
        self.assertEqual(match["job_id"], job_id)

        # 5. Preview notification.
        notification = self.service.preview_digest(
            candidate["id"], [match["id"]], actor, "http://localhost:8000"
        )
        self.assertEqual(notification["status"], "pending_approval")

        # 6. Review and send notification.
        notification = self.service.review_notification(notification["id"], True, actor)
        self.assertEqual(notification["status"], "approved")

        notification = self.service.send_notification(notification["id"], actor)
        self.assertEqual(notification["status"], "sent")

        # 7. Verify audit trail.
        audits = self.repo.audits(limit=50)
        events = [a["event"] for a in audits]
        self.assertIn("source.created", events)
        self.assertIn("notification.sent", events)

        # 8. Idempotent replay.
        replay = self.repo.idempotent(
            "test.replay",
            "unique-key",
            lambda: {"replayed": True},
        )
        self.assertEqual(replay, {"replayed": True})
        replay2 = self.repo.idempotent(
            "test.replay",
            "unique-key",
            lambda: {"should_not_run": True},
        )
        self.assertEqual(replay2, {"replayed": True})


if __name__ == "__main__":
    unittest.main()
