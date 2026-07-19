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
6. 为具体岗位生成申请材料（定制求职信 + 简历优化建议 + 申请链接）

规则：
- 用户首次对话时，引导他们上传简历或手动描述技能背景
- 推荐岗位时，说明匹配理由和各维度得分
- 用中文回复，除非用户用其他语言
- 回复简洁，避免冗长列表，突出重点
- 推荐岗位时使用 run_matches 工具，不要编造职位信息
- 用户再次要求推荐时，系统会自动优先展示之前没推荐过的岗位；\
如果新岗位不多，如实说明并建议用户调整偏好或稍后再试

申请材料生成（用户要求"生成申请材料/写求职信"时）：
- 先调用 get_job_detail 获取 JD 与申请链接，再调用 get_my_profile 获取画像与简历原文
- 求职信用岗位语言撰写（通常英文），250-350 词，放在 Markdown 引用块中；\
必须引用 JD 的具体要求和简历中的真实经历，严禁编造经历或技能
- 随后用中文给出 3-5 条针对该岗位的简历优化建议（该突出/补充什么）
- 结尾附上岗位的 canonical_url 申请链接，提醒用户自行提交
- 若画像中没有 resume_text，如实说明材料基于画像摘要生成，建议上传简历获得更精准的材料
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

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages. Returns True if found."""
        session = self.repo.get("chat_session", session_id)
        if session is None:
            return False
        self.repo.delete_by_session(session_id)
        return True

    def _set_title_if_empty(self, session_id: str, text: str) -> None:
        """Set session title from first user message (truncated to 50 chars)."""
        session = self.repo.get("chat_session", session_id)
        if session and not session.get("title"):
            title = text.strip().replace("\n", " ")
            if len(title) > 50:
                title = title[:47] + "..."
            session["title"] = title
            self.repo.put("chat_session", session)

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
        attachment: dict[str, Any] | None = None,
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
        if attachment is not None:
            msg["attachment"] = attachment
        self.repo.put("chat_message", msg)
        return msg

    def shown_job_ids(self, session_id: str) -> set[str]:
        """收集本会话已推荐过的岗位 ID，用于再次推荐时轮换出新岗位。"""
        shown: set[str] = set()
        for msg in self.repo.list_by_session(session_id):
            if msg.get("role") != "tool":
                continue
            try:
                payload = json.loads(msg.get("content") or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict) or payload.get("name") != "run_matches":
                continue
            result = payload.get("result") or {}
            for match in result.get("matches") or []:
                job_id = match.get("job_id") if isinstance(match, dict) else None
                if job_id:
                    shown.add(job_id)
        return shown

    def run_analysis(
        self,
        session_id: str,
        resume_text: str,
        actor: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """确定性简历流水线：解析 → 建候选人 → opt-in → 绑定会话 → 匹配。

        不依赖 LLM 决定是否调用工具；结果持久化为 assistant + tool 消息，
        便于刷新后从历史重建匹配卡片。返回富化后的匹配结果。
        """
        self._set_title_if_empty(session_id, "简历分析与岗位匹配")

        from .chat_tools import execute_tool

        parse_result = execute_tool(
            "parse_resume", {"pdf_text": resume_text}, service=self.service, actor=actor
        )
        if "error" in parse_result or "candidate" not in parse_result:
            raise RuntimeError(parse_result.get("error", "简历解析失败"))

        candidate = parse_result["candidate"]
        candidate_id = candidate["id"]
        self.bind_candidate(session_id, candidate_id)

        match_args: dict[str, Any] = {"candidate_id": candidate_id, "limit": limit}
        shown = self.shown_job_ids(session_id)
        if shown:
            match_args["exclude_job_ids"] = sorted(shown)
        match_result = execute_tool(
            "run_matches",
            match_args,
            service=self.service,
            actor=actor,
        )
        matches = match_result.get("matches", [])

        if matches:
            summary = f"简历解析完成，为你匹配到 {len(matches)} 个岗位："
        else:
            summary = (
                "简历解析完成，但暂时没有匹配到合适的岗位。"
                "你可以调整偏好（薪资、地区、工作模式）后再试。"
            )

        # Persist a valid assistant(tool_calls) + tool pair so replaying history
        # to the LLM satisfies the OpenAI protocol (tool must answer tool_calls).
        call_id = f"chat_match_{uuid.uuid4().hex}"
        assistant_msg = self.add_message(
            session_id,
            "assistant",
            summary,
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "run_matches",
                        "arguments": json.dumps({"candidate_id": candidate_id, "limit": limit}),
                    },
                }
            ],
        )
        self.add_message(
            session_id,
            "tool",
            json.dumps(
                {"name": "run_matches", "result": match_result}, ensure_ascii=False, default=str
            ),
            tool_call_id=call_id,
        )

        return {
            "candidate": candidate,
            "matches": matches,
            "matches_count": len(matches),
            "summary": summary,
            "message_id": assistant_msg["id"],
            "parsed_fields": parse_result.get("parsed_fields"),
        }

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

        for msg in self._sanitize_history(history):
            entry: dict[str, Any] = {"role": msg["role"], "content": msg["content"]}
            if msg.get("tool_calls"):
                entry["tool_calls"] = msg["tool_calls"]
            if msg.get("tool_call_id"):
                entry["tool_call_id"] = msg["tool_call_id"]
            messages.append(entry)

        return messages

    @staticmethod
    def _sanitize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop tool messages that don't answer a preceding assistant tool_calls.

        The OpenAI protocol rejects the whole request if a "tool" message is not
        an immediate response to an assistant message carrying matching
        tool_calls. Orphans appear when the history window truncation splits a
        pair, or from legacy rows persisted without tool_calls. Assistant
        tool_calls left unanswered (e.g. interrupted stream) are stripped for
        the same reason.
        """
        result: list[dict[str, Any]] = []
        i = 0
        while i < len(history):
            msg = history[i]
            role = msg["role"]
            if role == "tool":
                i += 1  # orphan tool message
                continue
            if role == "assistant" and msg.get("tool_calls"):
                call_ids = {tc["id"] for tc in msg["tool_calls"]}
                j = i + 1
                responses = []
                while (
                    j < len(history)
                    and history[j]["role"] == "tool"
                    and history[j].get("tool_call_id") in call_ids
                ):
                    responses.append(history[j])
                    j += 1
                if len(responses) == len(call_ids):
                    result.append(msg)
                    result.extend(responses)
                elif msg.get("content"):
                    stripped = {k: v for k, v in msg.items() if k != "tool_calls"}
                    result.append(stripped)
                i = j
                continue
            result.append(msg)
            i += 1
        return result

    def start_streaming(self, session_id: str, user_message: str, hub: Any) -> str:
        """把生成任务与 HTTP 连接解耦：后台线程跑 stream_response 并发布到 hub。

        返回 stream_id。客户端（包括断开后重连的）通过 hub.replay_and_follow
        消费；连接断开不影响生成，消息照常落库。
        """
        import threading

        stream_id = str(uuid.uuid4())
        hub.set_active(session_id, stream_id)

        def run() -> None:
            terminal_seen = False
            try:
                for event in self.stream_response(session_id, user_message):
                    hub.publish(stream_id, event["event"], event["data"])
                    if event["event"] in ("done", "error"):
                        terminal_seen = True
            except Exception as exc:  # noqa: BLE001 - stream must always terminate
                logger.exception("chat stream generation failed")
                hub.publish(stream_id, "error", {"detail": f"生成中断: {exc}"})
                terminal_seen = True
            finally:
                if not terminal_seen:
                    hub.publish(stream_id, "done", {})
                hub.clear_active(session_id)

        threading.Thread(target=run, daemon=True, name=f"chat-stream-{stream_id[:8]}").start()
        return stream_id

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

        # Save user message and auto-title the session
        self.add_message(session_id, "user", user_message)
        self._set_title_if_empty(session_id, user_message)

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

                    # 会话内轮换：已推荐过的岗位排后，保证再次推荐有差异性。
                    if tool_name == "run_matches":
                        shown = self.shown_job_ids(session_id)
                        if shown:
                            tool_args = {**tool_args, "exclude_job_ids": sorted(shown)}

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
