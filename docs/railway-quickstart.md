# Railway + Supabase 快速部署指南

本文档提供一步步的操作指南，帮你把后端部署到 Railway，数据库使用 Supabase。

## 前置准备

- GitHub 账号
- 代码已推送到 GitHub 仓库

## 第一步：创建 Supabase 数据库

1. 访问 [supabase.com](https://supabase.com) 并注册/登录
2. 点击 **New Project**
3. 配置：
   - Project name: `agent-hub`
   - Database Password: 设置一个强密码（保存好！）
   - Region: 选择 **Singapore** (亚太区延迟最低) 或 **US East**
4. 等待项目创建完成（约 1-2 分钟）

### 获取连接字符串

1. 进入项目 → 左侧菜单 **Project Settings** → **Database**
2. 滚动到 **Connection string** 部分
3. 选择 **URI** 标签，复制连接字符串

连接字符串格式：
```
postgresql://postgres.[project-ref]:[password]@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
```

**重要**：Railway 使用的 SQLAlchemy 需要 `postgresql+psycopg://` 格式，修改为：
```
postgresql+psycopg://postgres.[project-ref]:[password]@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
```

> 注意：使用 **端口 6543**（连接池模式），不要用 5432

## 第二步：部署后端到 Railway

1. 访问 [railway.app](https://railway.app) 并使用 GitHub 登录
2. 点击 **New Project** → **Deploy from GitHub repo**
3. 选择你的 `my-agent` 仓库
4. Railway 会自动检测到 `railway.toml` 配置

### 配置环境变量

在 Railway 项目页面，点击 **Variables** 添加以下变量：

| 变量名 | 值 |
|--------|-----|
| `DATABASE_URL` | `postgresql+psycopg://user:password@ep-xxx.neon.tech/agent_hub?sslmode=require` |
| `PUBLIC_BASE_URL` | `https://your-app.railway.app` (部署后获取) |
| `AUTH_JWT_SECRET` | 运行 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成 |
| `DEEPSEEK_API_KEY` | 你的 DeepSeek API Key |
| `SILICONFLOW_API_KEY` | 你的 SiliconFlow API Key |
| `EMBEDDING_BASE_URL` | `https://api.siliconflow.com/v1` |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` |

### 获取部署 URL

部署成功后：
1. 点击 **Settings** → **Networking**
2. 点击 **Generate Domain** 获取公开 URL
3. 将 URL 更新到 `PUBLIC_BASE_URL` 变量

## 第三步：验证部署

```bash
# 健康检查
curl https://your-app.railway.app/health

# 预期响应
{"status":"ok"}
```

## 第四步：部署前端到 Cloudflare

```bash
cd frontend
pnpm build
npx wrangler deploy

# 配置后端 URL
npx wrangler secret put AGENT_HUB_API_URL
# 输入: https://your-app.railway.app
```

## 常见问题

### Q: Railway 部署失败，提示找不到 Dockerfile？
确保 `railway.toml` 中的 `dockerfilePath` 路径正确，并且 `Dockerfile.production` 存在于仓库根目录。

### Q: 数据库连接失败？
1. 检查 `DATABASE_URL` 格式是否正确（必须是 `postgresql+psycopg://`）
2. 确保使用端口 6543（连接池模式）
3. 在 Supabase Dashboard 检查项目是否处于活跃状态

### Q: 首次请求很慢？
Supabase 免费层项目在 7 天无活动后会暂停。可以在 Dashboard 手动唤醒，或升级到 Pro 计划避免暂停。

### Q: Railway 免费额度用完了？
Railway 每月提供 $5 免费额度。超出后可以：
1. 升级到 Hobby 计划 ($5/月)
2. 或使用 Render.com 作为替代（免费层会休眠）

## 部署清单

- [ ] Supabase 数据库已创建
- [ ] Railway 项目已部署
- [ ] 环境变量已配置
- [ ] 健康检查通过
- [ ] 前端已部署到 Cloudflare
- [ ] 端到端测试通过
