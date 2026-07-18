"""全球兼职 Agent 的应用服务。

这里编排仓储和纯领域规则，但不关心调用来自兼容 REST API、统一 Agent API
还是定时任务。这个边界让同一个 Agent 能以多种入口接入扩展平台。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from .repository import RepositoryProtocol
from .domain import (
    RULE_VERSION,
    assess_risk,
    canonicalize_url,
    dedup_key,
    hard_filter,
    score_match,
    utcnow,
)
from .embedding import build_candidate_text


logger = logging.getLogger(__name__)

RECALL_LIMIT = 200


class NotFoundError(ValueError):
    pass


class PolicyError(ValueError):
    pass


class AgentService:
    """实现职位采集、候选匹配、审批和通知的完整业务用例。"""

    def __init__(
        self,
        repository: RepositoryProtocol,
        expand_fn: Callable[[list[str]], set[str]] | None = None,
        embed_fn: Callable[[str], list[float] | None] | None = None,
    ):
        self.repo = repository
        self.expand_fn = expand_fn
        self.embed_fn = embed_fn

    @staticmethod
    def _id() -> str:
        return str(uuid.uuid4())

    def _required(self, kind: str, entity_id: str) -> dict[str, Any]:
        item = self.repo.get(kind, entity_id)
        if not item:
            raise NotFoundError(f"{kind} {entity_id} not found")
        return item

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._required("job", job_id)

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        return self._required("candidate", candidate_id)

    def create_source(self, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        source = {**payload, "id": self._id(), "review_status": "pending", "enabled": False}
        source = self.repo.put("source", source)
        self.repo.audit("source.created", "source", source["id"], actor)
        return source

    def review_source(
        self, source_id: str, approved: bool, actor: str, note: str = ""
    ) -> dict[str, Any]:
        source = self._required("source", source_id)
        source.update(
            review_status="approved" if approved else "rejected",
            enabled=approved,
            reviewed_by=actor,
            reviewed_at=utcnow(),
            review_note=note,
        )
        self.repo.put("source", source)
        self.repo.audit("source.reviewed", "source", source_id, actor, {"approved": approved})
        return source

    def sync_source(self, source_id: str, jobs: list[dict[str, Any]], actor: str) -> dict[str, Any]:
        """同步一个已批准 Feed，并在入库前执行风险检查和跨来源去重。"""
        source = self._required("source", source_id)
        if source.get("review_status") != "approved" or not source.get("enabled"):
            raise PolicyError("only approved and enabled sources may be synchronized")
        imported = duplicates = review = rejected = 0
        ids: list[str] = []
        existing = self.repo.list("job")
        by_key = {item["dedup_key"]: item for item in existing}
        for raw in jobs:
            job = dict(raw)
            job["source_id"] = source_id
            job["canonical_url"] = canonicalize_url(job["canonical_url"])
            key = dedup_key(job)
            risk = assess_risk(job)
            if risk.action == "reject":
                rejected += 1
                self.repo.audit(
                    "job.rejected", "source", source_id, actor, {"signals": risk.signals}
                )
                continue
            prior = by_key.get(key)
            now = utcnow()
            if prior:
                prior.setdefault("alternate_sources", []).append(
                    {
                        "source_id": source_id,
                        "source_job_id": job.get("source_job_id"),
                        "url": job["canonical_url"],
                    }
                )
                prior["last_seen_at"] = now
                self.repo.put("job", prior)
                ids.append(prior["id"])
                duplicates += 1
                continue
            job.update(
                id=self._id(),
                dedup_key=key,
                status="active" if risk.action == "accept" else "pending_review",
                review_status="not_required" if risk.action == "accept" else "pending",
                risk_score=risk.score,
                risk_level=risk.level,
                risk_signals=risk.signals,
                quality_score=float(job.get("quality_score", 0.7)),
                extraction_confidence=float(job.get("extraction_confidence", 1.0)),
                first_seen_at=now,
                last_seen_at=now,
                last_verified_at=now,
                rule_version=RULE_VERSION,
            )
            self.repo.put("job", job)
            by_key[key] = job
            ids.append(job["id"])
            imported += 1
            review += int(risk.action == "review")
            self.repo.audit("job.imported", "job", job["id"], actor, {"risk": risk.level})
        self.repo.audit("source.synced", "source", source_id, actor, {"received": len(jobs)})
        return {
            "source_id": source_id,
            "received": len(jobs),
            "imported": imported,
            "duplicates": duplicates,
            "pending_review": review,
            "rejected": rejected,
            "job_ids": ids,
        }

    def review_job(self, job_id: str, approved: bool, actor: str, note: str = "") -> dict[str, Any]:
        job = self._required("job", job_id)
        job.update(
            review_status="approved" if approved else "rejected",
            status="active" if approved else "rejected",
            reviewed_by=actor,
            reviewed_at=utcnow(),
            review_note=note,
        )
        self.repo.put("job", job)
        self.repo.audit("job.reviewed", "job", job_id, actor, {"approved": approved})
        return job

    def report_job(self, job_id: str, reason: str, actor: str) -> dict[str, Any]:
        job = self._required("job", job_id)
        reports = job.setdefault("reports", [])
        reports.append({"reason": reason, "created_at": utcnow()})
        if len(reports) >= 3:
            job["status"] = "pending_review"
            job["review_status"] = "pending"
        self.repo.put("job", job)
        self.repo.audit("job.reported", "job", job_id, actor, {"reason": reason})
        return job

    def create_candidate(self, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        candidate = {**payload, "id": self._id(), "consent_status": "not_requested"}
        candidate = self.repo.put("candidate", candidate)
        self.repo.audit("candidate.created", "candidate", candidate["id"], actor)
        return candidate

    def update_candidate(
        self, candidate_id: str, changes: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        candidate = self._required("candidate", candidate_id)
        protected = {"id", "consent_status", "created_at", "updated_at"}
        candidate.update({k: v for k, v in changes.items() if k not in protected})
        self.repo.put("candidate", candidate)
        self.repo.audit("candidate.preferences_updated", "candidate", candidate_id, actor)
        return candidate

    def set_consent(
        self, candidate_id: str, opted_in: bool, actor: str, version: str
    ) -> dict[str, Any]:
        candidate = self._required("candidate", candidate_id)
        candidate.update(
            consent_status="opted_in" if opted_in else "opted_out",
            consent_record={"version": version, "recorded_at": utcnow(), "actor": actor},
        )
        self.repo.put("candidate", candidate)
        self.repo.audit(
            "candidate.consent_changed", "candidate", candidate_id, actor, {"opted_in": opted_in}
        )
        return candidate

    def delete_candidate(self, candidate_id: str, actor: str) -> dict[str, Any]:
        self._required("candidate", candidate_id)
        self.repo.delete("candidate", candidate_id)
        for kind in ("match", "notification", "feedback"):
            for item in self.repo.list(kind):
                if item.get("candidate_id") == candidate_id:
                    self.repo.delete(kind, item["id"])
        self.repo.audit(
            "candidate.deleted", "candidate", candidate_id, actor, {"personal_data_removed": True}
        )
        return {"deleted": True, "candidate_id": candidate_id}

    def run_matches(self, candidate_id: str, actor: str, limit: int = 50) -> dict[str, Any]:
        """先运行硬过滤，再为剩余职位生成版本化、可解释的匹配结果。"""
        candidate = self._required("candidate", candidate_id)
        expansion_failed = False

        def expand_skills(names: list[str]) -> set[str]:
            nonlocal expansion_failed
            if self.expand_fn is None or expansion_failed:
                return set()
            try:
                return self.expand_fn(names)
            except Exception as exc:
                expansion_failed = True
                logger.warning(
                    "Skill graph expansion failed; using direct skill matching: %s",
                    exc,
                    exc_info=True,
                )
                return set()

        embedding_failed = False

        def safe_embed(text: str) -> list[float] | None:
            nonlocal embedding_failed
            if self.embed_fn is None or embedding_failed:
                return None
            try:
                return self.embed_fn(text)
            except Exception as exc:
                embedding_failed = True
                logger.warning(
                    "Embedding call failed; using neutral semantic score: %s",
                    exc,
                    exc_info=True,
                )
                return None

        expand_fn = expand_skills if self.expand_fn is not None else None
        embed_fn = safe_embed if self.embed_fn is not None else None
        existing_matches = {
            item["job_id"]: item
            for item in self.repo.list("match")
            if item.get("candidate_id") == candidate_id
        }
        sent_job_ids = {
            job_id
            for notification in self.repo.list("notification")
            if notification.get("candidate_id") == candidate_id
            and notification.get("status") == "sent"
            for job_id in notification.get("job_ids", [])
        }
        # 召回阶段：优先 pgvector 向量检索；不可用或失败时降级为全量扫描。
        similarities: dict[str, float] = {}
        retrieval_meta: dict[str, dict[str, Any]] = {}
        retrieval_method = "full_scan"
        candidate_jobs: list[dict[str, Any]] | None = None
        if embed_fn is not None and hasattr(self.repo, "search_jobs_by_embedding"):
            candidate_vec = embed_fn(build_candidate_text(candidate))
            if candidate_vec is not None:
                hits = self.repo.search_jobs_by_embedding(candidate_vec, RECALL_LIMIT)
                if hits:
                    retrieval_method = "pgvector"
                    candidate_jobs = []
                    for rank, (job, similarity) in enumerate(hits, start=1):
                        candidate_jobs.append(job)
                        similarities[job["id"]] = similarity
                        retrieval_meta[job["id"]] = {
                            "method": "pgvector",
                            "similarity": round(similarity, 4),
                            "rank": rank,
                            "recall_size": len(hits),
                        }
        if candidate_jobs is None:
            candidate_jobs = self.repo.list("job")

        filtered = []
        eligible_jobs = []
        for job in candidate_jobs:
            failures = hard_filter(candidate, job, job["id"] in sent_job_ids)
            if failures:
                filtered.append({"job_id": job["id"], "reasons": failures})
                continue
            eligible_jobs.append(job)

        scored_jobs = []
        for job in eligible_jobs:
            scored_jobs.append(
                (
                    job,
                    *score_match(
                        candidate,
                        job,
                        expand_fn,
                        embed_fn,
                        semantic_similarity=similarities.get(job["id"]),
                    ),
                )
            )
            if expansion_failed:
                break
        if expansion_failed:
            scored_jobs = [
                (
                    job,
                    *score_match(
                        candidate,
                        job,
                        embed_fn=embed_fn,
                        semantic_similarity=similarities.get(job["id"]),
                    ),
                )
                for job in eligible_jobs
            ]

        results = []
        for job, score, breakdown, reasons in scored_jobs:
            match = {
                "id": existing_matches.get(job["id"], {}).get("id", self._id()),
                "candidate_id": candidate_id,
                "job_id": job["id"],
                "hard_filter_passed": True,
                "score": score,
                "score_breakdown": breakdown,
                "reasons": reasons,
                "rule_version": RULE_VERSION,
                "job_version": job["updated_at"],
                "retrieval": retrieval_meta.get(job["id"], {"method": "full_scan"}),
                "created_at": utcnow(),
            }
            self.repo.put("match", match)
            results.append(match)
        results.sort(key=lambda x: x["score"], reverse=True)
        results = results[:limit]
        self.repo.audit(
            "matches.run",
            "candidate",
            candidate_id,
            actor,
            {
                "matched": len(results),
                "filtered": len(filtered),
                "rule_version": RULE_VERSION,
                "retrieval_method": retrieval_method,
            },
        )
        return {"matches": results, "filtered": filtered}

    def candidate_matches(self, candidate_id: str) -> list[dict[str, Any]]:
        self._required("candidate", candidate_id)
        items = [x for x in self.repo.list("match") if x["candidate_id"] == candidate_id]
        items.sort(key=lambda x: x["score"], reverse=True)

        # Enrich with job details for display
        jobs_by_id = {j["id"]: j for j in self.repo.list("job")}
        for item in items:
            job = jobs_by_id.get(item.get("job_id"))
            if job:
                item["job_title"] = job.get("title_original", "")
                item["company_name"] = job.get("company_name", "")
        return items

    def feedback(self, match_id: str, value: str, actor: str) -> dict[str, Any]:
        match = self._required("match", match_id)
        item = self.repo.put(
            "feedback",
            {
                "id": self._id(),
                "match_id": match_id,
                "candidate_id": match["candidate_id"],
                "value": value,
            },
        )
        self.repo.audit("match.feedback", "match", match_id, actor, {"value": value})
        return item

    def request_approval(
        self,
        action: str,
        target_id: str,
        details: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        """创建审批任务而不直接执行目标动作。

        审批任务与通知/职位状态分开保存，便于未来接入统一审批中心或工作流引擎。
        """
        approval = self.repo.put(
            "approval",
            {
                "id": self._id(),
                "action": action,
                "target_id": target_id,
                "details": details,
                "status": "pending",
                "requested_by": actor,
            },
        )
        self.repo.audit(
            "approval.requested",
            "approval",
            approval["id"],
            actor,
            {"action": action, "target_id": target_id},
        )
        return approval

    def preview_digest(
        self, candidate_id: str, match_ids: list[str], actor: str, base_url: str
    ) -> dict[str, Any]:
        candidate = self._required("candidate", candidate_id)
        if candidate.get("consent_status") != "opted_in":
            raise PolicyError("candidate is not opted in")
        if candidate.get("notification_frequency") == "paused":
            raise PolicyError("candidate notifications are paused")
        if len(match_ids) > 5:
            raise PolicyError("a digest may contain at most 5 jobs")
        entries = []
        for match_id in match_ids:
            match = self._required("match", match_id)
            if match["candidate_id"] != candidate_id:
                raise PolicyError("match belongs to another candidate")
            job = self._required("job", match["job_id"])
            if hard_filter(candidate, job):
                raise PolicyError(f"job {job['id']} is no longer eligible")
            entries.append(
                {
                    "match_id": match_id,
                    "job_id": job["id"],
                    "title": job["title_original"],
                    "company": job["company_name"],
                    "score": match["score"],
                    "reasons": match["reasons"],
                    "canonical_url": job["canonical_url"],
                }
            )
        notification_id = self._id()
        draft = {
            "id": notification_id,
            "candidate_id": candidate_id,
            "match_ids": match_ids,
            "job_ids": [x["job_id"] for x in entries],
            "entries": entries,
            "status": "pending_approval",
            "subject": f"为你找到 {len(entries)} 个新的远程兼职机会",
            "unsubscribe_url": f"{base_url}/unsubscribe?candidate_id={candidate_id}",
            "report_base_url": f"{base_url}/jobs",
            "rule_version": RULE_VERSION,
        }
        self.repo.put("notification", draft)
        self.repo.audit("notification.previewed", "notification", notification_id, actor)
        return draft

    def review_notification(
        self, notification_id: str, approved: bool, actor: str
    ) -> dict[str, Any]:
        item = self._required("notification", notification_id)
        if item["status"] != "pending_approval":
            raise PolicyError("only pending drafts can be reviewed")
        item.update(
            status="approved" if approved else "rejected", reviewed_by=actor, reviewed_at=utcnow()
        )
        self.repo.put("notification", item)
        self.repo.audit(
            "notification.reviewed", "notification", notification_id, actor, {"approved": approved}
        )
        return item

    def send_notification(self, notification_id: str, actor: str) -> dict[str, Any]:
        """在发送前重新验证授权、频控、审批状态和每一个职位的有效性。"""
        item = self._required("notification", notification_id)
        if item["status"] == "sent":
            return item
        if item["status"] != "approved":
            raise PolicyError("notification requires approval")
        candidate = self._required("candidate", item["candidate_id"])
        if candidate.get("consent_status") != "opted_in":
            raise PolicyError("candidate is no longer opted in")
        if candidate.get("notification_frequency") == "paused":
            raise PolicyError("candidate notifications are paused")
        today = utcnow()[:10]
        already_today = [
            x
            for x in self.repo.list("notification")
            if x.get("candidate_id") == candidate["id"]
            and x.get("status") == "sent"
            and x.get("sent_at", "")[:10] == today
        ]
        if already_today:
            raise PolicyError("daily notification limit reached")
        for job_id in item["job_ids"]:
            job = self._required("job", job_id)
            if hard_filter(candidate, job):
                raise PolicyError(f"job {job_id} failed final eligibility check")
        item.update(
            status="sent",
            sent_at=utcnow(),
            provider="simulation",
            provider_message_id=f"sim-{self._id()}",
        )
        self.repo.put("notification", item)
        self.repo.audit(
            "notification.sent", "notification", notification_id, actor, {"provider": "simulation"}
        )
        return item
