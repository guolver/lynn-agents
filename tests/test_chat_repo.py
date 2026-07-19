"""Tests for chat session and message repository operations."""

from __future__ import annotations

import uuid

import pytest

from tests.factories import candidate_payload


def _new_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def repo():
    """Create a repository connected to the test database."""
    from agent_hub.database.config import create_repository

    return create_repository()


class TestChatSessionCRUD:
    def test_create_and_get_session(self, repo):
        session_id = _new_id()
        session = repo.put(
            "chat_session",
            {
                "id": session_id,
                "actor": "test-user",
                "status": "active",
                "candidate_id": None,
            },
        )
        assert session["id"] == session_id
        assert session["status"] == "active"

        fetched = repo.get("chat_session", session_id)
        assert fetched is not None
        assert fetched["actor"] == "test-user"

    def test_list_sessions(self, repo):
        repo.put("chat_session", {"id": _new_id(), "actor": "u1", "status": "active"})
        repo.put("chat_session", {"id": _new_id(), "actor": "u2", "status": "active"})
        sessions = repo.list("chat_session")
        assert len(sessions) >= 2

    def test_bind_candidate_to_session(self, repo):
        session_id = _new_id()
        repo.put("candidate", {**candidate_payload(), "id": "cand-123"})
        repo.put("chat_session", {"id": session_id, "actor": "u1", "status": "active"})
        repo.put(
            "chat_session",
            {
                "id": session_id,
                "actor": "u1",
                "status": "active",
                "candidate_id": "cand-123",
            },
        )
        fetched = repo.get("chat_session", session_id)
        assert fetched["candidate_id"] == "cand-123"


class TestChatMessageCRUD:
    def test_create_and_list_messages(self, repo):
        session_id = _new_id()
        repo.put("chat_session", {"id": session_id, "actor": "u1", "status": "active"})

        msg1_id = _new_id()
        repo.put(
            "chat_message",
            {
                "id": msg1_id,
                "session_id": session_id,
                "role": "user",
                "content": "Hello",
            },
        )
        msg2_id = _new_id()
        repo.put(
            "chat_message",
            {
                "id": msg2_id,
                "session_id": session_id,
                "role": "assistant",
                "content": "Hi there!",
                "tool_calls": None,
            },
        )

        messages = repo.list_by_session(session_id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_message_with_tool_calls(self, repo):
        session_id = _new_id()
        repo.put("chat_session", {"id": session_id, "actor": "u1", "status": "active"})

        msg_id = _new_id()
        tool_calls = [{"id": "call_1", "function": {"name": "run_matches", "arguments": "{}"}}]
        repo.put(
            "chat_message",
            {
                "id": msg_id,
                "session_id": session_id,
                "role": "assistant",
                "content": "",
                "tool_calls": tool_calls,
            },
        )

        messages = repo.list_by_session(session_id)
        assert messages[0]["tool_calls"] == tool_calls
