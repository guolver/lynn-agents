# 登录/注册页 UI/UX 重设计

## 背景

`frontend/app/login/page.tsx` 和 `frontend/app/register/page.tsx` 目前是纯 Tailwind 工具类拼出的极简表单，未使用项目的 "Warm Stone + Amber Gold" 设计系统（`app/globals.css` 中定义的 `--ink`/`--amber`/`--surface` 等变量与控制台既有的卡片、按钮、输入框样式）。本设计让登录/注册页在视觉上与控制台其余部分（`app-topbar`、`.panel`、`chat-send-btn`、`jh-search` 等）保持一致。

## 范围

- `app/login/page.tsx`、`app/register/page.tsx` 的视觉重做
- 新增两个可复用的展示型组件，供两页共用（避免图标输入框、密码可见性切换等标记重复 4 次）
- `app/globals.css` 新增一段 `── Auth Pages ──` 样式
- 不改动任何后端 API、路由逻辑、鉴权流程；"记住我"、"忘记密码" 不在范围内（后端未提供对应能力）

## 布局

全屏 `--bg` 背景，内容垂直水平居中。中央是一张白色卡片：

- 圆角 14px（对齐 `.panel`），`--shadow-lg` 阴影，最大宽度 400px，内边距 32–40px
- 卡片内自上而下：品牌区 → 标题/副标题 → 表单 → 底部切换链接

品牌区：48px 圆角方块（`--ink` 背景、`--amber` 文字 "AH"，即 `.app-brand-mark` 的放大版）居中，下方 "Agent Hub" 名称，再下方灰色副标题：
- 登录页："登录以继续使用 Agent Hub"
- 注册页："创建账号，开始使用 Agent Hub"

品牌区不可点击（保持静态展示，不作为返回首页的链接）。

## 表单细节

- **输入框**：`.auth-input-wrap` 相对定位容器，左侧内嵌图标（邮箱用信封图标、密码用锁图标），输入框左侧留出图标空间；边框 `--line`，聚焦态复用 `.jh-search:focus-within` 的琥珀色光晕（`box-shadow: 0 0 0 3px rgba(251,191,36,.08)` + 边框变 `--line-strong`）。
- **密码框**：右侧追加一个可点击的"眼睛"图标按钮，切换 `input type="password"/"text"`。
- **标签**：视觉上隐藏（`sr-only`），保留给屏幕阅读器；界面上靠图标 + placeholder 传达含义。
- **注册页密码提示**：保留"至少 8 位"的辅助文案，放在输入框下方的小号灰字。
- **错误提示**：整条浅红色背景条（`--red-soft` 背景、`--red` 文字）+ 左侧感叹号图标的 alert 组件，替换当前纯文字错误。
- **提交按钮**：全宽，`--ink` 背景 + `--amber` 文字，圆角 10px，hover 变 `#292524`（对齐 `.chat-send-btn`）；loading 态显示旋转 spinner（复用 `globals.css` 中已有的 `jh-spin` 关键帧）+ "登录中…"/"注册中…" 文案，按钮 disabled。
- **底部切换链接行**：居中，灰色说明文字 + `--amber-deep` 高亮下划线链接（hover 加深），替换当前默认下划线样式。

## 组件拆分

新增两个纯展示组件（无业务逻辑，两页共用）：

- `components/auth-shell.tsx` — 卡片外壳：品牌区 + 标题/副标题 + `children`（表单）+ 底部链接行（作为 prop 传入）
- `components/auth-input.tsx` — 带图标的输入框，`type` 为 `password` 时自动带可见性切换按钮

`login/page.tsx`、`register/page.tsx` 保留各自的状态管理和 `handleSubmit` 逻辑不变，仅替换渲染部分为上述组件 + 新的错误 alert / 提交按钮标记。

## 样式实现

在 `app/globals.css` 追加 `── Auth Pages ──` 分区，新增类名：`.auth-page`、`.auth-card`、`.auth-brand-mark`、`.auth-brand-name`、`.auth-subtitle`、`.auth-form`、`.auth-field`、`.auth-input-wrap`、`.auth-input-icon`、`.auth-input`、`.auth-toggle-visibility`、`.auth-hint`、`.auth-error`、`.auth-submit`、`.auth-footer`、`.auth-footer-link`。颜色、圆角、阴影均取自现有 CSS 变量，不新增变量。

## 不做的事

- 不引入图标库（沿用项目现有的内联 SVG 模式，参考 `chat-panel.tsx`）
- 不做"记住我"/"忘记密码"/第三方登录（无对应后端能力）
- 不改动 `app/api/auth/*` 路由或鉴权逻辑
