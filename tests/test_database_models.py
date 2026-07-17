import unittest

from sqlalchemy import UniqueConstraint

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
            "jobs": {("dedup_key",)},
            "matches": {("candidate_id", "job_id")},
            "notifications": {("provider_message_id",)},
            "idempotency_records": {("action", "key")},
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


if __name__ == "__main__":
    unittest.main()
