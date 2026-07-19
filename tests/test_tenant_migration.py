from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


TENANT_TABLES = (
    "job_sources",
    "jobs",
    "candidates",
    "matches",
    "approvals",
    "notifications",
    "feedback",
    "audit_logs",
    "idempotency_records",
    "workflow_runs",
    "chat_sessions",
)
MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260719_0007_tenant_security_workflow_commands.py"
)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _load_migration() -> ModuleType:
    assert MIGRATION_PATH.exists(), f"missing migration: {MIGRATION_PATH.name}"
    spec = importlib.util.spec_from_file_location("tenant_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOp:
    def __init__(self, duplicate_query: str | None = None) -> None:
        self.calls: list[tuple] = []
        self.events: list[tuple] = []
        self.duplicate_query = duplicate_query
        self.queries: list[str] = []

    def _record_call(self, call: tuple) -> None:
        self.calls.append(call)
        self.events.append(call)

    def add_column(self, table_name, column):
        self._record_call(("add_column", table_name, column))

    def execute(self, statement):
        self._record_call(("execute", str(statement)))

    def drop_constraint(self, name, table_name, type_):
        self._record_call(("drop_constraint", name, table_name, type_))

    def create_unique_constraint(self, name, table_name, columns):
        self._record_call(("create_unique_constraint", name, table_name, tuple(columns)))

    def alter_column(self, table_name, column_name, **kwargs):
        self._record_call(("alter_column", table_name, column_name, kwargs))

    def create_table(self, table_name, *columns, **kwargs):
        self._record_call(("create_table", table_name, columns, kwargs))

    def drop_table(self, table_name):
        self._record_call(("drop_table", table_name))

    def drop_column(self, table_name, column_name):
        self._record_call(("drop_column", table_name, column_name))

    def get_bind(self):
        return self

    def first(self):
        query = self.queries[-1]
        return ("duplicate",) if query == self.duplicate_query else None


class _RecordingBind:
    def __init__(self, recorder: _RecordingOp) -> None:
        self.recorder = recorder

    def execute(self, statement):
        query = str(statement)
        self.recorder.queries.append(query)
        self.recorder.events.append(("guard", query))
        return self.recorder


def test_upgrade_backfills_before_enforcing_non_null(monkeypatch):
    migration = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()

    for table_name in TENANT_TABLES:
        add_index = next(
            index
            for index, call in enumerate(recorder.calls)
            if call[0] == "add_column" and call[1] == table_name and call[2].name == "tenant_id"
        )
        assert recorder.calls[add_index][2].nullable is True
        update_sql = f"UPDATE {table_name} SET tenant_id = 'default' WHERE tenant_id IS NULL"
        update_indices = [
            index for index, call in enumerate(recorder.calls) if call == ("execute", update_sql)
        ]
        assert len(update_indices) == 1
        alter_index = next(
            index
            for index, call in enumerate(recorder.calls)
            if call[0] == "alter_column"
            and call[1:3] == (table_name, "tenant_id")
            and call[3].get("nullable") is False
        )
        assert add_index < update_indices[0] < alter_index

    owner_update = (
        "UPDATE candidates SET owner_actor_id = 'legacy-owner' WHERE owner_actor_id IS NULL"
    )
    assert ("execute", owner_update) in recorder.calls
    workflow_non_null = next(
        index
        for index, call in enumerate(recorder.calls)
        if call[0] == "alter_column"
        and call[1:3] == ("workflow_runs", "tenant_id")
        and call[3].get("nullable") is False
    )
    command_table = next(
        index
        for index, call in enumerate(recorder.calls)
        if call[0:2] == ("create_table", "workflow_commands")
    )
    assert workflow_non_null < command_table


def test_downgrade_restores_global_schema_after_all_guards(monkeypatch):
    migration = _load_migration()
    recorder = _RecordingOp()
    recorder.get_bind = lambda: _RecordingBind(recorder)
    monkeypatch.setattr(migration, "op", recorder)

    migration.downgrade()

    guard_events = [("guard", query) for _, query in migration.DOWNGRADE_DUPLICATE_QUERIES]
    expected_ddl = [
        ("drop_table", "workflow_command_payloads"),
        ("drop_table", "workflow_commands"),
        ("drop_constraint", "uq_jobs_tenant_dedup_key", "jobs", "unique"),
        ("create_unique_constraint", "uq_jobs_dedup_key", "jobs", ("dedup_key",)),
        ("drop_constraint", "uq_matches_tenant_candidate_job", "matches", "unique"),
        (
            "create_unique_constraint",
            "uq_matches_candidate_job",
            "matches",
            ("candidate_id", "job_id"),
        ),
        (
            "drop_constraint",
            "uq_idempotency_tenant_action_key",
            "idempotency_records",
            "unique",
        ),
        (
            "create_unique_constraint",
            "uq_idempotency_records_action_key",
            "idempotency_records",
            ("action", "key"),
        ),
        ("drop_column", "candidates", "owner_actor_id"),
        *(("drop_column", table_name, "tenant_id") for table_name in reversed(TENANT_TABLES)),
    ]
    assert recorder.queries == [query for _, query in migration.DOWNGRADE_DUPLICATE_QUERIES]
    assert recorder.calls == expected_ddl
    assert recorder.events == guard_events + expected_ddl


@pytest.mark.parametrize("guard_index", range(3))
def test_downgrade_refuses_each_cross_tenant_duplicate_before_ddl(monkeypatch, guard_index):
    migration = _load_migration()
    duplicate_query = migration.DOWNGRADE_DUPLICATE_QUERIES[guard_index][1]
    recorder = _RecordingOp(duplicate_query=duplicate_query)
    recorder.get_bind = lambda: _RecordingBind(recorder)
    monkeypatch.setattr(migration, "op", recorder)

    with pytest.raises(RuntimeError, match="cross-tenant duplicates"):
        migration.downgrade()

    assert recorder.queries == [
        query for _, query in migration.DOWNGRADE_DUPLICATE_QUERIES[: guard_index + 1]
    ]
    assert recorder.calls == []


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")
def test_postgresql_upgrade_backfills_and_downgrades():
    assert TEST_DATABASE_URL is not None
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    engine = create_engine(TEST_DATABASE_URL)
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "20260718_0006")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candidates "
                    "(id, country, timezone, consent_status, payload) "
                    "VALUES ('legacy-candidate', 'US', 'UTC', 'not_requested', '{}'::jsonb)"
                )
            )

        command.upgrade(config, "20260719_0007")
        upgraded = inspect(engine)
        for table_name in TENANT_TABLES:
            tenant_column = next(
                column
                for column in upgraded.get_columns(table_name)
                if column["name"] == "tenant_id"
            )
            assert tenant_column["nullable"] is False
        assert {"workflow_commands", "workflow_command_payloads"}.issubset(
            upgraded.get_table_names()
        )
        upgraded_constraints = {
            table_name: {
                item["name"]: tuple(item["column_names"])
                for item in upgraded.get_unique_constraints(table_name)
            }
            for table_name in ("jobs", "matches", "idempotency_records")
        }
        assert upgraded_constraints == {
            "jobs": {"uq_jobs_tenant_dedup_key": ("tenant_id", "dedup_key")},
            "matches": {
                "uq_matches_tenant_candidate_job": (
                    "tenant_id",
                    "candidate_id",
                    "job_id",
                )
            },
            "idempotency_records": {
                "uq_idempotency_tenant_action_key": ("tenant_id", "action", "key")
            },
        }
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT tenant_id, owner_actor_id FROM candidates WHERE id = 'legacy-candidate'"
                )
            ).one()
        assert row == ("default", "legacy-owner")

        command.downgrade(config, "20260718_0006")
        downgraded = inspect(engine)
        assert "workflow_commands" not in downgraded.get_table_names()
        assert "workflow_command_payloads" not in downgraded.get_table_names()
        assert "tenant_id" not in {column["name"] for column in downgraded.get_columns("jobs")}
        assert "owner_actor_id" not in {
            column["name"] for column in downgraded.get_columns("candidates")
        }
        downgraded_constraints = {
            table_name: {
                item["name"]: tuple(item["column_names"])
                for item in downgraded.get_unique_constraints(table_name)
            }
            for table_name in ("jobs", "matches", "idempotency_records")
        }
        assert downgraded_constraints == {
            "jobs": {"uq_jobs_dedup_key": ("dedup_key",)},
            "matches": {"uq_matches_candidate_job": ("candidate_id", "job_id")},
            "idempotency_records": {"uq_idempotency_records_action_key": ("action", "key")},
        }
    finally:
        command.upgrade(config, "head")
        engine.dispose()
