# ChatGPT 式聊天引导提示设计

日期：2026-07-18
状态：已确认

## 目标

让 `/chat` 聊天界面在四个位置给用户足够的引导提示词（对齐 ChatGPT 交互），降低新用户上手门槛。全部前端实现，零后端改动。

## 范围

改动文件：

- 新增 `frontend/lib/chat-suggestions.ts` — 集中管理所有提示词文案与追问规则
- `frontend/components/chat-panel.tsx` — 空状态卡片、追问 pill、快捷指令 chip、`initialPrompt` 支持
- `frontend/app/(console)/chat/page.tsx` — 无会话欢迎屏建议卡片（点击 = 建会话 + 自动发送）
- `frontend/app/globals.css` — 对应样式

不改后端、不改数据库、不改 API。

## 功能设计

### 1. 空会话建议卡片（会话内 0 条消息时）

中央显示 Logo + 标题「我是 Agent Hub 求职助手」+ 一句能力介绍（上传简历 / 搜索岗位 / 智能匹配 / 管理偏好）+ 6 张 2 列网格建议卡片：

| 图标 | 文案 | 行为 |
|---|---|---|
| 📄 | 上传简历，智能匹配岗位 | 打开文件选择器 |
| 💼 | 我会 Python 和 React，帮我找远程兼职 | 作为用户消息发送 |
| 🔍 | 有哪些海外客服类的兼职岗位？ | 发送 |
| 💰 | 时薪 $20 以上的岗位有哪些？ | 发送 |
| ⏰ | 我每周只能工作 15 小时，有什么合适的？ | 发送 |
| 👤 | 查看我的档案和求职偏好 | 发送 |

引导文案纯前端渲染，不写入会话历史。

### 2. 无会话欢迎屏（/chat 页面，未选中会话时）

展示同样的建议卡片；点击任一卡片 = 自动创建会话，并通过 `ChatPanel` 的新 prop `initialPrompt` 自动发送该提示。上传卡片则建会话后打开文件选择器。

### 3. 回复后的追问建议（前端规则）

在 SSE 流处理中记录本轮最后一次 `tool_call` 的工具名 `lastToolName`；流式结束后，在最后一条 AI 消息下方渲染 2~3 个追问 pill，点击即发送，用户发送下一条消息后消失。

规则表：

| 上一轮工具 | 追问建议 |
|---|---|
| run_matches | 换一批岗位 · 调整我的偏好 · 讲讲第一个岗位 |
| parse_resume | 根据简历帮我匹配岗位 · 我的技能识别对吗？ |
| search_jobs | 按匹配度排序 · 只看远程岗位 |
| update_preferences | 用新偏好重新匹配 |
| get_my_profile | 更新我的求职偏好 · 开始匹配岗位 |
| 无工具调用 | 上传简历 · 看看有哪些岗位 |

简历上传异步分析完成后视同 `run_matches`（展示其追问组）。

### 4. 输入框上方快捷指令

输入框上方一排常驻 chip：`📎 上传简历`（触发文件选择器）、`🔍 搜索岗位`、`🎯 开始匹配`、`👤 我的档案`、`⚙️ 调整偏好`（发送预设文本）。流式/上传中禁用。

## 数据结构（chat-suggestions.ts）

```ts
type Suggestion = { icon: string; label: string; prompt?: string; action?: 'upload' };
export const EMPTY_STATE_SUGGESTIONS: Suggestion[];   // 6 张卡片
export const QUICK_ACTIONS: Suggestion[];             // 5 个 chip
export const FOLLOW_UPS: Record<string, string[]>;    // 工具名 → 追问文案，含 default
```

## 错误处理

- `initialPrompt` 只在会话首次挂载且历史为空时发送一次，避免刷新重复发送。
- 追问 pill 与快捷 chip 在 `isStreaming || isUploading` 时禁用。

## 验证

- `pnpm lint`、`pnpm build` 通过
- 手动验证：新会话卡片点击发送、上传卡片打开选择器、追问 pill 按规则出现并可点击、快捷 chip 常驻可用、无会话欢迎屏点击建会话并自动发送
