import unittest

from agent_hub.agents.global_part_time.domain import (
    assess_risk,
    dedup_key,
    hard_filter,
    score_match,
    timezone_matches,
)


class DomainRulesTest(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "consent_status": "opted_in",
            "country": "CN",
            "timezone": "Asia/Shanghai",
            "languages": [{"code": "zh-CN"}, {"code": "en"}],
            "skills": [{"name": "python", "level": 4}, {"name": "data_annotation", "level": 4}],
            "desired_roles": ["ai_data"],
            "minimum_hourly_rate": {"amount": 15, "currency": "USD"},
            "availability_hours_per_week": 20,
            "allowed_work_modes": ["remote"],
            "excluded_companies": [],
        }
        self.job = {
            "title_original": "AI Evaluation Specialist",
            "company_name": "Example Ltd.",
            "description_original": "Evaluate model output using a written rubric.",
            "canonical_url": "https://example.com/jobs/123?utm_source=test",
            "status": "active",
            "review_status": "not_required",
            "risk_score": 0.0,
            "work_mode": "remote",
            "countries_allowed": ["CN", "SG"],
            "timezone_requirements": ["UTC+08:00"],
            "languages": ["zh-CN", "en"],
            "skills": ["data_annotation", "python"],
            "categories": ["ai_data"],
            "hours_per_week_min": 10,
            "compensation_max": 25,
            "compensation_currency": "USD",
            "quality_score": 0.9,
        }

    def test_timezone_iana_matches_utc_offset(self):
        self.assertTrue(timezone_matches("Asia/Shanghai", ["UTC+08:00"]))
        self.assertFalse(timezone_matches("Asia/Shanghai", ["UTC-05:00"]))

    def test_hard_filter_and_weighted_score(self):
        self.assertEqual(hard_filter(self.candidate, self.job), [])
        score, breakdown, reasons = score_match(self.candidate, self.job)
        self.assertGreaterEqual(score, 0.95)
        self.assertEqual(breakdown["skills"], 1.0)
        self.assertIn("薪资达到最低期望", reasons)

    def test_hard_filters_are_deterministic(self):
        self.job["countries_allowed"] = ["US"]
        self.job["compensation_max"] = 10
        self.job["timezone_requirements"] = ["UTC-05:00"]
        failures = hard_filter(self.candidate, self.job)
        self.assertIn("country_mismatch", failures)
        self.assertIn("timezone_mismatch", failures)
        self.assertIn("compensation_below_minimum", failures)

    def test_risk_rules_override_content_quality(self):
        risky = dict(self.job, description_original="先付款并提供验证码，然后开始刷单")
        result = assess_risk(risky)
        self.assertEqual(result.level, "high")
        self.assertEqual(result.action, "reject")

    def test_dedup_ignores_source_and_tracking_url(self):
        other = dict(self.job, source_id="other", canonical_url="https://mirror.test/x")
        self.assertEqual(dedup_key(self.job), dedup_key(other))


if __name__ == "__main__":
    unittest.main()
