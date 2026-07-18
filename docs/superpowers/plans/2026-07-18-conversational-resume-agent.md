# Conversational Resume Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ChatGPT-style chat interface where users upload resumes and get job recommendations via natural conversation powered by DeepSeek function calling.

**Architecture:** DeepSeek LLM orchestrates conversation via function calling, invoking existing service-layer methods (run_matches, get_candidate, etc.) as tools. Backend streams responses via SSE. Frontend renders a chat UI with markdown and match result cards.

**Tech Stack:** Python/FastAPI (SSE streaming), DeepSeek API (OpenAI SDK), PostgreSQL (chat persistence via Alembic), Next.js/React (chat UI), existing AgentService for all business logic.

---

## File Structure

### Backend (new files)

| File | Responsibility |
|------|---------------|
| `src/agent_hub/agents/global_part_time/chat_tools.py` | Tool definitions (JSON schema) + tool executor dispatch |
| `src/agent_hub/agents/global_part_time/chat_service.py` | Session CRUD, message persistence, LLM streaming orchestration |
| `src/agent_hub/database/models.py` | += ChatSession, ChatMessage models |
| `src/agent_hub/database/repository.py` | += chat_session/chat_message kind handlers |
| `src/agent_hub/agents/global_part_time/http_api.py` | += /chat/* routes |
| `src/agent_hub/app.py` | Wire ChatService into app |
| `alembic/versions/20260718_0003_chat_tables.py` | Migration for chat_sessions + chat_messages |

### Frontend (new files)

| File | Responsibility |
|------|---------------|
| `frontend/app/(console)/chat/page.tsx` | Chat page (session list + conversation) |
| `frontend/components/chat-panel.tsx` | Conversation panel (messages + input + upload) |
| `frontend/components/chat-message.tsx` | Single message bubble (markdown + match cards) |
| `frontend/components/match-card.tsx` | Inline match result card |
| `frontend/app/api/chat/sessions/route.ts` | BFF: create/list sessions |
| `frontend/app/api/chat/sessions/[id]/route.ts` | BFF: get session with history |
| `frontend/app/api/chat/sessions/[id]/messages/route.ts` | BFF: send message (SSE proxy) |
| `frontend/app/api/chat/sessions/[id]/upload/route.ts` | BFF: upload resume PDF |
| `frontend/lib/agent-hub.ts` | += chat API client functions |
| `frontend/components/console-shell.tsx` | += chat nav entry |

### Tests

| File | What it tests |
|------|--------------|
| `tests/test_chat_tools.py` | Tool executor dispatch + tool definitions |
| `tests/test_chat_service.py` | Session CRUD, message persistence, LLM call mocking |

---

## Task 1: Database Models + Migration

**Files:**
- Modify: `src/agent_hub/database/models.py` (add ChatSession, ChatMessage after line 464)
- Create: `alembic/versions/20260718_0003_chat_tables.py`

- [ ] **Step 1: Add ChatSession and ChatMessage models to models.py**

Add after the `IdempotencyRecord` class at the end of the file:

```python
# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    candidate_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("candidates.id"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="anonymous")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (Index("ix_chat_sessions_candidate_id", "candidate_id"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_chat_messages_session_id", "session_id"),)
```

- [ ] **Step 2: Create Alembic migration**

Create `alembic/versions/20260718_0003_chat_tables.py`:

```python
"""Add chat_sessions and chat_messages tables.

Revision ID: 20260718_0003
Revises: 20260717_0002
Create Date: 2026-07-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0003"
down_revision: Union[str, None] = "20260717_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("candidates.id"), nullable=True),
        sa.Column("actor", sa.String(100), nullable=False, server_default="anonymous"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_sessions_candidate_id", "chat_sessions", ["candidate_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("chat_sessions.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("tool_calls", postgresql.JSONB, nullable=True),
        sa.Column("tool_call_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
```

- [ ] **Step 3: Run migration**

Run: `docker compose -f compose.dev.yaml exec api alembic upgrade head`

Expected: Tables created successfully.

- [ ] **Step 4: Commit**

```bash
git add src/agent_hub/database/models.py alembic/versions/20260718_0003_chat_tables.py
git commit -m "feat(chat): add ChatSession and ChatMessage database models"
```

---

## Task 2: Repository Chat Support

**Files:**
- Modify: `src/agent_hub/database/repository.py`
- Test: `tests/test_chat_repo.py`

- [ ] **Step 1: Write failing test for chat session CRUD**

Create `tests/test_chat_repo.py`:

```python
"""Tests for chat session and message repository operations."""

from __future__ import annotations

import uuid

import pytest


def _new_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def repo():
    """Create a repository connected to the test database."""
    from agent_hub.database.config import create_repository

    return create_repository()


class TestChatSessionCRUD:
    def test_create_and_get_session(self, repo):
        session_id = _new_id()
        session = repo.put("chat_session", {
            "id": session_id,
            "actor": "test-user",
            "status": "active",
            "candidate_id": None,
        })
        assert session["id"] == session_id
        assert session["status"] == "active"

        fetched = repo.get("chat_session", session_id)
        assert fetched is not None
        assert fetched["actor"] == "test-user"

    def test_list_sessions(self, repo):
        repo.put("chat_session", {"id": _new_id(), "actor": "u1", "status": "active"})
        repo.put("chat_session", {"id": _new_id(), "actor": "u2", "status": "active"})
        sessions = repo.list("chat_session")
        assert len(sessions) >= 2

    def test_bind_candidate_to_session(self, repo):
        session_id = _new_id()
        repo.put("chat_session", {"id": session_id, "actor": "u1", "status": "active"})
        repo.put("chat_session", {
            "id": session_id,
            "actor": "u1",
            "status": "active",
            "candidate_id": "cand-123",
        })
        fetched = repo.get("chat_session", session_id)
        assert fetched["candidate_id"] == "cand-123"


class TestChatMessageCRUD:
    def test_create_and_list_messages(self, repo):
        session_id = _new_id()
        repo.put("chat_session", {"id": session_id, "actor": "u1", "status": "active"})

        msg1_id = _new_id()
        repo.put("chat_message", {
            "id": msg1_id,
            "session_id": session_id,
            "role": "user",
            "content": "Hello",
        })
        msg2_id = _new_id()
        repo.put("chat_message", {
            "id": msg2_id,
            "session_id": session_id,
            "role": "assistant",
            "content": "Hi there!",
            "tool_calls": None,
        })

        messages = repo.list_by_session(session_id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_message_with_tool_calls(self, repo):
        session_id = _new_id()
        repo.put("chat_session", {"id": session_id, "actor": "u1", "status": "active"})

        msg_id = _new_id()
        tool_calls = [{"id": "call_1", "function": {"name": "run_matches", "arguments": "{}"}}]
        repo.put("chat_message", {
            "id": msg_id,
            "session_id": session_id,
            "role": "assistant",
            "content": "",
            "tool_calls": tool_calls,
        })

        messages = repo.list_by_session(session_id)
        assert messages[0]["tool_calls"] == tool_calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f compose.dev.yaml exec api python -m pytest tests/test_chat_repo.py -v`

Expected: FAIL with `ValueError: unknown entity kind: chat_session`

- [ ] **Step 3: Add chat_session and chat_message to repository**

Modify `src/agent_hub/database/repository.py`:

Add imports at the top (after existing model imports):

```python
from agent_hub.database.models import (
    Approval,
    AuditLog,
    Base,
    Candidate,
    ChatMessage,
    ChatSession,
    Feedback,
    IdempotencyRecord,
    Job,
    JobSource,
    Match,
    Notification,
)
```

Add to `_KIND_MAP` dict:

```python
    "chat_session": ChatSession,
    "chat_message": ChatMessage,
```

Add to `_TYPED_COLUMNS` dict:

```python
    "chat_session": lambda p: {
        "candidate_id": p.get("candidate_id"),
        "actor": p.get("actor", "anonymous"),
        "status": p.get("status", "active"),
    },
    "chat_message": lambda p: {
        "session_id": p.get("session_id", ""),
        "role": p.get("role", "user"),
        "content": p.get("content", ""),
        "tool_calls": p.get("tool_calls"),
        "tool_call_id": p.get("tool_call_id"),
    },
```

Add `list_by_session` method to `PostgresRepository` class (after `list` method):

```python
    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Return all chat messages for a session, ordered by creation time ascending."""
        session = self._session()
        owns_session = not self._is_context_session()
        try:
            from agent_hub.database.models import ChatMessage

            rows = (
                session.execute(
                    select(ChatMessage)
                    .filter_by(session_id=session_id)
                    .order_by(ChatMessage.created_at.asc())
                )
                .scalars()
                .all()
            )
            return [
                {
                    "id": row.id,
                    "session_id": row.session_id,
                    "role": row.role,
                    "content": row.content,
                    "tool_calls": row.tool_calls,
                    "tool_call_id": row.tool_call_id,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
                for row in rows
            ]
        finally:
            if owns_session:
                session.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f compose.dev.yaml exec api python -m pytest tests/test_chat_repo.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/database/repository.py tests/test_chat_repo.py
git commit -m "feat(chat): add chat_session and chat_message repository support"
```

---

## Task 3: Chat Tools Definition + Executor

**Files:**
- Create: `src/agent_hub/agents/global_part_time/chat_tools.py`
- Test: `tests/test_chat_tools.py`

- [ ] **Step 1: Write failing test for tool executor**

Create `tests/test_chat_tools.py`:

```python
"""Tests for chat tool definitions and executor."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent_hub.agents.global_part_time.chat_tools import (
    TOOL_DEFINITIONS,
    execute_tool,
)


def test_tool_definitions_are_valid():
    """Each tool must have name, description, and parameters."""
    assert len(TOOL_DEFINITIONS) >= 5
    for tool in TOOL_DEFINITIONS:
        assert "function" in tool
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_execute_get_my_profile():
    service = MagicMock()
    service.get_candidate.return_value = {
        "id": "c1",
        "country": "US",
        "skills": [{"name": "python", "level": 4}],
    }
    result = execute_tool(
        "get_my_profile",
        {"candidate_id": "c1"},
        service=service,
        actor="test",
    )
    assert result["id"] == "c1"
    service.get_candidate.assert_called_once_with("c1")


def test_execute_run_matches():
    service = MagicMock()
    service.run_matches.return_value = {
        "matches": [{"id": "m1", "score": 0.8}],
        "filtered": [],
    }
    result = execute_tool(
        "run_matches",
        {"candidate_id": "c1", "limit": 10},
        service=service,
        actor="test",
    )
    assert len(result["matches"]) == 1
    service.run_matches.assert_called_once_with("c1", "test", 10)


def test_execute_unknown_tool():
    service = MagicMock()
    result = execute_tool("nonexistent", {}, service=service, actor="test")
    assert "error" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f compose.dev.yaml exec api python -m pytest tests/test_chat_tools.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.agents.global_part_time.chat_tools'`

- [ ] **Step 3: Implement chat_tools.py**

Create `src/agent_hub/agents/global_part_time/chat_tools.py`:

```python
"""Chat tool definitions and executor for DeepSeek function calling.

Each tool wraps an existing AgentService method. The TOOL_DEFINITIONS list
provides OpenAI-compatible function schemas. execute_tool() dispatches a
tool call to the correct service method and returns the result as a dict.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .service import AgentService

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "parse_resume",
            "description": "Parse resume text extracted from a PDF into structured candidate data (skills, languages, country, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_text": {
                        "type": "string",
                        "description": "The full text extracted from the resume PDF",
                    },
                },
                "required": ["pdf_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_matches",
            "description": "Run hard-filter and scoring to find matching jobs for a candidate. Returns ranked job matches with scores and reasons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "The candidate ID to match jobs for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of matches to return (default 10)",
                        "default": 10,
                    },
                },
                "required": ["candidate_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Search jobs by keyword, country, minimum pay, or work mode. Use this when the user wants to browse jobs without candidate-specific scoring.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Search keyword to match against job title or description",
                    },
                    "country": {
                        "type": "string",
                        "description": "ISO country code (e.g. US, CN) or GLOBAL",
                    },
                    "min_pay": {
                        "type": "number",
                        "description": "Minimum hourly pay in USD",
                    },
                    "work_mode": {
                        "type": "string",
                        "enum": ["remote", "hybrid", "onsite"],
                        "description": "Work mode filter",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_job_detail",
            "description": "Get full details of a specific job including description, requirements, and compensation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The job ID to look up",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_preferences",
            "description": "Update candidate preferences like minimum hourly rate, work modes, country, or skills. After updating, suggest re-running matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "The candidate ID to update",
                    },
                    "changes": {
                        "type": "object",
                        "description": "Fields to update. Supports: minimum_hourly_rate ({amount, currency}), allowed_work_modes, country, timezone, skills, languages, desired_roles, excluded_companies",
                    },
                },
                "required": ["candidate_id", "changes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_profile",
            "description": "Get the current candidate profile including skills, preferences, and consent status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "The candidate ID to look up",
                    },
                },
                "required": ["candidate_id"],
            },
        },
    },
]


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    service: AgentService,
    actor: str,
) -> dict[str, Any]:
    """Execute a tool call and return the result as a JSON-serializable dict."""
    try:
        if name == "parse_resume":
            from .resume_parser import parse_resume

            parsed = parse_resume(arguments["pdf_text"])
            candidate = service.create_candidate(parsed, actor)
            service.set_consent(candidate["id"], True, actor, "chat_upload")
            return {"candidate": candidate, "parsed_fields": parsed}

        if name == "run_matches":
            candidate_id = arguments["candidate_id"]
            limit = arguments.get("limit", 10)
            result = service.run_matches(candidate_id, actor, limit)
            # Enrich matches with job details
            jobs_by_id = {j["id"]: j for j in service.repo.list("job")}
            for match in result.get("matches", []):
                job = jobs_by_id.get(match.get("job_id"))
                if job:
                    match["job_title"] = job.get("title_original", "")
                    match["company_name"] = job.get("company_name", "")
                    match["compensation_min"] = job.get("compensation_min")
                    match["compensation_max"] = job.get("compensation_max")
                    match["compensation_currency"] = job.get("compensation_currency", "USD")
                    match["work_mode"] = job.get("work_mode", "remote")
            return result

        if name == "search_jobs":
            keyword = (arguments.get("keyword") or "").lower()
            country = arguments.get("country")
            min_pay = arguments.get("min_pay")
            work_mode = arguments.get("work_mode")
            jobs = service.repo.list("job")
            results = []
            for job in jobs:
                if job.get("status") != "active":
                    continue
                if keyword and keyword not in (job.get("title_original", "") + " " + job.get("description_original", "")).lower():
                    continue
                if country:
                    allowed = job.get("countries_allowed") or []
                    if "GLOBAL" not in allowed and country not in allowed:
                        continue
                if min_pay and (job.get("compensation_max") or 0) < min_pay:
                    continue
                if work_mode and job.get("work_mode") != work_mode:
                    continue
                results.append({
                    "id": job["id"],
                    "title": job.get("title_original", ""),
                    "company": job.get("company_name", ""),
                    "country": job.get("countries_allowed", []),
                    "compensation_max": job.get("compensation_max"),
                    "work_mode": job.get("work_mode"),
                })
                if len(results) >= 20:
                    break
            return {"jobs": results, "total": len(results)}

        if name == "get_job_detail":
            job = service.repo.get("job", arguments["job_id"])
            if job is None:
                return {"error": f"Job {arguments['job_id']} not found"}
            return job

        if name == "update_preferences":
            candidate_id = arguments["candidate_id"]
            changes = arguments["changes"]
            updated = service.update_candidate(candidate_id, changes, actor)
            return updated

        if name == "get_my_profile":
            candidate = service.get_candidate(arguments["candidate_id"])
            return candidate

        return {"error": f"Unknown tool: {name}"}

    except Exception as exc:
        logger.exception("Tool %s execution failed", name)
        return {"error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f compose.dev.yaml exec api python -m pytest tests/test_chat_tools.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/chat_tools.py tests/test_chat_tools.py
git commit -m "feat(chat): add tool definitions and executor for function calling"
```

---

## Task 4: ChatService (LLM Orchestration + SSE Streaming)

**Files:**
- Create: `src/agent_hub/agents/global_part_time/chat_service.py`
- Test: `tests/test_chat_service.py`

- [ ] **Step 1: Write failing test for ChatService**

Create `tests/test_chat_service.py`:

```python
"""Tests for ChatService session management and LLM orchestration."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from agent_hub.agents.global_part_time.chat_service import ChatService


@pytest.fixture()
def repo():
    from agent_hub.database.config import create_repository

    return create_repository()


@pytest.fixture()
def service(repo):
    from agent_hub.agents.global_part_time.service import AgentService

    return AgentService(repo)


@pytest.fixture()
def chat_service(service, repo):
    return ChatService(service=service, repo=repo)


class TestSessionManagement:
    def test_create_session(self, chat_service):
        session = chat_service.create_session(actor="test-user")
        assert session["id"]
        assert session["status"] == "active"
        assert session["actor"] == "test-user"
        assert session["candidate_id"] is None

    def test_get_session_with_messages(self, chat_service):
        session = chat_service.create_session(actor="test-user")
        chat_service.add_message(session["id"], "user", "Hello")
        chat_service.add_message(session["id"], "assistant", "Hi there!")

        result = chat_service.get_session(session["id"])
        assert result["session"]["id"] == session["id"]
        assert len(result["messages"]) == 2
        assert result["messages"][0]["content"] == "Hello"
        assert result["messages"][1]["content"] == "Hi there!"

    def test_get_nonexistent_session(self, chat_service):
        result = chat_service.get_session("nonexistent")
        assert result is None

    def test_list_sessions(self, chat_service):
        chat_service.create_session(actor="u1")
        chat_service.create_session(actor="u2")
        sessions = chat_service.list_sessions()
        assert len(sessions) >= 2

    def test_bind_candidate(self, chat_service):
        session = chat_service.create_session(actor="test")
        chat_service.bind_candidate(session["id"], "cand-123")
        result = chat_service.get_session(session["id"])
        assert result["session"]["candidate_id"] == "cand-123"


class TestMessageHistory:
    def test_build_llm_messages(self, chat_service):
        session = chat_service.create_session(actor="test")
        chat_service.add_message(session["id"], "user", "Hello")
        chat_service.add_message(session["id"], "assistant", "Hi!")

        messages = chat_service.build_llm_messages(session["id"])
        # Should include system prompt + 2 messages
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Hello"
        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "Hi!"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f compose.dev.yaml exec api python -m pytest tests/test_chat_service.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement ChatService**

Create `src/agent_hub/agents/global_part_time/chat_service.py`:

```python
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

from openai import OpenAI

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
        return self.repo.put("chat_session", {
            "id": session_id,
            "actor": actor,
            "status": "active",
            "candidate_id": None,
        })

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
        self, session_id: str, candidate_id: str | None = None,
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
        self, session_id: str, user_message: str,
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
                                current_tool_call["function"]["arguments"] += tc_delta.function.arguments

                # Check finish reason
                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None

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
                    session_id, "assistant", collected_content,
                    tool_calls=serializable_calls,
                )

                # Add assistant message to LLM context
                llm_messages.append({
                    "role": "assistant",
                    "content": collected_content or None,
                    "tool_calls": serializable_calls,
                })

                # Execute each tool call
                for tc in collected_tool_calls:
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        tool_args = {}

                    yield {"event": "tool_call", "data": {"name": tool_name, "arguments": tool_args}}

                    result = execute_tool(
                        tool_name, tool_args,
                        service=self.service, actor=actor,
                    )

                    # If parse_resume created a candidate, bind to session
                    if tool_name == "parse_resume" and "candidate" in result:
                        new_candidate_id = result["candidate"]["id"]
                        self.bind_candidate(session_id, new_candidate_id)
                        candidate_id = new_candidate_id

                    yield {"event": "tool_result", "data": {"name": tool_name, "result": result}}

                    # Save tool result message
                    result_content = json.dumps(result, ensure_ascii=False, default=str)
                    # Truncate very large results
                    if len(result_content) > 8000:
                        result_content = result_content[:8000] + "...(truncated)"
                    self.add_message(
                        session_id, "tool", result_content,
                        tool_call_id=tc["id"],
                    )

                    # Add to LLM context
                    llm_messages.append({
                        "role": "tool",
                        "content": result_content,
                        "tool_call_id": tc["id"],
                    })

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f compose.dev.yaml exec api python -m pytest tests/test_chat_service.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/chat_service.py tests/test_chat_service.py
git commit -m "feat(chat): add ChatService with LLM orchestration and SSE streaming"
```

---

## Task 5: Backend API Routes

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/http_api.py` (add chat routes)
- Modify: `src/agent_hub/app.py` (wire ChatService)

- [ ] **Step 1: Wire ChatService into app.py**

In `src/agent_hub/app.py`, after line 78 (`part_time_service = AgentService(repo, expand_fn=expand_fn)`), add:

```python
    from .agents.global_part_time.chat_service import ChatService

    chat_service = ChatService(service=part_time_service, repo=repo)
```

After line 127 (`application.state.celery_app = celery_instance`), add:

```python
    application.state.chat_service = chat_service
```

- [ ] **Step 2: Add chat routes to http_api.py**

Add at the end of `src/agent_hub/agents/global_part_time/http_api.py` (after the `upload_resume` endpoint):

```python
# ---------------------------------------------------------------------------
# Chat endpoints
# ---------------------------------------------------------------------------


def _chat_service(request: Request):
    return request.app.state.chat_service


ChatServiceDep = Annotated[Any, Depends(_chat_service)]


class ChatMessageRequest(APIModel):
    content: str = Field(min_length=1, max_length=5000)


@router.post("/chat/sessions", status_code=201)
def create_chat_session(actor: Actor) -> dict[str, Any]:
    from .chat_service import ChatService

    # Get chat service from app state via dependency
    import inspect
    frame = inspect.currentframe()
    # Simple approach: create inline
    from agent_hub.database.config import create_repository
    from .service import AgentService

    # This will be overridden by the proper dependency below
    raise NotImplementedError("use the request-based route")


# Proper routes using Request for access to app.state
@router.post("/chat/sessions", status_code=201, name="create_chat_session")
def create_chat_session(request: Request, actor: Actor) -> dict[str, Any]:
    chat_svc = request.app.state.chat_service
    return chat_svc.create_session(actor=actor)


@router.get("/chat/sessions")
def list_chat_sessions(request: Request) -> list[dict[str, Any]]:
    chat_svc = request.app.state.chat_service
    return chat_svc.list_sessions()


@router.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str, request: Request) -> dict[str, Any]:
    chat_svc = request.app.state.chat_service
    result = chat_svc.get_session(session_id)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Session not found"})
    return result


@router.post("/chat/sessions/{session_id}/messages")
def send_chat_message(
    session_id: str,
    body: ChatMessageRequest,
    request: Request,
):
    from fastapi.responses import StreamingResponse

    chat_svc = request.app.state.chat_service

    def event_stream():
        import json

        for event in chat_svc.stream_response(session_id, body.content):
            event_type = event["event"]
            event_data = json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {event_type}\ndata: {event_data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chat/sessions/{session_id}/upload", status_code=201)
def upload_chat_resume(
    session_id: str,
    file: UploadFile,
    request: Request,
    actor: Actor,
):
    chat_svc = request.app.state.chat_service

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=422, content={"detail": "仅支持 PDF 文件"})

    pdf_bytes = file.file.read()
    if not pdf_bytes:
        return JSONResponse(status_code=422, content={"detail": "文件为空"})

    try:
        from .resume_parser import extract_text_from_pdf
    except ImportError as exc:
        return JSONResponse(status_code=501, content={"detail": f"简历解析依赖未安装: {exc}"})

    try:
        text = extract_text_from_pdf(pdf_bytes)
    except Exception as exc:
        return JSONResponse(status_code=422, content={"detail": f"PDF 解析失败: {exc}"})

    if not text.strip():
        return JSONResponse(status_code=422, content={"detail": "无法从 PDF 中提取文本"})

    # Store the extracted text as a user message so the LLM can use it
    chat_svc.add_message(session_id, "user", f"[简历内容]\n{text}")

    return {"session_id": session_id, "resume_text_length": len(text), "status": "uploaded"}
```

Wait — that first `create_chat_session` is wrong. Let me fix the actual code. Replace the entire chat section with:

```python
# ---------------------------------------------------------------------------
# Chat endpoints
# ---------------------------------------------------------------------------


class ChatMessageRequest(APIModel):
    content: str = Field(min_length=1, max_length=5000)


@router.post("/chat/sessions", status_code=201)
def create_chat_session(request: Request, actor: Actor) -> dict[str, Any]:
    chat_svc = request.app.state.chat_service
    return chat_svc.create_session(actor=actor)


@router.get("/chat/sessions")
def list_chat_sessions(request: Request) -> list[dict[str, Any]]:
    chat_svc = request.app.state.chat_service
    return chat_svc.list_sessions()


@router.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str, request: Request) -> dict[str, Any]:
    chat_svc = request.app.state.chat_service
    result = chat_svc.get_session(session_id)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Session not found"})
    return result


@router.post("/chat/sessions/{session_id}/messages")
def send_chat_message(
    session_id: str,
    body: ChatMessageRequest,
    request: Request,
):
    import json as _json

    from fastapi.responses import StreamingResponse

    chat_svc = request.app.state.chat_service

    def event_stream():
        for event in chat_svc.stream_response(session_id, body.content):
            event_type = event["event"]
            event_data = _json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {event_type}\ndata: {event_data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chat/sessions/{session_id}/upload", status_code=201)
def upload_chat_resume(
    session_id: str,
    file: UploadFile,
    request: Request,
    actor: Actor,
):
    chat_svc = request.app.state.chat_service

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=422, content={"detail": "仅支持 PDF 文件"})

    pdf_bytes = file.file.read()
    if not pdf_bytes:
        return JSONResponse(status_code=422, content={"detail": "文件为空"})

    try:
        from .resume_parser import extract_text_from_pdf
    except ImportError as exc:
        return JSONResponse(status_code=501, content={"detail": f"简历解析依赖未安装: {exc}"})

    try:
        text = extract_text_from_pdf(pdf_bytes)
    except Exception as exc:
        return JSONResponse(status_code=422, content={"detail": f"PDF 解析失败: {exc}"})

    if not text.strip():
        return JSONResponse(status_code=422, content={"detail": "无法从 PDF 中提取文本"})

    # Store extracted text as user message for LLM context
    chat_svc.add_message(session_id, "user", f"[简历内容]\n{text}")

    return {"session_id": session_id, "resume_text_length": len(text), "status": "uploaded"}
```

- [ ] **Step 3: Test the API starts successfully**

Run: `docker compose -f compose.dev.yaml restart api`

Then: `curl -s http://127.0.0.1:8000/health`

Expected: `{"status":"ok","registered_agents":1}`

- [ ] **Step 4: Test session creation via curl**

Run:
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/sessions \
  -H "X-Actor: test-user" | python3 -m json.tool
```

Expected: JSON with `id`, `status: "active"`, `actor: "test-user"`

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/http_api.py src/agent_hub/app.py
git commit -m "feat(chat): add chat API routes (sessions, messages SSE, upload)"
```

---

## Task 6: Frontend BFF Routes

**Files:**
- Create: `frontend/app/api/chat/sessions/route.ts`
- Create: `frontend/app/api/chat/sessions/[id]/route.ts`
- Create: `frontend/app/api/chat/sessions/[id]/messages/route.ts`
- Create: `frontend/app/api/chat/sessions/[id]/upload/route.ts`

- [ ] **Step 1: Create sessions route (create + list)**

Create `frontend/app/api/chat/sessions/route.ts`:

```typescript
import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export async function POST(request: NextRequest) {
  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions`, {
      method: 'POST',
      headers: {
        'X-Actor': 'chat-user',
      },
      signal: AbortSignal.timeout(5000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}

export async function GET() {
  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions`, {
      signal: AbortSignal.timeout(5000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json([], { status: 200 });
  }
}
```

- [ ] **Step 2: Create session detail route**

Create `frontend/app/api/chat/sessions/[id]/route.ts`:

```typescript
import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions/${id}`, {
      signal: AbortSignal.timeout(5000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
```

- [ ] **Step 3: Create messages SSE route**

Create `frontend/app/api/chat/sessions/[id]/messages/route.ts`:

```typescript
import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json();

  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions/${id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(120000),
    });

    if (!response.ok) {
      return new Response(await response.text(), {
        status: response.status,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Stream-through the SSE response
    return new Response(response.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
```

- [ ] **Step 4: Create upload route**

Create `frontend/app/api/chat/sessions/[id]/upload/route.ts`:

```typescript
import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const formData = await request.formData();

  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions/${id}/upload`, {
      method: 'POST',
      headers: { 'X-Actor': 'chat-user' },
      body: formData,
      signal: AbortSignal.timeout(30000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/app/api/chat/
git commit -m "feat(chat): add frontend BFF routes for chat API"
```

---

## Task 7: Frontend Chat Components

**Files:**
- Create: `frontend/components/match-card.tsx`
- Create: `frontend/components/chat-message.tsx`
- Create: `frontend/components/chat-panel.tsx`

- [ ] **Step 1: Create match-card.tsx**

Create `frontend/components/match-card.tsx`:

```tsx
export function MatchCard({
  title,
  company,
  score,
  reasons,
  workMode,
  compensation,
}: {
  title: string;
  company: string;
  score: number;
  reasons: string[];
  workMode?: string;
  compensation?: string;
}) {
  const pct = Math.round(score * 100);
  return (
    <div className="match-card">
      <div className="match-card-header">
        <div>
          <div className="match-card-title">{title}</div>
          <div className="match-card-company">{company}</div>
        </div>
        <div className="match-card-score">{pct}%</div>
      </div>
      <div className="match-card-bar">
        <div className="match-card-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="match-card-meta">
        {workMode && <span className="tag">{workMode}</span>}
        {compensation && <span className="tag">{compensation}</span>}
      </div>
      {reasons.length > 0 && (
        <div className="match-card-reasons">
          {reasons.map((r) => (
            <span className="tag" key={r}>{r}</span>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create chat-message.tsx**

Create `frontend/components/chat-message.tsx`:

```tsx
import { MatchCard } from './match-card';

type ToolData = {
  name: string;
  result?: {
    matches?: Array<{
      job_title?: string;
      company_name?: string;
      score?: number;
      reasons?: string[];
      work_mode?: string;
      compensation_max?: number;
      compensation_currency?: string;
    }>;
  };
};

export function ChatMessage({
  role,
  content,
  toolData,
  isStreaming,
}: {
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolData?: ToolData;
  isStreaming?: boolean;
}) {
  if (role === 'tool') return null;

  const isUser = role === 'user';

  // Check if content has match results embedded (from tool_result)
  const matchCards =
    toolData?.name === 'run_matches' && toolData.result?.matches
      ? toolData.result.matches.slice(0, 5)
      : null;

  return (
    <div className={`chat-message ${isUser ? 'chat-message-user' : 'chat-message-assistant'}`}>
      <div className="chat-bubble">
        {content && <div className="chat-content">{content}</div>}
        {matchCards && (
          <div className="chat-matches">
            {matchCards.map((m, i) => (
              <MatchCard
                key={i}
                title={m.job_title ?? 'Unknown'}
                company={m.company_name ?? ''}
                score={m.score ?? 0}
                reasons={m.reasons ?? []}
                workMode={m.work_mode}
                compensation={
                  m.compensation_max
                    ? `$${m.compensation_max}/h ${m.compensation_currency ?? ''}`
                    : undefined
                }
              />
            ))}
          </div>
        )}
        {isStreaming && <span className="chat-cursor" />}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create chat-panel.tsx**

Create `frontend/components/chat-panel.tsx`:

```tsx
'use client';

import { useEffect, useRef, useState } from 'react';
import { ChatMessage } from './chat-message';

type Message = {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolData?: { name: string; result?: any };
};

export function ChatPanel({ sessionId }: { sessionId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load history on mount
  useEffect(() => {
    fetch(`/api/chat/sessions/${sessionId}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.messages) {
          setMessages(
            data.messages
              .filter((m: any) => m.role !== 'tool')
              .map((m: any) => ({
                id: m.id,
                role: m.role,
                content: m.content,
              })),
          );
        }
      })
      .catch(() => {});
  }, [sessionId]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleSend() {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');

    // Add user message
    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);

    // Start streaming
    setIsStreaming(true);
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }]);

    try {
      const response = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      });

      if (!response.ok) {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, content: 'Error: request failed' } : m)),
        );
        setIsStreaming(false);
        return;
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let eventType = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              const dataStr = line.slice(6);
              try {
                const data = JSON.parse(dataStr);

                if (eventType === 'delta') {
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId ? { ...m, content: m.content + data.content } : m,
                    ),
                  );
                } else if (eventType === 'tool_call') {
                  // Show loading indicator
                  const toolLabel =
                    data.name === 'run_matches'
                      ? 'Matching jobs...'
                      : data.name === 'parse_resume'
                        ? 'Parsing resume...'
                        : data.name === 'search_jobs'
                          ? 'Searching...'
                          : data.name === 'get_job_detail'
                            ? 'Loading job...'
                            : 'Processing...';
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId ? { ...m, content: m.content || toolLabel } : m,
                    ),
                  );
                } else if (eventType === 'tool_result') {
                  // If it's a match result, attach the data
                  if (data.name === 'run_matches' && data.result?.matches) {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantId
                          ? { ...m, content: '', toolData: { name: data.name, result: data.result } }
                          : m,
                      ),
                    );
                  }
                } else if (eventType === 'done') {
                  // Complete
                } else if (eventType === 'error') {
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId ? { ...m, content: `Error: ${data.detail}` } : m,
                    ),
                  );
                }
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: 'Network error. Please retry.' } : m,
        ),
      );
    } finally {
      setIsStreaming(false);
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`/api/chat/sessions/${sessionId}/upload`, {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        // After upload, send a message to trigger resume parsing
        setInput('');
        const userMsg: Message = {
          id: crypto.randomUUID(),
          role: 'user',
          content: `I uploaded my resume: ${file.name}. Please analyze it and find matching jobs for me.`,
        };
        setMessages((prev) => [...prev, userMsg]);

        // Trigger LLM to process the resume
        setIsStreaming(true);
        const assistantId = crypto.randomUUID();
        setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }]);

        const response = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            content: 'I just uploaded my resume. Please use the parse_resume tool on the resume text from my previous message to extract my profile, then run_matches to find suitable jobs.',
          }),
        });

        if (response.ok && response.body) {
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            let eventType = '';
            for (const line of lines) {
              if (line.startsWith('event: ')) {
                eventType = line.slice(7).trim();
              } else if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6));
                  if (eventType === 'delta') {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantId ? { ...m, content: m.content + data.content } : m,
                      ),
                    );
                  } else if (eventType === 'tool_result' && data.name === 'run_matches') {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantId
                          ? { ...m, content: '', toolData: { name: data.name, result: data.result } }
                          : m,
                      ),
                    );
                  }
                } catch {}
              }
            }
          }
        }
        setIsStreaming(false);
      } else {
        const data = await res.json();
        alert(data.detail ?? 'Upload failed');
      }
    } catch {
      alert('Upload failed');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <h2>Agent Hub Assistant</h2>
            <p>Upload your resume or describe your skills to get started.</p>
          </div>
        )}
        {messages.map((msg) => (
          <ChatMessage
            key={msg.id}
            role={msg.role}
            content={msg.content}
            toolData={msg.toolData}
            isStreaming={isStreaming && msg.id === messages[messages.length - 1]?.id && msg.role === 'assistant'}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-input-area">
        <input
          type="file"
          accept=".pdf"
          ref={fileInputRef}
          onChange={handleUpload}
          style={{ display: 'none' }}
        />
        <button
          className="chat-upload-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={isStreaming || isUploading}
          title="Upload Resume PDF"
        >
          {isUploading ? '...' : '📎'}
        </button>
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder="Type a message..."
          disabled={isStreaming}
        />
        <button className="chat-send-btn" onClick={handleSend} disabled={!input.trim() || isStreaming}>
          Send
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/components/match-card.tsx frontend/components/chat-message.tsx frontend/components/chat-panel.tsx
git commit -m "feat(chat): add frontend chat components (panel, message, match card)"
```

---

## Task 8: Chat Page + Navigation

**Files:**
- Create: `frontend/app/(console)/chat/page.tsx`
- Modify: `frontend/components/console-shell.tsx` (add nav entry)

- [ ] **Step 1: Create chat page**

Create `frontend/app/(console)/chat/page.tsx`:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { ChatPanel } from '../../../components/chat-panel';

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<Array<{ id: string; created_at?: string }>>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/chat/sessions')
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setSessions(data);
          // Auto-select the most recent active session
          const active = data.find((s: any) => s.status === 'active');
          if (active) setSessionId(active.id);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function handleNewSession() {
    try {
      const res = await fetch('/api/chat/sessions', { method: 'POST' });
      const data = await res.json();
      if (data.id) {
        setSessionId(data.id);
        setSessions((prev) => [data, ...prev]);
      }
    } catch {
      alert('Failed to create session');
    }
  }

  if (loading) {
    return <div className="panel"><div className="panel-body">Loading...</div></div>;
  }

  return (
    <div className="chat-page">
      <aside className="chat-sidebar">
        <button className="button" onClick={handleNewSession} style={{ width: '100%', marginBottom: 12 }}>
          + New Chat
        </button>
        <div className="chat-session-list">
          {sessions.map((s) => (
            <button
              key={s.id}
              className={`chat-session-item ${s.id === sessionId ? 'active' : ''}`}
              onClick={() => setSessionId(s.id)}
            >
              <span className="chat-session-id">{s.id.slice(0, 8)}...</span>
              {s.created_at && (
                <span className="chat-session-date">
                  {new Date(s.created_at).toLocaleDateString('zh-CN')}
                </span>
              )}
            </button>
          ))}
        </div>
      </aside>
      <div className="chat-main">
        {sessionId ? (
          <ChatPanel sessionId={sessionId} />
        ) : (
          <div className="chat-empty">
            <h2>Agent Hub Assistant</h2>
            <p>Click &quot;+ New Chat&quot; to start a conversation.</p>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add chat to navigation**

Modify `frontend/components/console-shell.tsx`, add to `businessNav` array:

```typescript
const businessNav = [
  { href: "/sources", label: "职位来源", glyph: "A" },
  { href: "/jobs", label: "职位中心", glyph: "B" },
  { href: "/candidates", label: "候选人", glyph: "C" },
  { href: "/matches", label: "匹配与推荐", glyph: "D" },
  { href: "/notifications", label: "通知中心", glyph: "E" },
  { href: "/workflows", label: "工作流", glyph: "F" },
  { href: "/chat", label: "AI 助手", glyph: "G" },
];
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/\(console\)/chat/page.tsx frontend/components/console-shell.tsx
git commit -m "feat(chat): add chat page and navigation entry"
```

---

## Task 9: Chat CSS Styles

**Files:**
- Identify and modify the global CSS file used by the app

- [ ] **Step 1: Find the global CSS file**

Run: `find frontend -name "*.css" | head -10` to locate the main stylesheet.

- [ ] **Step 2: Add chat styles**

Append to the global CSS file:

```css
/* ── Chat ── */
.chat-page {
  display: flex;
  height: calc(100vh - 64px);
  gap: 0;
}
.chat-sidebar {
  width: 240px;
  border-right: 1px solid var(--line);
  padding: 16px;
  overflow-y: auto;
  flex-shrink: 0;
}
.chat-session-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.chat-session-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
  cursor: pointer;
  font-size: 12px;
  text-align: left;
  width: 100%;
}
.chat-session-item:hover { background: var(--bg-hover); }
.chat-session-item.active { border-color: var(--accent); background: var(--bg-hover); }
.chat-session-id { font-family: var(--mono); }
.chat-session-date { color: var(--fg-muted); font-size: 11px; }
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--fg-muted);
}
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.chat-welcome {
  text-align: center;
  color: var(--fg-muted);
  margin: auto;
}
.chat-message { max-width: 80%; }
.chat-message-user { align-self: flex-end; }
.chat-message-assistant { align-self: flex-start; }
.chat-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
}
.chat-message-user .chat-bubble {
  background: var(--accent);
  color: white;
  border-bottom-right-radius: 4px;
}
.chat-message-assistant .chat-bubble {
  background: var(--bg-hover);
  border-bottom-left-radius: 4px;
}
.chat-content { white-space: pre-wrap; word-break: break-word; }
.chat-cursor {
  display: inline-block;
  width: 2px;
  height: 16px;
  background: var(--fg);
  animation: blink 1s infinite;
  vertical-align: text-bottom;
  margin-left: 2px;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
.chat-matches { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.chat-input-area {
  display: flex;
  gap: 8px;
  padding: 16px 24px;
  border-top: 1px solid var(--line);
  align-items: center;
}
.chat-input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 14px;
  background: var(--bg);
  color: var(--fg);
  outline: none;
}
.chat-input:focus { border-color: var(--accent); }
.chat-send-btn, .chat-upload-btn {
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}
.chat-send-btn {
  background: var(--accent);
  color: white;
}
.chat-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.chat-upload-btn {
  background: var(--bg-hover);
  font-size: 18px;
  padding: 8px 12px;
}
.chat-upload-btn:disabled { opacity: 0.5; }

/* Match card */
.match-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: var(--bg);
}
.match-card-header { display: flex; justify-content: space-between; align-items: flex-start; }
.match-card-title { font-weight: 600; font-size: 13px; }
.match-card-company { font-size: 12px; color: var(--fg-muted); }
.match-card-score { font-weight: 700; font-size: 18px; color: var(--accent); }
.match-card-bar {
  height: 4px;
  background: var(--line);
  border-radius: 2px;
  margin: 8px 0;
}
.match-card-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
}
.match-card-meta { display: flex; gap: 4px; flex-wrap: wrap; }
.match-card-reasons { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/globals.css  # or wherever the styles live
git commit -m "feat(chat): add chat UI styles"
```

---

## Task 10: Integration Test + Final Verification

- [ ] **Step 1: Run Alembic migration**

```bash
docker compose -f compose.dev.yaml exec api alembic upgrade head
```

- [ ] **Step 2: Restart API**

```bash
docker compose -f compose.dev.yaml restart api
```

- [ ] **Step 3: Verify API health**

```bash
curl -s http://127.0.0.1:8000/health
```

Expected: `{"status":"ok","registered_agents":1}`

- [ ] **Step 4: Test full chat flow via curl**

```bash
# Create session
SESSION=$(curl -s -X POST http://127.0.0.1:8000/api/v1/chat/sessions -H "X-Actor: test" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "Session: $SESSION"

# Send message (will stream SSE)
curl -N -X POST "http://127.0.0.1:8000/api/v1/chat/sessions/$SESSION/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "Hi! I am a Python developer looking for remote jobs."}' 2>&1 | head -20
```

Expected: SSE events with `delta` content streaming back.

- [ ] **Step 5: Start frontend and verify chat page**

```bash
cd frontend && pnpm dev
```

Open `http://localhost:3000/chat` in browser. Verify:
- Chat page loads with session list
- "New Chat" button works
- Messages can be sent and stream back
- Navigation shows "AI 助手" entry

- [ ] **Step 6: Run all tests**

```bash
docker compose -f compose.dev.yaml exec api python -m pytest tests/test_chat_tools.py tests/test_chat_service.py tests/test_chat_repo.py -v
```

Expected: All tests PASS.

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat(chat): complete conversational resume agent integration"
```
