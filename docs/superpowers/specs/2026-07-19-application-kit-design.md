# 设计：申请材料生成（帮助投简历·第一期）

日期：2026-07-19
状态：已确认

## 背景与目标

平台目前止步于"推荐"：用户拿到匹配卡片后，投递环节完全靠自己。本期为聊天助手增加"申请材料生成"能力：针对具体岗位一键生成定制求职信 + 简历优化建议 + 原始申请链接，帮用户走完"看到岗位 → 准备材料 → 去投递"的最后一公里。

明确不做（本期）：自动投递（聚合来源 ToS 普遍禁止自动化提交，与平台合规优先原则冲突）、申请状态追踪看板（后续期）、jobs 页入口（后续期）。

## 决策记录

| 决策点 | 结论 |
|---|---|
| 功能方向 | 材料生成 + 直达链接（不做自动投递） |
| 触发入口 | 聊天自然语言 + 推荐卡片/详情抽屉按钮（按钮通过 `sendPrompt` 发预置消息，同一链路） |
| 材料范围 | 求职信（岗位语言，通常英文，250-350 词）+ 3-5 条中文简历优化建议 + 申请链接 |
| 生成方式 | 路线 A：提示词驱动，主聊天 LLM 直接生成（流式、可对话迭代）；不新增专用生成工具 |
| 简历原文 | 存入 candidate payload 的 `resume_text` 字段（parse_resume 时写入，Candidate 为 JSONB payload 模型，无需迁移），`get_my_profile` 返回（截断 6000 字符） |
| 老数据兼容 | 无 `resume_text` 的候选人退化为基于 `resume_summary` + skills 生成，提示词要求说明局限并建议重新上传简历 |

## 架构与数据流

不新增服务组件，复用现有聊天工具编排：

```
用户点击卡片按钮 / 输入"帮我写这个岗位的申请材料"
  │  （按钮 → sendPrompt 预置消息，含岗位标题 + job_id）
  ▼
ChatService.stream_response（现有 LLM 工具循环）
  │  LLM 依提示词调用：
  │    get_job_detail(job_id)   → JD、canonical_url
  │    get_my_profile()         → 画像 + resume_text（新）
  ▼
LLM 流式生成：求职信（Markdown 引用块）+ 优化建议 + 申请链接
  │  走既有 StreamHub 可恢复流式 + 前端打字机渲染
  ▼
用户对话迭代："语气更正式" / "强调 FastAPI 经历"
```

## 改动清单

### 数据层

- 无迁移：`Candidate` 是 JSONB payload 模型（`payload` 列整体往返），`resume_text` 作为 payload 字段直接持久化。
- 写入上限 20000 字符（防止超大 PDF 撑爆 payload；candidate dict 会随多个接口返回）。

### 工具层（chat_tools.py）

- `parse_resume` 执行分支：建候选人时把入参 `pdf_text` 原文写入 `resume_text`。
- `get_my_profile` 执行分支：返回值加入 `resume_text`，超过 6000 字符截断并追加 `...(truncated)`。

### 提示词（chat_service.py SYSTEM_PROMPT）

新增"申请材料"一节：

- 用户要求申请材料时，先调 `get_job_detail` 和 `get_my_profile`。
- 求职信用岗位语言（默认英文），250-350 词，必须引用 JD 具体要求与简历真实经历，不得编造经历。
- 随后给 3-5 条中文建议：针对该岗位简历该突出/调整什么。
- 结尾附 canonical_url 申请链接；若候选人无 resume_text，如实说明建议基于画像摘要、可上传简历获得更精准材料。

### 前端

- `match-card.tsx`：卡片底部加"✍️ 生成申请材料"次级按钮（点击不触发卡片跳转，需 stopPropagation）。
- `job-detail-drawer.tsx`：抽屉底部同款按钮。
- 按钮回调沿组件树上抛到 `ChatPanel.sendPrompt`，预置消息：`请为岗位「{title}」（ID: {job_id}）生成申请材料`。
- 求职信为 Markdown 渲染（已具备 react-markdown），无需新组件。

## 错误处理

- 无绑定候选人（会话没传过简历也没建档）：LLM 按现有引导话术请用户先上传简历或描述背景（提示词已有此规则，无需新逻辑）。
- `get_job_detail` 拿不到岗位（ID 错/已下架）：工具返回现有 error 结构，LLM 如实告知。
- resume_text 缺失：见"老数据兼容"决策。

## 测试

- TDD 单元测试：① parse_resume 持久化 resume_text（含 20000 字符写入上限）；② get_my_profile 返回 resume_text 且超长截断（6000 字符）；③ 无 resume_text 的候选人 profile 兼容路径（键缺失或 None）。
- 提示词效果：真实会话人工验证（上传简历 → 推荐 → 点按钮生成 → 追问修改）。
- 前端：tsc + eslint；按钮行为人工验证。
