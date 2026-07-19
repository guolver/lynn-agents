import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_hub.core.security import (
    IdentityMiddleware,
    Principal,
    Role,
    SecuritySettings,
    parse_roles,
    require_roles,
)


def _app(mode="trusted_gateway", secret="secret", auth_jwt_secret=None):
    app = FastAPI()
    app.add_middleware(
        IdentityMiddleware, mode=mode, gateway_secret=secret, auth_jwt_secret=auth_jwt_secret
    )

    @app.get("/protected", dependencies=[require_roles(Role.OPERATOR)])
    def protected():
        return {"ok": True}

    return TestClient(app)


def test_trusted_gateway_rejects_forged_actor():
    response = _app().get(
        "/protected",
        headers={"X-Actor": "admin", "X-Tenant-Id": "acme", "X-Roles": "admin"},
    )
    assert response.status_code == 401


def test_trusted_gateway_builds_principal():
    client = _app()
    response = client.get(
        "/protected",
        headers={
            "X-Actor": "op-1",
            "X-Tenant-Id": "acme",
            "X-Roles": "operator",
            "X-Gateway-Token": "secret",
        },
    )
    assert response.status_code == 200


def test_development_defaults_are_explicit():
    principal = Principal.development("dev-user")
    assert principal.tenant_id == "default"
    assert principal.roles == frozenset({Role.ADMIN, Role.OPERATOR, Role.USER})
    assert principal.trusted is False


def test_security_settings_reject_trusted_gateway_without_secret(monkeypatch):
    monkeypatch.setenv("SECURITY_MODE", "trusted_gateway")
    monkeypatch.delenv("TRUSTED_GATEWAY_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="TRUSTED_GATEWAY_SECRET is required"):
        SecuritySettings.from_env()


def test_security_settings_load_development_roles(monkeypatch):
    monkeypatch.setenv("SECURITY_MODE", "development")
    monkeypatch.setenv("DEVELOPMENT_DEFAULT_ROLES", "operator,user")

    settings = SecuritySettings.from_env()

    assert settings.mode == "development"
    assert settings.gateway_secret is None
    assert settings.development_default_roles == frozenset({Role.OPERATOR, Role.USER})


@pytest.mark.parametrize("value", ["", "unknown", "operator,unknown"])
def test_parse_roles_rejects_empty_and_unknown_values(value):
    with pytest.raises(ValueError):
        parse_roles(value)


def test_development_mode_applies_default_tenant_and_roles():
    response = _app(mode="development", secret=None).get(
        "/protected",
        headers={"X-Actor": "dev-operator"},
    )

    assert response.status_code == 200


def test_roles_dependency_rejects_authenticated_but_disallowed_role():
    response = _app().get(
        "/protected",
        headers={
            "X-Actor": "user-1",
            "X-Tenant-Id": "acme",
            "X-Roles": "user",
            "X-Gateway-Token": "secret",
        },
    )

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/health", "/live", "/ready", "/docs", "/openapi.json", "/redoc"])
def test_identity_middleware_bypasses_public_system_paths(path):
    response = _app().get(path)

    assert response.status_code != 401


def test_identity_middleware_does_not_bypass_similar_path():
    response = _app().get("/health/details")

    assert response.status_code == 401


def test_bearer_token_builds_trusted_principal():
    import jwt

    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "acme", "roles": ["operator"]},
        "jwt-secret-that-is-at-least-32-chars-long",
        algorithm="HS256",
    )
    client = _app(auth_jwt_secret="jwt-secret-that-is-at-least-32-chars-long")

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_bearer_token_with_wrong_secret_is_rejected():
    import jwt

    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "acme", "roles": ["operator"]},
        "wrong-secret-that-is-also-32-plus-chars",
        algorithm="HS256",
    )
    client = _app(auth_jwt_secret="jwt-secret-that-is-at-least-32-chars-long")

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_bearer_token_with_unknown_role_is_rejected():
    import jwt

    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "acme", "roles": ["superuser"]},
        "jwt-secret-that-is-at-least-32-chars-long",
        algorithm="HS256",
    )
    client = _app(auth_jwt_secret="jwt-secret-that-is-at-least-32-chars-long")

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_bearer_path_ignored_when_no_secret_configured_falls_back_to_headers():
    client = _app(auth_jwt_secret=None)

    response = client.get(
        "/protected",
        headers={
            "Authorization": "Bearer whatever",
            "X-Actor": "op-1",
            "X-Tenant-Id": "acme",
            "X-Roles": "operator",
            "X-Gateway-Token": "secret",
        },
    )

    assert response.status_code == 200


def test_auth_endpoints_are_bypassed_by_identity_middleware():
    client = _app()

    response = client.get("/auth/login")  # no route registered, but must not 401

    assert response.status_code == 404


def test_security_settings_rejects_short_auth_jwt_secret(monkeypatch):
    monkeypatch.setenv("SECURITY_MODE", "development")
    monkeypatch.setenv("AUTH_JWT_SECRET", "too-short")

    with pytest.raises(RuntimeError, match="AUTH_JWT_SECRET must be at least 32 characters"):
        SecuritySettings.from_env()


def test_security_settings_accepts_auth_jwt_secret_at_minimum_length(monkeypatch):
    monkeypatch.setenv("SECURITY_MODE", "development")
    monkeypatch.setenv("AUTH_JWT_SECRET", "x" * 32)

    settings = SecuritySettings.from_env()

    assert settings.auth_jwt_secret == "x" * 32
