"""Authentication identities and role-based access primitives."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    USER = "user"


def parse_roles(value: str) -> frozenset[Role]:
    values = [item.strip() for item in value.split(",")]
    if not values or any(not item for item in values):
        raise ValueError("roles must not be empty")
    return frozenset(Role(item) for item in values)


@dataclass(frozen=True)
class Principal:
    actor_id: str
    tenant_id: str
    roles: frozenset[Role]
    trusted: bool

    @classmethod
    def development(cls, actor_id: str, roles: str = "admin,operator,user") -> "Principal":
        return cls(actor_id, "default", parse_roles(roles), False)


@dataclass(frozen=True)
class SecuritySettings:
    mode: Literal["trusted_gateway", "development"]
    gateway_secret: str | None
    development_default_roles: frozenset[Role]

    @classmethod
    def from_env(cls) -> "SecuritySettings":
        mode = os.getenv("SECURITY_MODE", "development")
        if mode not in {"trusted_gateway", "development"}:
            raise RuntimeError(f"unsupported SECURITY_MODE: {mode}")
        secret = os.getenv("TRUSTED_GATEWAY_SECRET")
        if mode == "trusted_gateway" and not secret:
            raise RuntimeError("TRUSTED_GATEWAY_SECRET is required in trusted_gateway mode")
        roles = parse_roles(os.getenv("DEVELOPMENT_DEFAULT_ROLES", "admin,operator,user"))
        return cls(mode=mode, gateway_secret=secret, development_default_roles=roles)


class IdentityMiddleware(BaseHTTPMiddleware):
    _BYPASS_PATHS = frozenset({"/health", "/live", "/ready", "/docs", "/openapi.json", "/redoc"})

    def __init__(
        self,
        app: ASGIApp,
        *,
        mode: Literal["trusted_gateway", "development"],
        gateway_secret: str | None = None,
        development_default_roles: frozenset[Role] = frozenset(Role),
    ) -> None:
        super().__init__(app)
        self.mode = mode
        self.gateway_secret = gateway_secret
        self.development_default_roles = development_default_roles

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._BYPASS_PATHS:
            return await call_next(request)

        actor = request.headers.get("X-Actor")
        tenant_id = request.headers.get("X-Tenant-Id")
        roles = request.headers.get("X-Roles")
        if self.mode == "development":
            if not actor:
                return self._unauthorized()
            try:
                parsed_roles = (
                    parse_roles(roles) if roles is not None else self.development_default_roles
                )
            except ValueError:
                return self._unauthorized()
            request.state.principal = Principal(
                actor_id=actor,
                tenant_id=tenant_id or "default",
                roles=parsed_roles,
                trusted=False,
            )
            return await call_next(request)

        token = request.headers.get("X-Gateway-Token")
        if not all((actor, tenant_id, roles, token)) or not hmac.compare_digest(
            token or "", self.gateway_secret or ""
        ):
            return self._unauthorized()
        try:
            parsed_roles = parse_roles(roles)
        except ValueError:
            return self._unauthorized()
        request.state.principal = Principal(actor, tenant_id, parsed_roles, True)
        return await call_next(request)

    @staticmethod
    def _unauthorized() -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "trusted gateway authentication required"},
        )


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authenticated principal required")
    return principal


def require_roles(*allowed: Role):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.roles.intersection(allowed):
            raise HTTPException(status_code=403, detail="insufficient role")
        return principal

    return Depends(dependency)
