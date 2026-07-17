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
