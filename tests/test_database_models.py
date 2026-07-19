import unittest

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from agent_hub.database.models import Base


EXPECTED_TABLES = {
    "job_sources",
    "source_sync_runs",
    "raw_jobs",
    "jobs",
    "job_versions",
    "candidates",
    "candidate_experiences",
    "candidate_skills",
    "skills",
    "skill_aliases",
    "skill_relations",
    "job_skills",
    "matches",
    "match_evidence",
    "match_score_items",
    "workflow_runs",
    "workflow_steps",
    "approvals",
    "notifications",
    "feedback",
    "audit_logs",
    "idempotency_records",
    "chat_sessions",
    "chat_messages",
    "workflow_commands",
    "workflow_command_payloads",
}

TENANT_TABLES = {
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
}


class DatabaseModelTest(unittest.TestCase):
    def test_phase_one_tables_are_declared_without_generic_entities(self):
        self.assertEqual(set(Base.metadata.tables), EXPECTED_TABLES)
        self.assertNotIn("entities", Base.metadata.tables)

    def test_natural_keys_have_database_unique_constraints(self):
        expected = {
            "raw_jobs": {
                ("source_id", "source_job_id"),
                ("canonical_url",),
                ("content_fingerprint",),
            },
            "jobs": {("tenant_id", "dedup_key")},
            "matches": {("tenant_id", "candidate_id", "job_id")},
            "notifications": {("provider_message_id",)},
            "idempotency_records": {("tenant_id", "action", "key")},
            "workflow_commands": {("tenant_id", "action", "idempotency_key")},
        }
        for table_name, required in expected.items():
            table = Base.metadata.tables[table_name]
            actual = {
                tuple(column.name for column in constraint.columns)
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            }
            self.assertTrue(
                required.issubset(actual),
                f"{table_name} missing unique constraints: {required - actual}",
            )

    def test_relationship_tables_have_explicit_foreign_keys(self):
        expected = {
            "source_sync_runs": {"source_id"},
            "raw_jobs": {"source_id"},
            "job_versions": {"job_id"},
            "candidate_experiences": {"candidate_id"},
            "candidate_skills": {"candidate_id", "skill_id"},
            "skill_aliases": {"skill_id"},
            "skill_relations": {"from_skill_id", "to_skill_id"},
            "job_skills": {"job_id", "skill_id"},
            "matches": {"candidate_id", "job_id"},
            "match_evidence": {"match_id"},
            "match_score_items": {"match_id"},
            "workflow_steps": {"workflow_run_id"},
            "notifications": {"candidate_id"},
            "feedback": {"match_id", "candidate_id"},
        }
        for table_name, required_columns in expected.items():
            table = Base.metadata.tables[table_name]
            actual_columns = {fk.parent.name for fk in table.foreign_keys}
            self.assertTrue(
                required_columns.issubset(actual_columns),
                f"{table_name} missing foreign keys: {required_columns - actual_columns}",
            )

    def test_tenant_columns_and_command_tables(self):
        for name in TENANT_TABLES:
            self.assertIn("tenant_id", Base.metadata.tables[name].c)
            self.assertFalse(Base.metadata.tables[name].c.tenant_id.nullable)
        self.assertIn("owner_actor_id", Base.metadata.tables["candidates"].c)
        self.assertIn("workflow_commands", Base.metadata.tables)
        self.assertIn("workflow_command_payloads", Base.metadata.tables)

    def test_workflow_command_schema_is_complete(self):
        table = Base.metadata.tables["workflow_commands"]
        expected = {
            "id": (String, 36, False),
            "tenant_id": (String, 100, False),
            "action": (String, 100, False),
            "idempotency_key": (String, 255, False),
            "request_hash": (String, 64, False),
            "workflow_run_id": (String, 36, False),
            "celery_task_id": (String, 255, True),
            "status": (String, 20, False),
            "last_error": (Text, None, True),
            "created_at": (DateTime, None, False),
            "updated_at": (DateTime, None, False),
        }
        self.assertEqual(set(table.c), {table.c[name] for name in expected})
        for name, (type_class, length, nullable) in expected.items():
            column = table.c[name]
            self.assertIsInstance(column.type, type_class)
            self.assertEqual(getattr(column.type, "length", None), length)
            self.assertEqual(column.nullable, nullable)
        self.assertTrue(table.c.created_at.type.timezone)
        self.assertTrue(table.c.updated_at.type.timezone)
        self.assertEqual(tuple(column.name for column in table.primary_key.columns), ("id",))
        self.assertEqual(
            {foreign_key.target_fullname for foreign_key in table.c.workflow_run_id.foreign_keys},
            {"workflow_runs.id"},
        )
        constraint = next(
            item
            for item in table.constraints
            if isinstance(item, UniqueConstraint) and item.name == "uq_workflow_commands_request"
        )
        self.assertEqual(
            tuple(column.name for column in constraint.columns),
            ("tenant_id", "action", "idempotency_key"),
        )

    def test_workflow_command_payload_schema_is_complete(self):
        table = Base.metadata.tables["workflow_command_payloads"]
        self.assertEqual(
            set(table.c),
            {table.c[name] for name in ("command_id", "tenant_id", "payload", "expires_at")},
        )
        self.assertIsInstance(table.c.command_id.type, String)
        self.assertEqual(table.c.command_id.type.length, 36)
        self.assertFalse(table.c.command_id.nullable)
        self.assertEqual(
            tuple(column.name for column in table.primary_key.columns), ("command_id",)
        )
        self.assertEqual(
            {foreign_key.target_fullname for foreign_key in table.c.command_id.foreign_keys},
            {"workflow_commands.id"},
        )
        self.assertIsInstance(table.c.tenant_id.type, String)
        self.assertEqual(table.c.tenant_id.type.length, 100)
        self.assertFalse(table.c.tenant_id.nullable)
        self.assertIsInstance(table.c.payload.type, JSONB)
        self.assertFalse(table.c.payload.nullable)
        self.assertIsInstance(table.c.expires_at.type, DateTime)
        self.assertTrue(table.c.expires_at.type.timezone)
        self.assertFalse(table.c.expires_at.nullable)


if __name__ == "__main__":
    unittest.main()
