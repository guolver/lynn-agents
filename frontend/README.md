# Agent Hub Console

Agent Hub 的多路由可视化控制台。当前包含运行总览、Agent 目录、通用动作执行器、职位来源、职位风险、匹配漏斗和审计时间线。

## 本地启动

要求 Node.js 22.13 或更高版本：

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

默认启用演示数据，便于独立查看完整界面。复制 `.env.example` 为 `.env.local`，并设置：

```text
AGENT_HUB_DEMO_MODE=false
AGENT_HUB_API_URL=http://127.0.0.1:8000
```

即可读取并调用本仓库的 FastAPI Agent Hub。

## 页面结构

```text
app/(console)/
├── dashboard/          # 平台核心指标、职位漏斗、风险分布
├── agents/             # Agent 目录与通用动作控制台
├── sources/            # 来源授权和同步状态
├── jobs/               # 职位质量、风险与审核状态
├── matches/            # 硬过滤、匹配分项和推荐理由
└── audit/              # 可追溯事件时间线
```

共享 UI 位于 `components/`，API 和演示数据边界位于 `lib/`。浏览器端动作统一提交到 `/api/invoke`，由薄 BFF 附加 actor、request ID 和幂等键后转发给 FastAPI。

## 验证

```bash
pnpm build
node --test tests/rendered-html.test.mjs
```
