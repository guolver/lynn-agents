"""可恢复聊天流的 API 层测试。

POST /messages 应通过 StreamHub 中转（生成与连接解耦），
GET /chat/sessions/{id}/stream 用于断开后重连。依赖本地 Redis。
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent_hub.agents.global_part_time.chat_service import ChatService
from agent_hub.agents.global_part_time.stream_hub import StreamHub
from agent_hub.app import create_app
from tests.inmemory_repo import InMemoryRepository


def _redis_available() -> bool:
    return StreamHub("redis://localhost:6379/0").available()


pytestmark = pytest.mark.skipif(not _redis_available(), reason="Redis not available")

ACTOR_HEADERS = {"X-Actor": "stream-test"}


@pytest.fixture()
def client():
    app = create_app(InMemoryRepository())
    with TestClient(app) as c:
        yield c


def _create_session(client) -> str:
    resp = client.post("/api/v1/chat/sessions", headers=ACTOR_HEADERS)
    assert resp.status_code == 201
    return resp.json()["id"]


def _parse_sse(text: str) -> list[tuple[str, str]]:
    events = []
    for frame in text.split("\n\n"):
        event, data = "", ""
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data += line[6:]
        if event:
            events.append((event, data))
    return events


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_get_stream_without_active_returns_204(client):
    session_id = _create_session(client)
    resp = client.get(f"/api/v1/chat/sessions/{session_id}/stream", headers=ACTOR_HEADERS)
    assert resp.status_code == 204


def test_post_message_streams_events_and_clears_active(client, monkeypatch):
    session_id = _create_session(client)

    def fake_stream(self, sid, user_message):
        yield {"event": "delta", "data": {"content": "你好"}}
        yield {"event": "done", "data": {"message_id": "m1"}}

    monkeypatch.setattr(ChatService, "stream_response", fake_stream)
    resp = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "hi"},
        headers=ACTOR_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert ("delta", '{"content": "你好"}') in events
    assert events[-1][0] == "done"

    hub = client.app.state.stream_hub
    assert _wait_for(lambda: hub.get_active(session_id) is None)
    after = client.get(f"/api/v1/chat/sessions/{session_id}/stream", headers=ACTOR_HEADERS)
    assert after.status_code == 204


def test_resume_replays_in_progress_stream(client, monkeypatch):
    session_id = _create_session(client)
    release: list = []

    def slow_stream(self, sid, user_message):
        yield {"event": "delta", "data": {"content": "前半"}}
        while not release:
            time.sleep(0.05)
        yield {"event": "delta", "data": {"content": "后半"}}
        yield {"event": "done", "data": {}}

    monkeypatch.setattr(ChatService, "stream_response", slow_stream)
    chat_svc = client.app.state.chat_service
    hub = client.app.state.stream_hub
    stream_id = chat_svc.start_streaming(session_id, "hi", hub)
    try:
        assert _wait_for(lambda: hub.get_active(session_id) == stream_id)
        # TestClient 会缓冲整个响应，无法观察逐字节到达；
        # 用定时器在 GET 进行中释放生成端，验证"重放已有内容 + 跟读后续"。
        timer = threading.Timer(0.5, lambda: release.append(True))
        timer.start()
        resp = client.get(
            f"/api/v1/chat/sessions/{session_id}/stream",
            headers=ACTOR_HEADERS,
        )
        assert resp.status_code == 200
        collected = _parse_sse(resp.text)
        assert ("delta", '{"content": "前半"}') in collected
        assert ("delta", '{"content": "后半"}') in collected
        assert collected[-1][0] == "done"
    finally:
        release.append(True)
        hub.cleanup(stream_id)
