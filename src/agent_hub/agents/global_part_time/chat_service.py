"""Chat service: session management, message persistence, LLM streaming.

Orchestrates conversation between user and DeepSeek LLM via function calling.
All business logic is delegated to AgentService through chat_tools.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Generator
from typing import Any

from .chat_tools import TOOL_DEFINITIONS, execute_tool
from .service import AgentService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是 Agent Hub 职位推荐助手。你可以：
1. 解析用户上传的简历，提取技能、经验、偏好
2. 根据候选人画像匹配合适的远程兼职岗位
3. 查看岗位详情，回答关于具体岗位的问题
4. 帮用户调整匹配偏好（薪资、地区、工作模式等）
5. 给出简历优化建议和求职策略建议

规则：
- 用户首次对话时，引导他们上传简历或手动描述技能背景
- 推荐岗位时，说明匹配理由和各维度得分
- 用中文回复，除非用户用其他语言
- 回复简洁，避免冗长列表，突出重点
- 推荐岗位时使用 run_matches 工具，不要编造职位信息
"""

MAX_HISTORY_MESSAGES = 40


class ChatService:
    """Manages chat sessions, persists messages, and streams LLM responses."""

    def __init__(self, *, service: AgentService, repo: Any):
        self.service = service
        self.repo = repo

    def create_session(self, actor: str = "anonymous") -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        return self.repo.put(
            "chat_session",
            {
                "id": session_id,
                "actor": actor,
                "status": "active",
                "candidate_id": None,
            },
        )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self.repo.get("chat_session", session_id)
        if session is None:
            return None
        messages = self.repo.list_by_session(session_id)
        return {"session": session, "messages": messages}

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.repo.list("chat_session")

    def bind_candidate(self, session_id: str, candidate_id: str) -> None:
        session = self.repo.get("chat_session", session_id)
        if session:
            session["candidate_id"] = candidate_id
            self.repo.put("chat_session", session)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        msg = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "role": role,
            "content": content,
        }
        if tool_calls is not None:
            msg["tool_calls"] = tool_calls
        if tool_call_id is not None:
            msg["tool_call_id"] = tool_call_id
        self.repo.put("chat_message", msg)
        return msg

    def build_llm_messages(
        self,
        session_id: str,
        candidate_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the messages array for DeepSeek API from session history."""
        system_content = SYSTEM_PROMPT
        if candidate_id:
            system_content += f"\n\n当前候选人 ID: {candidate_id}。调用工具时请使用此 ID。"

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]

        history = self.repo.list_by_session(session_id)
        # Keep last N messages to stay within context window
        history = history[-MAX_HISTORY_MESSAGES:]

        for msg in history:
            entry: dict[str, Any] = {"role": msg["role"], "content": msg["content"]}
            if msg.get("tool_calls"):
                entry["tool_calls"] = msg["tool_calls"]
            if msg.get("tool_call_id"):
                entry["tool_call_id"] = msg["tool_call_id"]
            messages.append(entry)

        return messages

    def stream_response(
        self,
        session_id: str,
        user_message: str,
    ) -> Generator[dict[str, Any], None, None]:
        """Process a user message and yield SSE events.

        Yields dicts with "event" and "data" keys:
          {"event": "delta", "data": {"content": "..."}}
          {"event": "tool_call", "data": {"name": "...", "arguments": {...}}}
          {"event": "tool_result", "data": {"name": "...", "result": {...}}}
          {"event": "done", "data": {"message_id": "..."}}
          {"event": "error", "data": {"detail": "..."}}
        """
        # Get session and candidate_id
        session = self.repo.get("chat_session", session_id)
        if session is None:
            yield {"event": "error", "data": {"detail": "Session not found"}}
            return
        candidate_id = session.get("candidate_id")

        # Save user message
        self.add_message(session_id, "user", user_message)

        # Build LLM messages
        llm_messages = self.build_llm_messages(session_id, candidate_id)

        # Create DeepSeek client
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        if not api_key:
            yield {"event": "error", "data": {"detail": "DEEPSEEK_API_KEY not configured"}}
            return

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        actor = session.get("actor", "chat-user")

        # Allow multiple rounds of tool calling
        max_rounds = 5
        for _ in range(max_rounds):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=llm_messages,
                    tools=TOOL_DEFINITIONS,
                    stream=True,
                    temperature=0.7,
                    max_tokens=2048,
                )
            except Exception as exc:
                logger.exception("DeepSeek API call failed")
                yield {"event": "error", "data": {"detail": f"LLM service error: {exc}"}}
                return

            # Collect the streamed response
            collected_content = ""
            collected_tool_calls: list[dict[str, Any]] = []
            current_tool_call: dict[str, Any] | None = None

            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # Content delta
                if delta.content:
                    collected_content += delta.content
                    yield {"event": "delta", "data": {"content": delta.content}}

                # Tool call deltas
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        if tc_delta.index is not None:
                            while len(collected_tool_calls) <= tc_delta.index:
                                collected_tool_calls.append(
                                    {"id": "", "function": {"name": "", "arguments": ""}}
                                )
                            current_tool_call = collected_tool_calls[tc_delta.index]
                        if tc_delta.id:
                            current_tool_call["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                current_tool_call["function"]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                current_tool_call["function"]["arguments"] += (
                                    tc_delta.function.arguments
                                )

                # finish_reason is checked implicitly when stream ends

            if collected_tool_calls:
                # Save assistant message with tool calls
                serializable_calls = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in collected_tool_calls
                ]
                self.add_message(
                    session_id,
                    "assistant",
                    collected_content,
                    tool_calls=serializable_calls,
                )

                # Add assistant message to LLM context
                llm_messages.append(
                    {
                        "role": "assistant",
                        "content": collected_content or None,
                        "tool_calls": serializable_calls,
                    }
                )

                # Execute each tool call
                for tc in collected_tool_calls:
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        tool_args = {}

                    yield {
                        "event": "tool_call",
                        "data": {"name": tool_name, "arguments": tool_args},
                    }

                    result = execute_tool(
                        tool_name,
                        tool_args,
                        service=self.service,
                        actor=actor,
                    )

                    # If parse_resume created a candidate, bind to session
                    if tool_name == "parse_resume" and "candidate" in result:
                        new_candidate_id = result["candidate"]["id"]
                        self.bind_candidate(session_id, new_candidate_id)
                        candidate_id = new_candidate_id

                    yield {
                        "event": "tool_result",
                        "data": {"name": tool_name, "result": result},
                    }

                    # Save tool result message
                    result_content = json.dumps(result, ensure_ascii=False, default=str)
                    # Truncate very large results
                    if len(result_content) > 8000:
                        result_content = result_content[:8000] + "...(truncated)"
                    self.add_message(
                        session_id,
                        "tool",
                        result_content,
                        tool_call_id=tc["id"],
                    )

                    # Add to LLM context
                    llm_messages.append(
                        {
                            "role": "tool",
                            "content": result_content,
                            "tool_call_id": tc["id"],
                        }
                    )

                # Continue the loop to let LLM generate a response based on tool results
                continue

            else:
                # No tool calls — final text response
                msg = self.add_message(session_id, "assistant", collected_content)
                yield {"event": "done", "data": {"message_id": msg["id"]}}
                return

        # If we hit max rounds
        msg = self.add_message(session_id, "assistant", collected_content)
        yield {"event": "done", "data": {"message_id": msg["id"]}}
