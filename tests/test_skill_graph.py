import unittest


NEO4J_AVAILABLE = False
try:
    from testcontainers.neo4j import Neo4jContainer

    NEO4J_AVAILABLE = True
except Exception:
    pass


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
        cls.container = Neo4jContainer("neo4j:5")
        cls.container.start()
        cls.bolt_url = cls.container.get_connection_url()

    @classmethod
    def tearDownClass(cls):
        cls.container.stop()

    def test_create_driver_connects(self):
        from agent_hub.skill_graph.config import create_neo4j_driver

        driver = create_neo4j_driver(self.bolt_url, auth=("neo4j", "test"))
        driver.verify_connectivity()
        driver.close()


@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class SeedDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5")
        cls.container.start()
        cls.bolt_url = cls.container.get_connection_url()

    @classmethod
    def tearDownClass(cls):
        cls.container.stop()

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
        cls.container = Neo4jContainer("neo4j:5")
        cls.container.start()
        bolt_url = cls.container.get_connection_url()
        from agent_hub.skill_graph.config import create_neo4j_driver
        from agent_hub.skill_graph.service import SkillGraphService

        cls.driver = create_neo4j_driver(bolt_url, auth=("neo4j", "test"))
        cls.service = SkillGraphService(cls.driver)
        cls.service.seed()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()
        cls.container.stop()

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

    def test_seed_is_idempotent(self):
        self.service.seed()
        self.service.seed()
        self.assertEqual(self.service.resolve("K8s"), "Kubernetes")


@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class EndToEndSkillMatchTest(unittest.TestCase):
    """Test the full flow: seed → expand → score_match."""

    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5")
        cls.container.start()
        bolt_url = cls.container.get_connection_url()
        from agent_hub.skill_graph.config import create_neo4j_driver
        from agent_hub.skill_graph.service import SkillGraphService

        cls.driver = create_neo4j_driver(bolt_url, auth=("neo4j", "test"))
        cls.service = SkillGraphService(cls.driver)
        cls.service.seed()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()
        cls.container.stop()

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
