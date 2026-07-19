"""将兼职招聘业务能力适配为 Agent Hub 的标准 Agent。"""

from __future__ import annotations

import os
from typing import Any, Callable

from ...core.contracts import (
    ActionDefinition,
    ActionNotFoundError,
    AgentManifest,
    ExecutionContext,
    InvalidInvocationError,
)
from .repository import RootRepositoryProtocol
from .service import AgentService


class GlobalPartTimeAgent:
    """平台适配器：声明能力白名单，并把统一调用映射到领域服务。"""

    manifest = AgentManifest(
        agent_id="global-part-time",
        name="全球兼职职位匹配 Agent",
        version="0.2.0",
        description="从已批准 Feed 同步职位，并为主动订阅的候选人生成可审计推荐。",
        tags=("jobs", "matching", "compliance"),
    )

    _actions = (
        ActionDefinition("list_sources", "列出已登记来源", input_schema={"type": "object"}),
        ActionDefinition(
            "sync_source",
            "同步一个已批准的结构化职位 Feed",
            mode="write",
            risk_level="medium",
            requires_idempotency_key=True,
            input_schema={"required": ["source_id", "jobs"]},
        ),
        ActionDefinition(
            "validate_job",
            "读取确定性风险与质量校验结果",
            input_schema={"required": ["job_id"]},
        ),
        ActionDefinition(
            "find_matches",
            "为已订阅候选人执行硬过滤和匹配排序",
            mode="write",
            requires_idempotency_key=True,
            input_schema={"required": ["candidate_id"]},
        ),
        ActionDefinition(
            "draft_digest",
            "生成最多五个职位的通知草稿",
            mode="write",
            risk_level="medium",
            requires_idempotency_key=True,
            input_schema={"required": ["candidate_id", "match_ids"]},
        ),
        ActionDefinition(
            "request_approval",
            "为高风险动作创建人工审批任务",
            mode="write",
            risk_level="high",
            requires_idempotency_key=True,
            input_schema={"required": ["action", "target_id"]},
        ),
        ActionDefinition(
            "send_digest",
            "发送已经批准的通知草稿",
            mode="write",
            risk_level="high",
            requires_idempotency_key=True,
            input_schema={"required": ["notification_id"]},
        ),
    )

    def __init__(
        self,
        repository: RootRepositoryProtocol,
        expand_fn: Callable[[list[str]], set[str]] | None = None,
        embed_fn: Callable[[str], list[float] | None] | None = None,
    ):
        # Root, unscoped repository: every invocation carves out its own
        # tenant-scoped view (and a matching request-scoped AgentService) from
        # context.principal.tenant_id, rather than sharing one fixed service
        # across every tenant/actor — see invoke() below.
        self.repository = repository
        self.expand_fn = expand_fn
        self.embed_fn = embed_fn

    def actions(self) -> tuple[ActionDefinition, ...]:
        return self._actions

    def invoke(
        self, action: str, payload: dict[str, Any], context: ExecutionContext
    ) -> dict[str, Any]:
        repo = self.repository.for_tenant(context.tenant_id)
        service = AgentService(
            repo,
            expand_fn=self.expand_fn,
            embed_fn=self.embed_fn,
            principal=context.principal,
            request_id=context.request_id,
        )
        handlers: dict[str, Callable[[], dict[str, Any]]] = {
            "list_sources": lambda: self._list_sources(payload, repo),
            "sync_source": lambda: self._sync_source(payload, context, service),
            "validate_job": lambda: self._validation_result(
                self._required(payload, "job_id", str), service
            ),
            "find_matches": lambda: service.run_matches(
                self._required(payload, "candidate_id", str),
                context.actor,
                self._limit(payload),
            ),
            "draft_digest": lambda: service.preview_digest(
                self._required(payload, "candidate_id", str),
                self._required(payload, "match_ids", list),
                context.actor,
                os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            ),
            "request_approval": lambda: service.request_approval(
                self._required(payload, "action", str),
                self._required(payload, "target_id", str),
                self._optional_dict(payload, "details"),
                context.actor,
            ),
            "send_digest": lambda: service.send_notification(
                self._required(payload, "notification_id", str), context.actor
            ),
        }
        handler = handlers.get(action)
        if handler is None:
            raise ActionNotFoundError(f"action {action} is not implemented")

        definition = next(item for item in self._actions if item.name == action)
        if definition.mode == "read":
            return handler()
        # 各 Agent 自己选择幂等存储；平台只负责要求调用者提供幂等键。
        assert context.idempotency_key is not None
        return repo.idempotent(
            f"agent:{self.manifest.agent_id}:{action}", context.idempotency_key, handler
        )

    @staticmethod
    def _validation_result(job_id: str, service: AgentService) -> dict[str, Any]:
        job = service.get_job(job_id)
        return {
            "job_id": job_id,
            "status": job["status"],
            "risk_score": job["risk_score"],
            "risk_level": job["risk_level"],
            "risk_signals": job["risk_signals"],
            "quality_score": job["quality_score"],
            "rule_version": job["rule_version"],
        }

    @staticmethod
    def _sync_source(
        payload: dict[str, Any], context: ExecutionContext, service: AgentService
    ) -> dict[str, Any]:
        source_id = GlobalPartTimeAgent._required(payload, "source_id", str)
        jobs = GlobalPartTimeAgent._required(payload, "jobs", list)
        if not all(isinstance(job, dict) for job in jobs):
            raise InvalidInvocationError("payload.jobs must contain objects")
        return service.sync_source(source_id, jobs, context.actor)

    @staticmethod
    def _limit(payload: dict[str, Any]) -> int:
        value = payload.get("limit", 50)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
            raise InvalidInvocationError("payload.limit must be an integer between 1 and 100")
        return value

    @staticmethod
    def _optional_dict(payload: dict[str, Any], field: str) -> dict[str, Any]:
        value = payload.get(field, {})
        if not isinstance(value, dict):
            raise InvalidInvocationError(f"payload.{field} must be an object")
        return value

    @staticmethod
    def _list_sources(payload: dict[str, Any], repo: Any) -> dict[str, Any]:
        # Agent 工具默认只暴露已批准来源；运营兼容 API 仍可查看全部审核状态。
        review_status = payload.get("review_status", "approved")
        sources = [
            source
            for source in repo.list("source")
            if review_status == "all" or source.get("review_status") == review_status
        ]
        return {"sources": sources}

    @staticmethod
    def _required(
        payload: dict[str, Any], field: str, expected_type: type[Any] | None = None
    ) -> Any:
        value = payload.get(field)
        if value is None:
            raise InvalidInvocationError(f"payload.{field} is required")
        if expected_type is not None and not isinstance(value, expected_type):
            raise InvalidInvocationError(f"payload.{field} must be {expected_type.__name__}")
        return value
