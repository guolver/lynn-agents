"""RBAC coverage for the legacy /api/v1 REST routes.

Task 4 already isolates data by tenant at the repository layer; this module
covers the layer above it — that ``/api/v1/...`` routes actually consume the
request's Principal (role gates) and that AgentService enriches every audit
entry with the Principal's tenant/actor/roles/request id (Task 5, Step 6).

Development-mode Principals get every role by default unless the request
sends an explicit ``X-Roles`` header (see core/security.py), so tests that
want a *restricted* role must set X-Roles explicitly.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from agent_hub.app import create_app
from tests.factories import job_payload, source_payload
from tests.inmemory_repo import InMemoryRepository as Repository


def headers_for(actor: str, roles: str | None = None) -> dict[str, str]:
    headers = {"X-Actor": actor}
    if roles is not None:
        headers["X-Roles"] = roles
    return headers


class RBACRouteMatrixTest(unittest.TestCase):
    def setUp(self):
        self.repository = Repository(":memory:")
        self.client = TestClient(create_app(self.repository))

    def _create_source(self, actor: str = "op-1") -> str:
        response = self.client.post(
            "/api/v1/sources",
            json=source_payload(),
            headers={
                **headers_for(actor, "operator"),
                "Idempotency-Key": "source-create-001",
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    # -- ADMIN-only: audit + global workflow routes -----------------------

    def test_user_cannot_read_audit(self):
        response = self.client.get("/api/v1/audit", headers=headers_for("user-1", "user"))
        self.assertEqual(response.status_code, 403)

    def test_operator_cannot_read_audit(self):
        response = self.client.get("/api/v1/audit", headers=headers_for("op-1", "operator"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_read_audit(self):
        response = self.client.get("/api/v1/audit", headers=headers_for("admin-1", "admin"))
        self.assertEqual(response.status_code, 200)

    def test_operator_cannot_list_workflows(self):
        response = self.client.get("/api/v1/workflows", headers=headers_for("op-1", "operator"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_list_workflows(self):
        response = self.client.get("/api/v1/workflows", headers=headers_for("admin-1", "admin"))
        self.assertEqual(response.status_code, 200)

    # -- OPERATOR/ADMIN: source/review/sync/matching/notification ---------

    def test_user_cannot_create_source(self):
        response = self.client.post(
            "/api/v1/sources",
            json=source_payload(),
            headers={
                **headers_for("user-1", "user"),
                "Idempotency-Key": "source-create-002",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_can_review_sources(self):
        source_id = self._create_source()
        response = self.client.post(
            f"/api/v1/sources/{source_id}/review",
            json={"approved": True, "note": "ok"},
            headers={
                **headers_for("op-1", "operator"),
                "Idempotency-Key": "review-001",
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_user_cannot_review_sources(self):
        source_id = self._create_source()
        response = self.client.post(
            f"/api/v1/sources/{source_id}/review",
            json={"approved": True, "note": "ok"},
            headers={
                **headers_for("user-1", "user"),
                "Idempotency-Key": "review-002",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_user_cannot_list_sources(self):
        response = self.client.get("/api/v1/sources", headers=headers_for("user-1", "user"))
        self.assertEqual(response.status_code, 403)

    def test_user_cannot_trigger_bulk_matches(self):
        response = self.client.post(
            "/api/v1/matches/run",
            json={"candidate_id": "cand-x", "limit": 10},
            headers={
                **headers_for("user-1", "user"),
                "Idempotency-Key": "matches-run-001",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_user_cannot_list_notifications(self):
        response = self.client.get("/api/v1/notifications", headers=headers_for("user-1", "user"))
        self.assertEqual(response.status_code, 403)

    def test_operator_can_list_notifications(self):
        response = self.client.get("/api/v1/notifications", headers=headers_for("op-1", "operator"))
        self.assertEqual(response.status_code, 200)

    def test_user_cannot_list_all_candidates(self):
        response = self.client.get("/api/v1/candidates", headers=headers_for("user-1", "user"))
        self.assertEqual(response.status_code, 403)

    def test_operator_can_list_all_candidates(self):
        response = self.client.get("/api/v1/candidates", headers=headers_for("op-1", "operator"))
        self.assertEqual(response.status_code, 200)

    # -- USER/ADMIN: chat + personal candidate routes ----------------------

    def test_operator_cannot_create_chat_session(self):
        response = self.client.post(
            "/api/v1/chat/sessions", headers=headers_for("op-1", "operator")
        )
        self.assertEqual(response.status_code, 403)

    def test_user_can_create_chat_session(self):
        response = self.client.post("/api/v1/chat/sessions", headers=headers_for("user-1", "user"))
        self.assertEqual(response.status_code, 201)

    def test_operator_cannot_create_candidate(self):
        from tests.factories import candidate_payload

        response = self.client.post(
            "/api/v1/candidates",
            json=candidate_payload(),
            headers={
                **headers_for("op-1", "operator"),
                "Idempotency-Key": "candidate-create-001",
            },
        )
        self.assertEqual(response.status_code, 403)

    # -- Left unrestricted (beyond authentication) -------------------------

    def test_user_can_browse_jobs(self):
        response = self.client.get("/api/v1/jobs", headers=headers_for("user-1", "user"))
        self.assertEqual(response.status_code, 200)

    def test_user_can_report_job(self):
        source_id = self._create_source()
        self.client.post(
            f"/api/v1/sources/{source_id}/review",
            json={"approved": True, "note": "ok"},
            headers={
                **headers_for("op-1", "operator"),
                "Idempotency-Key": "review-003",
            },
        )
        sync = self.client.post(
            f"/api/v1/sources/{source_id}/sync",
            json={"jobs": [job_payload()]},
            headers={
                **headers_for("op-1", "operator"),
                "Idempotency-Key": "sync-001",
            },
        )
        self.assertEqual(sync.status_code, 200)
        job_id = sync.json()["job_ids"][0]

        response = self.client.post(
            f"/api/v1/jobs/{job_id}/report",
            json={"reason": "looks like a scam"},
            headers={
                **headers_for("user-1", "user"),
                "Idempotency-Key": "report-001",
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_unsubscribe_works_without_special_role(self):
        response = self.client.post(
            "/api/v1/unsubscribe",
            json={"candidate_id": "missing-candidate"},
            headers={
                **headers_for("self-service", "user"),
                "Idempotency-Key": "unsub-001",
            },
        )
        # No role restriction: a not-found candidate is a 404, not a 403.
        self.assertEqual(response.status_code, 404)

    # -- Audit enrichment (Step 6) ------------------------------------------

    def test_operator_action_records_security_context(self):
        source_id = self._create_source(actor="op-audit")
        self.client.post(
            f"/api/v1/sources/{source_id}/review",
            json={"approved": True, "note": "ok"},
            headers={
                **headers_for("op-audit", "operator"),
                "Idempotency-Key": "review-audit-001",
                "X-Request-Id": "req-audit-001",
            },
        )
        audits = self.client.get("/api/v1/audit", headers=headers_for("admin-1", "admin")).json()
        reviewed = next(a for a in audits if a["event"] == "source.reviewed")
        context = reviewed["details"]["security_context"]
        self.assertEqual(context["tenant_id"], "default")
        self.assertEqual(context["actor"], "op-audit")
        self.assertIn("operator", context["roles"])
        self.assertEqual(context["request_id"], "req-audit-001")


if __name__ == "__main__":
    unittest.main()
