"""Ownership coverage for chat sessions and personal candidate profiles.

Chat sessions and candidates are tenant-isolated (Task 4) but, before this
task, any authenticated actor within a tenant could read/mutate any other
actor's chat session or candidate by id. These tests cover the missing
per-owner boundary: cross-owner access must 404 (not 403 — a 403 would
confirm the resource exists), same-owner access must keep working, and ADMIN
retains cross-owner access as an operational escape hatch.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from agent_hub.app import create_app
from tests.factories import candidate_payload, job_payload, source_payload
from tests.inmemory_repo import InMemoryRepository as Repository


def headers_for(actor: str, roles: str = "user") -> dict[str, str]:
    return {"X-Actor": actor, "X-Roles": roles}


class ChatSessionOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.repository = Repository(":memory:")
        self.client = TestClient(create_app(self.repository))

    def _create_session(self, actor: str) -> str:
        response = self.client.post("/api/v1/chat/sessions", headers=headers_for(actor))
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def test_user_cannot_read_another_users_chat(self):
        created_id = self._create_session("alice")
        response = self.client.get(
            f"/api/v1/chat/sessions/{created_id}", headers=headers_for("bob")
        )
        self.assertEqual(response.status_code, 404)

    def test_owner_can_read_own_chat(self):
        session_id = self._create_session("alice")
        response = self.client.get(
            f"/api/v1/chat/sessions/{session_id}", headers=headers_for("alice")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session"]["id"], session_id)

    def test_user_cannot_delete_another_users_chat(self):
        session_id = self._create_session("alice")
        response = self.client.delete(
            f"/api/v1/chat/sessions/{session_id}", headers=headers_for("bob")
        )
        self.assertEqual(response.status_code, 404)
        # And it must still exist for the real owner.
        still_there = self.client.get(
            f"/api/v1/chat/sessions/{session_id}", headers=headers_for("alice")
        )
        self.assertEqual(still_there.status_code, 200)

    def test_owner_can_delete_own_chat(self):
        session_id = self._create_session("alice")
        response = self.client.delete(
            f"/api/v1/chat/sessions/{session_id}", headers=headers_for("alice")
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_can_read_another_users_chat(self):
        session_id = self._create_session("alice")
        response = self.client.get(
            f"/api/v1/chat/sessions/{session_id}", headers=headers_for("admin-1", "admin")
        )
        self.assertEqual(response.status_code, 200)

    def test_list_sessions_scoped_to_caller(self):
        self._create_session("alice")
        self._create_session("alice")
        self._create_session("bob")

        alice_sessions = self.client.get(
            "/api/v1/chat/sessions", headers=headers_for("alice")
        ).json()
        bob_sessions = self.client.get("/api/v1/chat/sessions", headers=headers_for("bob")).json()

        self.assertEqual(len(alice_sessions), 2)
        self.assertEqual(len(bob_sessions), 1)
        self.assertTrue(all(s["actor"] == "alice" for s in alice_sessions))

    def test_admin_sees_every_session(self):
        self._create_session("alice")
        self._create_session("bob")

        admin_sessions = self.client.get(
            "/api/v1/chat/sessions", headers=headers_for("admin-1", "admin")
        ).json()
        self.assertEqual(len(admin_sessions), 2)

    def test_user_cannot_message_another_users_session(self):
        session_id = self._create_session("alice")
        response = self.client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"content": "hi"},
            headers=headers_for("bob"),
        )
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_resume_another_users_stream(self):
        session_id = self._create_session("alice")
        response = self.client.get(
            f"/api/v1/chat/sessions/{session_id}/stream", headers=headers_for("bob")
        )
        self.assertEqual(response.status_code, 404)

    def test_owner_resuming_own_stream_with_none_active_returns_204(self):
        session_id = self._create_session("alice")
        response = self.client.get(
            f"/api/v1/chat/sessions/{session_id}/stream", headers=headers_for("alice")
        )
        self.assertEqual(response.status_code, 204)


class CandidateOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.repository = Repository(":memory:")
        self.client = TestClient(create_app(self.repository))

    def _create_candidate(self, actor: str) -> str:
        response = self.client.post(
            "/api/v1/candidates",
            json=candidate_payload(),
            headers={
                **headers_for(actor),
                "Idempotency-Key": f"candidate-create-{actor}",
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def test_user_cannot_read_another_users_candidate(self):
        candidate_id = self._create_candidate("alice")
        response = self.client.get(f"/api/v1/candidates/{candidate_id}", headers=headers_for("bob"))
        self.assertEqual(response.status_code, 404)

    def test_owner_can_read_own_candidate(self):
        candidate_id = self._create_candidate("alice")
        response = self.client.get(
            f"/api/v1/candidates/{candidate_id}", headers=headers_for("alice")
        )
        self.assertEqual(response.status_code, 200)

    def test_user_cannot_update_another_users_candidate_preferences(self):
        candidate_id = self._create_candidate("alice")
        response = self.client.patch(
            f"/api/v1/candidates/{candidate_id}/preferences",
            json={"country": "US"},
            headers={
                **headers_for("bob"),
                "Idempotency-Key": "candidate-update-001",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_delete_another_users_candidate(self):
        candidate_id = self._create_candidate("alice")
        response = self.client.delete(
            f"/api/v1/candidates/{candidate_id}",
            headers={
                **headers_for("bob"),
                "Idempotency-Key": "candidate-delete-001",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_read_another_users_candidate_matches(self):
        candidate_id = self._create_candidate("alice")
        response = self.client.get(
            f"/api/v1/candidates/{candidate_id}/matches", headers=headers_for("bob")
        )
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_set_consent_for_another_users_candidate(self):
        candidate_id = self._create_candidate("alice")
        response = self.client.post(
            f"/api/v1/candidates/{candidate_id}/consent",
            json={"opted_in": True},
            headers={
                **headers_for("bob"),
                "Idempotency-Key": "candidate-consent-001",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_admin_can_read_another_users_candidate(self):
        candidate_id = self._create_candidate("alice")
        response = self.client.get(
            f"/api/v1/candidates/{candidate_id}", headers=headers_for("admin-1", "admin")
        )
        self.assertEqual(response.status_code, 200)

    def test_unsubscribe_bypasses_ownership_for_self_service(self):
        """POST /unsubscribe is a public self-service flow (e.g. an email
        link) — the caller is intentionally not the candidate's owner, so it
        must keep working even though "self-service" never created the
        candidate.
        """
        candidate_id = self._create_candidate("alice")
        response = self.client.post(
            "/api/v1/unsubscribe",
            json={"candidate_id": candidate_id},
            headers={
                **headers_for("self-service"),
                "Idempotency-Key": "unsub-002",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["consent_status"], "opted_out")


class MatchFeedbackOwnershipTest(unittest.TestCase):
    """POST /matches/{match_id}/feedback had zero test coverage before this
    task even though it now carries an owner check (AgentService.feedback
    verifies the match's candidate belongs to the caller). Covers both the
    role gate (USER/ADMIN only) and the owner check (can't react to a match
    computed for someone else's candidate).
    """

    def setUp(self):
        self.repository = Repository(":memory:")
        self.client = TestClient(create_app(self.repository))

    def _create_match_for(self, actor: str) -> str:
        source = self.client.post(
            "/api/v1/sources",
            json=source_payload(),
            headers={
                **headers_for("op-1", "operator"),
                "Idempotency-Key": f"source-create-{actor}",
            },
        ).json()
        self.client.post(
            f"/api/v1/sources/{source['id']}/review",
            json={"approved": True, "note": "ok"},
            headers={
                **headers_for("op-1", "operator"),
                "Idempotency-Key": f"source-review-{actor}",
            },
        )
        self.client.post(
            f"/api/v1/sources/{source['id']}/sync",
            json={"jobs": [job_payload()]},
            headers={
                **headers_for("op-1", "operator"),
                "Idempotency-Key": f"source-sync-{actor}",
            },
        )
        candidate = self.client.post(
            "/api/v1/candidates",
            json=candidate_payload(),
            headers={
                **headers_for(actor),
                "Idempotency-Key": f"candidate-create-{actor}",
            },
        ).json()
        # hard_filter rejects any job for a candidate that hasn't opted in.
        self.client.post(
            f"/api/v1/candidates/{candidate['id']}/consent",
            json={"opted_in": True},
            headers={
                **headers_for(actor),
                "Idempotency-Key": f"candidate-consent-{actor}",
            },
        )
        # Matching is triggered by an operator (POST /matches/run is
        # OPERATOR/ADMIN-only ops tooling) but must still land against the
        # actor's own candidate — OPERATOR bypasses the owner check that
        # would otherwise block it from acting on someone else's candidate.
        matches = self.client.post(
            "/api/v1/matches/run",
            json={"candidate_id": candidate["id"], "limit": 10},
            headers={
                **headers_for("op-1", "operator"),
                "Idempotency-Key": f"matches-run-{actor}",
            },
            params={"sync": "true"},
        ).json()
        self.assertTrue(matches["matches"], "fixture setup must produce at least one match")
        return matches["matches"][0]["id"]

    def test_owner_can_give_feedback_on_own_match(self):
        match_id = self._create_match_for("alice")
        response = self.client.post(
            f"/api/v1/matches/{match_id}/feedback",
            json={"value": "saved"},
            headers={**headers_for("alice"), "Idempotency-Key": "feedback-001"},
        )
        self.assertEqual(response.status_code, 200)

    def test_user_cannot_give_feedback_on_another_users_match(self):
        match_id = self._create_match_for("alice")
        response = self.client.post(
            f"/api/v1/matches/{match_id}/feedback",
            json={"value": "saved"},
            headers={**headers_for("bob"), "Idempotency-Key": "feedback-002"},
        )
        self.assertEqual(response.status_code, 404)

    def test_operator_cannot_give_feedback(self):
        """match_feedback is USER/ADMIN — OPERATOR has no self to react as."""
        match_id = self._create_match_for("alice")
        response = self.client.post(
            f"/api/v1/matches/{match_id}/feedback",
            json={"value": "saved"},
            headers={**headers_for("op-1", "operator"), "Idempotency-Key": "feedback-003"},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_give_feedback_on_any_match(self):
        match_id = self._create_match_for("alice")
        response = self.client.post(
            f"/api/v1/matches/{match_id}/feedback",
            json={"value": "saved"},
            headers={**headers_for("admin-1", "admin"), "Idempotency-Key": "feedback-004"},
        )
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
