"""REST endpoints for registration/login/refresh/logout.

These four routes are listed in ``IdentityMiddleware._BYPASS_PATHS`` — they
establish identity, so they cannot themselves require an already-authenticated
principal. Errors are handled inline (matching the style already used in
``agents/global_part_time/http_api.py``) rather than via app-wide exception
handlers, keeping this router self-contained.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .domain import ValidationError
from .service import (
    EmailAlreadyRegisteredError,
    IdentityService,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    LoginRateLimitedError,
)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str = Field(max_length=128)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


def create_identity_router(service: IdentityService) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["identity"])

    @router.post("/register", status_code=201)
    def register(body: RegisterRequest):
        try:
            return service.register(body.email, body.password)
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": str(exc)})
        except EmailAlreadyRegisteredError:
            return JSONResponse(status_code=409, content={"detail": "email already registered"})

    @router.post("/login")
    def login(body: LoginRequest):
        try:
            return service.login(body.email, body.password)
        except LoginRateLimitedError:
            return JSONResponse(
                status_code=429, content={"detail": "too many failed login attempts"}
            )
        except InvalidCredentialsError:
            return JSONResponse(status_code=401, content={"detail": "invalid email or password"})

    @router.post("/refresh")
    def refresh(body: RefreshRequest):
        try:
            return service.refresh(body.refresh_token)
        except InvalidRefreshTokenError:
            return JSONResponse(status_code=401, content={"detail": "invalid refresh token"})

    @router.post("/logout", status_code=204)
    def logout(body: LogoutRequest):
        service.logout(body.refresh_token)
        return None

    return router
