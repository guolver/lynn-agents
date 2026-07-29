"""将模拟面试业务能力适配为 Agent Hub 的标准 Agent。"""

from __future__ import annotations

from typing import Any, Callable

from ...core.contracts import (
    ActionDefinition,
    ActionNotFoundError,
    AgentManifest,
    ExecutionContext,
    InvalidInvocationError,
)


class MockInterviewAgent:
    """模拟面试 Agent 适配器。"""

    manifest = AgentManifest(
        agent_id="mock-interview",
        name="技术模拟面试 Agent",
        version="1.0.0",
        description="提供知识库管理和技术模拟面试功能，支持 RAG 检索增强对话。",
        tags=("interview", "knowledge", "rag"),
    )

    _actions = (
        ActionDefinition(
            "list_knowledge",
            "列出知识库文档",
            input_schema={"type": "object"},
        ),
        ActionDefinition(
            "search_knowledge",
            "基于语义搜索知识库",
            input_schema={"required": ["query"]},
        ),
        ActionDefinition(
            "create_session",
            "创建面试会话",
            mode="write",
            input_schema={"required": ["target_role"]},
        ),
        ActionDefinition(
            "end_session",
            "结束面试并生成评估",
            mode="write",
            input_schema={"required": ["session_id"]},
        ),
    )

    def __init__(
        self,
        repository: Any,
        embed_fn: Callable[[str], list[float] | None] | None = None,
    ):
        self.repository = repository
        self.embed_fn = embed_fn

    def actions(self) -> tuple[ActionDefinition, ...]:
        return self._actions

    def invoke(
        self, action: str, payload: dict[str, Any], context: ExecutionContext
    ) -> dict[str, Any]:
        from sqlalchemy.orm import sessionmaker

        from .repository import InterviewRepository
        from .service import InterviewService

        # 创建租户隔离的服务
        session_factory = sessionmaker(bind=self.repository._engine)
        interview_repo = InterviewRepository(session_factory, context.tenant_id)
        service = InterviewService(interview_repo, embed_fn=self.embed_fn)

        handlers: dict[str, Callable[[], dict[str, Any]]] = {
            "list_knowledge": lambda: {
                "knowledge": service.list_knowledge(
                    category=payload.get("category"),
                    limit=payload.get("limit", 100),
                )
            },
            "search_knowledge": lambda: {
                "results": [
                    {"knowledge": k, "score": s}
                    for k, s in service.search_knowledge(
                        self._required(payload, "query", str),
                        limit=payload.get("limit", 5),
                    )
                ]
            },
            "create_session": lambda: service.create_session(
                target_role=self._required(payload, "target_role", str),
                difficulty=payload.get("difficulty", "medium"),
                actor=context.actor,
                category=payload.get("category"),
            ),
            "end_session": lambda: (
                service.end_session(self._required(payload, "session_id", str))
                or {"error": "Session not found"}
            ),
        }

        handler = handlers.get(action)
        if handler is None:
            raise ActionNotFoundError(f"action {action} is not implemented")

        return handler()

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
