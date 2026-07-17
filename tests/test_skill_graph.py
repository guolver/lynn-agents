import unittest


NEO4J_AVAILABLE = False
try:
    from testcontainers.neo4j import Neo4jContainer

    NEO4J_AVAILABLE = True
except Exception:
    pass


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
