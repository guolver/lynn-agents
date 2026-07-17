import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from agent_hub.agents.global_part_time.repository import Repository
from agent_hub.app import create_app


class SkillGraphLifecycleTest(unittest.TestCase):
    @patch.dict("os.environ", {"NEO4J_URI": "bolt://graph.example:7687"})
    @patch("agent_hub.skill_graph.service.SkillGraphService")
    @patch("agent_hub.skill_graph.config.create_neo4j_driver")
    def test_seed_failure_closes_driver_and_disables_expansion(
        self, create_driver: MagicMock, service_type: MagicMock
    ):
        driver = create_driver.return_value
        service_type.return_value.seed.side_effect = RuntimeError("seed failed")

        application = create_app(Repository(":memory:"))

        driver.close.assert_called_once_with()
        self.assertIsNone(application.state.part_time_service.expand_fn)

    @patch.dict("os.environ", {"NEO4J_URI": "bolt://graph.example:7687"})
    @patch("agent_hub.skill_graph.service.SkillGraphService")
    @patch("agent_hub.skill_graph.config.create_neo4j_driver")
    def test_success_injects_expansion_and_closes_driver_on_shutdown(
        self, create_driver: MagicMock, service_type: MagicMock
    ):
        driver = create_driver.return_value
        expand_fn = service_type.return_value.expand

        application = create_app(Repository(":memory:"))

        self.assertIs(application.state.part_time_service.expand_fn, expand_fn)
        driver.close.assert_not_called()
        with TestClient(application) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            driver.close.assert_not_called()
        driver.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
