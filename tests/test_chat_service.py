"""Tests for ChatService session management and LLM orchestration."""

from __future__ import annotations

import pytest

from agent_hub.agents.global_part_time.chat_service import ChatService


@pytest.fixture()
def repo():
    from agent_hub.database.config import create_repository

    return create_repository()


@pytest.fixture()
def service(repo):
    from agent_hub.agents.global_part_time.service import AgentService

    return AgentService(repo)


@pytest.fixture()
def chat_service(service, repo):
    return ChatService(service=service, repo=repo)


class TestSessionManagement:
    def test_create_session(self, chat_service):
        session = chat_service.create_session(actor="test-user")
        assert session["id"]
        assert session["status"] == "active"
        assert session["actor"] == "test-user"
        assert session["candidate_id"] is None

    def test_get_session_with_messages(self, chat_service):
        session = chat_service.create_session(actor="test-user")
        chat_service.add_message(session["id"], "user", "Hello")
        chat_service.add_message(session["id"], "assistant", "Hi there!")

        result = chat_service.get_session(session["id"])
        assert result["session"]["id"] == session["id"]
        assert len(result["messages"]) == 2
        assert result["messages"][0]["content"] == "Hello"
        assert result["messages"][1]["content"] == "Hi there!"

    def test_get_nonexistent_session(self, chat_service):
        result = chat_service.get_session("nonexistent")
        assert result is None

    def test_list_sessions(self, chat_service):
        chat_service.create_session(actor="u1")
        chat_service.create_session(actor="u2")
        sessions = chat_service.list_sessions()
        assert len(sessions) >= 2

    def test_bind_candidate(self, chat_service):
        session = chat_service.create_session(actor="test")
        chat_service.bind_candidate(session["id"], "cand-123")
        result = chat_service.get_session(session["id"])
        assert result["session"]["candidate_id"] == "cand-123"


class TestMessageHistory:
    def test_build_llm_messages(self, chat_service):
        session = chat_service.create_session(actor="test")
        chat_service.add_message(session["id"], "user", "Hello")
        chat_service.add_message(session["id"], "assistant", "Hi!")

        messages = chat_service.build_llm_messages(session["id"])
        # Should include system prompt + 2 messages
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Hello"
        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "Hi!"
