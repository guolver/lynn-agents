"""StreamHub: Redis-Streams-backed pub/sub for resumable chat streams.

生成端把 SSE 事件逐条 XADD 到 Redis Stream；任意数量的消费者（首次请求、
切回页面后的恢复请求、多标签页）都能从头重放并跟读到终止事件。
活跃流注册表（session_id -> stream_id）也放在 Redis 并带 TTL，
进程崩溃后能自动过期，不会留下永远"进行中"的僵尸流。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Generator
from typing import Any

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = frozenset({"done", "error"})

# 流数据只是断连窗口期的重放缓冲，DB 才是最终真相；TTL 覆盖最长生成时间即可。
STREAM_TTL_SECONDS = 1800
BLOCK_MS = 2000


class StreamHub:
    """Publish/replay chat stream events via Redis Streams."""

    def __init__(self, redis_url: str):
        import redis

        self._redis = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=BLOCK_MS / 1000 + 3,
        )

    # -- availability -----------------------------------------------------

    def available(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    # -- keys -------------------------------------------------------------

    @staticmethod
    def _stream_key(stream_id: str) -> str:
        return f"chat:stream:{stream_id}"

    @staticmethod
    def _active_key(session_id: str) -> str:
        return f"chat:active:{session_id}"

    # -- publish ----------------------------------------------------------

    def publish(self, stream_id: str, event: str, data: dict[str, Any] | None) -> None:
        key = self._stream_key(stream_id)
        payload = json.dumps(data or {}, ensure_ascii=False, default=str)
        pipe = self._redis.pipeline()
        pipe.xadd(key, {"event": event, "data": payload})
        pipe.expire(key, STREAM_TTL_SECONDS)
        pipe.execute()

    # -- consume ----------------------------------------------------------

    def replay_and_follow(
        self, stream_id: str, timeout: float = 600
    ) -> Generator[dict[str, Any], None, None]:
        """从头重放整条流并持续跟读，直到终止事件或超时。

        timeout 是"无新事件"的空闲上限，防止生成端崩溃后消费者悬挂。
        """
        key = self._stream_key(stream_id)
        last_id = "0-0"
        idle_deadline = time.monotonic() + timeout
        while time.monotonic() < idle_deadline:
            resp = self._redis.xread({key: last_id}, block=BLOCK_MS, count=100)
            if not resp:
                continue
            for _key, entries in resp:
                for entry_id, fields in entries:
                    last_id = entry_id
                    event = fields.get("event", "")
                    try:
                        data = json.loads(fields.get("data", "{}"))
                    except json.JSONDecodeError:
                        data = {}
                    yield {"event": event, "data": data}
                    if event in TERMINAL_EVENTS:
                        return
                    idle_deadline = time.monotonic() + timeout

    # -- active-stream registry -------------------------------------------

    def set_active(self, session_id: str, stream_id: str) -> None:
        self._redis.set(self._active_key(session_id), stream_id, ex=STREAM_TTL_SECONDS)

    def get_active(self, session_id: str) -> str | None:
        return self._redis.get(self._active_key(session_id))

    def clear_active(self, session_id: str) -> None:
        self._redis.delete(self._active_key(session_id))

    # -- cleanup ----------------------------------------------------------

    def cleanup(self, stream_id: str) -> None:
        self._redis.delete(self._stream_key(stream_id))
