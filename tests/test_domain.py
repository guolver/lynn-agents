import unittest

from agent_hub.agents.global_part_time.domain import (
    assess_risk,
    dedup_key,
    hard_filter,
    score_match,
    score_match_with_evidence,
    timezone_matches,
)
from agent_hub.skill_graph.types import ExpansionEvidence, ExpansionResult
from tests.factories import candidate_payload, job_payload


def evidence(source, target, relations, nodes, weight, target_kind="skill", canonical=None):
    return ExpansionEvidence(
        source,
        canonical or source,
        target,
        target_kind,
        tuple(relations),
        tuple(nodes),
        len(relations),
        weight,
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

    def test_country_and_timezone_mismatches_are_soft_constraints(self):
        self.job["countries_allowed"] = ["US"]
        self.job["compensation_max"] = 10
        self.job["timezone_requirements"] = ["UTC-05:00"]

        failures = hard_filter(self.candidate, self.job)

        self.assertNotIn("country_mismatch", failures)
        self.assertNotIn("timezone_mismatch", failures)
        self.assertIn("compensation_below_minimum", failures)

    def test_location_and_timezone_matches_score_higher_without_filtering(self):
        mismatched = dict(
            self.job,
            countries_allowed=["US"],
            timezone_requirements=["UTC-05:00"],
        )

        matching_score, matching_breakdown, _ = score_match(self.candidate, self.job)
        mismatched_score, mismatched_breakdown, _ = score_match(self.candidate, mismatched)

        self.assertEqual(hard_filter(self.candidate, mismatched), [])
        self.assertGreater(
            matching_breakdown["location_timezone"],
            mismatched_breakdown["location_timezone"],
        )
        self.assertGreater(matching_score, mismatched_score)

    def test_reasons_cover_multiple_informative_dimensions(self):
        _, _, reasons = score_match(self.candidate, self.job, semantic_similarity=0.9)
        combined = "|".join(reasons)

        self.assertIn("技能", combined)
        self.assertIn("语义高度相似", combined)
        self.assertIn("语言要求", combined)
        self.assertTrue("薪资" in combined or "可用工时" in combined)

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

    def test_positive_reasons_are_capped_at_five(self):
        _, _, reasons = score_match(self.candidate, self.rich_job, semantic_similarity=0.9)
        positive = [reason for reason in reasons if "评分仅供参考" not in reason]

        self.assertLessEqual(len(positive), 5)

    def test_zero_skill_overlap_scores_zero_not_half(self):
        job = {**self.rich_job, "skills": ["golang", "rust"]}
        _, breakdown, _ = score_match(self.candidate, job)
        self.assertEqual(breakdown["skills"], 0.0)
        self.assertNotIn("skills", breakdown["uninformative"])


class WeightedSkillEvidenceTest(unittest.TestCase):
    def test_normalized_direct_match_uses_required_canonical_evidence(self):
        def expand(names):
            if names == ["Python"]:
                return ExpansionResult.from_iterable(
                    [evidence("Python", "Python", [], ["Python"], 1.0)]
                )
            return ExpansionResult()

        _, breakdown, reasons, graph = score_match_with_evidence(
            {"skills": [{"name": "python"}]},
            {"skills": ["Python"]},
            expand,
        )

        self.assertEqual(breakdown["skills"], 1.0)
        self.assertEqual(reasons[0], "技能python与职位要求Python直接匹配")
        self.assertEqual(
            graph["requirements"],
            [
                {
                    "required_skill": "Python",
                    "candidate_skill": "python",
                    "score": 1.0,
                    "path": {
                        "input_skill": "Python",
                        "canonical_skill": "Python",
                        "target": "Python",
                        "target_kind": "skill",
                        "relations": [],
                        "nodes": ["Python"],
                        "depth": 0,
                        "weight": 1.0,
                    },
                }
            ],
        )

    def test_identical_unknown_skill_keeps_direct_score_and_evidence(self):
        def expand(_names):
            return ExpansionResult()

        _, breakdown, reasons, graph = score_match_with_evidence(
            {"skills": [{"name": "WebAssembly"}]},
            {"skills": ["WebAssembly"]},
            expand,
        )

        self.assertEqual(breakdown["skills"], 1.0)
        self.assertEqual(reasons[0], "技能WebAssembly与职位要求WebAssembly直接匹配")
        self.assertEqual(
            graph,
            {
                "requirements": [
                    {
                        "required_skill": "WebAssembly",
                        "candidate_skill": "WebAssembly",
                        "score": 1.0,
                        "path": {
                            "input_skill": "WebAssembly",
                            "canonical_skill": "WebAssembly",
                            "target": "WebAssembly",
                            "target_kind": "skill",
                            "relations": [],
                            "nodes": ["WebAssembly"],
                            "depth": 0,
                            "weight": 1.0,
                        },
                    }
                ]
            },
        )

    def test_direct_and_alias_match_score_one(self):
        # K8s canonicalizes to Kubernetes on the required side.
        def expand(names):
            values = []
            for name in names:
                canonical = "Kubernetes" if name == "K8s" else name
                values.append(evidence(name, canonical, [], [canonical], 1.0, canonical=canonical))
            return ExpansionResult.from_iterable(values)

        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "Kubernetes"}]}, {"skills": ["K8s"]}, expand
        )
        self.assertEqual(breakdown["skills"], 1.0)
        self.assertEqual(graph["requirements"][0]["score"], 1.0)

    def test_requires_direction_and_weight(self):
        # Only job-side Kubernetes expansion reaches candidate-owned Docker.
        def expand(names):
            values = [evidence(name, name, [], [name], 1.0) for name in names]
            if names == ["Kubernetes"]:
                values.append(
                    evidence(
                        "Kubernetes",
                        "Docker",
                        ["REQUIRES"],
                        ["Kubernetes", "Docker"],
                        0.75,
                    )
                )
            return ExpansionResult.from_iterable(values)

        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "Docker"}]}, {"skills": ["Kubernetes"]}, expand
        )
        self.assertEqual(breakdown["skills"], 0.75)
        self.assertEqual(graph["requirements"][0]["path"]["relations"], ["REQUIRES"])

    def test_related_and_two_hop_weights(self):
        cases = [
            (
                "one hop",
                evidence("React", "Vue", ["RELATED_TO"], ["React", "Vue"], 0.4),
                0.4,
            ),
            (
                "two hops",
                evidence(
                    "Next.js",
                    "Vue",
                    ["REQUIRES", "RELATED_TO"],
                    ["Next.js", "React", "Vue"],
                    0.2,
                ),
                0.2,
            ),
        ]
        for label, path, expected in cases:
            with self.subTest(label=label):

                def expand(names):
                    values = [evidence(name, name, [], [name], 1.0) for name in names]
                    if names == [path.input_skill]:
                        values.append(path)
                    return ExpansionResult.from_iterable(values)

                _, breakdown, _, graph = score_match_with_evidence(
                    {"skills": [{"name": "Vue"}]},
                    {"skills": [path.input_skill]},
                    expand,
                )
                self.assertEqual(breakdown["skills"], expected)
                self.assertEqual(graph["requirements"][0]["score"], expected)

    def test_shared_category_does_not_match_two_concrete_skills(self):
        def expand(names):
            values = [evidence(name, name, [], [name], 1.0) for name in names]
            for name in names:
                if name in {"React", "Vue"}:
                    values.append(
                        evidence(
                            name,
                            "前端开发",
                            ["CHILD_OF"],
                            [name, "前端开发"],
                            0.65,
                            target_kind="category",
                        )
                    )
            return ExpansionResult.from_iterable(values)

        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "React"}]}, {"skills": ["Vue"]}, expand
        )
        self.assertEqual(breakdown["skills"], 0.0)
        self.assertIsNone(graph["requirements"][0]["path"])

    def test_tie_break_uses_weight_depth_then_lexical_path(self):
        def expand(names):
            values = [evidence(name, name, [], [name], 1.0) for name in names]
            if names == ["Framework"]:
                values.extend(
                    [
                        evidence(
                            "Framework",
                            "React",
                            ["RELATED_TO", "RELATED_TO"],
                            ["Framework", "Angular", "React"],
                            0.2,
                        ),
                        evidence(
                            "Framework",
                            "React",
                            ["RELATED_TO", "RELATED_TO"],
                            ["Framework", "Vue", "React"],
                            0.2,
                        ),
                    ]
                )
            return ExpansionResult.from_iterable(values)

        _, _, _, graph = score_match_with_evidence(
            {"skills": [{"name": "React"}]}, {"skills": ["Framework"]}, expand
        )
        self.assertEqual(
            graph["requirements"][0]["path"]["nodes"],
            ["Framework", "Angular", "React"],
        )

    def test_candidate_related_to_requires_path_is_rejected(self):
        def expand(names):
            values = [evidence(name, name, [], [name], 1.0) for name in names]
            if names == ["Framework"]:
                values.append(
                    evidence(
                        "Framework",
                        "React",
                        ["RELATED_TO", "REQUIRES"],
                        ["Framework", "Library", "React"],
                        0.2,
                    )
                )
            return ExpansionResult.from_iterable(values)

        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "Framework"}]}, {"skills": ["React"]}, expand
        )

        self.assertEqual(breakdown["skills"], 0.0)
        self.assertIsNone(graph["requirements"][0]["path"])

    def test_candidate_requires_to_child_of_path_is_rejected(self):
        def expand(names):
            values = [
                evidence(
                    name,
                    name,
                    [],
                    [name],
                    1.0,
                    target_kind="category" if name == "前端开发" else "skill",
                )
                for name in names
            ]
            if names == ["Next.js"]:
                values.append(
                    evidence(
                        "Next.js",
                        "前端开发",
                        ["REQUIRES", "CHILD_OF"],
                        ["Next.js", "React", "前端开发"],
                        0.325,
                        target_kind="category",
                    )
                )
            return ExpansionResult.from_iterable(values)

        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "Next.js"}]}, {"skills": ["前端开发"]}, expand
        )

        self.assertEqual(breakdown["skills"], 0.0)
        self.assertIsNone(graph["requirements"][0]["path"])

    def test_candidate_related_to_path_matches_symmetrically(self):
        def expand(names):
            values = [evidence(name, name, [], [name], 1.0) for name in names]
            if names == ["React"]:
                values.append(evidence("React", "Vue", ["RELATED_TO"], ["React", "Vue"], 0.4))
            return ExpansionResult.from_iterable(values)

        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "React"}]}, {"skills": ["Vue"]}, expand
        )

        self.assertEqual(breakdown["skills"], 0.4)
        self.assertEqual(graph["requirements"][0]["path"]["relations"], ["RELATED_TO"])

    def test_candidate_child_of_path_matches_required_category(self):
        def expand(names):
            values = [
                evidence(
                    name,
                    name,
                    [],
                    [name],
                    1.0,
                    target_kind="category" if name == "前端开发" else "skill",
                )
                for name in names
            ]
            if names == ["React"]:
                values.append(
                    evidence(
                        "React",
                        "前端开发",
                        ["CHILD_OF"],
                        ["React", "前端开发"],
                        0.65,
                        target_kind="category",
                    )
                )
            return ExpansionResult.from_iterable(values)

        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "React"}]}, {"skills": ["前端开发"]}, expand
        )

        self.assertEqual(breakdown["skills"], 0.65)
        self.assertEqual(graph["requirements"][0]["path"]["relations"], ["CHILD_OF"])

    def test_graph_winner_does_not_reuse_legacy_generic_fallback_reason(self):
        def expand(names):
            values = []
            for name in names:
                canonical = "Kubernetes" if name == "K8s" else name
                values.append(evidence(name, canonical, [], [canonical], 1.0, canonical=canonical))
            return ExpansionResult.from_iterable(values)

        candidate = {
            "skills": [{"name": "Kubernetes"}],
            "country": "CN",
            "timezone": None,
            "desired_roles": ["backend"],
            "minimum_hourly_rate": {"amount": 100},
        }
        job = {
            "skills": ["K8s"],
            "countries_allowed": ["US"],
            "timezone_requirements": ["UTC-05:00"],
            "categories": ["frontend"],
            "compensation_max": 10,
        }

        _, _, reasons, _ = score_match_with_evidence(candidate, job, expand)

        self.assertNotIn("该职位通过了你的全部硬性条件", reasons)


if __name__ == "__main__":
    unittest.main()
