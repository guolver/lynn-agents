# Phase One Security and Workflow Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add trusted gateway identity, tenant/owner isolation, idempotent asynchronous command submission, and recoverable workflow retries without changing the existing matching rules.

**Architecture:** FastAPI creates one immutable `Principal` per request and enforces RBAC at route boundaries. Business services receive tenant-scoped repositories so HTTP, platform, chat, MCP, and Celery paths share the same isolation rule. Asynchronous endpoints persist a `WorkflowCommand` before dispatch and use a declarative workflow registry for both first dispatch and manual retry.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL, Celery/Redis, Next.js 16, TypeScript, pytest, unittest, Ruff, ESLint.

## Global Constraints

- Production identity mode is `SECURITY_MODE=trusted_gateway`; it requires `TRUSTED_GATEWAY_SECRET` and validates `X-Gateway-Token` with `hmac.compare_digest`.
- Development identity mode is `SECURITY_MODE=development`; its default tenant is exactly `default` and its default roles are exactly `admin,operator,user`.
- Roles are exactly `admin`, `operator`, and `user`.
- Historical tenant data migrates to exactly `default`; historical missing owners migrate to exactly `legacy-owner`.
- Cross-tenant and cross-owner resource access returns HTTP 404; role denial returns HTTP 403.
- Request idempotency is keyed by `(tenant_id, action, idempotency_key)` and rejects a reused key with a different canonical payload hash using HTTP 409.
- Worker step idempotency remains keyed by `(workflow_run_id, step_name)`.
- Manual retry reuses the original `workflow_run_id`; allowed states are `failed`, `manual_review`, and `dispatch_failed`.
- No login page, token issuer, OAuth/OIDC provider, microservice split, Kafka, or transactional outbox is added.
- Existing matching, risk, recommendation, and LLM domain behavior must not change.

## Planned File Structure

- `agent_hub/core/security.py`: Principal, security settings, gateway authentication, RBAC dependencies.
- `agent_hub/core/contracts.py`: ExecutionContext compatibility bridge to Principal.
- `agent_hub/database/models.py`: tenant/owner columns and workflow command models.
- `agent_hub/database/repository.py`: tenant-scoped repository and command persistence.
- `agent_hub/agents/global_part_time/repository.py`: root/scoped repository protocols.
- `agent_hub/agents/global_part_time/service.py`: principal-aware service factory and owner checks.
- `agent_hub/agents/global_part_time/chat_service.py`: tenant/owner-safe chat operations.
- `agent_hub/worker/definitions.py`: workflow payload models and registry.
- `agent_hub/worker/dispatcher.py`: idempotent command submission and redispatch.
- `agent_hub/api/workflows.py`: tenant-aware workflow list/detail/retry routes.
- `agent_hub/agents/global_part_time/http_api.py`: RBAC and dispatcher wiring.
- `frontend/lib/agent-hub-api.ts`: centralized BFF identity forwarding.
- `frontend/app/api/chat/sessions/route.ts`: use the centralized client for chat collection calls.
- `frontend/app/api/chat/sessions/[id]/route.ts`,
  `frontend/app/api/chat/sessions/[id]/messages/route.ts`,
  `frontend/app/api/chat/sessions/[id]/stream/route.ts`, and
  `frontend/app/api/chat/sessions/[id]/upload/route.ts`: use the centralized client for chat resource
  calls.
- `frontend/app/api/chat/tasks/[taskId]/route.ts`: use the centralized client for task polling.
- `frontend/app/api/jobs/route.ts`, `frontend/app/api/jobs/categories/route.ts`,
  `frontend/app/api/jobs/[id]/route.ts`, and `frontend/app/api/jobs/[id]/translate/route.ts`: use the
  centralized client for job calls.
- `alembic/versions/20260719_0007_tenant_security_workflow_commands.py`: additive/backfill/constraint migration.

---

### Task 1: Establish a Reliable Test Baseline

**Files:**
- Create: `tests/__init__.py`
- Modify: `pyproject.toml:35-37`
- Modify: `tests/test_skill_graph.py:30-152`
- Test: `tests/test_pytest_collection.py`

**Interfaces:**
- Consumes: the existing `tests` directory and Neo4j Testcontainers dependency.
- Produces: `pytest -q` can import `tests.*`; Neo4j tests use the container-provided credentials and always close drivers.

- [ ] **Step 1: Write the failing collection smoke test**

```python
# tests/test_pytest_collection.py
def test_tests_package_is_importable() -> None:
    from tests.inmemory_repo import InMemoryRepository

    assert InMemoryRepository is not None
```

- [ ] **Step 2: Run the collection smoke test and verify it fails**

Run: `.venv/bin/pytest tests/test_pytest_collection.py -v`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'tests'`.

- [ ] **Step 3: Make tests an explicit package and include the repository root on pytest's path**

```python
# tests/__init__.py
"""Agent Hub test package."""
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
pythonpath = [".", "src"]
testpaths = ["tests"]
```

- [ ] **Step 4: Use Testcontainers credentials instead of hard-coded `neo4j/test`**

Replace every driver construction in `tests/test_skill_graph.py` with this helper and ensure cleanup is registered before seeding:

```python
def _driver_for(container):
    from agent_hub.skill_graph.config import create_neo4j_driver

    return create_neo4j_driver(
        container.get_connection_url(),
        auth=(container.username, container.password),
    )
```

For each `setUpClass`, assign `cls.driver = _driver_for(cls.container)` before calling `seed()`; in failure paths close the driver and stop the container with `addClassCleanup`.

- [ ] **Step 5: Verify the baseline**

Run: `.venv/bin/pytest tests/test_pytest_collection.py tests/test_api.py tests/test_skill_graph.py -v`

Expected: collection succeeds; unit/API tests pass; Neo4j tests pass when Docker is available or skip when its dependency is unavailable.

- [ ] **Step 6: Commit**

```bash
git add tests/__init__.py tests/test_pytest_collection.py tests/test_skill_graph.py pyproject.toml
git commit -m "test: make pytest collection and neo4j fixtures reliable"
```

### Task 2: Add Principal Authentication and RBAC Primitives

**Files:**
- Create: `agent_hub/core/security.py`
- Modify: `agent_hub/core/contracts.py:50-62`
- Modify: `agent_hub/core/registry.py:67-91`
- Modify: `agent_hub/app.py:36-174`
- Test: `tests/test_security.py`

**Interfaces:**
- Consumes: `SECURITY_MODE`, `TRUSTED_GATEWAY_SECRET`, `DEVELOPMENT_DEFAULT_ROLES`, and request headers.
- Produces: `Principal`, `SecuritySettings.from_env()`, `IdentityMiddleware`, `get_principal(request)`,
  `require_roles(*roles)`, and platform action role enforcement.

- [ ] **Step 1: Write failing Principal and gateway-authentication tests**

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_hub.core.security import IdentityMiddleware, Principal, Role, require_roles


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
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_security.py -v`

Expected: FAIL because `agent_hub.core.security` does not exist.

- [ ] **Step 3: Implement the immutable security types and settings**

```python
# agent_hub/core/security.py
class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    USER = "user"


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
```

`from_env()` must raise `RuntimeError` when mode is `trusted_gateway` and the secret is empty. `parse_roles()` must reject empty and unknown values.

- [ ] **Step 4: Implement middleware and dependencies**

`IdentityMiddleware` bypasses exactly `/health`, `/live`, `/ready`, `/docs`, `/openapi.json`, and `/redoc`. For every other path it stores `Principal` in `request.state.principal`. Trusted mode requires all four gateway headers and constant-time token comparison. Development mode accepts missing tenant/roles and applies configured defaults.

```python
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
```

- [ ] **Step 5: Bridge ExecutionContext without breaking plugins**

```python
@dataclass(frozen=True)
class ExecutionContext:
    principal: Principal
    request_id: str
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def actor(self) -> str:
        return self.principal.actor_id

    @property
    def tenant_id(self) -> str:
        return self.principal.tenant_id
```

- [ ] **Step 6: Enforce roles on unified platform actions**

Extend `ActionDefinition` with
`allowed_roles: frozenset[Role] = frozenset({Role.ADMIN, Role.OPERATOR, Role.USER})`. In
`AgentRegistry.invoke()`, reject the invocation with `AuthorizationError` unless
`context.principal.roles` intersects `action.allowed_roles`. Add a platform test where a user invokes
an operator-only action and receives the mapped HTTP 403. Existing third-party actions that omit the
field remain callable by all authenticated roles.

- [ ] **Step 7: Install middleware in `create_app` and verify GREEN**

Add optional `security_settings: SecuritySettings | None = None` to `create_app`, resolve it once, and install `IdentityMiddleware` with those values.

Run: `.venv/bin/pytest tests/test_security.py tests/test_platform.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add agent_hub/core/security.py agent_hub/core/contracts.py agent_hub/core/registry.py agent_hub/app.py tests/test_security.py tests/test_platform.py
git commit -m "feat: add trusted gateway principal and rbac primitives"
```

### Task 3: Add Tenant and Workflow Command Schema

**Files:**
- Modify: `agent_hub/database/models.py`
- Create: `alembic/versions/20260719_0007_tenant_security_workflow_commands.py`
- Modify: `tests/test_database_models.py`
- Test: `tests/test_tenant_migration.py`

**Interfaces:**
- Consumes: existing PostgreSQL aggregate models and Alembic revision `20260718_0006`.
- Produces: tenant columns, candidate owner, `WorkflowCommand`, and `WorkflowCommandPayload` models.

- [ ] **Step 1: Write failing model metadata tests**

```python
TENANT_TABLES = {
    "job_sources", "jobs", "candidates", "matches", "approvals",
    "notifications", "feedback", "audit_logs", "idempotency_records",
    "workflow_runs", "chat_sessions",
}


def test_tenant_columns_and_command_tables():
    from agent_hub.database.models import Base

    for name in TENANT_TABLES:
        assert "tenant_id" in Base.metadata.tables[name].c
        assert Base.metadata.tables[name].c.tenant_id.nullable is False
    assert "owner_actor_id" in Base.metadata.tables["candidates"].c
    assert "workflow_commands" in Base.metadata.tables
    assert "workflow_command_payloads" in Base.metadata.tables
```

- [ ] **Step 2: Run metadata test and verify RED**

Run: `.venv/bin/pytest tests/test_database_models.py -v`

Expected: FAIL because tenant and command columns do not exist.

- [ ] **Step 3: Add model columns and tenant-aware constraints**

Add `tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")` to every table in `TENANT_TABLES`. Add `owner_actor_id` to Candidate. Replace unique constraints with:

```python
UniqueConstraint("tenant_id", "dedup_key", name="uq_jobs_tenant_dedup_key")
UniqueConstraint("tenant_id", "candidate_id", "job_id", name="uq_matches_tenant_candidate_job")
UniqueConstraint("tenant_id", "action", "key", name="uq_idempotency_tenant_action_key")
```

Define:

```python
class WorkflowCommand(Base):
    __tablename__ = "workflow_commands"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_dispatch")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("tenant_id", "action", "idempotency_key", name="uq_workflow_commands_request"),
    )


class WorkflowCommandPayload(Base):
    __tablename__ = "workflow_command_payloads"
    command_id: Mapped[str] = mapped_column(ForeignKey("workflow_commands.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 4: Write the additive/backfill Alembic migration**

The migration must add nullable columns and execute
`UPDATE job_sources/jobs/candidates/matches/approvals/notifications/feedback/audit_logs/idempotency_records/workflow_runs/chat_sessions SET tenant_id = 'default' WHERE tenant_id IS NULL`
as one statement per named table. It then sets candidate owner to `legacy-owner`, rebuilds the three unique constraints, then
alter columns to non-null. Create command tables after `workflow_runs` is tenantized. Downgrade must
query for cross-tenant duplicates and raise `RuntimeError` before restoring old global unique
constraints.

- [ ] **Step 5: Verify model and migration tests**

Run: `.venv/bin/pytest tests/test_database_models.py tests/test_tenant_migration.py -v`

Expected: PASS; migration test skips only when `TEST_DATABASE_URL` is absent.

- [ ] **Step 6: Commit**

```bash
git add agent_hub/database/models.py alembic/versions/20260719_0007_tenant_security_workflow_commands.py tests/test_database_models.py tests/test_tenant_migration.py
git commit -m "feat: add tenant and workflow command schema"
```

### Task 4: Introduce Tenant-Scoped Repositories

**Files:**
- Modify: `agent_hub/agents/global_part_time/repository.py`
- Modify: `agent_hub/database/repository.py`
- Modify: `tests/inmemory_repo.py`
- Modify: `tests/test_repository_contract.py`
- Test: `tests/test_tenant_repository.py`

**Interfaces:**
- Consumes: root `PostgresRepository` and `InMemoryRepository`.
- Produces: `RootRepositoryProtocol.for_tenant(tenant_id)` and `TenantRepositoryProtocol` with the existing business methods.

- [ ] **Step 1: Write failing isolation tests**

```python
def test_entity_lookup_is_isolated_between_tenants(root_repo):
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("candidate", {"id": "c1", "country": "US", "timezone": "UTC"})
    beta.put("candidate", {"id": "c2", "country": "CA", "timezone": "UTC"})
    assert acme.get("candidate", "c1") is not None
    assert beta.get("candidate", "c1") is None


def test_same_natural_key_is_allowed_in_different_tenants(root_repo, job_payload):
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("job", {**job_payload, "id": "j1", "dedup_key": "shared"})
    beta.put("job", {**job_payload, "id": "j2", "dedup_key": "shared"})
    assert acme.get("job", "j1")["dedup_key"] == "shared"
    assert beta.get("job", "j2")["dedup_key"] == "shared"


def test_idempotency_key_is_scoped_by_tenant(root_repo):
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    assert acme.idempotent("create", "same-key", lambda: {"tenant": "acme"}) == {"tenant": "acme"}
    assert beta.idempotent("create", "same-key", lambda: {"tenant": "beta"}) == {"tenant": "beta"}
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest tests/test_tenant_repository.py -v`

Expected: FAIL because `for_tenant` does not exist.

- [ ] **Step 3: Split root and scoped protocols**

```python
class RootRepositoryProtocol(Protocol):
    def for_tenant(self, tenant_id: str) -> "TenantRepositoryProtocol":
        raise NotImplementedError


class TenantRepositoryProtocol(Protocol):
    tenant_id: str
    def put(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        raise NotImplementedError
    def list(self, kind: str) -> list[dict[str, Any]]:
        raise NotImplementedError
    def delete(self, kind: str, entity_id: str) -> None:
        raise NotImplementedError
    def idempotent(self, action: str, key: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError
```

- [ ] **Step 4: Implement scoped adapters**

`PostgresRepository.for_tenant()` returns a lightweight `_TenantPostgresRepository`. Every select/update/delete includes `model_cls.tenant_id == self.tenant_id`; every insert overwrites payload `tenant_id` with the scope value. Audit and idempotency rows use the scope tenant. Vector search and job category aggregation also filter tenant.

`InMemoryRepository` stores entities by `(tenant_id, kind, id)` and idempotency by `(tenant_id, action, key)`. Its constructor exposes `for_tenant()` and keeps legacy direct methods delegated to `default` only until all tests migrate.

- [ ] **Step 5: Run contract and isolation tests**

Run: `.venv/bin/pytest tests/test_repository_contract.py tests/test_tenant_repository.py tests/test_postgres_repository.py -v`

Expected: in-memory tests PASS; PostgreSQL tests PASS with `TEST_DATABASE_URL` or SKIP without it.

- [ ] **Step 6: Commit**

```bash
git add agent_hub/agents/global_part_time/repository.py agent_hub/database/repository.py tests/inmemory_repo.py tests/test_repository_contract.py tests/test_tenant_repository.py
git commit -m "feat: isolate repository operations by tenant"
```

### Task 5: Enforce RBAC and Chat/Candidate Ownership

**Files:**
- Modify: `agent_hub/api/platform.py`
- Modify: `agent_hub/agents/global_part_time/http_api.py`
- Modify: `agent_hub/agents/global_part_time/service.py`
- Modify: `agent_hub/agents/global_part_time/chat_service.py`
- Modify: `agent_hub/agents/global_part_time/agent.py`
- Modify: `agent_hub/app.py`
- Test: `tests/test_rbac_api.py`
- Test: `tests/test_chat_ownership.py`

**Interfaces:**
- Consumes: `Principal`, `require_roles`, and `RootRepositoryProtocol.for_tenant`.
- Produces: principal-aware request services and owner-safe chat/candidate operations.

- [ ] **Step 1: Write failing RBAC and ownership tests**

```python
def test_user_cannot_read_audit(client, user_headers):
    assert client.get("/api/v1/audit", headers=user_headers).status_code == 403


def test_operator_can_review_sources(client, operator_headers, source_id):
    response = client.post(
        f"/api/v1/sources/{source_id}/review",
        json={"approved": True, "note": "ok"},
        headers={**operator_headers, "Idempotency-Key": "review-001"},
    )
    assert response.status_code == 200


def test_user_cannot_read_another_users_chat(client, headers_for):
    created = client.post("/api/v1/chat/sessions", headers=headers_for("alice")).json()
    assert client.get(
        f"/api/v1/chat/sessions/{created['id']}", headers=headers_for("bob")
    ).status_code == 404
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest tests/test_rbac_api.py tests/test_chat_ownership.py -v`

Expected: FAIL because routes do not consume Principal or enforce owner.

- [ ] **Step 3: Build request-scoped services**

```python
def get_tenant_repository(request: Request, principal: Principal = Depends(get_principal)):
    return request.app.state.root_repository.for_tenant(principal.tenant_id)


def get_service(repo=Depends(get_tenant_repository), principal=Depends(get_principal)):
    return AgentService(repo, principal=principal)


def get_chat_service(repo=Depends(get_tenant_repository), principal=Depends(get_principal)):
    return ChatService(service=AgentService(repo, principal=principal), repo=repo, principal=principal)
```

Store the root repository, provider factories, and registry factory in `application.state`; do not store a user-specific service singleton.

- [ ] **Step 4: Enforce route role matrix**

Add `Principal = require_roles(Role.OPERATOR, Role.ADMIN)` to source/review/sync/matching/notification
route signatures, `Principal = require_roles(Role.ADMIN)` to audit and global workflow route
signatures, and `Principal = require_roles(Role.USER, Role.ADMIN)` to chat and personal candidate
route signatures. Public health remains unauthenticated.

Platform invocation creates
`ExecutionContext(principal=principal, request_id=request_id or str(uuid.uuid4()), idempotency_key=idempotency_key)`.
`GlobalPartTimeAgent.invoke()` constructs a tenant-scoped service from the context rather than using
a default singleton.

- [ ] **Step 5: Enforce owner checks inside ChatService and AgentService**

```python
def _owned_session(self, session_id: str) -> dict[str, Any]:
    session = self.repo.get("chat_session", session_id)
    if session is None or (
        Role.ADMIN not in self.principal.roles
        and session.get("owner_actor_id", session.get("actor")) != self.principal.actor_id
    ):
        raise NotFoundError(f"chat_session {session_id} not found")
    return session
```

Use `_owned_session` in get, delete, add message, bind candidate, stream start/resume, and upload paths. Candidate creation writes `owner_actor_id`; personal candidate lookup applies the same owner rule.

- [ ] **Step 6: Enrich every audit from Principal**

Change `TenantRepositoryProtocol.audit()` to accept optional keyword-only
`request_id: str | None`, `roles: frozenset[str]`, and `workflow_run_id: str | None`. Store these
values inside `details["security_context"]` together with the scoped tenant and actor. `AgentService`
uses its Principal for tenant/roles and the request context for request/workflow IDs; it never stores
the gateway token. Add an assertion in `tests/test_rbac_api.py` that an operator action records tenant,
actor, roles, and request ID.

- [ ] **Step 7: Verify isolation and existing API compatibility**

Run: `.venv/bin/pytest tests/test_security.py tests/test_rbac_api.py tests/test_chat_ownership.py tests/test_api.py tests/test_chat_service.py -v`

Expected: PASS in development mode; trusted gateway cases reject forged headers.

- [ ] **Step 8: Commit**

```bash
git add agent_hub/api/platform.py agent_hub/agents/global_part_time/http_api.py agent_hub/agents/global_part_time/service.py agent_hub/agents/global_part_time/chat_service.py agent_hub/agents/global_part_time/agent.py agent_hub/app.py tests/test_rbac_api.py tests/test_chat_ownership.py tests/test_api.py tests/test_chat_service.py
git commit -m "feat: enforce tenant rbac and resource ownership"
```

### Task 6: Define Every Recoverable Workflow Declaratively

**Files:**
- Create: `agent_hub/worker/definitions.py`
- Modify: `agent_hub/worker/tasks.py`
- Test: `tests/test_workflow_definitions.py`

**Interfaces:**
- Consumes: Celery task names and `Principal` snapshots.
- Produces: `WorkflowDefinition`, typed payload models, `WORKFLOW_DEFINITIONS`,
  `get_definition(workflow_type: str)`, and
  `WorkflowDefinition.build_task_kwargs(raw: dict[str, Any], principal: Principal, workflow_run_id: str)`.

- [ ] **Step 1: Write failing registry coverage and reconstruction tests**

```python
RECORDED_WORKFLOW_TYPES = {
    "source_sync", "matching", "notification", "notification_send",
    "source_fetch_sync", "resume_parsing", "chat_parse_match",
    "embedding", "embedding_backfill",
}


def test_every_recorded_workflow_has_definition():
    assert set(WORKFLOW_DEFINITIONS) == RECORDED_WORKFLOW_TYPES


def test_source_sync_reconstructs_jobs_and_identity():
    payload = SourceSyncPayload(source_id="s1", jobs=[{"title_original": "Dev"}])
    kwargs = get_definition("source_sync").build_task_kwargs(
        payload.model_dump(), Principal("op", "acme", frozenset({Role.OPERATOR}), True), "run-1"
    )
    assert kwargs["jobs"] == [{"title_original": "Dev"}]
    assert kwargs["tenant_id"] == "acme"
    assert kwargs["workflow_run_id"] == "run-1"
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest tests/test_workflow_definitions.py -v`

Expected: FAIL because `worker.definitions` does not exist.

- [ ] **Step 3: Implement payload models and registry**

Define one Pydantic model per type, including all required recovery fields. `NotificationPayload` includes `base_url`; `SourceSyncPayload` includes jobs when stored in command payload; resume/chat payloads use `chat_message_id` rather than raw resume text.

```python
@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_type: str
    task_name: str
    payload_model: type[BaseModel]
    allowed_roles: frozenset[Role]
    retryable: bool = True

    def validate_payload(self, raw: dict[str, Any]) -> BaseModel:
        return self.payload_model.model_validate(raw)

    def build_task_kwargs(self, raw, principal, workflow_run_id):
        payload = self.validate_payload(raw).model_dump(mode="json")
        return {
            **payload,
            "actor": principal.actor_id,
            "tenant_id": principal.tenant_id,
            "roles": sorted(role.value for role in principal.roles),
            "workflow_run_id": workflow_run_id,
        }
```

Use the actual registered Celery task `.name` values and explicit definitions; do not derive task names from workflow type strings.

- [ ] **Step 4: Update task signatures to reconstruct tenant Principal**

Every recoverable task accepts `tenant_id: str`, `roles: list[str]`, and `workflow_run_id`.
`_get_service_and_tracker(principal)` scopes the repository to tenant and builds
`AgentService(root_repo.for_tenant(principal.tenant_id), principal=principal)`.

- [ ] **Step 5: Verify registry coverage and worker tests**

Run: `.venv/bin/pytest tests/test_workflow_definitions.py tests/test_celery_tasks.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_hub/worker/definitions.py agent_hub/worker/tasks.py tests/test_workflow_definitions.py tests/test_celery_tasks.py
git commit -m "feat: register recoverable workflow definitions"
```

### Task 7: Persist Idempotent Workflow Commands and Dispatch Them

**Files:**
- Create: `agent_hub/worker/dispatcher.py`
- Modify: `agent_hub/worker/workflow.py`
- Modify: `agent_hub/database/repository.py`
- Modify: `tests/inmemory_repo.py`
- Test: `tests/test_workflow_dispatcher.py`
- Test: `tests/test_postgres_command_concurrency.py`

**Interfaces:**
- Consumes: `WorkflowDefinition`, tenant Principal, Celery `send_task`, and command models.
- Produces:
  `WorkflowDispatcher.submit(workflow_type: str, payload: dict[str, Any], principal: Principal, idempotency_key: str) -> DispatchResult`
  and `WorkflowDispatcher.redispatch(workflow_run_id: str, principal: Principal) -> DispatchResult`.

- [ ] **Step 1: Write failing request-idempotency tests**

```python
def test_duplicate_submit_dispatches_once(dispatcher, celery, operator):
    first = dispatcher.submit("matching", {"candidate_id": "c1", "limit": 10}, operator, "key-0001")
    second = dispatcher.submit("matching", {"candidate_id": "c1", "limit": 10}, operator, "key-0001")
    assert first.workflow_run_id == second.workflow_run_id
    assert second.replayed is True
    assert celery.send_task.call_count == 1


def test_same_key_with_different_payload_conflicts(dispatcher, operator):
    dispatcher.submit("matching", {"candidate_id": "c1", "limit": 10}, operator, "key-0001")
    with pytest.raises(IdempotencyConflictError):
        dispatcher.submit("matching", {"candidate_id": "c1", "limit": 20}, operator, "key-0001")
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest tests/test_workflow_dispatcher.py -v`

Expected: FAIL because dispatcher and command persistence do not exist.

- [ ] **Step 3: Implement canonical hashing and result types**

```python
def canonical_request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DispatchResult:
    command_id: str
    workflow_run_id: str
    celery_task_id: str | None
    status: str
    replayed: bool
```

- [ ] **Step 4: Add transactional command creation**

Add root repository method:

```python
def create_workflow_command(
    self,
    *,
    principal: Principal,
    action: str,
    idempotency_key: str,
    request_hash: str,
    workflow_type: str,
    target_id: str,
    public_payload: dict[str, Any],
    recoverable_payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    raise NotImplementedError
```

It acquires a PostgreSQL advisory transaction lock derived from tenant/action/key, checks the unique command, raises `IdempotencyConflictError` on hash mismatch, and atomically inserts WorkflowRun, WorkflowCommand, and WorkflowCommandPayload. The in-memory implementation performs the same logic under `threading.RLock`.

- [ ] **Step 5: Implement dispatch status transitions**

`submit()` validates roles and payload, persists first, then calls
`celery_app.send_task(definition.task_name, kwargs=definition.build_task_kwargs(payload, principal, workflow_run_id))`.
On success update command/run task ID and command status `dispatched`; on exception store
`dispatch_failed` and a 2,000-character error, then return a result with no task ID. A replayed
dispatched command never sends another task.

- [ ] **Step 6: Implement bounded command-payload retention**

Add `PostgresRepository.purge_expired_workflow_payloads(now: datetime) -> int` and the equivalent
in-memory method. Register a daily Celery beat task named
`agent_hub.worker.purge_workflow_command_payloads` that deletes only rows whose `expires_at <= now`
and whose associated command is in `dispatched`, `dispatch_failed`, or a terminal workflow state.
Unit tests freeze `now`, retain active payloads, and delete a terminal payload older than seven days.

- [ ] **Step 7: Verify unit and PostgreSQL concurrency behavior**

Run: `.venv/bin/pytest tests/test_workflow_dispatcher.py tests/test_postgres_command_concurrency.py -v`

Expected: unit tests PASS; PostgreSQL concurrency tests PASS with `TEST_DATABASE_URL` or SKIP without it.

- [ ] **Step 8: Commit**

```bash
git add agent_hub/worker/dispatcher.py agent_hub/worker/workflow.py agent_hub/worker/tasks.py agent_hub/worker/celery_app.py agent_hub/database/repository.py tests/inmemory_repo.py tests/test_workflow_dispatcher.py tests/test_postgres_command_concurrency.py
git commit -m "feat: submit asynchronous workflows idempotently"
```

### Task 8: Wire Async APIs and Declarative Manual Retry

**Files:**
- Create: `agent_hub/api/workflows.py`
- Modify: `agent_hub/agents/global_part_time/http_api.py`
- Modify: `agent_hub/app.py`
- Test: `tests/test_async_idempotency_api.py`
- Test: `tests/test_workflow_retry_api.py`

**Interfaces:**
- Consumes: `WorkflowDispatcher`, `WORKFLOW_DEFINITIONS`, Principal, and tenant-aware WorkflowTracker.
- Produces: uniform 202 responses and tenant/role-safe workflow list/detail/retry routes.

- [ ] **Step 1: Write failing HTTP idempotency and retry tests**

```python
def test_duplicate_async_match_returns_same_workflow(client, operator_headers):
    headers = {**operator_headers, "Idempotency-Key": "match-command-001"}
    first = client.post("/api/v1/matches/run", json={"candidate_id": "c1", "limit": 10}, headers=headers)
    second = client.post("/api/v1/matches/run", json={"candidate_id": "c1", "limit": 10}, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["workflow_run_id"] == second.json()["workflow_run_id"]
    assert second.json()["replayed"] is True


def test_retry_uses_saved_notification_base_url(client, tracker, operator_headers):
    run_id = tracker.failed_run(
        tenant_id="default",
        workflow_type="notification",
        payload={"candidate_id": "c1", "match_ids": ["m1"], "base_url": "https://agent.example"},
    )
    response = client.post(f"/api/v1/workflows/{run_id}/retry", headers=operator_headers)
    assert response.status_code == 202
    assert response.json()["workflow_run_id"] == run_id
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/pytest tests/test_async_idempotency_api.py tests/test_workflow_retry_api.py -v`

Expected: FAIL because async branches ignore the key and retry still reconstructs payload manually.

- [ ] **Step 3: Replace every asynchronous `.delay()` branch**

Use one helper:

```python
def accepted(result: DispatchResult) -> JSONResponse:
    return JSONResponse(status_code=202, content={
        "status": result.status,
        "workflow_run_id": result.workflow_run_id,
        "celery_task_id": result.celery_task_id,
        "replayed": result.replayed,
    })
```

Wire source sync, matches, notification preview/send, resume parse, and chat resume analysis through `dispatcher.submit()` with the incoming `Idempotency-Key`. Add required keys to async upload routes.

- [ ] **Step 4: Move workflow routes out of composition root**

`create_workflow_router(tracker, dispatcher)` lists and gets runs filtered by `principal.tenant_id`; admin sees all owners within tenant, operator sees operational definitions, and user sees only rows where `actor == principal.actor_id` and definition allows user. Retry loads the saved command payload, checks state and roles, then calls `dispatcher.redispatch(run_id, principal)`.

- [ ] **Step 5: Map domain errors**

Map invalid gateway to 401 in middleware, role failure to 403, ownership/tenant misses to 404, `IdempotencyConflictError` and invalid retry state to 409, and missing/non-retryable workflow definitions to 422.

- [ ] **Step 6: Verify API behavior**

Run: `.venv/bin/pytest tests/test_async_idempotency_api.py tests/test_workflow_retry_api.py tests/test_api.py tests/test_celery_tasks.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agent_hub/api/workflows.py agent_hub/agents/global_part_time/http_api.py agent_hub/app.py tests/test_async_idempotency_api.py tests/test_workflow_retry_api.py tests/test_api.py
git commit -m "feat: wire idempotent async APIs and workflow retry"
```

### Task 9: Forward Trusted Identity Through Frontend BFF and MCP

**Files:**
- Create: `frontend/lib/agent-hub-api.ts`
- Modify: `frontend/app/api/chat/sessions/route.ts`
- Modify: `frontend/app/api/chat/sessions/[id]/route.ts`
- Modify: `frontend/app/api/chat/sessions/[id]/messages/route.ts`
- Modify: `frontend/app/api/chat/sessions/[id]/stream/route.ts`
- Modify: `frontend/app/api/chat/sessions/[id]/upload/route.ts`
- Modify: `frontend/app/api/chat/tasks/[taskId]/route.ts`
- Modify: `frontend/app/api/jobs/route.ts`
- Modify: `frontend/app/api/jobs/categories/route.ts`
- Modify: `frontend/app/api/jobs/[id]/route.ts`
- Modify: `frontend/app/api/jobs/[id]/translate/route.ts`
- Modify: `agent_hub/mcp_server.py`
- Modify: `frontend/.env.example`
- Modify: `.env.example`
- Test: `frontend/tests/agent-hub-api.test.mjs`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: upstream authenticated user headers and gateway deployment secrets.
- Produces: `agentHubFetch(request, path, init)` and a gateway-aware `PlatformClient`.

- [ ] **Step 1: Write failing forwarding tests**

```javascript
test('agentHubFetch forwards identity without hard-coded chat-user', async () => {
  const headers = buildAgentHubHeaders(new Headers({
    'oai-authenticated-user-email': 'alice@example.com',
    'x-tenant-id': 'acme',
    'x-roles': 'user',
  }), { gatewayToken: 'secret' });
  assert.equal(headers.get('X-Actor'), 'alice@example.com');
  assert.equal(headers.get('X-Tenant-Id'), 'acme');
  assert.equal(headers.get('X-Roles'), 'user');
  assert.equal(headers.get('X-Gateway-Token'), 'secret');
});
```

Add Python tests asserting PlatformClient sends actor, tenant, roles, and gateway token and refuses `MCP_EXPOSE_WRITE=1` without all production identity settings.

- [ ] **Step 2: Run and verify RED**

Run: `cd frontend && node --test tests/agent-hub-api.test.mjs`

Run: `.venv/bin/pytest tests/test_mcp_server.py -v`

Expected: FAIL because centralized forwarding and new client fields do not exist.

- [ ] **Step 3: Implement the centralized BFF client**

```typescript
export function buildAgentHubHeaders(source: Headers, config = process.env): Headers {
  const result = new Headers();
  result.set('X-Actor', source.get('oai-authenticated-user-email') ?? config.AGENT_HUB_DEV_ACTOR ?? 'local-user');
  result.set('X-Tenant-Id', source.get('x-tenant-id') ?? config.AGENT_HUB_DEV_TENANT ?? 'default');
  result.set('X-Roles', source.get('x-roles') ?? config.AGENT_HUB_DEV_ROLES ?? 'user');
  if (config.AGENT_HUB_GATEWAY_TOKEN) result.set('X-Gateway-Token', config.AGENT_HUB_GATEWAY_TOKEN);
  return result;
}
```

`agentHubFetch` merges content headers and `Idempotency-Key`, applies route-specific timeout, and preserves streaming bodies. Replace every route-local `API_URL` and fixed `chat-user` header.

- [ ] **Step 4: Extend MCP PlatformClient**

Constructor becomes:

```python
PlatformClient(base_url, actor, tenant_id="default", roles=("user",), gateway_token=None)
```

Every request includes tenant and roles; include gateway token when configured. `_serve()` reads `MCP_TENANT_ID`, `MCP_ROLES`, and `MCP_GATEWAY_TOKEN`; if write tools are enabled and any is absent, raise `RuntimeError` before contacting the platform.

- [ ] **Step 5: Verify frontend and MCP tests**

Run: `cd frontend && ./node_modules/.bin/eslint . --ignore-pattern dist --ignore-pattern .next && node --test tests/agent-hub-api.test.mjs`

Run: `.venv/bin/pytest tests/test_mcp_server.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/agent-hub-api.ts frontend/app/api frontend/tests/agent-hub-api.test.mjs frontend/.env.example .env.example agent_hub/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: forward trusted identity through bff and mcp"
```

### Task 10: Documentation, Full Verification, and Migration Evidence

**Files:**
- Modify: `README.md`
- Modify: `docs/system-architecture.md`
- Modify: `docs/dev-guide.md`
- Modify: `docs/observability.md`
- Modify: `docker-compose.yml`
- Modify: `Makefile`
- Test: full backend/frontend suites

**Interfaces:**
- Consumes: all completed tasks.
- Produces: documented configuration, reproducible quality gates, and final migration evidence.

- [ ] **Step 1: Document exact operating modes**

Document these production variables and fail-fast behavior:

```dotenv
SECURITY_MODE=trusted_gateway
TRUSTED_GATEWAY_SECRET=replace-with-secret-manager-value
```

Document local defaults:

```dotenv
SECURITY_MODE=development
DEVELOPMENT_DEFAULT_ROLES=admin,operator,user
```

Update README to state PostgreSQL is required; remove the stale SQLite claim. Add the Principal flow, role matrix, tenant boundaries, command lifecycle, retry states, and 401/403/404/409/422 semantics to architecture docs.

- [ ] **Step 2: Make pytest the canonical test command**

Change Makefile:

```make
test-py:
	. .venv/bin/activate && pytest -q
```

Retain explicit `test-pg` and Neo4j targets for infrastructure-backed suites; never label a command “all tests” if it skips required infrastructure.

- [ ] **Step 3: Run migration verification**

Run: `DATABASE_URL=$TEST_DATABASE_URL .venv/bin/alembic upgrade head`

Expected: revision `20260719_0007` applies; existing rows have `tenant_id='default'`; no tenant/owner required column contains NULL.

Run: `DATABASE_URL=$TEST_DATABASE_URL .venv/bin/alembic downgrade 20260718_0006`

Expected: succeeds only when no cross-tenant natural-key collisions exist; otherwise exits with the designed explicit error.

Run: `DATABASE_URL=$TEST_DATABASE_URL .venv/bin/alembic upgrade head`

Expected: upgrade succeeds again.

- [ ] **Step 4: Run complete verification**

Run: `.venv/bin/ruff check src/ tests/`

Expected: `All checks passed!`

Run: `.venv/bin/pytest -q`

Expected: all unit tests pass; infrastructure tests either pass with configured services or show only documented skips.

Run: `cd frontend && ./node_modules/.bin/eslint . --ignore-pattern dist --ignore-pattern .next`

Expected: exit 0 with no lint errors.

Run: `cd frontend && pnpm build`

Expected: production build exits 0.

- [ ] **Step 5: Review the final diff for security regressions**

Run: `git diff --check`

Run: `rg -n "chat-user|X-Actor.*Header|\.delay\(" frontend/app/api agent_hub/agents/global_part_time/http_api.py`

Expected: no hard-coded `chat-user`; HTTP identity comes from Principal; no protected async route directly dispatches `.delay()`.

- [ ] **Step 6: Commit documentation and verification configuration**

```bash
git add README.md docs/system-architecture.md docs/dev-guide.md docs/observability.md docker-compose.yml Makefile
git commit -m "docs: document tenant security and workflow operations"
```

---

## Execution Order and Checkpoints

1. Tasks 1-2 establish reliable tests and trusted identity primitives.
2. Tasks 3-5 migrate and enforce tenant/owner boundaries. Stop for a security review after Task 5.
3. Tasks 6-8 implement declarative workflow recovery and request idempotency. Stop for a workflow review after Task 8.
4. Tasks 9-10 complete edge adapters, documentation, migrations, and full verification.

Do not begin a later checkpoint while an earlier checkpoint has failing focused tests. Preserve unrelated working-tree changes and use `git commit --only` when committing planned files.
