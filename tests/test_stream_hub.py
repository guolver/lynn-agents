"""Tests for StreamHub: Redis-Streams-backed resumable chat stream pub/sub.

依赖本地 Redis（docker compose 的 redis 服务，localhost:6379）。
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from agent_hub.agents.global_part_time.stream_hub import StreamHub

REDIS_URL = "redis://localhost:6379/0"


@pytest.fixture()
def hub():
    h = StreamHub(REDIS_URL)
    if not h.available():
        pytest.skip("Redis not available at localhost:6379")
    return h


@pytest.fixture()
def stream_id(hub):
    sid = f"test-{uuid.uuid4()}"
    yield sid
    hub.cleanup(sid)


class TestPublishReplay:
    def test_replay_yields_published_events_until_done(self, hub, stream_id):
        hub.publish(stream_id, "delta", {"content": "你"})
        hub.publish(stream_id, "delta", {"content": "好"})
        hub.publish(stream_id, "done", {"message_id": "m1"})

        events = list(hub.replay_and_follow(stream_id, timeout=5))
        assert events == [
            {"event": "delta", "data": {"content": "你"}},
            {"event": "delta", "data": {"content": "好"}},
            {"event": "done", "data": {"message_id": "m1"}},
        ]

    def test_error_event_is_terminal(self, hub, stream_id):
        hub.publish(stream_id, "error", {"detail": "boom"})
        events = list(hub.replay_and_follow(stream_id, timeout=5))
        assert events == [{"event": "error", "data": {"detail": "boom"}}]

    def test_follow_receives_events_published_after_consumer_starts(self, hub, stream_id):
        hub.publish(stream_id, "delta", {"content": "a"})

        def late_publish():
            time.sleep(0.3)
            hub.publish(stream_id, "delta", {"content": "b"})
            hub.publish(stream_id, "done", {})

        t = threading.Thread(target=late_publish)
        t.start()
        events = list(hub.replay_and_follow(stream_id, timeout=10))
        t.join()
        assert [e["event"] for e in events] == ["delta", "delta", "done"]
        assert events[1]["data"] == {"content": "b"}

    def test_replay_times_out_without_terminal_event(self, hub, stream_id):
        hub.publish(stream_id, "delta", {"content": "a"})
        start = time.monotonic()
        events = list(hub.replay_and_follow(stream_id, timeout=1))
        elapsed = time.monotonic() - start
        assert [e["event"] for e in events] == ["delta"]
        assert elapsed < 5


class TestActiveStreamRegistry:
    def test_set_get_clear_active_stream(self, hub):
        session_id = f"sess-{uuid.uuid4()}"
        stream_id = f"test-{uuid.uuid4()}"
        assert hub.get_active(session_id) is None
        hub.set_active(session_id, stream_id)
        assert hub.get_active(session_id) == stream_id
        hub.clear_active(session_id)
        assert hub.get_active(session_id) is None


class TestAvailability:
    def test_unreachable_redis_reports_unavailable(self):
        h = StreamHub("redis://localhost:1/0")
        assert h.available() is False
