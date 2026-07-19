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


def _app(mode="trusted_gateway", secret="secret"):
    app = FastAPI()
    app.add_middleware(IdentityMiddleware, mode=mode, gateway_secret=secret)

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
