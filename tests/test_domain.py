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
        # Without embed_fn, semantic defaults to 0.5 (neutral); total ~0.93 for a perfect match
        self.assertGreaterEqual(score, 0.93)
        self.assertEqual(breakdown["skills"], 1.0)
        self.assertEqual(breakdown["semantic"], 0.5)
        self.assertEqual(breakdown["availability"], 1.0)
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


class SkillScoreExpansionTest(unittest.TestCase):
    def test_skill_score_without_expand_fn_is_backward_compatible(self):
        candidate = {"skills": [{"name": "Python"}, {"name": "React"}]}
        job = {"skills": ["Python", "React"]}
        score, breakdown, reasons = score_match(candidate, job)
        self.assertEqual(breakdown["skills"], 1.0)

    def test_skill_score_with_expand_fn_boosts_indirect_matches(self):
        candidate = {"skills": [{"name": "React"}]}
        job = {"skills": ["前端开发"]}

        def mock_expand(names):
            mapping = {"React": {"React", "前端开发"}}
            result = set()
            for n in names:
                result.update(mapping.get(n, set()))
            return result

        score, breakdown, reasons = score_match(candidate, job, expand_fn=mock_expand)
        self.assertGreater(breakdown["skills"], 0.0)
        self.assertLessEqual(breakdown["skills"], 0.6)

    def test_skill_score_direct_match_preferred_over_indirect(self):
        candidate = {"skills": [{"name": "Python"}, {"name": "React"}]}
        job = {"skills": ["Python", "前端开发"]}

        def mock_expand(names):
            return {"Python", "React", "前端开发", "后端开发"}

        score, breakdown, reasons = score_match(candidate, job, expand_fn=mock_expand)
        # Python direct (1.0) + 前端开发 indirect (0.6) → (1.0 + 0.6) / 2 = 0.8
        self.assertAlmostEqual(breakdown["skills"], 0.8, places=2)

    def test_skill_score_expands_job_aliases_symmetrically(self):
        candidate = {"skills": [{"name": "Kubernetes"}]}
        job = {"skills": ["K8s"]}

        def mock_expand(names):
            mapping = {
                "Kubernetes": {"Kubernetes", "容器与云"},
                "K8s": {"Kubernetes", "容器与云"},
            }
            result = set()
            for name in names:
                result.update(mapping.get(name, set()))
            return result

        _, breakdown, _ = score_match(candidate, job, expand_fn=mock_expand)

        self.assertEqual(breakdown["skills"], 0.6)

    def test_score_match_reasons_include_skill_expansion(self):
        candidate = {
            "consent_status": "opted_in",
            "country": "CN",
            "timezone": "Asia/Shanghai",
            "languages": [{"code": "en"}],
            "skills": [{"name": "React"}],
            "desired_roles": [],
            "minimum_hourly_rate": None,
            "availability_hours_per_week": 40,
            "allowed_work_modes": ["remote"],
            "excluded_companies": [],
        }
        job = {
            "title_original": "Frontend Dev",
            "company_name": "Test",
            "description_original": "Build UIs",
            "canonical_url": "https://example.com/1",
            "status": "active",
            "review_status": "not_required",
            "risk_score": 0.0,
            "work_mode": "remote",
            "countries_allowed": ["GLOBAL"],
            "timezone_requirements": [],
            "languages": ["en"],
            "skills": ["前端开发"],
            "categories": [],
            "hours_per_week_min": 10,
            "compensation_max": None,
            "compensation_currency": "USD",
            "quality_score": 0.8,
        }

        def mock_expand(names):
            return {"React", "前端开发"}

        score, breakdown, reasons = score_match(candidate, job, expand_fn=mock_expand)
        has_expansion_reason = any("扩展" in r or "相关" in r for r in reasons)
        self.assertTrue(has_expansion_reason, f"Expected expansion reason in {reasons}")


if __name__ == "__main__":
    unittest.main()
