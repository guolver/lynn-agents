import unittest

from agent_hub.agents.global_part_time.repository import Repository
from agent_hub.agents.global_part_time.service import AgentService, PolicyError


class ServiceWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")
        self.service = AgentService(self.repo)
        self.source = self.service.create_source(
            {
                "name": "Approved Partner Feed",
                "source_type": "partner_feed",
                "base_url": "https://feed.example.com/",
                "authorization_basis": "partner contract",
                "allowed_paths": ["/jobs"],
                "prohibited_actions": ["login automation"],
                "rate_limit": "60/hour",
                "retention_policy": "30 days",
            },
            "operator@example.com",
        )
        self.job = {
            "source_job_id": "job-1",
            "canonical_url": "https://feed.example.com/jobs/1?tracking=x",
            "title_original": "Python Data Evaluation",
            "company_name": "Example Ltd.",
            "description_original": "Review AI data with documented guidelines.",
            "employment_type": "part_time",
            "work_mode": "remote",
            "countries_allowed": ["CN"],
            "timezone_requirements": ["UTC+08:00"],
            "languages": ["zh-CN", "en"],
            "skills": ["python", "data_annotation"],
            "categories": ["ai_data"],
            "hours_per_week_min": 10,
            "hours_per_week_max": 20,
            "compensation_min": 15,
            "compensation_max": 25,
            "compensation_currency": "USD",
            "compensation_period": "hour",
            "quality_score": 0.9,
        }

    def candidate(self):
        candidate = self.service.create_candidate(
            {
                "country": "CN",
                "timezone": "Asia/Shanghai",
                "email": "candidate@example.com",
                "languages": [{"code": "zh-CN", "level": "native"}, {"code": "en", "level": "working"}],
                "skills": [{"name": "python", "level": 4}, {"name": "data_annotation", "level": 4}],
                "desired_roles": ["ai_data"],
                "minimum_hourly_rate": {"amount": 15, "currency": "USD"},
                "availability_hours_per_week": 20,
                "allowed_work_modes": ["remote"],
                "notification_channels": ["email"],
                "notification_frequency": "daily",
                "excluded_companies": [],
            },
            "candidate",
        )
        return self.service.set_consent(candidate["id"], True, "candidate", "mvp-1")

    def test_unapproved_source_cannot_sync(self):
        with self.assertRaises(PolicyError):
            self.service.sync_source(self.source["id"], [self.job], "worker")

    def test_end_to_end_approval_match_and_delivery(self):
        self.service.review_source(self.source["id"], True, "operator")
        result = self.service.sync_source(self.source["id"], [self.job], "worker")
        self.assertEqual(result["imported"], 1)
        candidate = self.candidate()
        matches = self.service.run_matches(candidate["id"], "scheduler")
        self.assertEqual(len(matches["matches"]), 1)

        # A second run updates the stable candidate/job match instead of duplicating it.
        second = self.service.run_matches(candidate["id"], "scheduler")
        self.assertEqual(second["matches"][0]["id"], matches["matches"][0]["id"])
        self.assertEqual(len(self.repo.list("match")), 1)

        draft = self.service.preview_digest(
            candidate["id"], [matches["matches"][0]["id"]], "scheduler", "https://app.example.com"
        )
        with self.assertRaises(PolicyError):
            self.service.send_notification(draft["id"], "scheduler")
        self.service.review_notification(draft["id"], True, "operator")
        sent = self.service.send_notification(draft["id"], "scheduler")
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(sent["provider"], "simulation")

        # Sent jobs cannot be recommended again unless a future versioning policy permits it.
        after_send = self.service.run_matches(candidate["id"], "scheduler")
        self.assertEqual(after_send["matches"], [])
        self.assertIn("already_sent", after_send["filtered"][0]["reasons"])

    def test_cross_source_duplicate_merges_provenance(self):
        self.service.review_source(self.source["id"], True, "operator")
        first = self.service.sync_source(self.source["id"], [self.job], "worker")
        second_source = self.service.create_source(
            {
                "name": "ATS",
                "source_type": "ats",
                "base_url": "https://ats.example.org",
                "authorization_basis": "public API terms",
                "allowed_paths": ["/v1/jobs"],
                "prohibited_actions": [],
                "rate_limit": "30/hour",
                "retention_policy": "14 days",
            },
            "operator",
        )
        self.service.review_source(second_source["id"], True, "operator")
        mirrored = dict(self.job, source_job_id="ats-99", canonical_url="https://ats.example.org/jobs/99")
        second = self.service.sync_source(second_source["id"], [mirrored], "worker")
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(first["job_ids"][0], second["job_ids"][0])
        self.assertEqual(len(self.repo.list("job")), 1)

    def test_high_risk_job_is_not_stored(self):
        self.service.review_source(self.source["id"], True, "operator")
        risky = dict(self.job, source_job_id="scam", description_original="先付款充值，再提供验证码开始刷单")
        result = self.service.sync_source(self.source["id"], [risky], "worker")
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(self.repo.list("job"), [])

    def test_unsubscribe_is_immediate_and_deletion_removes_personal_data(self):
        candidate = self.candidate()
        opted_out = self.service.set_consent(candidate["id"], False, "candidate", "unsubscribe")
        self.assertEqual(opted_out["consent_status"], "opted_out")
        with self.assertRaises(PolicyError):
            self.service.preview_digest(candidate["id"], [], "scheduler", "https://app.example.com")
        result = self.service.delete_candidate(candidate["id"], "candidate")
        self.assertTrue(result["deleted"])
        self.assertIsNone(self.repo.get("candidate", candidate["id"]))
        self.assertTrue(any(x["event"] == "candidate.deleted" for x in self.repo.audits()))

    def test_idempotency_returns_original_result(self):
        operation_calls = []

        def operation():
            operation_calls.append(True)
            return {"id": "stable"}

        first = self.repo.idempotent("create", "abcdefgh", operation)
        second = self.repo.idempotent("create", "abcdefgh", operation)
        self.assertEqual(first, second)
        self.assertEqual(len(operation_calls), 1)


if __name__ == "__main__":
    unittest.main()
