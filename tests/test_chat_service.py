"""Tests for ChatService session management and LLM orchestration."""

from __future__ import annotations

import json
import time

import pytest

from agent_hub.agents.global_part_time.chat_service import MAX_HISTORY_MESSAGES, ChatService
from agent_hub.agents.global_part_time.stream_hub import StreamHub
from tests.factories import candidate_payload


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
        chat_service.repo.put("candidate", {**candidate_payload(), "id": "cand-123"})
        session = chat_service.create_session(actor="test")
        chat_service.bind_candidate(session["id"], "cand-123")
        result = chat_service.get_session(session["id"])
        assert result["session"]["candidate_id"] == "cand-123"


@pytest.fixture()
def hub():
    h = StreamHub("redis://localhost:6379/0")
    if not h.available():
        pytest.skip("Redis not available at localhost:6379")
    return h


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class TestStartStreaming:
    """生成任务与 HTTP 连接解耦：后台线程把事件写入 StreamHub。"""

    def test_events_land_in_hub_and_active_cleared_on_completion(
        self, chat_service, hub, monkeypatch
    ):
        session = chat_service.create_session(actor="test")

        def fake_stream(session_id, user_message):
            yield {"event": "delta", "data": {"content": "你好"}}
            yield {"event": "done", "data": {"message_id": "m1"}}

        monkeypatch.setattr(chat_service, "stream_response", fake_stream)
        stream_id = chat_service.start_streaming(session["id"], "hi", hub)
        try:
            assert stream_id
            events = list(hub.replay_and_follow(stream_id, timeout=5))
            assert events[-1]["event"] == "done"
            assert {"event": "delta", "data": {"content": "你好"}} in events
            assert _wait_for(lambda: hub.get_active(session["id"]) is None)
        finally:
            hub.cleanup(stream_id)

    def test_active_stream_registered_while_generating(self, chat_service, hub, monkeypatch):
        session = chat_service.create_session(actor="test")
        release = []

        def slow_stream(session_id, user_message):
            yield {"event": "delta", "data": {"content": "a"}}
            while not release:
                time.sleep(0.05)
            yield {"event": "done", "data": {}}

        monkeypatch.setattr(chat_service, "stream_response", slow_stream)
        stream_id = chat_service.start_streaming(session["id"], "hi", hub)
        try:
            assert _wait_for(lambda: hub.get_active(session["id"]) == stream_id)
        finally:
            release.append(True)
            assert _wait_for(lambda: hub.get_active(session["id"]) is None)
            hub.cleanup(stream_id)

    def test_unexpected_exception_publishes_error_and_clears_active(
        self, chat_service, hub, monkeypatch
    ):
        session = chat_service.create_session(actor="test")

        def broken_stream(session_id, user_message):
            yield {"event": "delta", "data": {"content": "a"}}
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(chat_service, "stream_response", broken_stream)
        stream_id = chat_service.start_streaming(session["id"], "hi", hub)
        try:
            events = list(hub.replay_and_follow(stream_id, timeout=5))
            assert events[-1]["event"] == "error"
            assert _wait_for(lambda: hub.get_active(session["id"]) is None)
        finally:
            hub.cleanup(stream_id)


class TestShownJobIds:
    def test_collects_job_ids_from_run_matches_tool_history(self, chat_service):
        session = chat_service.create_session(actor="t")
        chat_service.add_message(
            session["id"],
            "tool",
            json.dumps(
                {"name": "run_matches", "result": {"matches": [{"job_id": "j1"}, {"job_id": "j2"}]}}
            ),
            tool_call_id="c1",
        )
        chat_service.add_message(
            session["id"],
            "tool",
            json.dumps({"name": "get_job_detail", "result": {"job": {"id": "j9"}}}),
            tool_call_id="c2",
        )
        assert chat_service.shown_job_ids(session["id"]) == {"j1", "j2"}

    def test_empty_session_has_no_shown_jobs(self, chat_service):
        session = chat_service.create_session(actor="t")
        assert chat_service.shown_job_ids(session["id"]) == set()


class TestMessageHistory:
    def test_attachment_metadata_roundtrip(self, chat_service):
        """上传简历的消息应携带附件元数据，历史回放据此重建附件卡片。"""
        session = chat_service.create_session(actor="test")
        attachment = {"name": "resume.pdf", "size": 12345, "type": "application/pdf"}
        chat_service.add_message(
            session["id"], "user", "[简历内容]\n张三 Python 工程师", attachment=attachment
        )

        result = chat_service.get_session(session["id"])
        msg = result["messages"][0]
        assert msg["attachment"] == attachment

    def test_message_without_attachment_has_none(self, chat_service):
        session = chat_service.create_session(actor="test")
        chat_service.add_message(session["id"], "user", "Hello")
        result = chat_service.get_session(session["id"])
        assert result["messages"][0].get("attachment") is None

    def test_build_llm_messages_excludes_attachment(self, chat_service):
        """LLM 上下文只需要简历文本内容，不应包含附件元数据字段。"""
        session = chat_service.create_session(actor="test")
        chat_service.add_message(
            session["id"],
            "user",
            "[简历内容]\n文本",
            attachment={"name": "a.pdf", "size": 1, "type": "application/pdf"},
        )
        messages = chat_service.build_llm_messages(session["id"])
        assert messages[1]["content"] == "[简历内容]\n文本"
        assert "attachment" not in messages[1]

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


def _assert_valid_tool_sequence(messages):
    """OpenAI 协议：tool 消息必须紧跟携带对应 tool_calls 的 assistant 消息。"""
    pending: set[str] = set()
    for msg in messages:
        if msg["role"] == "tool":
            assert msg.get("tool_call_id") in pending, f"orphan tool message: {msg}"
            pending.discard(msg["tool_call_id"])
        else:
            assert not pending, f"tool_calls left unanswered before {msg['role']} message"
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                pending = {tc["id"] for tc in msg["tool_calls"]}
    assert not pending, "history ends with unanswered tool_calls"


class TestLlmMessageValidity:
    def test_orphan_tool_message_dropped(self, chat_service):
        """旧版 run_analysis 持久化了无 tool_calls 的 assistant + tool 消息，
        回放时必须丢弃孤儿 tool 消息，否则 DeepSeek 返回 400。"""
        session = chat_service.create_session(actor="test")
        chat_service.add_message(session["id"], "user", "[简历内容]\n张三")
        assistant = chat_service.add_message(session["id"], "assistant", "匹配到 3 个岗位")
        chat_service.add_message(
            session["id"],
            "tool",
            json.dumps({"name": "run_matches", "result": {"matches": []}}),
            tool_call_id=f"chat_match_{assistant['id']}",
        )
        chat_service.add_message(session["id"], "user", "查看我的档案和求职偏好")

        messages = chat_service.build_llm_messages(session["id"])
        _assert_valid_tool_sequence(messages)
        assert all(m["role"] != "tool" for m in messages)

    def test_valid_tool_pair_preserved(self, chat_service):
        session = chat_service.create_session(actor="test")
        chat_service.add_message(session["id"], "user", "帮我匹配岗位")
        chat_service.add_message(
            session["id"],
            "assistant",
            "",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "run_matches", "arguments": "{}"},
                }
            ],
        )
        chat_service.add_message(session["id"], "tool", "{}", tool_call_id="call_1")
        chat_service.add_message(session["id"], "assistant", "为你找到这些岗位")

        messages = chat_service.build_llm_messages(session["id"])
        _assert_valid_tool_sequence(messages)
        assert any(m["role"] == "tool" for m in messages)

    def test_truncation_does_not_orphan_tool_messages(self, chat_service):
        """历史截断把 assistant(tool_calls) 切出窗口时，其 tool 回复也必须一并丢弃。"""
        session = chat_service.create_session(actor="test")
        chat_service.add_message(session["id"], "user", "hi")
        chat_service.add_message(
            session["id"],
            "assistant",
            "",
            tool_calls=[
                {
                    "id": "call_cut",
                    "type": "function",
                    "function": {"name": "run_matches", "arguments": "{}"},
                }
            ],
        )
        chat_service.add_message(session["id"], "tool", "{}", tool_call_id="call_cut")
        # 39 filler messages: window of MAX_HISTORY_MESSAGES starts exactly at the tool message
        for i in range(MAX_HISTORY_MESSAGES - 1):
            role = "user" if i % 2 == 0 else "assistant"
            chat_service.add_message(session["id"], role, f"msg {i}")

        messages = chat_service.build_llm_messages(session["id"])
        _assert_valid_tool_sequence(messages)

    def test_incomplete_tool_responses_strip_tool_calls(self, chat_service):
        """assistant 带 tool_calls 但 tool 回复缺失（如流式中断），回放时应剥离 tool_calls。"""
        session = chat_service.create_session(actor="test")
        chat_service.add_message(session["id"], "user", "帮我匹配岗位")
        chat_service.add_message(
            session["id"],
            "assistant",
            "好的",
            tool_calls=[
                {
                    "id": "call_lost",
                    "type": "function",
                    "function": {"name": "run_matches", "arguments": "{}"},
                }
            ],
        )
        chat_service.add_message(session["id"], "user", "怎么样了")

        messages = chat_service.build_llm_messages(session["id"])
        _assert_valid_tool_sequence(messages)

    def test_run_analysis_persists_replayable_history(self, chat_service, monkeypatch):
        """run_analysis 持久化的 assistant + tool 消息必须能原样回放给 LLM。"""
        import agent_hub.agents.global_part_time.chat_tools as chat_tools

        def fake_execute_tool(name, args, *, service, actor):
            if name == "parse_resume":
                return {"candidate": {"id": "cand-fake"}, "parsed_fields": ["skills"]}
            if name == "run_matches":
                return {"matches": [{"job_id": "j1", "score": 0.9}]}
            raise AssertionError(f"unexpected tool {name}")

        monkeypatch.setattr(chat_tools, "execute_tool", fake_execute_tool)
        # candidate "cand-fake" 不在库中，绑定会触发外键约束，这里不是被测点
        monkeypatch.setattr(chat_service, "bind_candidate", lambda *a, **k: None)

        session = chat_service.create_session(actor="test")
        chat_service.run_analysis(session["id"], "张三 Python 工程师", "test")
        chat_service.add_message(session["id"], "user", "查看我的档案和求职偏好")

        messages = chat_service.build_llm_messages(session["id"])
        _assert_valid_tool_sequence(messages)
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1, "匹配结果应保留在 LLM 上下文中"
