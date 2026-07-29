# Conversational Resume Agent Design

A chat-based agent that lets users upload resumes, get job recommendations, ask follow-up questions, adjust preferences, and receive career advice -- all through natural conversation.

## Goals

- Users upload a resume (PDF) and immediately get matched jobs via conversation
- Users can ask follow-up questions about specific jobs, adjust preferences, and get career advice
- Both job seekers and HR/recruiters can use the system
- Conversation history persists across browser sessions

## Architecture

```
Browser Chat UI
    |
    v (SSE stream)
Next.js BFF  /api/chat/*
    |
    v (HTTP)
FastAPI  /api/v1/chat/*
    |
    +-- ChatService (session management + message persistence)
    |
    +-- DeepSeek LLM (Function Calling / tool use)
         |
         +-- tool: parse_resume      -> resume_parser.py
         +-- tool: run_matches       -> service.run_matches()
         +-- tool: search_jobs       -> new: keyword/filter search
         +-- tool: get_job_detail    -> service.get_job()
         +-- tool: update_preferences -> service.update_candidate()
         +-- tool: get_my_profile    -> service.get_candidate()
```

The LLM acts as a dialogue controller. It decides when to call tools based on user intent. All business logic stays in the existing service layer; the chat layer only orchestrates.

## Data Model

Two new PostgreSQL tables via Alembic migration:

### chat_sessions

| Column | Type | Notes |
|--------|------|-------|
| id | VARCHAR(36) PK | UUID |
| candidate_id | VARCHAR(36) FK nullable | Bound after resume upload |
| actor | VARCHAR(100) | Who started the session |
| status | VARCHAR(20) | `active` or `closed` |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### chat_messages

| Column | Type | Notes |
|--------|------|-------|
| id | VARCHAR(36) PK | UUID |
| session_id | VARCHAR(36) FK | -> chat_sessions.id |
| role | VARCHAR(20) | `user`, `assistant`, or `tool` |
| content | TEXT | Message text |
| tool_calls | JSONB nullable | Function calls initiated by LLM |
| tool_call_id | VARCHAR(100) nullable | Matches tool result to its call |
| created_at | TIMESTAMPTZ | |

Messages are stored in their complete form (including tool calls and results) so the full conversation can be replayed as the DeepSeek `messages` array without transformation.

## Tool Definitions

Six tools registered with the DeepSeek function calling API:

### parse_resume

- **Input**: `{pdf_text: string}`
- **Implementation**: `resume_parser.parse_resume(text)`
- **Returns**: Structured candidate data (country, skills, languages, etc.)
- **Side effect**: Creates candidate record, sets consent to opted_in, binds to session

### run_matches

- **Input**: `{candidate_id: string, limit?: int}`
- **Implementation**: `service.run_matches(candidate_id, actor, limit)`
- **Returns**: Matched jobs with scores, breakdowns, and reasons

### search_jobs

- **Input**: `{keyword?: string, country?: string, min_pay?: float, work_mode?: string}`
- **Implementation**: New method. Filters `repo.list("job")` by criteria.
- **Returns**: Matching jobs (without candidate-specific scoring)

### get_job_detail

- **Input**: `{job_id: string}`
- **Implementation**: `repo.get("job", job_id)`
- **Returns**: Full job record including description, requirements, compensation

### update_preferences

- **Input**: `{candidate_id: string, changes: object}`
- **Implementation**: `service.update_candidate(candidate_id, changes, actor)`
- **Returns**: Updated candidate profile
- **Note**: Protected fields (id, consent_status) cannot be changed

### get_my_profile

- **Input**: `{candidate_id: string}`
- **Implementation**: `repo.get("candidate", candidate_id)`
- **Returns**: Current candidate profile with skills, preferences, etc.

## System Prompt

```
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
```

## API Endpoints

### Backend (FastAPI)

```
POST /api/v1/chat/sessions
  -> Creates a new chat session. Returns {id, status, created_at}.

GET  /api/v1/chat/sessions/{id}
  -> Returns session info + all messages (for restoring history).

POST /api/v1/chat/sessions/{id}/messages
  -> Send a user message. Returns SSE stream with assistant response.
  -> Content-Type: text/event-stream

POST /api/v1/chat/sessions/{id}/upload
  -> Upload resume PDF. Extracts text, stores in session context.
  -> Returns {candidate_id, parsed_fields}.
```

### SSE Protocol

The `/messages` endpoint returns a Server-Sent Events stream:

```
event: delta
data: {"content": "partial text token"}

event: tool_call
data: {"name": "run_matches", "arguments": {...}}

event: tool_result
data: {"name": "run_matches", "result": {...}}

event: done
data: {"message_id": "xxx"}

event: error
data: {"detail": "error message"}
```

The frontend reads `delta` events to render streaming text, `tool_call`/`tool_result` to show loading indicators, and `done` to finalize the message.

### Frontend BFF (Next.js)

```
POST /api/chat/sessions           -> proxy to backend
GET  /api/chat/sessions/[id]      -> proxy to backend
POST /api/chat/sessions/[id]/messages -> SSE proxy (stream-through)
POST /api/chat/sessions/[id]/upload   -> proxy file upload to backend
```

## Frontend UI

New `/chat` page added to the console navigation.

### Layout

- **Left panel**: Session list (past conversations), new chat button
- **Right panel**: Active conversation
  - Top bar: candidate summary if bound (name, country, skills count)
  - Message area: scrollable list of messages
  - Input area: text input + PDF upload button + send button

### Message Rendering

- **User messages**: Plain text, right-aligned
- **Assistant messages**: Markdown rendered (via existing setup), left-aligned
- **Match results**: Rendered as interactive cards showing company, title, score bar, top reasons
- **Tool calls**: Shown as subtle status indicators ("Searching jobs..." / "Analyzing resume...")

### Match Result Card

Displayed inline in assistant messages when matches are returned:

```
+------------------------------------------+
| Company Name                     Score 85%|
| Job Title                    [====----]  |
| Reason 1, Reason 2                       |
| [View Details]                           |
+------------------------------------------+
```

## New Files

### Backend

```
agent_hub/agents/global_part_time/
  chat_service.py      # ChatService: session CRUD, LLM orchestration, SSE streaming
  chat_tools.py        # Tool definitions, tool executor dispatch

agent_hub/database/
  models.py            # += ChatSession, ChatMessage SQLAlchemy models
  repository.py        # += chat_session / chat_message kind handlers
```

Register chat routes in `http_api.py` (add `/chat/*` routes to the existing router).

### Frontend

```
frontend/app/(console)/chat/
  page.tsx             # Chat page (session list + conversation area)

frontend/components/
  chat-panel.tsx       # Conversation panel (messages + input)
  chat-message.tsx     # Single message component (markdown + cards)
  match-card.tsx       # Match result card component

frontend/app/api/chat/
  sessions/route.ts                    # BFF: create/list sessions
  sessions/[id]/route.ts              # BFF: get session with history
  sessions/[id]/messages/route.ts     # BFF: send message (SSE proxy)
  sessions/[id]/upload/route.ts       # BFF: upload resume
```

### Database Migration

One Alembic migration adding `chat_sessions` and `chat_messages` tables.

## Conversation Flow Examples

### Flow 1: Resume Upload -> Job Recommendations

```
User: [uploads resume.pdf]
System: extracts PDF text, stores in session
LLM: calls parse_resume(pdf_text) -> creates candidate
LLM: calls run_matches(candidate_id) -> gets matches
Assistant: "I've parsed your resume! Your skills include Python, React, Node.js...
           Here are your top 3 matches:
           [Match Card 1] [Match Card 2] [Match Card 3]"
```

### Flow 2: Follow-up Question

```
User: "Tell me more about the first job"
LLM: calls get_job_detail(job_id)
Assistant: "This is a remote frontend role at XXX Corp..."
```

### Flow 3: Preference Adjustment

```
User: "I only want jobs paying $30/hour or more"
LLM: calls update_preferences(candidate_id, {minimum_hourly_rate: {amount: 30, currency: "USD"}})
LLM: calls run_matches(candidate_id)
Assistant: "Updated! With the $30/h minimum, 5 jobs match: ..."
```

### Flow 4: Career Advice (no tool call)

```
User: "How can I improve my resume?"
LLM: responds directly based on candidate profile context
Assistant: "Based on your profile, I'd suggest..."
```

## Error Handling

- **DeepSeek API failure**: Return SSE `error` event with user-friendly message. Do not crash the stream.
- **Tool execution failure**: Send tool result with error field. LLM will explain the error to the user naturally.
- **PDF parsing failure**: Return error from upload endpoint. Frontend shows inline error.
- **Session not found**: 404 from backend, frontend redirects to new session.
- **Rate limiting**: DeepSeek rate limits handled with retry + backoff in chat_service.

## LLM Configuration

- **Provider**: DeepSeek (OpenAI-compatible API)
- **Env vars**: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`
- **Streaming**: `stream=True` on chat completions
- **Max tokens**: 2048 per response
- **Temperature**: 0.7 (conversational but not too creative)
- **Context window management**: Include system prompt + last N messages (keep under 16k tokens). Summarize older messages if needed.
