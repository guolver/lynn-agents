"""Tests for the Redis-backed login rate limiter.

依赖本地 Redis（docker compose 的 redis 服务，localhost:6379），沿用
tests/test_stream_hub.py 的可用性探测 + skip 模式。
"""

from __future__ import annotations

import uuid

import pytest

from agent_hub.identity.rate_limiter import RedisLoginRateLimiter

REDIS_URL = "redis://localhost:6379/0"


@pytest.fixture()
def limiter():
    instance = RedisLoginRateLimiter(REDIS_URL, max_failures=3, window_seconds=900)
    if not instance.available():
        pytest.skip("Redis not available at localhost:6379")
    return instance


@pytest.fixture()
def key():
    return f"test:{uuid.uuid4()}"


def test_is_locked_false_when_no_failures(limiter, key):
    assert limiter.is_locked(key) is False


def test_locks_after_max_failures(limiter, key):
    for _ in range(3):
        limiter.record_failure(key)
    assert limiter.is_locked(key) is True


def test_reset_clears_failures(limiter, key):
    for _ in range(3):
        limiter.record_failure(key)
    limiter.reset(key)
    assert limiter.is_locked(key) is False


def test_fails_open_when_redis_unreachable():
    unreachable = RedisLoginRateLimiter("redis://127.0.0.1:1/0", max_failures=3, window_seconds=900)
    assert unreachable.available() is False
    assert unreachable.is_locked("any-key") is False
    unreachable.record_failure("any-key")  # must not raise
    unreachable.reset("any-key")  # must not raise
