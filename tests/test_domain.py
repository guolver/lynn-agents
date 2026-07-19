import unittest

from agent_hub.agents.global_part_time.domain import (
    assess_risk,
    dedup_key,
    hard_filter,
    score_match,
    timezone_matches,
)
from tests.factories import candidate_payload, job_payload


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
        # Without embed_fn/semantic_similarity, semantic is excluded (uninformative) rather
        # than defaulting to a neutral 0.5. active_weight = 0.82 (all but semantic);
        # base = (1.0*0.32 + 1.0*0.11 + 1.0*0.11 + 1.0*0.11 + 1.0*0.06 + 1.0*0.05 + 0.9*0.06) / 0.82
        # total = round(base * (0.5 + 0.5*0.82), 4) = 0.9033
        self.assertAlmostEqual(score, 0.9033, places=4)
        self.assertEqual(breakdown["skills"], 1.0)
        self.assertEqual(breakdown["semantic"], 0.0)
        self.assertIn("semantic", breakdown["uninformative"])
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

    def test_stub_description_requires_review(self):
        """LinkedIn 转载存根：截断样板文而非真实 JD，应进入人工审核而非直接放行。"""
        stub = dict(
            self.job,
            description_original=(
                "Posted 1:21:26 PM. Project ManagerLocation: Remote, Canada Empire life is "
                "looking to hire a Project Manager to join…See this and similar jobs on LinkedIn."
            ),
        )
        result = assess_risk(stub)
        self.assertTrue(any(s.startswith("stub_description") for s in result.signals))
        self.assertEqual(result.action, "review")

    def test_tag_stuffing_requires_review(self):
        """标签堆砌（几十个不相关 tag 当 skills）会污染技能匹配，应进入人工审核。"""
        stuffed = dict(
            self.job,
            skills=[f"tag{i}" for i in range(30)],
        )
        result = assess_risk(stuffed)
        self.assertIn("tag_stuffing", result.signals)
        self.assertEqual(result.action, "review")

    def test_normal_job_with_reasonable_skills_still_accepted(self):
        result = assess_risk(self.job)
        self.assertEqual(result.action, "accept")

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


class PrecomputedSemanticScoreTest(unittest.TestCase):
    def test_precomputed_similarity_maps_to_semantic_score(self):
        candidate = candidate_payload()
        job = job_payload()
        # (0.9 - 0.3) / 0.6 = 1.0
        _total, breakdown, _reasons = score_match(candidate, job, semantic_similarity=0.9)
        self.assertEqual(breakdown["semantic"], 1.0)

    def test_precomputed_similarity_clamps_low_values(self):
        candidate = candidate_payload()
        job = job_payload()
        _total, breakdown, _reasons = score_match(candidate, job, semantic_similarity=0.1)
        self.assertEqual(breakdown["semantic"], 0.0)

    def test_without_precomputed_and_without_embed_fn_stays_neutral(self):
        candidate = candidate_payload()
        job = job_payload()
        _total, breakdown, _reasons = score_match(candidate, job)
        self.assertEqual(breakdown["semantic"], 0.0)
        self.assertIn("semantic", breakdown["uninformative"])


class CompletenessWeightingTests(unittest.TestCase):
    """信息完备度加权：缺信息分项剔除 + 归一化 + 折扣（spec 2026-07-18）。"""

    def setUp(self):
        self.candidate = {
            "skills": [{"name": "python"}, {"name": "react"}, {"name": "typescript"}],
            "languages": [{"code": "en"}],
            "country": "CN",
            "timezone": "Asia/Shanghai",
            "minimum_hourly_rate": {"amount": 20, "currency": "USD"},
            "availability_hours_per_week": 20,
            "desired_roles": ["backend"],
        }
        self.rich_job = {
            "title_original": "Backend Engineer",
            "skills": ["python", "react", "typescript", "go", "rust", "kafka"],
            "languages": ["en"],
            "countries_allowed": ["GLOBAL"],
            "timezone_requirements": [],
            "compensation_max": 40,
            "compensation_currency": "USD",
            "hours_per_week_min": 10,
            "hours_per_week_max": 20,
            "categories": ["backend"],
            "quality_score": 0.5,
        }
        self.sparse_job = {
            "title_original": "Head of Marketing",
            "countries_allowed": ["GLOBAL"],
            "compensation_max": 110,
            "compensation_currency": "USD",
            "quality_score": 0.5,
        }

    def test_sparse_job_ranks_below_matching_job(self):
        rich_score, _, _ = score_match(self.candidate, self.rich_job)
        sparse_score, _, _ = score_match(self.candidate, self.sparse_job)
        self.assertGreater(rich_score, sparse_score)

    def test_uninformative_components_listed(self):
        _, breakdown, _ = score_match(self.candidate, self.sparse_job)
        for key in ("skills", "semantic", "language", "availability"):
            self.assertIn(key, breakdown["uninformative"])
        self.assertNotIn("location_timezone", breakdown["uninformative"])
        self.assertNotIn("preference", breakdown["uninformative"])

    def test_full_information_no_discount(self):
        total, breakdown, _ = score_match(self.candidate, self.rich_job, semantic_similarity=0.9)
        self.assertEqual(breakdown["uninformative"], [])
        self.assertEqual(breakdown["completeness"], 1.0)
        expected = round(
            0.32 * 0.5
            + 0.18 * 1.0
            + 0.11 * 1.0
            + 0.11 * 1.0
            + 0.11 * 1.0
            + 0.06 * 1.0
            + 0.05 * 1.0
            + 0.06 * 0.5,
            4,
        )
        self.assertAlmostEqual(total, expected, places=4)

    def test_discount_formula_on_sparse_job(self):
        total, breakdown, _ = score_match(self.candidate, self.sparse_job)
        # informative: location_timezone 0.11(=1.0) + compensation 0.11(=1.0)
        # + preference 0.05(=0.4) + freshness_quality 0.06(=0.5) → active=0.33
        base = (0.11 * 1.0 + 0.11 * 1.0 + 0.05 * 0.4 + 0.06 * 0.5) / 0.33
        factor = 0.5 + 0.5 * 0.33
        self.assertAlmostEqual(breakdown["completeness"], 0.33, places=4)
        self.assertAlmostEqual(total, round(base * factor, 4), places=3)

    def test_no_skill_requirement_never_claims_skill_match(self):
        _, _, reasons = score_match(self.candidate, self.sparse_job)
        self.assertFalse(any("技能" in r for r in reasons))

    def test_low_completeness_adds_disclaimer(self):
        _, _, reasons = score_match(self.candidate, self.sparse_job)
        self.assertIn("职位信息不完整，评分仅供参考", reasons)

    def test_high_completeness_has_no_disclaimer(self):
        _, _, reasons = score_match(self.candidate, self.rich_job)
        self.assertNotIn("职位信息不完整，评分仅供参考", reasons)

    def test_zero_skill_overlap_scores_zero_not_half(self):
        job = {**self.rich_job, "skills": ["golang", "rust"]}
        _, breakdown, _ = score_match(self.candidate, job)
        self.assertEqual(breakdown["skills"], 0.0)
        self.assertNotIn("skills", breakdown["uninformative"])


if __name__ == "__main__":
    unittest.main()
