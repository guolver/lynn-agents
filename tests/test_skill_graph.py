import json
import unittest


NEO4J_AVAILABLE = False
try:
    from testcontainers.neo4j import Neo4jContainer

    NEO4J_AVAILABLE = True
except Exception:
    pass


def _driver_for(container):
    from agent_hub.skill_graph.config import create_neo4j_driver

    return create_neo4j_driver(
        container.get_connection_url(),
        auth=(container.username, container.password),
    )


class SeedAliasValidationTest(unittest.TestCase):
    def test_aliases_are_globally_unique(self):
        from agent_hub.skill_graph.seed import SKILL_GRAPH_SEED

        owners: dict[str, str] = {}
        for data in SKILL_GRAPH_SEED.values():
            for canonical, aliases in data.get("aliases", {}).items():
                for alias in aliases:
                    normalized = alias.casefold()
                    previous = owners.get(normalized)
                    self.assertTrue(
                        previous is None or previous == canonical,
                        f"alias {alias!r} belongs to both {previous!r} and {canonical!r}",
                    )
                    owners[normalized] = canonical


@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class Neo4jConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5", password="test")
        cls.container.start()
        cls.addClassCleanup(cls.container.stop)
        cls.driver = _driver_for(cls.container)
        cls.addClassCleanup(cls.driver.close)

    def test_create_driver_connects(self):
        self.driver.verify_connectivity()


@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class SeedDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5", password="test")
        cls.container.start()
        cls.addClassCleanup(cls.container.stop)

    def test_seed_data_structure_is_valid(self):
        from agent_hub.skill_graph.seed import SKILL_GRAPH_SEED

        for category, data in SKILL_GRAPH_SEED.items():
            self.assertIsInstance(category, str)
            self.assertIn("skills", data)
            self.assertIsInstance(data["skills"], list)
            self.assertTrue(len(data["skills"]) > 0, f"{category} has no skills")
            aliases = data.get("aliases", {})
            for skill_name, alias_list in aliases.items():
                self.assertIn(skill_name, data["skills"], f"alias key {skill_name} not in skills")
                self.assertIsInstance(alias_list, list)

    def test_seed_has_expected_categories(self):
        from agent_hub.skill_graph.seed import SKILL_GRAPH_SEED

        expected = {"前端开发", "后端开发", "数据库", "容器与云", "移动开发", "数据与AI"}
        self.assertEqual(set(SKILL_GRAPH_SEED.keys()), expected)


@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class SkillGraphServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5", password="test")
        cls.container.start()
        cls.addClassCleanup(cls.container.stop)
        from agent_hub.skill_graph.service import SkillGraphService

        cls.driver = _driver_for(cls.container)
        cls.addClassCleanup(cls.driver.close)
        cls.service = SkillGraphService(cls.driver)
        cls.service.seed()

    def test_resolve_canonical_returns_self(self):
        self.assertEqual(self.service.resolve("React"), "React")

    def test_resolve_alias_returns_canonical(self):
        self.assertEqual(self.service.resolve("K8s"), "Kubernetes")
        self.assertEqual(self.service.resolve("ReactJS"), "React")
        self.assertEqual(self.service.resolve("Golang"), "Go")

    def test_resolve_unknown_returns_none(self):
        self.assertIsNone(self.service.resolve("NonExistentSkill"))

    def test_expand_returns_canonical_and_categories(self):
        result = self.service.expand(["K8s", "React.js"])
        self.assertIn("Kubernetes", result)
        self.assertIn("React", result)
        self.assertIn("容器与云", result)
        self.assertIn("前端开发", result)

    def test_expand_empty_returns_empty(self):
        result = self.service.expand([])
        self.assertEqual(result, set())

    def test_expand_unknown_skill_ignored(self):
        result = self.service.expand(["NonExistent"])
        self.assertEqual(result, set())

    def test_expand_with_evidence_rejects_invalid_depth(self):
        with self.assertRaisesRegex(ValueError, "max_depth must be 1 or 2"):
            self.service.expand_with_evidence(["React"], max_depth=3)

    def test_requires_is_directional(self):
        forward = self.service.expand_with_evidence(["Kubernetes"], max_depth=1)
        reverse = self.service.expand_with_evidence(["Docker"], max_depth=1)
        self.assertTrue(
            any(x.target == "Docker" and x.relations == ("REQUIRES",) for x in forward.evidence)
        )
        self.assertFalse(
            any(x.target == "Kubernetes" and "REQUIRES" in x.relations for x in reverse.evidence)
        )

    def test_related_to_is_symmetric(self):
        react = self.service.expand_with_evidence(["React"], max_depth=1)
        vue = self.service.expand_with_evidence(["Vue"], max_depth=1)
        self.assertTrue(any(x.target == "Vue" and x.weight == 0.4 for x in react.evidence))
        self.assertTrue(any(x.target == "React" and x.weight == 0.4 for x in vue.evidence))

    def test_two_hop_weight_and_cycle_protection(self):
        result = self.service.expand_with_evidence(["Next.js"], max_depth=2)
        vue_paths = [x for x in result.evidence if x.target == "Vue" and x.depth == 2]
        self.assertEqual(len(vue_paths), 1)
        self.assertEqual(vue_paths[0].weight, 0.2)
        self.assertEqual(len(vue_paths[0].nodes), len(set(vue_paths[0].nodes)))

    def test_seed_is_idempotent(self):
        self.service.seed()
        self.service.seed()
        self.assertEqual(self.service.resolve("K8s"), "Kubernetes")


@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class EndToEndSkillMatchTest(unittest.TestCase):
    """Test the full flow: seed → expand → score_match."""

    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5", password="test")
        cls.container.start()
        cls.addClassCleanup(cls.container.stop)
        from agent_hub.skill_graph.service import SkillGraphService

        cls.driver = _driver_for(cls.container)
        cls.addClassCleanup(cls.driver.close)
        cls.service = SkillGraphService(cls.driver)
        cls.service.seed()

    def test_alias_improves_match_score(self):
        from agent_hub.agents.global_part_time.domain import score_match

        candidate = {"skills": [{"name": "K8s"}, {"name": "ReactJS"}]}
        job = {"skills": ["Kubernetes", "React"]}

        # Without expansion: no match (different strings)
        _, breakdown_without, _ = score_match(candidate, job)
        self.assertEqual(breakdown_without["skills"], 0.0)

        # With expansion: aliases resolved
        _, breakdown_with, reasons = score_match(candidate, job, expand_fn=self.service.expand)
        self.assertGreater(breakdown_with["skills"], 0.0)

    def test_category_expansion_enables_indirect_match(self):
        from agent_hub.agents.global_part_time.domain import score_match

        candidate = {"skills": [{"name": "React"}, {"name": "Vue"}]}
        job = {"skills": ["前端开发"]}

        # Without expansion: no match
        _, breakdown_without, _ = score_match(candidate, job)
        self.assertEqual(breakdown_without["skills"], 0.0)

        # With expansion: React/Vue → 前端开发
        _, breakdown_with, reasons = score_match(candidate, job, expand_fn=self.service.expand)
        self.assertGreater(breakdown_with["skills"], 0.0)
        has_expansion = any("扩展" in r or "相关" in r for r in reasons)
        self.assertTrue(has_expansion, f"Expected expansion reason in {reasons}")

    def test_direct_match_scores_higher_than_indirect(self):
        from agent_hub.agents.global_part_time.domain import score_match

        candidate = {"skills": [{"name": "Python"}, {"name": "React"}]}

        # Job requires Python (direct) and 前端开发 (indirect via React)
        job = {"skills": ["Python", "前端开发"]}
        _, breakdown, _ = score_match(candidate, job, expand_fn=self.service.expand)

        # Direct(Python)=1.0 + Indirect(前端开发)=0.6 → avg = 0.8
        self.assertAlmostEqual(breakdown["skills"], 0.8, places=1)

    def test_reverse_alias_direction_matches_with_real_graph(self):
        from agent_hub.agents.global_part_time.domain import score_match_with_evidence

        _, breakdown, _, evidence = score_match_with_evidence(
            {"skills": [{"name": "Kubernetes"}]},
            {"skills": ["K8s"]},
            self.service.expand_with_evidence,
        )
        self.assertEqual(breakdown["skills"], 1.0)
        self.assertEqual(evidence["requirements"][0]["score"], 1.0)

    def test_real_graph_requires_path_is_explainable(self):
        from agent_hub.agents.global_part_time.domain import score_match_with_evidence

        _, breakdown, reasons, evidence = score_match_with_evidence(
            {"skills": [{"name": "Docker"}]},
            {"skills": ["Kubernetes"]},
            self.service.expand_with_evidence,
        )
        self.assertEqual(breakdown["skills"], 0.75)
        path = evidence["requirements"][0]["path"]
        self.assertEqual(path["relations"], ["REQUIRES"])
        self.assertEqual(path["nodes"], ["Kubernetes", "Docker"])
        self.assertEqual(
            reasons[0],
            "候选人技能Docker通过REQUIRES与职位要求Kubernetes匹配",
        )

    def test_real_graph_match_persists_exact_sanitized_evidence(self):
        from agent_hub.agents.global_part_time.repository import Repository
        from agent_hub.agents.global_part_time.service import AgentService
        from tests.factories import candidate_payload, job_payload, source_payload

        repo = Repository(":memory:")
        service = AgentService(repo, expand_evidence_fn=self.service.expand_with_evidence)
        source = service.create_source(source_payload(), "operator")
        service.review_source(source["id"], True, "operator")
        graph_job = dict(job_payload(), skills=["Kubernetes"])
        service.sync_source(source["id"], [graph_job], "worker")
        candidate = service.create_candidate(
            dict(candidate_payload(), skills=[{"name": "Docker", "level": 4}]),
            "candidate",
        )
        candidate = service.set_consent(candidate["id"], True, "candidate", "mvp-1")

        returned = service.run_matches(candidate["id"], "scheduler")["matches"][0]
        stored = repo.get("match", returned["id"])
        expected_requirement = {
            "required_skill": "Kubernetes",
            "candidate_skill": "Docker",
            "score": 0.75,
            "path": {
                "input_skill": "Kubernetes",
                "canonical_skill": "Kubernetes",
                "target": "Docker",
                "target_kind": "skill",
                "relations": ["REQUIRES"],
                "nodes": ["Kubernetes", "Docker"],
                "depth": 1,
                "weight": 0.75,
            },
        }

        self.assertEqual(returned["skill_graph_evidence"]["mode"], "graph")
        self.assertEqual(returned["score_breakdown"]["skills"], 0.75)
        self.assertEqual(
            returned["skill_graph_evidence"]["requirements"],
            [expected_requirement],
        )
        self.assertNotIn("exception", json.dumps(returned, ensure_ascii=False).casefold())
        self.assertEqual(stored, returned)
