"""Login attempt rate limiting.

``LoginRateLimiterProtocol`` lets ``IdentityService`` be tested with a fake
(no Redis dependency); ``RedisLoginRateLimiter`` is the production
implementation, reusing the same Redis instance as Celery/StreamHub.

Fails open: if Redis is unreachable, login proceeds without rate limiting
rather than locking every user out — consistent with how ``StreamHub`` and
the skill graph degrade when their backing service is unavailable.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class LoginRateLimiterProtocol(Protocol):
    def is_locked(self, key: str) -> bool: ...

    def record_failure(self, key: str) -> None: ...

    def reset(self, key: str) -> None: ...


class RedisLoginRateLimiter:
    """Fixed-window login failure counter backed by Redis."""

    def __init__(self, redis_url: str, *, max_failures: int = 5, window_seconds: int = 900):
        import redis

        self._redis = redis.Redis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )
        self._max_failures = max_failures
        self._window_seconds = window_seconds

    def available(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    @staticmethod
    def _redis_key(key: str) -> str:
        return f"login_fail:{key}"

    def is_locked(self, key: str) -> bool:
        try:
            count = self._redis.get(self._redis_key(key))
        except Exception:
            logger.warning("Redis unreachable for login rate limit check", exc_info=True)
            return False
        return count is not None and int(count) >= self._max_failures

    def record_failure(self, key: str) -> None:
        try:
            redis_key = self._redis_key(key)
            pipeline = self._redis.pipeline()
            pipeline.incr(redis_key)
            pipeline.expire(redis_key, self._window_seconds)
            pipeline.execute()
        except Exception:
            logger.warning("Redis unreachable for login failure recording", exc_info=True)

    def reset(self, key: str) -> None:
        try:
            self._redis.delete(self._redis_key(key))
        except Exception:
            logger.warning("Redis unreachable for login rate limit reset", exc_info=True)
