# 申请材料生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 聊天助手可针对具体岗位一键生成定制求职信 + 中文简历优化建议 + 申请链接（提示词驱动，卡片/抽屉按钮与自然语言同一链路）。

**Architecture:** 不新增服务组件。简历原文存入 candidate JSONB payload（`resume_text`，写入上限 20000 字符）；`get_my_profile` 工具返回截断版（6000 字符）；SYSTEM_PROMPT 新增材料生成指引，由主聊天 LLM 调 `get_job_detail` + `get_my_profile` 后流式生成；前端卡片/抽屉按钮通过 `sendPrompt` 发预置消息。

**Tech Stack:** FastAPI + 现有聊天工具循环（chat_tools/chat_service）、React 19（chat-panel/match-card/job-detail-drawer）、pytest。

**规格:** `docs/superpowers/specs/2026-07-19-application-kit-design.md`

**注意事项（执行者必读）:**
- 测试命令统一为：`cd /Users/linguo/Desktop/codes/my-agent && source .venv/bin/activate && set -a && source .env && set +a && python -m pytest ...`（需要 DATABASE_URL 等环境变量）。
- `tests/test_chat_service.py::TestSessionManagement::test_bind_candidate` 是已知的预存在失败（假 candidate_id 撞真实外键），与本计划无关，不要试图修复。
- 简历上传分析跑在 Celery worker 容器里且**不热重载**——改完 chat_tools 后需 `docker restart my-agent-worker-1` 才能在真实上传链路生效（单元测试不受影响）。
- 前端检查：`cd frontend && pnpm exec tsc --noEmit`（忽略 `jobs/page.tsx`、`db/index.ts`、`worker/index.ts` 的预存在报错）和 `pnpm exec eslint <改动文件>`。

---

### Task 1: parse_resume 持久化简历原文

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/chat_tools.py`（`execute_tool` 的 `parse_resume` 分支，约 153-159 行）
- Test: `tests/test_chat_tools.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/test_chat_tools.py` 追加（文件已有 `from unittest.mock import MagicMock` 与 `execute_tool` 导入，沿用即可）：

```python
def test_execute_parse_resume_persists_resume_text(monkeypatch):
    import agent_hub.agents.global_part_time.resume_parser as rp

    monkeypatch.setattr(rp, "parse_resume", lambda text: {"country": "CN", "skills": []})
    service = MagicMock()
    service.create_candidate.return_value = {"id": "c1", "resume_text": "张三的简历原文"}
    result = execute_tool(
        "parse_resume", {"pdf_text": "张三的简历原文"}, service=service, actor="t"
    )
    # 建档 payload 里带原文
    created_payload = service.create_candidate.call_args[0][0]
    assert created_payload["resume_text"] == "张三的简历原文"
    # 工具返回值不回显原文（避免撑爆 LLM 上下文与 tool 消息）
    assert "resume_text" not in result["candidate"]


def test_execute_parse_resume_caps_resume_text_at_20000(monkeypatch):
    import agent_hub.agents.global_part_time.resume_parser as rp

    monkeypatch.setattr(rp, "parse_resume", lambda text: {"country": "CN", "skills": []})
    service = MagicMock()
    service.create_candidate.return_value = {"id": "c1"}
    execute_tool("parse_resume", {"pdf_text": "x" * 25000}, service=service, actor="t")
    created_payload = service.create_candidate.call_args[0][0]
    assert len(created_payload["resume_text"]) == 20000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chat_tools.py -q -k parse_resume`
Expected: 2 FAILED（`KeyError: 'resume_text'` 之类——分支尚未写入该字段）

- [ ] **Step 3: Write minimal implementation**

`chat_tools.py` 模块顶部（`TOOL_DEFINITIONS` 之前或 logger 附近）加常量：

```python
# 简历原文入库上限：防止超大 PDF 撑爆 candidate payload（会随多个接口返回）。
RESUME_TEXT_STORE_LIMIT = 20000
```

`parse_resume` 分支改为：

```python
        if name == "parse_resume":
            from .resume_parser import parse_resume

            parsed = parse_resume(arguments["pdf_text"])
            candidate = service.create_candidate(
                {**parsed, "resume_text": arguments["pdf_text"][:RESUME_TEXT_STORE_LIMIT]},
                actor,
            )
            service.set_consent(candidate["id"], True, actor, "chat_upload")
            # 原文已入库，工具返回值剔除它：避免整份简历进入 LLM 上下文和 tool 消息。
            candidate_public = {k: v for k, v in candidate.items() if k != "resume_text"}
            return {"candidate": candidate_public, "parsed_fields": parsed}
```

注意：monkeypatch 打在 `rp.parse_resume` 上，而分支内是 `from .resume_parser import parse_resume`（调用时才导入），所以 monkeypatch 生效。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chat_tools.py -q`
Expected: 全部 PASS（含既有用例）

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/chat_tools.py tests/test_chat_tools.py
git commit -m "feat(chat): persist resume raw text on candidate at parse time"
```

---

### Task 2: get_my_profile 返回截断的简历原文

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/chat_tools.py`（`get_my_profile` 分支，约 232-234 行）
- Test: `tests/test_chat_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_get_my_profile_truncates_long_resume_text():
    service = MagicMock()
    service.get_candidate.return_value = {"id": "c1", "resume_text": "y" * 7000}
    result = execute_tool("get_my_profile", {"candidate_id": "c1"}, service=service, actor="t")
    assert result["resume_text"].endswith("...(truncated)")
    assert len(result["resume_text"]) == 6000 + len("...(truncated)")


def test_get_my_profile_without_resume_text_unchanged():
    service = MagicMock()
    service.get_candidate.return_value = {"id": "c1", "country": "CN"}
    result = execute_tool("get_my_profile", {"candidate_id": "c1"}, service=service, actor="t")
    assert "resume_text" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chat_tools.py -q -k get_my_profile`
Expected: 第一个 FAILED（现在原样返回 7000 字符，无截断后缀）；第二个可能 PASS（原样透传）——只要第一个红即可继续

- [ ] **Step 3: Write minimal implementation**

常量区追加：

```python
# get_my_profile 返回给 LLM 的原文截断长度。
RESUME_TEXT_PROFILE_LIMIT = 6000
```

`get_my_profile` 分支改为：

```python
        if name == "get_my_profile":
            candidate = service.get_candidate(arguments["candidate_id"])
            resume_text = candidate.get("resume_text")
            if resume_text and len(resume_text) > RESUME_TEXT_PROFILE_LIMIT:
                candidate = {
                    **candidate,
                    "resume_text": resume_text[:RESUME_TEXT_PROFILE_LIMIT] + "...(truncated)",
                }
            return candidate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chat_tools.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/chat_tools.py tests/test_chat_tools.py
git commit -m "feat(chat): expose truncated resume_text via get_my_profile"
```

---

### Task 3: SYSTEM_PROMPT 申请材料指引

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/chat_service.py`（`SYSTEM_PROMPT`，约 21-36 行）

- [ ] **Step 1: Modify the prompt**

在 SYSTEM_PROMPT 能力列表第 5 条后加第 6 条，并在"规则"末尾追加材料生成规则。整段改为：

```python
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
```

- [ ] **Step 2: Verify nothing broke**

Run: `python -m pytest tests/test_chat_service.py -q` 和 `ruff check src/agent_hub/agents/global_part_time/chat_service.py`
Expected: 除已知预存在失败 `test_bind_candidate` 外全部 PASS；ruff 无报错

- [ ] **Step 3: Commit**

```bash
git add src/agent_hub/agents/global_part_time/chat_service.py
git commit -m "feat(chat): system prompt guidance for application-kit generation"
```

---

### Task 4: MatchCard 与 ChatMessage 按钮

**Files:**
- Modify: `frontend/components/match-card.tsx`
- Modify: `frontend/components/chat-message.tsx`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: MatchCard 加 onGenerateKit 属性与按钮**

`match-card.tsx`——props 类型与解构中加 `onGenerateKit?: () => void`：

```tsx
export function MatchCard({
  title,
  company,
  score,
  reasons,
  workMode,
  compensation,
  onClick,
  onGenerateKit,
}: {
  title: string;
  company: string;
  score: number;
  reasons: string[];
  workMode?: string;
  compensation?: string;
  onClick?: () => void;
  onGenerateKit?: () => void;
}) {
```

在 `{reasons.length > 0 && (...)}` 区块之后、卡片根 `</div>` 之前插入（stopPropagation 防止触发卡片自身的 onClick 跳详情）：

```tsx
      {onGenerateKit && (
        <button
          className="match-card-kit-btn"
          onClick={(e) => {
            e.stopPropagation();
            onGenerateKit();
          }}
        >
          ✍️ 生成申请材料
        </button>
      )}
```

- [ ] **Step 2: ChatMessage 透传回调**

`chat-message.tsx`——props 加 `onGenerateKit?: (jobId: string, title: string) => void`（与 `onCardClick` 并列声明），`MatchCard` 处传入：

```tsx
                  <MatchCard
                    title={m.job_title ?? 'Unknown'}
                    company={m.company_name ?? ''}
                    score={m.score ?? 0}
                    reasons={[]}
                    workMode={m.work_mode}
                    compensation={
                      m.compensation_max ? `$${m.compensation_max}/h ${m.compensation_currency ?? ''}` : undefined
                    }
                    onClick={m.job_id && onCardClick ? () => onCardClick(m.job_id!) : undefined}
                    onGenerateKit={
                      m.job_id && onGenerateKit ? () => onGenerateKit(m.job_id!, m.job_title ?? '') : undefined
                    }
                  />
```

- [ ] **Step 3: 按钮样式**

`globals.css` 中 `.chat-match-reason-icon` 规则之后追加：

```css
.match-card-kit-btn {
  margin-top: 10px;
  padding: 6px 12px;
  font-size: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: transparent;
  color: var(--ink-soft);
  cursor: pointer;
  transition: 150ms ease;
}

.match-card-kit-btn:hover {
  border-color: var(--amber);
  color: var(--amber-deep);
}
```

- [ ] **Step 4: Verify**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint components/match-card.tsx components/chat-message.tsx`
Expected: 无本任务文件的新报错（预存在报错见"注意事项"）

- [ ] **Step 5: Commit**

```bash
git add frontend/components/match-card.tsx frontend/components/chat-message.tsx frontend/app/globals.css
git commit -m "feat(chat): application-kit button on match cards"
```

---

### Task 5: JobDetailDrawer 按钮

**Files:**
- Modify: `frontend/components/job-detail-drawer.tsx`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Drawer 加 onGenerateKit 属性与按钮**

组件签名改为：

```tsx
export function JobDetailDrawer({
  jobId,
  onClose,
  onGenerateKit,
}: {
  jobId: string;
  onClose: () => void;
  onGenerateKit?: (title: string) => void;
}) {
```

在 `{job.canonical_url && (...)}` 区块之前插入：

```tsx
              {onGenerateKit && (
                <div className="job-drawer-section">
                  <button
                    className="match-card-kit-btn"
                    onClick={() => onGenerateKit(job.title_zh || job.title_original || '')}
                  >
                    ✍️ 生成申请材料
                  </button>
                </div>
              )}
```

（jobs 页也用了这个抽屉但不传新属性，行为不变。样式复用 Task 4 的 `.match-card-kit-btn`，无需新 CSS。）

- [ ] **Step 2: Verify**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint components/job-detail-drawer.tsx`
Expected: 无本任务文件的新报错

- [ ] **Step 3: Commit**

```bash
git add frontend/components/job-detail-drawer.tsx
git commit -m "feat(chat): application-kit button in job detail drawer"
```

---

### Task 6: ChatPanel 接线

**Files:**
- Modify: `frontend/components/chat-panel.tsx`

- [ ] **Step 1: 加统一回调**

在 `handleKeyDown` 函数之前加：

```tsx
  function handleGenerateKit(jobId: string, title: string) {
    setSelectedJobId(null);
    sendPrompt(`请为岗位「${title}」（ID: ${jobId}）生成申请材料`);
  }
```

- [ ] **Step 2: 接到 ChatMessage 与 Drawer**

`<ChatMessage ...>` 处加一行属性：

```tsx
              onGenerateKit={handleGenerateKit}
```

底部抽屉渲染改为：

```tsx
      {selectedJobId && (
        <JobDetailDrawer
          jobId={selectedJobId}
          onClose={() => setSelectedJobId(null)}
          onGenerateKit={(title) => handleGenerateKit(selectedJobId, title)}
        />
      )}
```

- [ ] **Step 3: Verify**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint components/chat-panel.tsx`
Expected: 无本任务文件的新报错

- [ ] **Step 4: Commit**

```bash
git add frontend/components/chat-panel.tsx
git commit -m "feat(chat): wire application-kit button to chat prompt"
```

---

### Task 7: 全量校验 + 真实链路验证

**Files:** 无新改动（验证任务）

- [ ] **Step 1: 后端全量测试与 lint**

Run: `python -m pytest tests/test_chat_tools.py tests/test_chat_service.py tests/test_service.py tests/test_chat_stream_api.py -q && ruff check src/ tests/ --exclude src/agent_hub/agents/global_part_time/fetchers && ruff format --check src/agent_hub/agents/global_part_time/chat_tools.py src/agent_hub/agents/global_part_time/chat_service.py`
Expected: 除已知 `test_bind_candidate` 外全部 PASS；lint 干净（fetchers 的 F401 是预存在 WIP，不属于本计划）

- [ ] **Step 2: 重启 worker 使 parse_resume 新代码生效**

Run: `docker restart my-agent-worker-1`
Expected: `docker logs my-agent-worker-1 --since 15s 2>&1 | grep ready` 出现 `celery@... ready.`

- [ ] **Step 3: 真实链路验证（人工，浏览器）**

1. 打开 localhost:3000/chat，新会话上传简历 PDF → 出推荐卡片。
2. 卡片上点"✍️ 生成申请材料"→ 聊天里出现预置消息，助手流式生成英文求职信（引用块）+ 中文建议 + 申请链接。
3. 点开某岗位详情抽屉 → 底部按钮同样触发。
4. 追问"语气更正式一点" → 助手基于上下文重写。
5. 新开会话（不上传简历）直接要求生成 → 助手引导先上传简历。

- [ ] **Step 4: Push**

```bash
git push
```
