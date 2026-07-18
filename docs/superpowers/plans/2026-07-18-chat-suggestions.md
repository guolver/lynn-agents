# ChatGPT 式聊天引导提示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/chat` 界面四个位置提供引导提示词（空会话建议卡片、无会话欢迎屏、回复后追问 pill、输入框快捷 chip），对齐 ChatGPT 交互。

**Architecture:** 纯前端实现，零后端改动。所有提示词文案集中在新文件 `frontend/lib/chat-suggestions.ts`；`ChatPanel` 增加 `sendPrompt` 复用发送逻辑、`lastToolName` 状态驱动追问规则、`initialPrompt`/`initialAction` props 支持欢迎屏"建会话即发送"。

**Tech Stack:** Next.js 16 / React 19 / 全局 CSS（globals.css 的 `gpt-*` 类）。

**Testing note:** 本仓库前端没有单元测试框架（只有 ESLint + build，见 CLAUDE.md）。每个任务的验证方式为 `pnpm lint` + `pnpm build`（在 `frontend/` 目录下运行），最后统一手动验证。不引入新测试框架（YAGNI）。

Spec: `docs/superpowers/specs/2026-07-18-chat-suggestions-design.md`

---

### Task 1: 提示词数据模块

**Files:**
- Create: `frontend/lib/chat-suggestions.ts`

- [ ] **Step 1: 创建数据文件**

```ts
// frontend/lib/chat-suggestions.ts
export type Suggestion = {
  icon: string;
  label: string;
  /** 点击后作为用户消息发送的文本；action 为 upload 时可省略 */
  prompt?: string;
  /** 特殊行为：upload = 打开简历文件选择器 */
  action?: 'upload';
};

/** 空会话 / 无会话欢迎屏的建议卡片（2 列网格） */
export const EMPTY_STATE_SUGGESTIONS: Suggestion[] = [
  { icon: '📄', label: '上传简历，智能匹配岗位', action: 'upload' },
  {
    icon: '💼',
    label: '我会 Python 和 React，帮我找远程兼职',
    prompt: '我会 Python 和 React，帮我找远程兼职',
  },
  { icon: '🔍', label: '有哪些海外客服类的兼职岗位？', prompt: '有哪些海外客服类的兼职岗位？' },
  { icon: '💰', label: '时薪 $20 以上的岗位有哪些？', prompt: '时薪 $20 以上的岗位有哪些？' },
  {
    icon: '⏰',
    label: '我每周只能工作 15 小时，有什么合适的？',
    prompt: '我每周只能工作 15 小时，有什么合适的？',
  },
  { icon: '👤', label: '查看我的档案和求职偏好', prompt: '查看我的档案和求职偏好' },
];

/** 输入框上方常驻快捷指令 chip */
export const QUICK_ACTIONS: Suggestion[] = [
  { icon: '📎', label: '上传简历', action: 'upload' },
  { icon: '🔍', label: '搜索岗位', prompt: '帮我搜索适合我的兼职岗位' },
  { icon: '🎯', label: '开始匹配', prompt: '根据我的档案帮我匹配岗位' },
  { icon: '👤', label: '我的档案', prompt: '查看我的档案和求职偏好' },
  { icon: '⚙️', label: '调整偏好', prompt: '我想调整我的求职偏好' },
];

/** 追问建议：按上一轮工具调用名选择，无工具调用时用 default */
export const FOLLOW_UPS: Record<string, string[]> = {
  run_matches: ['换一批岗位', '调整我的偏好', '讲讲第一个岗位'],
  parse_resume: ['根据简历帮我匹配岗位', '我的技能识别对吗？'],
  search_jobs: ['按匹配度排序', '只看远程岗位'],
  update_preferences: ['用新偏好重新匹配'],
  get_my_profile: ['更新我的求职偏好', '开始匹配岗位'],
  default: ['帮我匹配岗位', '现在有哪些兼职岗位？'],
};
```

- [ ] **Step 2: 验证**

Run: `cd frontend && pnpm lint`
Expected: 无新增错误（未被引用的导出不会报错，`lib/` 下现有文件同样是纯数据/工具模块）。

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/chat-suggestions.ts
git commit -m "feat(chat): add suggestion prompt data module"
```

---

### Task 2: sendPrompt 复用 + 空会话建议卡片

**Files:**
- Modify: `frontend/components/chat-panel.tsx`（导入、`handleSend` 拆分、空状态 JSX）
- Modify: `frontend/app/globals.css`（`.gpt-empty*` 样式）

- [ ] **Step 1: 导入数据模块**

在 `chat-panel.tsx` 顶部 import 区（`import { JobDetailDrawer } ...` 之后）加：

```ts
import { EMPTY_STATE_SUGGESTIONS } from '../lib/chat-suggestions';
```

- [ ] **Step 2: 拆出 sendPrompt**

将现有 `handleSend`（约 184-193 行）替换为：

```ts
  async function sendPrompt(text: string) {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || isUploading) return;

    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: trimmed };
    setMessages((prev) => [...prev, userMsg]);

    await streamAssistant(trimmed);
  }

  async function handleSend() {
    const text = input.trim();
    if (!text) return;
    setInput('');
    await sendPrompt(text);
  }
```

- [ ] **Step 3: 替换空状态 JSX**

把现有的：

```tsx
          {messages.length === 0 && (
            <div className="gpt-empty">
              <div className="gpt-empty-logo">AH</div>
              <p>有什么可以帮你的？</p>
            </div>
          )}
```

替换为：

```tsx
          {messages.length === 0 && (
            <div className="gpt-empty">
              <div className="gpt-empty-logo">AH</div>
              <h2 className="gpt-empty-title">我是 Agent Hub 求职助手</h2>
              <p className="gpt-empty-sub">上传简历、搜索岗位、智能匹配、管理求职偏好 —— 有什么可以帮你的？</p>
              <div className="gpt-empty-cards">
                {EMPTY_STATE_SUGGESTIONS.map((s) => (
                  <button
                    key={s.label}
                    className="gpt-empty-card"
                    disabled={isStreaming || isUploading}
                    onClick={() =>
                      s.action === 'upload' ? fileInputRef.current?.click() : sendPrompt(s.prompt!)
                    }
                  >
                    <span className="gpt-empty-card-icon">{s.icon}</span>
                    <span>{s.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
```

- [ ] **Step 4: CSS**

`globals.css` 中把 `.gpt-empty` 的 `height: 50vh;` 改为 `min-height: 50vh;`（卡片加入后 50vh 固定高度会溢出），并在 `.gpt-empty p { ... }`（约 1469 行）之后追加：

```css
.gpt-empty-title { font-size: 22px; font-weight: 600; color: var(--fg); margin: 0; }
.gpt-empty-sub { font-size: 14px; color: var(--fg-muted); margin: 0; text-align: center; }
.gpt-empty-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 20px;
  width: 100%;
  max-width: 560px;
}
.gpt-empty-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--bg);
  color: var(--fg);
  font-size: 13.5px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.gpt-empty-card:hover:not(:disabled) { background: var(--bg-hover); border-color: var(--fg-muted); }
.gpt-empty-card:disabled { opacity: 0.4; cursor: not-allowed; }
.gpt-empty-card-icon { font-size: 18px; flex-shrink: 0; }
```

- [ ] **Step 5: 验证**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: 均通过。

- [ ] **Step 6: Commit**

```bash
git add frontend/components/chat-panel.tsx frontend/app/globals.css
git commit -m "feat(chat): empty-session suggestion cards with welcome copy"
```

---

### Task 3: 输入框上方快捷指令 chip

**Files:**
- Modify: `frontend/components/chat-panel.tsx`（导入 QUICK_ACTIONS、输入区 JSX）
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: 扩展导入**

```ts
import { EMPTY_STATE_SUGGESTIONS, QUICK_ACTIONS } from '../lib/chat-suggestions';
```

- [ ] **Step 2: 在输入框上方插入 chip 行**

在 `<div className="gpt-input-wrap">` 与 `<div className="gpt-input-box">` 之间插入：

```tsx
        <div className="gpt-quick-actions">
          {QUICK_ACTIONS.map((q) => (
            <button
              key={q.label}
              className="gpt-quick-chip"
              disabled={isStreaming || isUploading}
              onClick={() =>
                q.action === 'upload' ? fileInputRef.current?.click() : sendPrompt(q.prompt!)
              }
            >
              <span>{q.icon}</span>
              {q.label}
            </button>
          ))}
        </div>
```

- [ ] **Step 3: CSS**

在 `/* Input area */` 注释上方（`@keyframes gpt-blink` 之后）追加：

```css
/* Quick action chips */
.gpt-quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-width: 768px;
  margin: 0 auto 8px;
}
.gpt-quick-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--bg);
  color: var(--fg-muted);
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.gpt-quick-chip:hover:not(:disabled) { background: var(--bg-hover); color: var(--fg); }
.gpt-quick-chip:disabled { opacity: 0.4; cursor: not-allowed; }
```

- [ ] **Step 4: 验证**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: 均通过。

- [ ] **Step 5: Commit**

```bash
git add frontend/components/chat-panel.tsx frontend/app/globals.css
git commit -m "feat(chat): quick action chips above input box"
```

---

### Task 4: 回复后的追问建议 pill

**Files:**
- Modify: `frontend/components/chat-panel.tsx`（lastToolName 状态、SSE 记录、pill 渲染）
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: 扩展导入**

```ts
import { EMPTY_STATE_SUGGESTIONS, FOLLOW_UPS, QUICK_ACTIONS } from '../lib/chat-suggestions';
```

- [ ] **Step 2: 新增状态**

在 `const [selectedJobId, ...]` 一行后加：

```ts
  const [lastToolName, setLastToolName] = useState<string | null>(null);
```

- [ ] **Step 3: 在 SSE 流中记录工具名**

`streamAssistant` 开头 `setIsStreaming(true);` 之后加一行：

```ts
    setLastToolName(null);
```

`tool_call` 事件分支（`const label = TOOL_LABELS[data.name] ...` 之前）加一行：

```ts
            setLastToolName(data.name);
```

- [ ] **Step 4: 简历分析完成视同 run_matches**

`applyAnalysisResult` 函数体内（`setMessages(...)` 之前）加：

```ts
    setLastToolName('run_matches');
```

- [ ] **Step 5: 派生 followUps 并渲染**

在 `return (` 之前加派生逻辑：

```ts
  const lastMsg = messages[messages.length - 1];
  const followUps =
    !isStreaming && !isUploading && lastMsg?.role === 'assistant' && (lastMsg.content || lastMsg.toolData)
      ? (FOLLOW_UPS[lastToolName ?? 'default'] ?? FOLLOW_UPS.default)
      : [];
```

在 `{messages.map(...)}` 之后、`<div ref={messagesEndRef} />` 之前插入：

```tsx
          {followUps.length > 0 && (
            <div className="gpt-followups">
              {followUps.map((f) => (
                <button key={f} className="gpt-followup-pill" onClick={() => sendPrompt(f)}>
                  {f}
                </button>
              ))}
            </div>
          )}
```

说明：条件里 `lastMsg?.role === 'assistant'` 保证用户发送下一条后 pill 立即消失（此时最后一条是 user，流式中又被 `!isStreaming` 挡住）；历史加载后 `lastToolName` 为 null → 展示 default 组。

- [ ] **Step 6: CSS**

在 Task 3 的 `.gpt-quick-chip:disabled` 规则后追加：

```css
/* Follow-up suggestion pills */
.gpt-followups {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px 0 8px 44px;
}
.gpt-followup-pill {
  padding: 6px 14px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--bg);
  color: var(--fg);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.gpt-followup-pill:hover { background: var(--bg-hover); border-color: var(--fg-muted); }
```

（44px 左边距 = 32px 头像宽 + 12px gap，与 AI 消息正文对齐。）

- [ ] **Step 7: 验证**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: 均通过。

- [ ] **Step 8: Commit**

```bash
git add frontend/components/chat-panel.tsx frontend/app/globals.css
git commit -m "feat(chat): rule-based follow-up suggestion pills after replies"
```

---

### Task 5: 无会话欢迎屏卡片 + initialPrompt 直通

**Files:**
- Modify: `frontend/components/chat-panel.tsx`（新增 props、首发逻辑）
- Modify: `frontend/app/(console)/chat/page.tsx`（欢迎屏卡片、pending 状态、ChatPanel key）

- [ ] **Step 1: ChatPanel 新增 props 和一次性首发**

函数签名改为：

```tsx
export function ChatPanel({
  sessionId,
  initialPrompt,
  initialAction,
}: {
  sessionId: string;
  initialPrompt?: string;
  initialAction?: 'upload';
}) {
```

在 `const textareaRef = ...` 后加：

```ts
  const initialFired = useRef(false);
```

历史加载 effect 的 `.then((data) => { ... })` 中，`setMessages(rebuilt);` 之后加：

```ts
        if (rebuilt.length === 0 && !initialFired.current) {
          initialFired.current = true;
          if (initialPrompt) sendPrompt(initialPrompt);
          else if (initialAction === 'upload') fileInputRef.current?.click();
        }
```

同时该 effect 依赖数组保持 `[sessionId]` 不变；若 lint 报 react-hooks/exhaustive-deps，在依赖数组那一行（`}, [sessionId]);`）正上方加：

```ts
    // eslint-disable-next-line react-hooks/exhaustive-deps
```

（sendPrompt/initialPrompt 故意不入依赖，避免重复触发。）

注意：`initialAction === 'upload'` 的程序化 `click()` 依赖浏览器的 transient activation，若被浏览器拦截则静默失败——空状态里仍有"上传简历"卡片兜底，可接受。

- [ ] **Step 2: chat/page.tsx 欢迎屏 + pending**

顶部加导入：

```ts
import { EMPTY_STATE_SUGGESTIONS } from '../../../lib/chat-suggestions';
```

在 `const [sidebarOpen, ...]` 后加：

```ts
  const [pending, setPending] = useState<{ prompt?: string; action?: 'upload' } | null>(null);
```

`handleNewSession` 改为接受可选参数：

```ts
  async function handleNewSession(prompt?: string, action?: 'upload') {
    try {
      const res = await fetch('/api/chat/sessions', { method: 'POST' });
      const data = await res.json();
      if (data.id) {
        setPending(prompt || action ? { prompt, action } : null);
        setSessionId(data.id);
        setSessions((prev) => [data, ...prev]);
      }
    } catch {
      alert('Failed to create session');
    }
  }
```

侧边栏 "New Chat" 按钮的 `onClick={handleNewSession}` 必须改为 `onClick={() => handleNewSession()}`（否则 MouseEvent 会被当成 prompt 参数传入）。

历史会话按钮的 onClick 改为：

```ts
              onClick={() => {
                setPending(null);
                setSessionId(s.id);
              }}
```

- [ ] **Step 3: ChatPanel 渲染加 key 并传参**

```tsx
        {sessionId ? (
          <ChatPanel
            key={sessionId}
            sessionId={sessionId}
            initialPrompt={pending?.prompt}
            initialAction={pending?.action}
          />
        ) : (
```

（`key={sessionId}` 同时修复了切换会话时 lastToolName 等旧状态残留的问题。）

- [ ] **Step 4: 欢迎屏建议卡片**

把欢迎屏中现有的 `<div className="gpt-suggestions"> ... </div>`（单张"开始新对话"卡）替换为：

```tsx
            <div className="gpt-empty-cards">
              {EMPTY_STATE_SUGGESTIONS.map((s) => (
                <button
                  key={s.label}
                  className="gpt-empty-card"
                  onClick={() =>
                    s.action === 'upload' ? handleNewSession(undefined, 'upload') : handleNewSession(s.prompt)
                  }
                >
                  <span className="gpt-empty-card-icon">{s.icon}</span>
                  <span>{s.label}</span>
                </button>
              ))}
            </div>
            <div className="gpt-suggestions">
              <button className="gpt-suggestion" onClick={() => handleNewSession()}>
                <span className="gpt-suggestion-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                    <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                </span>
                <span>开始新对话</span>
              </button>
            </div>
```

（复用 Task 2 的 `.gpt-empty-cards` 样式，无需新 CSS。）

- [ ] **Step 5: 验证**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: 均通过。

- [ ] **Step 6: Commit**

```bash
git add frontend/components/chat-panel.tsx "frontend/app/(console)/chat/page.tsx"
git commit -m "feat(chat): welcome-screen suggestion cards auto-create session and send"
```

---

### Task 6: 手动验证

**Files:** 无代码改动。

- [ ] **Step 1: 启动前后端**

后端（仓库根目录）：`source .venv/bin/activate && uvicorn agent_hub.app:app --reload`
前端：`cd frontend && pnpm dev`，打开 `http://localhost:3000/chat`。

- [ ] **Step 2: 核对清单**

1. 无会话欢迎屏：6 张卡片可见；点击文字卡 → 自动建会话并发送该文本，AI 开始回复；点击"上传简历"卡 → 建会话（文件选择器打开或可从空状态再点）。
2. 新建空会话：显示标题、能力介绍和 6 张卡片；点击文字卡直接发送；点击上传卡打开文件选择器。
3. AI 回复结束后：出现对应追问 pill（触发匹配后应为"换一批岗位/调整我的偏好/讲讲第一个岗位"）；点击 pill 即发送；流式期间 pill 不显示。
4. 输入框上方 5 个快捷 chip 常驻；流式/上传中变灰不可点。
5. 刷新页面：历史正常恢复，不重复发送 initialPrompt。

- [ ] **Step 3: 完成**

按 superpowers:verification-before-completion 确认后汇报结果。
