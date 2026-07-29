"""Security headers middleware for FastAPI."""

from __future__ import annotations

import os
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses.

    Headers added:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Content-Security-Policy: configurable
    - Strict-Transport-Security: opt-in via ENABLE_HSTS=true

    Environment variables:
    - ENABLE_HSTS: Enable HSTS header (default: false)
    - HSTS_MAX_AGE: HSTS max-age in seconds (default: 31536000 = 1 year)
    - CSP_POLICY: Content-Security-Policy value (default: see below)
    """

    DEFAULT_CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )

    def __init__(
        self,
        app: ASGIApp,
        *,
        enable_hsts: bool | None = None,
        hsts_max_age: int | None = None,
        csp_policy: str | None = None,
    ) -> None:
        super().__init__(app)
        self._enable_hsts = (
            enable_hsts
            if enable_hsts is not None
            else (os.getenv("ENABLE_HSTS", "false").lower() == "true")
        )
        self._hsts_max_age = hsts_max_age or int(os.getenv("HSTS_MAX_AGE", "31536000"))
        self._csp_policy = csp_policy or os.getenv("CSP_POLICY", self.DEFAULT_CSP)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Content Security Policy
        if self._csp_policy:
            response.headers["Content-Security-Policy"] = self._csp_policy

        # HSTS (only enable in production with HTTPS)
        if self._enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self._hsts_max_age}; includeSubDomains"
            )

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy (disable unnecessary browser features)
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        return response
