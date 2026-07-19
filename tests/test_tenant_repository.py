"""Tenant isolation tests for the repository layer.

Exercises ``RootRepositoryProtocol.for_tenant(tenant_id)`` against both the
in-memory fake and the PostgreSQL repository (skipped without
``TEST_DATABASE_URL``, matching the pattern in ``tests/test_postgres_repository.py``).

These tests intentionally use distinct entity ids per tenant even where two
tenants share a natural key (e.g. ``dedup_key``): primary keys are single
global columns, not composite with ``tenant_id``, so two tenants can never
legitimately share a row id — only natural/business keys may collide.
"""

from __future__ import annotations

import os

import pytest

from tests.factories import ensure_vector_extension
from tests.inmemory_repo import InMemoryRepository

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _make_inmemory():
    return InMemoryRepository(":memory:")


def _make_postgres():
    from agent_hub.database.models import Base
    from agent_hub.database.repository import PostgresRepository

    repo = PostgresRepository(TEST_DATABASE_URL)
    ensure_vector_extension(repo._engine)
    Base.metadata.drop_all(repo._engine)
    Base.metadata.create_all(repo._engine)
    return repo


_BACKENDS = [pytest.param(_make_inmemory, id="inmemory")]
if TEST_DATABASE_URL:
    _BACKENDS.append(pytest.param(_make_postgres, id="postgres"))


@pytest.fixture(params=_BACKENDS)
def root_repo(request):
    """A root repository (InMemory or Postgres) exposing ``for_tenant()``."""
    return request.param()


@pytest.fixture()
def job_payload() -> dict:
    """Minimal valid payload for the ``job`` kind (id/dedup_key supplied per-test)."""
    return {
        "source_id": "src-1",
        "title_original": "Data Annotator",
        "company_name": "Acme Ltd",
        "status": "active",
    }


@pytest.fixture()
def candidate_payload() -> dict:
    return {"country": "US", "timezone": "UTC"}


# ---------------------------------------------------------------------------
# Illustrative tests from the task spec
# ---------------------------------------------------------------------------


def test_entity_lookup_is_isolated_between_tenants(root_repo, candidate_payload):
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("candidate", {**candidate_payload, "id": "c1"})
    beta.put("candidate", {**candidate_payload, "id": "c2", "country": "CA"})
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


# ---------------------------------------------------------------------------
# Additional coverage: list(), delete(), audits(), search_jobs(), chat scoping
# ---------------------------------------------------------------------------


def test_list_is_isolated_between_tenants(root_repo, job_payload):
    """A real gap not covered by the illustrative tests: list() must not leak."""
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("job", {**job_payload, "id": "j1", "dedup_key": "d1"})
    beta.put("job", {**job_payload, "id": "j2", "dedup_key": "d2"})
    beta.put("job", {**job_payload, "id": "j3", "dedup_key": "d3"})

    assert [j["id"] for j in acme.list("job")] == ["j1"]
    assert sorted(j["id"] for j in beta.list("job")) == ["j2", "j3"]


def test_delete_does_not_affect_other_tenants(root_repo, job_payload):
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("job", {**job_payload, "id": "j1", "dedup_key": "d1"})
    beta.put("job", {**job_payload, "id": "j2", "dedup_key": "d2"})

    beta.delete("job", "j1")  # beta must not be able to delete acme's row

    assert acme.get("job", "j1") is not None


def test_audits_are_isolated_between_tenants(root_repo):
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.audit("job.created", "job", "j1", "operator")
    beta.audit("job.created", "job", "j2", "operator")

    assert [a["entity_id"] for a in acme.audits()] == ["j1"]
    assert [a["entity_id"] for a in beta.audits()] == ["j2"]


def test_search_jobs_is_isolated_between_tenants(root_repo, job_payload):
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("job", {**job_payload, "id": "j1", "dedup_key": "d1"})
    beta.put("job", {**job_payload, "id": "j2", "dedup_key": "d2"})

    total, jobs = acme.search_jobs()

    assert total == 1
    assert [j["id"] for j in jobs] == ["j1"]


def test_chat_message_list_by_session_is_scoped_to_owning_tenant(root_repo):
    """ChatMessage has no tenant_id column; scoping must flow through the session."""
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("chat_session", {"id": "s1", "actor": "u1", "status": "active"})
    acme.put("chat_message", {"id": "m1", "session_id": "s1", "role": "user", "content": "hi"})

    assert [m["id"] for m in acme.list_by_session("s1")] == ["m1"]
    assert beta.list_by_session("s1") == []


def test_chat_message_delete_by_session_is_scoped_to_owning_tenant(root_repo):
    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("chat_session", {"id": "s1", "actor": "u1", "status": "active"})
    acme.put("chat_message", {"id": "m1", "session_id": "s1", "role": "user", "content": "hi"})

    beta.delete_by_session("s1")  # must be a no-op: s1 does not belong to beta

    assert acme.get("chat_session", "s1") is not None
    assert [m["id"] for m in acme.list_by_session("s1")] == ["m1"]

    acme.delete_by_session("s1")
    assert acme.get("chat_session", "s1") is None
    assert acme.list_by_session("s1") == []


def test_chat_message_put_is_rejected_for_a_session_owned_by_another_tenant(root_repo):
    """The write-side counterpart of the read/delete scoping above: a tenant
    must not be able to insert a chat_message into a session it does not own.
    """
    from agent_hub.core.contracts import AuthorizationError

    acme = root_repo.for_tenant("acme")
    beta = root_repo.for_tenant("beta")
    acme.put("chat_session", {"id": "s1", "actor": "u1", "status": "active"})

    with pytest.raises(AuthorizationError):
        beta.put("chat_message", {"id": "m1", "session_id": "s1", "role": "user", "content": "hi"})

    # The rejected write must not have leaked into either tenant's data.
    assert acme.list_by_session("s1") == []
    assert beta.get("chat_message", "m1") is None


def test_chat_message_put_is_rejected_for_a_nonexistent_session(root_repo):
    beta = root_repo.for_tenant("beta")

    from agent_hub.core.contracts import AuthorizationError

    with pytest.raises(AuthorizationError):
        beta.put(
            "chat_message",
            {"id": "m1", "session_id": "does-not-exist", "role": "user", "content": "hi"},
        )


# ---------------------------------------------------------------------------
# for_tenant() must never silently degrade to an unscoped repository.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_tenant_id", [None, ""])
def test_for_tenant_rejects_none_or_empty_tenant_id(root_repo, bad_tenant_id):
    """A previous bug: `for_tenant(None)` meant "unscoped" to the internal
    `_method(..., tenant_id=None)` convention on PostgresRepository, so it
    silently returned an object that read/wrote across every tenant instead
    of failing. InMemoryRepository diverged the other way (fails closed).
    Both backends must now reject invalid input the same way.
    """
    with pytest.raises(ValueError):
        root_repo.for_tenant(bad_tenant_id)


# ---------------------------------------------------------------------------
# PostgreSQL-only: cross-tenant id-collision guard on put().
#
# InMemoryRepository cannot reproduce this scenario at all: its storage is
# nested tenant -> kind -> id, so two tenants writing the same id land in
# separate buckets and never collide (see the comment in
# tests/inmemory_repo.py's _TenantInMemoryRepository.put). PostgresRepository
# uses a single global `id` primary key per kind, so a tenant-scoped put()
# must explicitly reject writes that would overwrite another tenant's row —
# this guard, and therefore this test, is Postgres-only.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")
class TestPostgresCrossTenantIdCollisionGuard:
    def setup_method(self):
        self.repo = _make_postgres()

    def test_put_is_rejected_when_candidate_id_belongs_to_another_tenant(self):
        from agent_hub.core.contracts import AuthorizationError

        acme = self.repo.for_tenant("acme")
        beta = self.repo.for_tenant("beta")
        acme.put("candidate", {"id": "c1", "country": "US", "timezone": "UTC"})

        with pytest.raises(AuthorizationError):
            beta.put("candidate", {"id": "c1", "country": "CA", "timezone": "PST"})

        # acme's row must be provably unaffected by the rejected write.
        preserved = acme.get("candidate", "c1")
        assert preserved is not None
        assert preserved["country"] == "US"
        assert preserved["timezone"] == "UTC"
        # beta must not have gained access to (or ownership of) acme's row.
        assert beta.get("candidate", "c1") is None

    def test_put_is_rejected_when_job_id_belongs_to_another_tenant(self):
        from agent_hub.core.contracts import AuthorizationError

        acme = self.repo.for_tenant("acme")
        beta = self.repo.for_tenant("beta")
        acme.put(
            "job",
            {
                "id": "j1",
                "source_id": "s1",
                "dedup_key": "acme-key",
                "title_original": "Acme Job",
                "company_name": "Acme",
                "status": "active",
            },
        )

        with pytest.raises(AuthorizationError):
            beta.put(
                "job",
                {
                    "id": "j1",
                    "source_id": "s1",
                    "dedup_key": "beta-key",
                    "title_original": "Beta Job",
                    "company_name": "Beta",
                    "status": "active",
                },
            )

        preserved = acme.get("job", "j1")
        assert preserved is not None
        assert preserved["title_original"] == "Acme Job"
        assert preserved["dedup_key"] == "acme-key"
        assert beta.get("job", "j1") is None


# ---------------------------------------------------------------------------
# PostgreSQL-only: vector search and category aggregation, which InMemory does
# not implement, but which the concrete Postgres wrapper must scope per the spec.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")
class TestPostgresVectorAndCategoryTenantIsolation:
    def setup_method(self):
        self.repo = _make_postgres()

    def _job(self, job_id: str, dedup_key: str, categories: list[str] | None = None) -> dict:
        payload = {
            "id": job_id,
            "source_id": "s1",
            "dedup_key": dedup_key,
            "title_original": "T",
            "company_name": "C",
            "status": "active",
        }
        if categories is not None:
            payload["categories"] = categories
        return payload

    def test_vector_search_is_isolated_between_tenants(self):
        acme = self.repo.for_tenant("acme")
        beta = self.repo.for_tenant("beta")
        acme.put("job", self._job("j1", "d1"))
        beta.put("job", self._job("j2", "d2"))
        vec = [0.1] * 1024
        # update_job_embeddings is a root/worker-level operation, not tenant-scoped.
        self.repo.update_job_embeddings({"j1": vec, "j2": vec})

        hits = acme.search_jobs_by_embedding(vec, limit=10)

        assert [job["id"] for job, _sim in hits] == ["j1"]

    def test_list_job_categories_is_isolated_between_tenants(self):
        acme = self.repo.for_tenant("acme")
        beta = self.repo.for_tenant("beta")
        acme.put("job", self._job("j1", "d1", categories=["Dev"]))
        beta.put("job", self._job("j2", "d2", categories=["Sales"]))

        cats = acme.list_job_categories()

        assert cats == [{"name": "Dev", "count": 1}]
