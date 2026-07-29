# PostgreSQL Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Phase 0 and Phase 1 of the global part-time plan: freeze existing behavior, add a PostgreSQL 16 data model and Alembic migration, implement a transaction-safe PostgreSQL repository, and make PostgreSQL selectable without breaking SQLite tests.

**Architecture:** Keep the application-facing repository contract (`put`, `get`, `list`, `delete`, `audit`, `audits`, `idempotent`) stable. SQLite remains the lightweight test/local fallback; a SQLAlchemy-backed `PostgresRepository` maps each current entity kind to a dedicated table with typed constraint columns plus a JSONB payload for backward-compatible response shapes. PostgreSQL idempotent operations reuse one SQLAlchemy session through a context variable so the business writes and idempotency record commit atomically.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x, Alembic, psycopg 3, PostgreSQL 16, Docker Compose, unittest, ruff.

## Global Constraints

- Existing REST and platform API response shapes remain backward compatible.
- Hard filtering, risk decisions, scoring, approval, and notification policy remain deterministic application code.
- `RepositoryProtocol` exposes `put`, `get`, `list`, `delete`, `audit`, `audits`, and `idempotent` with the current dictionary-based signatures.
- SQLite remains available through `DATABASE_PATH`; PostgreSQL is selected only when `DATABASE_URL` is set.
- PostgreSQL uses dedicated domain tables rather than a generic `entities` table.
- `audit_logs` is append-only through the repository API.
- `idempotency_records` has a unique `(action, key)` constraint and the first successful result is returned to all retries.
- A PostgreSQL idempotent operation and all repository writes it performs share one transaction.
- Jobs are unique by `dedup_key`; source inputs are constrained by source job ID, canonical URL, and content fingerprint; matches are unique by `(candidate_id, job_id)`.
- Automated unit tests never require PostgreSQL or external network access; PostgreSQL integration tests use `TEST_DATABASE_URL` and skip when it is absent.
- The existing `data/agent.db` is never deleted or modified by PostgreSQL setup or migrations.

---

### Task 1: Freeze Repository and API Contracts

**Files:**
- Create: `tests/factories.py`
- Create: `tests/test_repository_contract.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_service.py`
- Create: `docs/adr/0001-postgresql-primary-database.md`
- Create: `docs/adr/0002-celery-redis-workflows.md`
- Create: `docs/adr/0003-provider-boundaries.md`
- Create: `docs/adr/0004-sqlite-data-migration.md`

**Interfaces:**
- Produces reusable `source_payload()`, `job_payload()`, and `candidate_payload()` factories.
- Freezes the existing dictionary Repository behavior and API status/body contracts.
- Records that SQLite remains a fallback and existing local data is not automatically migrated.

- [ ] Move repeated valid source, job, and candidate dictionaries into `tests/factories.py`, returning fresh dictionaries on every call.
- [ ] Add a repository contract test mixin covering round-trip CRUD, reverse-created ordering, append-only audit reads, failed idempotent results remaining retryable, and same-key idempotency. Atomic rollback of writes inside an idempotent callback is PostgreSQL-only behavior covered in Task 4.
- [ ] Run `.venv/bin/python -m unittest tests.test_repository_contract -v`; verify the new test fails before wiring the SQLite repository fixture.
- [ ] Wire the existing SQLite `Repository(':memory:')` into the contract suite and make it pass without changing production behavior.
- [ ] Extend API tests to assert the exact health response, write-header validation, stable replay response, platform envelope, 404 detail shape, and 409 policy conflict shape.
- [ ] Extend service tests for medium-risk review approval, final notification eligibility recheck, and duplicate match stability.
- [ ] Write four ADRs covering PostgreSQL, later Celery/Redis use, LLM/Embedding/notification provider boundaries, and the no-automatic-SQLite-migration decision.
- [ ] Run `.venv/bin/python -m unittest discover -s tests -v` and confirm all baseline and new tests pass.
- [ ] Commit with `test: freeze repository and API contracts`.

### Task 2: Add SQLAlchemy Models and Alembic Migration

**Files:**
- Modify: `pyproject.toml`
- Create: `agent_hub/database/__init__.py`
- Create: `agent_hub/database/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/20260717_0001_postgresql_foundation.py`
- Create: `tests/test_database_models.py`

**Interfaces:**
- Produces `Base.metadata` and model classes for all Phase 1 tables.
- The migration consumes `DATABASE_URL` and upgrades an empty PostgreSQL database to revision `20260717_0001`.

- [ ] Add runtime dependencies `sqlalchemy>=2.0,<3`, `alembic>=1.16,<2`, and `psycopg[binary]>=3.2,<4`.
- [ ] Write failing metadata tests asserting these table names exist: `job_sources`, `source_sync_runs`, `raw_jobs`, `jobs`, `job_versions`, `candidates`, `candidate_experiences`, `candidate_skills`, `skills`, `skill_aliases`, `skill_relations`, `job_skills`, `matches`, `match_evidence`, `match_score_items`, `workflow_runs`, `workflow_steps`, `approvals`, `notifications`, `feedback`, `audit_logs`, and `idempotency_records`.
- [ ] Run `.venv/bin/python -m unittest tests.test_database_models -v`; verify failure because the database package does not exist.
- [ ] Implement SQLAlchemy 2 declarative models with timezone-aware timestamps, JSONB payloads, explicit foreign keys, and indexes. Current aggregate tables expose typed constraint columns while retaining the complete payload.
- [ ] Assert metadata contains unique constraints for raw source identity fields, job `dedup_key`, match candidate/job, notification provider message ID, and idempotency action/key.
- [ ] Implement the initial Alembic revision from the same model design; do not create a generic `entities` table.
- [ ] Run `.venv/bin/python -m unittest tests.test_database_models -v` and `alembic check`; confirm model tests pass and no schema diff is reported when `DATABASE_URL` points to an upgraded database.
- [ ] Commit with `feat: add PostgreSQL schema and migration`.

### Task 3: Extract the Repository Protocol and Implement PostgreSQL CRUD/Audit

**Files:**
- Modify: `agent_hub/agents/global_part_time/repository.py`
- Create: `agent_hub/database/repository.py`
- Modify: `agent_hub/agents/global_part_time/service.py`
- Modify: `agent_hub/agents/global_part_time/agent.py`
- Modify: `agent_hub/agents/global_part_time/http_api.py`
- Modify: `agent_hub/app.py`
- Create: `tests/test_postgres_repository.py`

**Interfaces:**
- Produces runtime-checkable `RepositoryProtocol` with the existing method signatures.
- Produces `PostgresRepository(database_url: str)` implementing that protocol.
- Current entity mappings are `source -> job_sources`, `job -> jobs`, `candidate -> candidates`, `match -> matches`, `approval -> approvals`, `notification -> notifications`, and `feedback -> feedback`.

- [ ] Define `RepositoryProtocol` and rename the concrete SQLite implementation to `SQLiteRepository`, retaining `Repository = SQLiteRepository` as a compatibility alias.
- [ ] Change service, agent, API dependency, and app type annotations to `RepositoryProtocol`; no route or service behavior changes.
- [ ] Add PostgreSQL integration contract tests by reusing the Task 1 mixin when `TEST_DATABASE_URL` is present.
- [ ] Run `TEST_DATABASE_URL=... .venv/bin/python -m unittest tests.test_postgres_repository -v`; verify failure because `PostgresRepository` is missing.
- [ ] Implement SQLAlchemy session management and entity-kind/model mapping. `put` must preserve payload `created_at`, refresh `updated_at`, and return the persisted payload; `get` and `list` return the same shapes as SQLite.
- [ ] Populate typed columns from payloads for constraints and foreign keys. For job and match natural-key conflicts, use a savepoint and return the already persisted record instead of creating another row.
- [ ] Implement append-only `audit` and bounded reverse-order `audits` reads.
- [ ] Update `sync_source` and `run_matches` to use the dictionary returned by `repo.put`, so concurrent natural-key resolution propagates the stable persisted ID.
- [ ] Run SQLite unit tests plus PostgreSQL repository contract tests and confirm both implementations satisfy the same contract.
- [ ] Commit with `feat: implement PostgreSQL repository`.

### Task 4: Make PostgreSQL Idempotency Transactional and Concurrency-Safe

**Files:**
- Modify: `agent_hub/database/repository.py`
- Modify: `tests/test_postgres_repository.py`
- Create: `tests/test_postgres_concurrency.py`

**Interfaces:**
- `PostgresRepository.idempotent(action, key, operation)` returns the first committed JSON result.
- Repository methods called inside `operation` reuse the active SQLAlchemy session and transaction.

- [ ] Add a failing integration test with two threads and two repository instances invoking the same action/key; assert one business entity, one idempotency row, identical responses, and one operation execution.
- [ ] Add a failing test where the operation writes an entity then raises; assert neither entity nor idempotency record persists.
- [ ] Run `TEST_DATABASE_URL=... .venv/bin/python -m unittest tests.test_postgres_concurrency -v` and verify both tests fail for the expected missing transaction behavior.
- [ ] Add a context variable for the active session. Every repository method uses it when present and opens its own transaction only when absent.
- [ ] In `idempotent`, begin a transaction, check the existing row, acquire a transaction-scoped PostgreSQL advisory lock derived from SHA-256 of `(action, key)`, recheck, run the operation in the active session, insert the response, and commit once.
- [ ] Ensure exceptions roll back both domain writes and the idempotency record and reset the context variable in `finally`.
- [ ] Run the concurrency tests repeatedly and confirm stable results with no duplicate rows or leaked sessions.
- [ ] Commit with `feat: add transactional PostgreSQL idempotency`.

### Task 5: Select the Repository at the Composition Root

**Files:**
- Create: `agent_hub/database/config.py`
- Modify: `agent_hub/app.py`
- Modify: `tests/test_api.py`
- Create: `tests/test_database_config.py`
- Create: `tests/test_postgres_workflow.py`

**Interfaces:**
- Produces `create_repository(database_url: str | None = None, sqlite_path: str | None = None) -> RepositoryProtocol`.
- Selection order: explicit `database_url`, `DATABASE_URL`, then explicit `sqlite_path`, then `DATABASE_PATH`, then `./data/agent.db`.

- [ ] Write failing configuration tests for explicit PostgreSQL URL, environment PostgreSQL URL, and SQLite fallback selection.
- [ ] Implement `create_repository` and update `create_app` to call it only when no repository was injected.
- [ ] Preserve direct repository injection used by all current API tests.
- [ ] Add a PostgreSQL full-workflow integration test covering source creation/review, job sync, candidate consent, matching, notification preview/review/send, audit, and idempotent replay.
- [ ] Run `.venv/bin/python -m unittest tests.test_database_config tests.test_api -v` and the PostgreSQL workflow test.
- [ ] Run the entire unit suite without `DATABASE_URL`; confirm it never attempts a PostgreSQL connection.
- [ ] Commit with `feat: configure PostgreSQL application storage`.

### Task 6: Add Local PostgreSQL/Redis Development and Verification

**Files:**
- Create: `compose.dev.yaml`
- Create: `.env.example`
- Modify: `docs/dev-guide.md`
- Modify: `README.md`
- Modify: `Makefile`

**Interfaces:**
- PostgreSQL listens on `127.0.0.1:5432`, Redis on `127.0.0.1:6379` for local development.
- Default development database URL is `postgresql+psycopg://agent_hub:agent_hub@127.0.0.1:5432/agent_hub`.

- [ ] Add Compose services using `postgres:16` and `redis:7`, health checks, named volumes, and loopback-only published ports.
- [ ] Add `.env.example` entries for `DATABASE_URL`, `TEST_DATABASE_URL`, `DATABASE_PATH`, and `PUBLIC_BASE_URL` without secrets used outside local development.
- [ ] Add Make targets for starting infrastructure, applying migrations, running unit tests, running PostgreSQL integration tests, and stopping infrastructure without deleting volumes.
- [ ] Document SQLite fallback, PostgreSQL setup, Alembic commands, test commands, and the explicit decision not to auto-migrate the existing SQLite file.
- [ ] Start the services, wait for health, run `alembic upgrade head`, run all unit and PostgreSQL integration tests, run `ruff check src/ tests/`, and run `ruff format --check src/ tests/`.
- [ ] Run `alembic downgrade base` followed by `alembic upgrade head` on the test database to prove empty-database rebuildability.
- [ ] Commit with `docs: add PostgreSQL development workflow`.
