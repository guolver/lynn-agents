"""面试 Agent 业务逻辑：知识库管理 + RAG 对话。"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Generator
from typing import Any, Callable

import httpx

from .knowledge_parser import parse_file
from .prompts import (
    INTERVIEWER_SYSTEM_PROMPT,
    SUMMARY_PROMPT,
    get_opening_message,
)
from .repository import InterviewRepository

logger = logging.getLogger(__name__)

DEEPSEEK_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
MAX_HISTORY_MESSAGES = 30


class InterviewService:
    """面试 Agent 核心服务：知识库管理和面试对话。"""

    def __init__(
        self,
        repo: InterviewRepository,
        embed_fn: Callable[[str], list[float] | None] | None = None,
    ):
        self.repo = repo
        self.embed_fn = embed_fn

    # -------------------------------------------------------------------------
    # 知识库管理
    # -------------------------------------------------------------------------

    def list_knowledge(self, category: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """列出知识库文档。"""
        return self.repo.list_knowledge(category=category, limit=limit)

    def get_knowledge(self, knowledge_id: str) -> dict[str, Any] | None:
        """获取单条知识库文档。"""
        return self.repo.get_knowledge(knowledge_id)

    def upload_knowledge(
        self,
        file_content: bytes | None,
        text_content: str | None,
        filename: str,
        category: str,
        title: str | None = None,
    ) -> list[dict[str, Any]]:
        """上传并解析知识库文件，返回创建的知识块列表。"""
        from io import BytesIO

        file_obj = BytesIO(file_content) if file_content else None
        text = text_content
        if file_content and not text_content:
            # 尝试解码文本内容（非 PDF）
            if not filename.lower().endswith(".pdf"):
                try:
                    text = file_content.decode("utf-8")
                except UnicodeDecodeError:
                    text = file_content.decode("latin-1")

        chunks = parse_file(file_obj, text, filename)
        if not chunks:
            raise ValueError("No content extracted from file")

        results = []
        for chunk in chunks:
            item = {
                "id": str(uuid.uuid4()),
                "category": category,
                "title": title or chunk.title,
                "content": chunk.content,
                "source_file": filename,
                "source_format": _detect_format(filename),
                "metadata": chunk.metadata,
            }
            saved = self.repo.put_knowledge(item)

            # 异步生成 embedding
            if self.embed_fn:
                try:
                    embedding = self.embed_fn(chunk.content)
                    if embedding:
                        self.repo.update_knowledge_embedding(saved["id"], embedding)
                        saved["has_embedding"] = True
                except Exception:
                    logger.warning(
                        "Failed to generate embedding for %s", saved["id"], exc_info=True
                    )

            results.append(saved)

        return results

    def update_knowledge(
        self,
        knowledge_id: str,
        title: str | None = None,
        content: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any] | None:
        """更新知识库文档。"""
        existing = self.repo.get_knowledge(knowledge_id)
        if not existing:
            return None

        if title is not None:
            existing["title"] = title
        if content is not None:
            existing["content"] = content
            # 内容更新后重新生成 embedding
            if self.embed_fn:
                try:
                    embedding = self.embed_fn(content)
                    if embedding:
                        self.repo.update_knowledge_embedding(knowledge_id, embedding)
                except Exception:
                    logger.warning("Failed to update embedding", exc_info=True)
        if category is not None:
            existing["category"] = category

        return self.repo.put_knowledge(existing)

    def delete_knowledge(self, knowledge_id: str) -> bool:
        """删除知识库文档。"""
        existing = self.repo.get_knowledge(knowledge_id)
        if not existing:
            return False
        self.repo.delete_knowledge(knowledge_id)
        return True

    def search_knowledge(self, query: str, limit: int = 5) -> list[tuple[dict[str, Any], float]]:
        """基于向量相似度搜索知识库。"""
        if not self.embed_fn:
            return []
        embedding = self.embed_fn(query)
        if not embedding:
            return []
        return self.repo.search_knowledge_by_embedding(embedding, limit=limit)

    # -------------------------------------------------------------------------
    # 面试会话管理
    # -------------------------------------------------------------------------

    def create_session(
        self,
        target_role: str,
        difficulty: str = "medium",
        actor: str = "anonymous",
        category: str | None = None,
    ) -> dict[str, Any]:
        """创建新面试会话并发送开场白。"""
        session = self.repo.put_session(
            {
                "id": str(uuid.uuid4()),
                "actor": actor,
                "target_role": target_role,
                "difficulty": difficulty,
                "status": "in_progress",
            }
        )

        # 添加面试官开场白
        opening = get_opening_message(target_role, difficulty, category)
        self.repo.put_message(
            {
                "id": str(uuid.uuid4()),
                "session_id": session["id"],
                "role": "assistant",
                "content": opening,
            }
        )

        return session

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """列出面试会话。"""
        return self.repo.list_sessions(limit=limit)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """获取会话详情及消息。"""
        session = self.repo.get_session(session_id)
        if not session:
            return None
        messages = self.repo.list_messages_by_session(session_id)
        return {"session": session, "messages": messages}

    def delete_session(self, session_id: str) -> bool:
        """删除会话及其消息。"""
        existing = self.repo.get_session(session_id)
        if not existing:
            return False
        self.repo.delete_session(session_id)
        return True

    def end_session(self, session_id: str) -> dict[str, Any] | None:
        """结束面试并生成综合评价。"""
        session = self.repo.get_session(session_id)
        if not session:
            return None

        if session["status"] == "completed":
            return session  # 已经结束

        # 获取所有消息生成总结
        messages = self.repo.list_messages_by_session(session_id)
        conversation = self._format_conversation(messages)

        summary = self._generate_summary(
            target_role=session["target_role"],
            difficulty=session["difficulty"],
            conversation=conversation,
        )

        # 更新会话状态
        session["status"] = "completed"
        session["summary"] = summary
        return self.repo.put_session(session)

    # -------------------------------------------------------------------------
    # 面试对话
    # -------------------------------------------------------------------------

    def stream_response(
        self, session_id: str, user_message: str
    ) -> Generator[dict[str, Any], None, None]:
        """处理用户消息并流式返回面试官回复。"""
        session = self.repo.get_session(session_id)
        if not session:
            yield {"event": "error", "data": {"detail": "Session not found"}}
            return

        if session["status"] == "completed":
            yield {"event": "error", "data": {"detail": "Session already completed"}}
            return

        # 保存用户消息
        self.repo.put_message(
            {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "role": "user",
                "content": user_message,
            }
        )

        # 搜索相关知识
        context = self._get_context(user_message)

        # 获取历史对话
        messages = self.repo.list_messages_by_session(session_id)
        history = self._format_history(messages[-MAX_HISTORY_MESSAGES:])

        # 构建 LLM 消息
        system_prompt = INTERVIEWER_SYSTEM_PROMPT.format(
            target_role=session["target_role"],
            difficulty=session["difficulty"],
            context=context,
            history=history,
        )

        llm_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 调用 LLM
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        if not api_key:
            yield {"event": "error", "data": {"detail": "DEEPSEEK_API_KEY not configured"}}
            return

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url, timeout=DEEPSEEK_STREAM_TIMEOUT)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=llm_messages,
                stream=True,
                temperature=0.7,
                max_tokens=1024,
            )

            collected_content = ""
            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    collected_content += delta.content
                    yield {"event": "delta", "data": {"content": delta.content}}

            # 保存面试官回复
            msg = self.repo.put_message(
                {
                    "id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "role": "assistant",
                    "content": collected_content,
                }
            )

            # 异步评估用户回答（可选，用于生成报告）
            # self._evaluate_answer(session_id, user_message, context)

            yield {"event": "done", "data": {"message_id": msg["id"]}}

        except Exception as exc:
            logger.exception("Interview LLM call failed")
            yield {"event": "error", "data": {"detail": f"LLM service error: {exc}"}}

    def _get_context(self, query: str) -> str:
        """从知识库检索相关内容。"""
        results = self.search_knowledge(query, limit=5)
        if not results:
            return "（无相关知识库内容）"

        parts = []
        for knowledge, score in results:
            if score < 0.5:  # 相似度阈值
                continue
            parts.append(f"【{knowledge['title']}】\n{knowledge['content'][:500]}")

        return "\n\n---\n\n".join(parts) if parts else "（无相关知识库内容）"

    def _format_history(self, messages: list[dict[str, Any]]) -> str:
        """格式化历史对话。"""
        parts = []
        for msg in messages:
            role = "面试官" if msg["role"] == "assistant" else "候选人"
            parts.append(f"{role}: {msg['content']}")
        return "\n\n".join(parts)

    def _format_conversation(self, messages: list[dict[str, Any]]) -> str:
        """格式化完整对话用于生成总结。"""
        parts = []
        for msg in messages:
            role_label = "面试官" if msg["role"] == "assistant" else "候选人"
            parts.append(f"[{role_label}]\n{msg['content']}")
        return "\n\n---\n\n".join(parts)

    def _generate_summary(
        self, target_role: str, difficulty: str, conversation: str
    ) -> dict[str, Any]:
        """生成面试综合评价。"""
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        if not api_key:
            return {"error": "DEEPSEEK_API_KEY not configured"}

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)

        prompt = SUMMARY_PROMPT.format(
            target_role=target_role,
            difficulty=difficulty,
            conversation=conversation,
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
            )

            content = response.choices[0].message.content or "{}"
            # 提取 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except Exception as exc:
            logger.exception("Failed to generate interview summary")
            return {"error": str(exc)}


def _detect_format(filename: str) -> str:
    """根据文件扩展名检测格式。"""
    lower = filename.lower()
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "markdown"
    elif lower.endswith(".pdf"):
        return "pdf"
    elif lower.endswith(".json"):
        return "json"
    elif lower.endswith(".txt"):
        return "txt"
    return "txt"
