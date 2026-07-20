import unittest
from unittest.mock import patch

from agent_hub.skill_graph.config import create_neo4j_driver


class Neo4jDriverConfigTest(unittest.TestCase):
    @patch("agent_hub.skill_graph.config.neo4j.GraphDatabase.driver")
    def test_uri_only_environment_uses_documented_default_credentials(self, driver):
        with patch.dict(
            "os.environ",
            {"NEO4J_URI": "bolt://graph.example.test:7687"},
            clear=True,
        ):
            create_neo4j_driver()

        driver.assert_called_once_with(
            "bolt://graph.example.test:7687",
            auth=("neo4j", "agent_hub_graph"),
        )

    @patch("agent_hub.skill_graph.config.neo4j.GraphDatabase.driver")
    def test_explicit_uri_and_auth_override_environment(self, driver):
        with patch.dict(
            "os.environ",
            {
                "NEO4J_URI": "bolt://ignored.example.test:7687",
                "NEO4J_USER": "ignored-user",
                "NEO4J_PASSWORD": "ignored-password",
            },
            clear=True,
        ):
            create_neo4j_driver(
                "bolt://explicit.example.test:7687",
                auth=("explicit-user", "explicit-password"),
                connection_timeout=3,
            )

        driver.assert_called_once_with(
            "bolt://explicit.example.test:7687",
            auth=("explicit-user", "explicit-password"),
            connection_timeout=3,
        )


if __name__ == "__main__":
    unittest.main()
