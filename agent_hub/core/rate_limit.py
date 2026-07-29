"""Redis sliding-window rate limiter middleware."""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter using Redis.

    Features:
    - Default: 100 requests/minute per client IP
    - Sensitive paths have stricter limits (login: 10/min, register: 5/min)
    - Graceful degradation: pass-through when Redis is unavailable

    Environment variables:
    - RATE_LIMIT_ENABLED: Set to "false" to disable (default: "true")
    - RATE_LIMIT_RPM: Default requests per minute (default: 100)
    - RATE_LIMIT_REDIS_URL: Redis URL (default: redis://localhost:6379/0)
    """

    # Stricter limits for sensitive paths (path prefix -> rpm)
    SENSITIVE_PATHS: dict[str, int] = {
        "/auth/login": 10,
        "/auth/register": 5,
        "/identity/login": 10,
        "/identity/register": 5,
    }

    def __init__(
        self,
        app: ASGIApp,
        *,
        redis_url: str | None = None,
        default_rpm: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        super().__init__(app)
        self._enabled = (
            enabled
            if enabled is not None
            else (os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true")
        )
        self._default_rpm = default_rpm or int(os.getenv("RATE_LIMIT_RPM", "100"))
        self._redis_url = redis_url or os.getenv(
            "RATE_LIMIT_REDIS_URL",
            os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        )
        self._redis = None
        self._redis_available = False

        if self._enabled:
            self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection."""
        try:
            from redis import Redis

            self._redis = Redis.from_url(
                self._redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            # Test connection
            self._redis.ping()
            self._redis_available = True
            logger.info("Rate limiter initialized with Redis at %s", self._redis_url)
        except Exception:
            logger.warning(
                "Redis unavailable at %s - rate limiting disabled (pass-through mode)",
                self._redis_url,
            )
            self._redis = None
            self._redis_available = False

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, respecting X-Forwarded-For header."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _get_rate_limit(self, path: str) -> int:
        """Get rate limit for a given path."""
        for prefix, rpm in self.SENSITIVE_PATHS.items():
            if path.startswith(prefix):
                return rpm
        return self._default_rpm

    def _check_rate_limit(self, client_ip: str, path: str) -> tuple[bool, int, int]:
        """Check if request is within rate limit.

        Returns:
            (allowed, remaining, reset_seconds)
        """
        if not self._redis or not self._redis_available:
            return True, -1, 0

        rpm = self._get_rate_limit(path)
        window_seconds = 60
        now = time.time()
        window_start = now - window_seconds

        # Key format: rate_limit:{client_ip}:{path_group}
        path_group = "default"
        for prefix in self.SENSITIVE_PATHS:
            if path.startswith(prefix):
                path_group = prefix.replace("/", "_")
                break
        key = f"rate_limit:{client_ip}:{path_group}"

        try:
            pipe = self._redis.pipeline()
            # Remove old entries outside the window
            pipe.zremrangebyscore(key, 0, window_start)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Count requests in window
            pipe.zcard(key)
            # Set expiry on key
            pipe.expire(key, window_seconds + 1)
            results = pipe.execute()

            count = results[2]
            remaining = max(0, rpm - count)
            reset_seconds = int(window_seconds - (now - window_start))

            if count > rpm:
                return False, 0, reset_seconds
            return True, remaining, reset_seconds

        except Exception:
            # Redis error - fail open (allow request)
            logger.warning("Rate limit check failed - allowing request", exc_info=True)
            return True, -1, 0

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        if not self._enabled or not self._redis_available:
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        path = request.url.path

        # Skip rate limiting for health checks
        if path in ("/health", "/healthz", "/ready"):
            return await call_next(request)

        allowed, remaining, reset_seconds = self._check_rate_limit(client_ip, path)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests",
                    "retry_after": reset_seconds,
                },
                headers={
                    "Retry-After": str(reset_seconds),
                    "X-RateLimit-Limit": str(self._get_rate_limit(path)),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_seconds),
                },
            )

        response = await call_next(request)

        # Add rate limit headers to successful responses
        if remaining >= 0:
            response.headers["X-RateLimit-Limit"] = str(self._get_rate_limit(path))
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_seconds)

        return response
