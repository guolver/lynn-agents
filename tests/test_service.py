import unittest
from unittest.mock import patch

from tests.inmemory_repo import InMemoryRepository as Repository
from agent_hub.agents.global_part_time.service import AgentService, PolicyError
from tests.factories import candidate_payload, job_payload, source_payload


class ServiceWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")
        self.service = AgentService(self.repo)
        self.source = self.service.create_source(source_payload(), "operator@example.com")
        self.job = job_payload()

    def candidate(self):
        candidate = self.service.create_candidate(candidate_payload(), "candidate")
        return self.service.set_consent(candidate["id"], True, "candidate", "mvp-1")

    def test_unapproved_source_cannot_sync(self):
        with self.assertRaises(PolicyError):
            self.service.sync_source(self.source["id"], [self.job], "worker")

    def test_end_to_end_approval_match_and_delivery(self):
        self.service.review_source(self.source["id"], True, "operator")
        result = self.service.sync_source(self.source["id"], [self.job], "worker")
        self.assertEqual(result["imported"], 1)
        candidate = self.candidate()
        matches = self.service.run_matches(candidate["id"], "scheduler")
        self.assertEqual(len(matches["matches"]), 1)

        draft = self.service.preview_digest(
            candidate["id"], [matches["matches"][0]["id"]], "scheduler", "https://app.example.com"
        )
        with self.assertRaises(PolicyError):
            self.service.send_notification(draft["id"], "scheduler")
        self.service.review_notification(draft["id"], True, "operator")
        sent = self.service.send_notification(draft["id"], "scheduler")
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(sent["provider"], "simulation")

        # Sent jobs cannot be recommended again unless a future versioning policy permits it.
        after_send = self.service.run_matches(candidate["id"], "scheduler")
        self.assertEqual(after_send["matches"], [])
        self.assertIn("already_sent", after_send["filtered"][0]["reasons"])

    def test_cross_source_duplicate_merges_provenance(self):
        self.service.review_source(self.source["id"], True, "operator")
        first = self.service.sync_source(self.source["id"], [self.job], "worker")
        second_source = self.service.create_source(
            {
                "name": "ATS",
                "source_type": "ats",
                "base_url": "https://ats.example.org",
                "authorization_basis": "public API terms",
                "allowed_paths": ["/v1/jobs"],
                "prohibited_actions": [],
                "rate_limit": "30/hour",
                "retention_policy": "14 days",
            },
            "operator",
        )
        self.service.review_source(second_source["id"], True, "operator")
        mirrored = dict(
            self.job, source_job_id="ats-99", canonical_url="https://ats.example.org/jobs/99"
        )
        second = self.service.sync_source(second_source["id"], [mirrored], "worker")
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(first["job_ids"][0], second["job_ids"][0])
        self.assertEqual(len(self.repo.list("job")), 1)

    def test_high_risk_job_is_not_stored(self):
        self.service.review_source(self.source["id"], True, "operator")
        risky = dict(
            self.job, source_job_id="scam", description_original="先付款充值，再提供验证码开始刷单"
        )
        result = self.service.sync_source(self.source["id"], [risky], "worker")
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(self.repo.list("job"), [])

    def test_medium_risk_job_requires_and_accepts_review_approval(self):
        self.service.review_source(self.source["id"], True, "operator")
        medium_risk = dict(
            self.job,
            source_job_id="review-1",
            description_original="Review AI data; contractors must buy equipment.",
        )

        result = self.service.sync_source(self.source["id"], [medium_risk], "worker")
        job = self.repo.get("job", result["job_ids"][0])
        self.assertEqual(result["pending_review"], 1)
        self.assertEqual(job["risk_level"], "medium")
        self.assertEqual(job["status"], "pending_review")
        self.assertEqual(job["review_status"], "pending")

        candidate = self.candidate()
        before_review = self.service.run_matches(candidate["id"], "scheduler")
        self.assertIn("risk_not_approved", before_review["filtered"][0]["reasons"])

        approved = self.service.review_job(job["id"], True, "operator", "verified")
        after_review = self.service.run_matches(candidate["id"], "scheduler")
        self.assertEqual(approved["status"], "active")
        self.assertEqual(approved["review_status"], "approved")
        self.assertEqual(len(after_review["matches"]), 1)

    def test_send_rechecks_final_job_eligibility(self):
        self.service.review_source(self.source["id"], True, "operator")
        result = self.service.sync_source(self.source["id"], [self.job], "worker")
        candidate = self.candidate()
        match = self.service.run_matches(candidate["id"], "scheduler")["matches"][0]
        draft = self.service.preview_digest(
            candidate["id"], [match["id"]], "scheduler", "https://app.example.com"
        )
        self.service.review_notification(draft["id"], True, "operator")
        self.service.review_job(result["job_ids"][0], False, "operator", "expired")

        with self.assertRaisesRegex(PolicyError, "failed final eligibility check"):
            self.service.send_notification(draft["id"], "scheduler")
        self.assertEqual(self.repo.get("notification", draft["id"])["status"], "approved")

    def test_duplicate_match_run_keeps_stable_identity(self):
        self.service.review_source(self.source["id"], True, "operator")
        self.service.sync_source(self.source["id"], [self.job], "worker")
        candidate = self.candidate()

        first = self.service.run_matches(candidate["id"], "scheduler")["matches"][0]
        second = self.service.run_matches(candidate["id"], "scheduler")["matches"][0]

        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(self.repo.list("match")), 1)

    def test_match_run_falls_back_when_skill_graph_expansion_fails(self):
        self.service.review_source(self.source["id"], True, "operator")
        self.service.sync_source(self.source["id"], [self.job], "worker")
        candidate = self.candidate()

        def unavailable_graph(_names):
            raise RuntimeError("neo4j unavailable")

        self.service.expand_fn = unavailable_graph
        with self.assertLogs("agent_hub.agents.global_part_time.service", level="WARNING") as logs:
            result = self.service.run_matches(candidate["id"], "scheduler")

        self.assertEqual(result["matches"][0]["score_breakdown"]["skills"], 1.0)
        self.assertTrue(any("neo4j unavailable" in message for message in logs.output))

    def test_partial_skill_expansion_failure_discards_graph_scores(self):
        self.service.review_source(self.source["id"], True, "operator")
        graph_job = dict(self.job, skills=["前端开发", "后端开发"])
        self.service.sync_source(self.source["id"], [graph_job], "worker")
        candidate = self.candidate()
        candidate["skills"] = [{"name": "React"}]
        self.repo.put("candidate", candidate)
        calls = 0

        def partially_available_graph(_names):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("graph failed mid-score")
            return {"React", "前端开发"}

        self.service.expand_fn = partially_available_graph
        with self.assertLogs("agent_hub.agents.global_part_time.service", level="WARNING"):
            result = self.service.run_matches(candidate["id"], "scheduler")

        self.assertEqual(result["matches"][0]["score_breakdown"]["skills"], 0.0)

    def test_batch_discards_all_graph_scores_when_later_job_expansion_fails(self):
        for reverse_order in (False, True):
            with self.subTest(reverse_order=reverse_order):
                repo = Repository(":memory:")
                service = AgentService(repo)
                source = service.create_source(source_payload(), "operator")
                service.review_source(source["id"], True, "operator")
                jobs = [
                    dict(
                        job_payload(),
                        source_job_id="frontend-job",
                        canonical_url="https://feed.example.com/jobs/frontend",
                        title_original="Frontend Specialist",
                        skills=["前端开发"],
                    ),
                    dict(
                        job_payload(),
                        source_job_id="backend-job",
                        canonical_url="https://feed.example.com/jobs/backend",
                        title_original="Backend Specialist",
                        skills=["后端开发"],
                    ),
                ]
                imported = service.sync_source(source["id"], jobs, "worker")
                candidate = service.create_candidate(candidate_payload(), "candidate")
                candidate["skills"] = [{"name": "React"}]
                repo.put("candidate", candidate)
                candidate = service.set_consent(candidate["id"], True, "candidate", "mvp-1")
                ordered_ids = list(imported["job_ids"])
                if reverse_order:
                    ordered_ids.reverse()
                jobs_by_id = {job["id"]: job for job in repo.list("job")}
                original_list = repo.list

                def list_in_order(kind):
                    if kind == "job":
                        return [jobs_by_id[job_id] for job_id in ordered_ids]
                    return original_list(kind)

                calls = 0

                def graph_fails_on_second_job(_names):
                    nonlocal calls
                    calls += 1
                    if calls == 3:
                        raise RuntimeError("graph failed on second job")
                    return {"React", "前端开发", "后端开发"}

                service.expand_fn = graph_fails_on_second_job
                with (
                    patch.object(repo, "list", side_effect=list_in_order),
                    self.assertLogs("agent_hub.agents.global_part_time.service", level="WARNING"),
                ):
                    result = service.run_matches(candidate["id"], "scheduler")

                self.assertEqual(
                    [match["score_breakdown"]["skills"] for match in result["matches"]],
                    [0.0, 0.0],
                )
                self.assertEqual(
                    [match["score_breakdown"]["skills"] for match in repo.list("match")],
                    [0.0, 0.0],
                )

    def test_match_run_does_not_mask_scoring_failures(self):
        self.service.review_source(self.source["id"], True, "operator")
        self.service.sync_source(self.source["id"], [self.job], "worker")
        candidate = self.candidate()

        with patch(
            "agent_hub.agents.global_part_time.service.score_match",
            side_effect=RuntimeError("scoring bug"),
        ):
            with self.assertRaisesRegex(RuntimeError, "scoring bug"):
                self.service.run_matches(candidate["id"], "scheduler")

    def test_unsubscribe_is_immediate_and_deletion_removes_personal_data(self):
        candidate = self.candidate()
        opted_out = self.service.set_consent(candidate["id"], False, "candidate", "unsubscribe")
        self.assertEqual(opted_out["consent_status"], "opted_out")
        with self.assertRaises(PolicyError):
            self.service.preview_digest(candidate["id"], [], "scheduler", "https://app.example.com")
        result = self.service.delete_candidate(candidate["id"], "candidate")
        self.assertTrue(result["deleted"])
        self.assertIsNone(self.repo.get("candidate", candidate["id"]))
        self.assertTrue(any(x["event"] == "candidate.deleted" for x in self.repo.audits()))

    def test_idempotency_returns_original_result(self):
        operation_calls = []

        def operation():
            operation_calls.append(True)
            return {"id": "stable"}

        first = self.repo.idempotent("create", "abcdefgh", operation)
        second = self.repo.idempotent("create", "abcdefgh", operation)
        self.assertEqual(first, second)
        self.assertEqual(len(operation_calls), 1)


class FakeVectorRepo(Repository):
    """SQLite 仓储 + 假 pgvector 检索接口，用于验证召回路径。"""

    def __init__(self):
        super().__init__(":memory:")
        self.search_calls = []
        self.hits = []

    def search_jobs_by_embedding(self, vec, limit=200):
        self.search_calls.append((vec, limit))
        return self.hits


class VectorRecallTest(unittest.TestCase):
    def setUp(self):
        self.repo = FakeVectorRepo()
        self.service = AgentService(self.repo, embed_fn=lambda text: [0.1, 0.2, 0.3])
        source = self.service.create_source(source_payload(), "operator")
        self.service.review_source(source["id"], True, "operator")
        self.service.sync_source(source["id"], [job_payload()], "worker")
        self.job = self.repo.list("job")[0]
        candidate = self.service.create_candidate(candidate_payload(), "candidate")
        self.candidate = self.service.set_consent(candidate["id"], True, "candidate", "mvp-1")

    def test_pgvector_recall_records_retrieval_evidence(self):
        self.repo.hits = [(self.job, 0.9)]
        result = self.service.run_matches(self.candidate["id"], "scheduler")
        self.assertEqual(len(self.repo.search_calls), 1)
        match = result["matches"][0]
        self.assertEqual(match["retrieval"]["method"], "pgvector")
        self.assertEqual(match["retrieval"]["similarity"], 0.9)
        self.assertEqual(match["retrieval"]["rank"], 1)
        self.assertEqual(match["retrieval"]["recall_size"], 1)
        self.assertEqual(match["score_breakdown"]["semantic"], 1.0)

    def test_empty_recall_falls_back_to_full_scan(self):
        self.repo.hits = []
        result = self.service.run_matches(self.candidate["id"], "scheduler")
        match = result["matches"][0]
        self.assertEqual(match["retrieval"]["method"], "full_scan")

    def test_no_embed_fn_never_calls_vector_search(self):
        plain_service = AgentService(self.repo)
        result = plain_service.run_matches(self.candidate["id"], "scheduler")
        self.assertEqual(self.repo.search_calls, [])
        self.assertEqual(result["matches"][0]["retrieval"]["method"], "full_scan")


if __name__ == "__main__":
    unittest.main()
