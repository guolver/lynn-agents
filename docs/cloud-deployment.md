# 云端部署方案

> 适用版本：Agent Hub 0.2.x（PostgreSQL 版本）
> 更新日期：2026-07

本文档提供多种云端部署方案，从低成本 MVP 验证到生产级部署。

## 当前本地配置

```bash
# .env
DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub
```

| 组件 | 本地地址 |
|------|----------|
| PostgreSQL | localhost:5432 |
| 后端 API | localhost:8000 |
| 前端 | localhost:3000 |

## 方案对比

| 方案 | 月成本 | 适用场景 | 复杂度 |
|------|--------|----------|--------|
| A. 免费层组合 | ¥0 | MVP 验证、演示 | ⭐ |
| B. 低成本云服务 | ¥50-150 | 早期用户、小规模 | ⭐⭐ |
| C. 阿里云标准 | ¥200-500 | 国内用户、正式上线 | ⭐⭐⭐ |

---

## 方案 A：免费层组合（推荐 MVP 验证）

适合：快速验证产品、收集早期用户反馈

### 架构

```
用户浏览器
    │
    ├── 前端 ──→ Cloudflare Workers (免费)
    │              │
    │              ▼
    └── API ───→ Railway / Render (免费层)
                   │
                   ▼
               Neon / Supabase (免费 PostgreSQL)
```

### 服务选择

| 组件 | 服务 | 免费额度 |
|------|------|----------|
| 数据库 | [Neon](https://neon.tech) | 0.5GB 存储，无限项目 |
| 数据库备选 | [Supabase](https://supabase.com) | 500MB 存储，2 个项目 |
| 后端 | [Railway](https://railway.app) | $5 免费额度/月 |
| 后端备选 | [Render](https://render.com) | 750 小时/月（会休眠） |
| 前端 | Cloudflare Workers | 10 万请求/天 |

### 实施步骤

#### 1. 创建 Neon 数据库

1. 注册 [neon.tech](https://neon.tech)
2. 创建项目，选择区域（推荐 Singapore 或 US East）
3. 获取连接字符串：

```
postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/agent_hub?sslmode=require
```

#### 2. 部署后端到 Railway

1. 注册 [railway.app](https://railway.app)
2. 连接 GitHub 仓库
3. 添加环境变量：

```bash
DATABASE_URL=postgresql+psycopg://user:password@ep-xxx.neon.tech/agent_hub?sslmode=require
PUBLIC_BASE_URL=https://your-app.railway.app
AUTH_JWT_SECRET=<生成一个随机字符串>
DEEPSEEK_API_KEY=<你的 API Key>
SILICONFLOW_API_KEY=<你的 API Key>
EMBEDDING_BASE_URL=https://api.siliconflow.com/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
```

4. 设置启动命令：

```bash
alembic upgrade head && uvicorn agent_hub.app:app --host 0.0.0.0 --port $PORT
```

#### 3. 部署前端到 Cloudflare Workers

项目已配置好 Cloudflare Workers，执行：

```bash
cd frontend
pnpm build
npx wrangler deploy
```

配置环境变量：

```bash
npx wrangler secret put AGENT_HUB_API_URL
# 输入: https://your-app.railway.app
```

### 免费层限制

| 服务 | 限制 | 影响 |
|------|------|------|
| Neon | 计算自动暂停 | 首次请求延迟 ~500ms |
| Railway | $5/月额度 | 超出后暂停 |
| Render 免费层 | 15 分钟无请求休眠 | 唤醒延迟 ~30s |
| Cloudflare | 10 万请求/天 | MVP 足够 |

---

## 方案 B：低成本云服务

适合：有稳定早期用户、需要更好的响应速度

### 推荐组合

| 组件 | 服务 | 月成本 |
|------|------|--------|
| 数据库 | Neon Pro / Supabase Pro | $25 |
| 后端 | Railway Pro / Render Starter | $7-20 |
| 前端 | Cloudflare Workers | 免费 |
| **合计** | | **¥50-150** |

### Neon Pro 优势

- 无自动暂停，始终在线
- 更大存储和计算资源
- 分支功能（开发/测试环境）

### Railway Pro 优势

- 无休眠
- 更多 CPU/内存
- 自定义域名

---

## 方案 C：阿里云标准部署

适合：面向国内用户、需要 ICP 备案、生产级稳定性

### 架构

```
用户浏览器
    │
    │ HTTPS :443
    ▼
阿里云 SLB / Nginx
    │
    ├── /api/*     → ECS (FastAPI)
    └── /*         → ECS (Next.js) 或 CDN
                         │
                         ▼
                   RDS PostgreSQL
```

### 资源清单

| 资源 | 推荐配置 | 月成本 |
|------|----------|--------|
| ECS | 2 核 4GB | ¥100-200 |
| RDS PostgreSQL | 1 核 2GB 基础版 | ¥80-150 |
| SLB | 按量付费 | ¥20-50 |
| OSS + CDN | 静态资源 | ¥10-30 |
| 域名 + SSL | - | ¥50/年 |
| **合计** | | **¥200-400/月** |

### 实施步骤

#### 1. 创建 RDS PostgreSQL

1. 阿里云控制台 → RDS → 创建实例
2. 选择：
   - 引擎：PostgreSQL 15
   - 规格：1 核 2GB 基础版
   - 存储：20GB ESSD
3. 创建数据库：`agent_hub`
4. 创建账号，获取连接地址

#### 2. 配置 ECS

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 创建部署目录
sudo mkdir -p /srv/agent-hub
cd /srv/agent-hub

# 创建 .env
cat > .env << 'EOF'
DATABASE_URL=postgresql+psycopg://user:password@rm-xxx.pg.rds.aliyuncs.com:5432/agent_hub
PUBLIC_BASE_URL=https://your-domain.com
AUTH_JWT_SECRET=<随机字符串>
DEEPSEEK_API_KEY=<API Key>
SILICONFLOW_API_KEY=<API Key>
EMBEDDING_BASE_URL=https://api.siliconflow.com/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
EOF
```

#### 3. 部署应用

创建 `docker-compose.yml`：

```yaml
services:
  api:
    image: your-registry/agent-hub-api:latest
    restart: unless-stopped
    env_file: .env
    ports:
      - "8000:8000"
    command: >
      sh -c "alembic upgrade head &&
             uvicorn agent_hub.app:app --host 0.0.0.0 --port 8000"

  frontend:
    image: your-registry/agent-hub-frontend:latest
    restart: unless-stopped
    environment:
      - AGENT_HUB_API_URL=http://api:8000
    ports:
      - "3000:3000"
```

启动：

```bash
docker compose up -d
```

#### 4. 配置 Nginx 反向代理

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/private.key;

    # API 路由到后端
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /platform/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location /auth/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    # 其他路由到前端
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 数据库迁移

### 本地数据导出

```bash
# 导出 schema 和数据
pg_dump -h localhost -U agent_hub -d agent_hub > backup.sql
```

### 导入到云数据库

```bash
# Neon
psql "postgresql://user:pass@ep-xxx.neon.tech/agent_hub?sslmode=require" < backup.sql

# 阿里云 RDS
psql -h rm-xxx.pg.rds.aliyuncs.com -U user -d agent_hub < backup.sql
```

### 或者只运行迁移（空数据库）

```bash
DATABASE_URL="postgresql+psycopg://..." alembic upgrade head
```

---

## 环境变量清单

| 变量 | 必需 | 说明 |
|------|------|------|
| `DATABASE_URL` | 是 | PostgreSQL 连接字符串 |
| `PUBLIC_BASE_URL` | 是 | 后端公开 URL |
| `AUTH_JWT_SECRET` | 是 | JWT 签名密钥（≥32 字符） |
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API 密钥 |
| `SILICONFLOW_API_KEY` | 是 | 向量嵌入 API 密钥 |
| `EMBEDDING_BASE_URL` | 是 | 向量嵌入服务 URL |
| `EMBEDDING_MODEL` | 是 | 嵌入模型名称 |
| `LANGFUSE_SECRET_KEY` | 否 | 可观测性（可选） |
| `LANGFUSE_PUBLIC_KEY` | 否 | 可观测性（可选） |
| `NEO4J_PASSWORD` | 否 | 技能图谱（可选） |

---

## 推荐路径

```
MVP 验证（方案 A）
    │
    │  用户增长，验证 PMF
    ▼
低成本云服务（方案 B）
    │
    │  需要国内访问/备案
    ▼
阿里云标准（方案 C）
```

### 建议

1. **先用方案 A 验证**：零成本，快速上线
2. **收集用户反馈**：观察使用情况
3. **按需升级**：用户增长后再投入更多资源

---

## 快速开始检查清单

### 方案 A（免费层）

- [ ] 注册 Neon，创建数据库
- [ ] 注册 Railway，连接 GitHub
- [ ] 配置 Railway 环境变量
- [ ] 运行数据库迁移
- [ ] 部署前端到 Cloudflare Workers
- [ ] 验证端到端功能

### 方案 C（阿里云）

- [ ] 创建 RDS PostgreSQL 实例
- [ ] 创建 ECS 实例
- [ ] 安装 Docker 和 Nginx
- [ ] 配置 SSL 证书
- [ ] 部署应用容器
- [ ] 配置域名解析
- [ ] 验证端到端功能
- [ ] 配置监控告警
