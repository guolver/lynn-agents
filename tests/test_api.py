import unittest

from fastapi.testclient import TestClient

from agent_hub.agents.global_part_time.repository import Repository
from agent_hub.app import create_app


class APISmokeTest(unittest.TestCase):
    def setUp(self):
        self.repository = Repository(":memory:")
        self.client = TestClient(create_app(self.repository))

    def test_health_and_openapi(self):
        self.assertEqual(
            self.client.get("/health").json(),
            {"status": "ok", "registered_agents": 1},
        )
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)

    def test_write_headers_and_idempotency(self):
        source = {
            "name": "Partner",
            "source_type": "partner_feed",
            "base_url": "https://feed.example.com",
            "authorization_basis": "signed partner contract",
            "allowed_paths": ["/jobs"],
            "prohibited_actions": ["login automation"],
            "rate_limit": "60/hour",
            "retention_policy": "30 days",
        }
        self.assertEqual(self.client.post("/api/v1/sources", json=source).status_code, 422)
        headers = {"Idempotency-Key": "source-create-001", "X-Actor": "operator"}
        first = self.client.post("/api/v1/sources", json=source, headers=headers)
        second = self.client.post("/api/v1/sources", json=source, headers=headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(len(self.repository.list("source")), 1)

    def test_platform_discovers_and_invokes_agent(self):
        catalog = self.client.get("/platform/v1/agents")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json()[0]["agent_id"], "global-part-time")

        detail = self.client.get("/platform/v1/agents/global-part-time").json()
        self.assertIn("find_matches", {action["name"] for action in detail["actions"]})

        response = self.client.post(
            "/platform/v1/agents/global-part-time/actions/list_sources",
            json={"payload": {}},
            headers={"X-Actor": "operator"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], {"sources": []})

    def test_platform_requires_idempotency_for_write_action(self):
        path = "/platform/v1/agents/global-part-time/actions/request_approval"
        body = {"payload": {"action": "send_digest", "target_id": "draft-1"}}
        missing_key = self.client.post(path, json=body, headers={"X-Actor": "operator"})
        self.assertEqual(missing_key.status_code, 422)

        headers = {"X-Actor": "operator", "Idempotency-Key": "approval-request-001"}
        first = self.client.post(path, json=body, headers=headers)
        second = self.client.post(path, json=body, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["result"]["id"], second.json()["result"]["id"])
        self.assertEqual(len(self.repository.list("approval")), 1)

    def test_platform_rejects_invalid_action_payload_types(self):
        response = self.client.post(
            "/platform/v1/agents/global-part-time/actions/find_matches",
            json={"payload": {"candidate_id": 123, "limit": 10}},
            headers={"X-Actor": "operator", "Idempotency-Key": "match-invalid-001"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("candidate_id", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
