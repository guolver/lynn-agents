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
