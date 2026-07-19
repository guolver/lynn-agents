"""LLM 可观测性：把对话 Agent 的每一轮调用与工具执行上报 Langfuse。

设计原则与向量层/图谱层一致——观测是旁路，永远不能影响主流程：
- 未配置 ``LANGFUSE_PUBLIC_KEY``/``LANGFUSE_SECRET_KEY`` 时返回 no-op tracer，零开销；
- langfuse SDK 未安装、初始化失败、上报异常，全部降级为日志告警，不抛出。

追踪结构（一次用户消息 = 一条 trace）：
    chat-turn (root span, 关联 session_id/actor)
    ├── llm-round-1 (generation: model、输入消息、输出、token 用量)
    ├── tool:search_jobs (span: 参数、结果摘要、耗时)
    └── llm-round-2 (generation)

环境变量：
    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY   未设置则观测关闭
    LANGFUSE_HOST                               默认 https://cloud.langfuse.com（可指向自托管）
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_TOOL_OUTPUT_LIMIT = 2000


class NoopHandle:
    """generation/tool 的空句柄。"""

    def end(self, **_kwargs: Any) -> None:
        return None


class NoopTurn:
    """观测关闭时的空 turn。"""

    def generation(self, **_kwargs: Any) -> NoopHandle:
        return NoopHandle()

    def tool(self, **_kwargs: Any) -> NoopHandle:
        return NoopHandle()

    def end(self, **_kwargs: Any) -> None:
        return None


class NoopTracer:
    enabled = False

    def start_turn(self, **_kwargs: Any) -> NoopTurn:
        return NoopTurn()


class _LangfuseGeneration:
    def __init__(self, span: Any):
        self._span = span

    def end(
        self,
        *,
        output: Any = None,
        usage: dict[str, int] | None = None,
        error: str | None = None,
    ) -> None:
        try:
            updates: dict[str, Any] = {"output": output}
            if usage:
                updates["usage_details"] = usage
            if error:
                updates["level"] = "ERROR"
                updates["status_message"] = error
            self._span.update(**updates)
            self._span.end()
        except Exception:
            logger.warning("langfuse generation end failed", exc_info=True)


class _LangfuseTool:
    def __init__(self, span: Any):
        self._span = span

    def end(self, *, output: Any = None, error: str | None = None) -> None:
        try:
            text = str(output) if output is not None else None
            if text and len(text) > _TOOL_OUTPUT_LIMIT:
                text = text[:_TOOL_OUTPUT_LIMIT] + "...(truncated)"
            updates: dict[str, Any] = {"output": text}
            if error:
                updates["level"] = "ERROR"
                updates["status_message"] = error
            self._span.update(**updates)
            self._span.end()
        except Exception:
            logger.warning("langfuse tool end failed", exc_info=True)


class LangfuseTurn:
    def __init__(self, client: Any, root: Any):
        self._client = client
        self._root = root

    def generation(
        self,
        *,
        name: str,
        model: str,
        input_messages: list[dict[str, Any]],
        parameters: dict[str, Any] | None = None,
    ) -> _LangfuseGeneration | NoopHandle:
        try:
            span = self._root.start_generation(
                name=name,
                model=model,
                input=input_messages,
                model_parameters=parameters or {},
            )
            return _LangfuseGeneration(span)
        except Exception:
            logger.warning("langfuse generation start failed", exc_info=True)
            return NoopHandle()

    def tool(self, *, name: str, arguments: dict[str, Any]) -> _LangfuseTool | NoopHandle:
        try:
            span = self._root.start_span(name=f"tool:{name}", input=arguments)
            return _LangfuseTool(span)
        except Exception:
            logger.warning("langfuse tool start failed", exc_info=True)
            return NoopHandle()

    def end(self, *, output: str | None = None, error: str | None = None) -> None:
        try:
            updates: dict[str, Any] = {"output": output}
            if error:
                updates["level"] = "ERROR"
                updates["status_message"] = error
            self._root.update(**updates)
            self._root.end()
            self._client.flush()
        except Exception:
            logger.warning("langfuse turn end failed", exc_info=True)


class LangfuseTracer:
    enabled = True

    def __init__(self, client: Any):
        self._client = client

    def start_turn(
        self,
        *,
        session_id: str,
        actor: str,
        user_message: str,
        candidate_id: str | None = None,
    ) -> LangfuseTurn | NoopTurn:
        try:
            root = self._client.start_span(
                name="chat-turn",
                input={"user_message": user_message, "candidate_id": candidate_id},
            )
            root.update_trace(
                name="chat-turn",
                session_id=session_id,
                user_id=actor,
                input=user_message,
            )
            return LangfuseTurn(self._client, root)
        except Exception:
            logger.warning("langfuse turn start failed", exc_info=True)
            return NoopTurn()


_tracer: NoopTracer | LangfuseTracer | None = None


def get_chat_tracer() -> NoopTracer | LangfuseTracer:
    """进程级单例；无 key / SDK 缺失 / 初始化失败一律返回 no-op。"""
    global _tracer
    if _tracer is not None:
        return _tracer
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        _tracer = NoopTracer()
        return _tracer
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        _tracer = LangfuseTracer(client)
        logger.info("langfuse tracing enabled")
    except Exception:
        logger.warning("langfuse init failed; tracing disabled", exc_info=True)
        _tracer = NoopTracer()
    return _tracer


def reset_tracer() -> None:
    """测试用：清掉单例缓存。"""
    global _tracer
    _tracer = None
