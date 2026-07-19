import unittest

from fastapi.testclient import TestClient

from tests.inmemory_repo import InMemoryRepository as Repository
from agent_hub.app import create_app
from tests.factories import job_payload, source_payload


class APISmokeTest(unittest.TestCase):
    def setUp(self):
        self.repository = Repository(":memory:")
        self.client = TestClient(create_app(self.repository))

    def test_health_and_openapi(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok", "registered_agents": 1})
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)

    def test_write_headers_and_idempotency(self):
        source = source_payload()
        missing_headers = self.client.post("/api/v1/sources", json=source)
        self.assertEqual(missing_headers.status_code, 422)
        self.assertEqual(
            missing_headers.json(),
            {
                "detail": [
                    {
                        "type": "missing",
                        "loc": ["header", "Idempotency-Key"],
                        "msg": "Field required",
                        "input": None,
                    },
                    {
                        "type": "missing",
                        "loc": ["header", "X-Actor"],
                        "msg": "Field required",
                        "input": None,
                    },
                ]
            },
        )
        headers = {"Idempotency-Key": "source-create-001", "X-Actor": "operator"}
        first = self.client.post("/api/v1/sources", json=source, headers=headers)
        second = self.client.post("/api/v1/sources", json=source, headers=headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json(), second.json())
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
            headers={"X-Actor": "operator", "X-Request-Id": "request-001"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "agent_id": "global-part-time",
                "action": "list_sources",
                "request_id": "request-001",
                "result": {"sources": []},
            },
        )

    def test_not_found_detail_shape(self):
        response = self.client.get("/api/v1/jobs/missing-job")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "job missing-job not found"})

    def test_policy_conflict_detail_shape(self):
        headers = {"Idempotency-Key": "source-create-001", "X-Actor": "operator"}
        source = self.client.post("/api/v1/sources", json=source_payload(), headers=headers).json()
        response = self.client.post(
            f"/api/v1/sources/{source['id']}/sync",
            json={"jobs": [job_payload()]},
            headers={"Idempotency-Key": "source-sync-001", "X-Actor": "worker"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "only approved and enabled sources may be synchronized"},
        )

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


class JobsCategoryFilterTest(unittest.TestCase):
    def setUp(self):
        self.repository = Repository(":memory:")
        self.client = TestClient(create_app(self.repository))
        base = job_payload()
        for i, (title, categories) in enumerate(
            [
                ("Backend Dev", ["Developer", "Backend"]),
                ("Sales Rep", ["Sales"]),
                ("Fullstack Dev", ["Developer"]),
            ]
        ):
            job = dict(
                base,
                id=f"job-{i}",
                source_job_id=f"job-{i}",
                canonical_url=f"https://feed.example.com/jobs/{i}",
                title_original=title,
                categories=categories,
                status="active",
            )
            self.repository.put("job", job)

    def test_list_jobs_filters_by_category(self):
        response = self.client.get("/api/v1/jobs", params={"category": "Developer"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(
            {j["title_original"] for j in data["jobs"]}, {"Backend Dev", "Fullstack Dev"}
        )

    def test_list_job_categories_aggregated(self):
        response = self.client.get("/api/v1/jobs/categories")
        self.assertEqual(response.status_code, 200)
        cats = response.json()["categories"]
        self.assertEqual(cats[0], {"name": "Developer", "count": 2})
        self.assertIn({"name": "Sales", "count": 1}, cats)


if __name__ == "__main__":
    unittest.main()
