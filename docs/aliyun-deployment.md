# Agent Hub 阿里云实施手册

> 文档状态：实施方案  
> 适用版本：Agent Hub 0.2.x  
> 更新日期：2026-07-17

本文说明如何把本仓库的 FastAPI 后端、Next.js 管理控制台和 SQLite 数据库部署到阿里云。第一阶段采用一台 ECS 和 Docker Compose，适合内部使用、演示和小规模 MVP。

生产环境不要直接照搬当前的演示配置。上线前必须关闭演示数据、启用 HTTPS、限制管理后台访问，并为 SQLite 配置持久化和备份。

## 1. 目标和边界

第一阶段的目标：

- 使用一个域名通过 HTTPS 访问管理控制台。
- FastAPI 不直接暴露 `8000` 端口。
- SQLite 数据保存在 ECS 云盘，而不是容器内部。
- 前后端使用独立 Docker 镜像，可以单独升级和回滚。
- 每天备份数据库，并配置 ECS 自动快照。
- 在不改动业务规则的前提下尽快上线。

第一阶段不包含：

- 多台后端服务器或自动扩容。
- RDS PostgreSQL。
- 完整的用户、角色和权限系统。
- Kubernetes/ACK。

当前仓储是 SQLite 实现，多实例并发会破坏幂等和一致性假设。因此在迁移到 PostgreSQL 之前，后端只能运行一个实例和一个 Uvicorn worker。

## 2. 部署架构

```text
用户浏览器
    │
    │ HTTPS :443
    ▼
阿里云 DNS
    │
    ▼
ECS 安全组
    │
    ▼
Nginx 容器
    ├── /                  → frontend:3000
    ├── /api/v1/*          → backend:8000
    ├── /platform/*        → backend:8000
    └── /health            → backend:8000
                                │
                                ▼
                    /srv/agent-hub/data/agent.db
```

前端的 `/api/invoke` 必须继续交给前端服务处理。Nginx 不能把整个 `/api/*` 都代理给 FastAPI，只代理 `/api/v1/*`。

## 3. 阿里云资源清单

### 3.1 MVP 推荐规格

| 资源 | 推荐配置 | 说明 |
| --- | --- | --- |
| ECS | 2 核 4 GB | 同时运行 Nginx、Node.js 和 FastAPI |
| 操作系统 | Ubuntu 24.04 LTS x86_64 | 示例命令以 Ubuntu 为准 |
| 系统盘 | 60～100 GB ESSD | 保存镜像、日志和小规模业务数据 |
| 公网带宽 | 3～5 Mbps 起步 | 后续按监控扩容 |
| ACR | 测试可用个人版 | 保存前后端 Docker 镜像 |
| DNS | 阿里云云解析 DNS | 域名解析到 ECS 公网 IP |
| SSL | 阿里云证书或其他可信证书 | Nginx HTTPS 终止 |
| 自动快照 | 每天一次，保留 7～14 天 | 保护 ECS 云盘 |
| OSS | 可选，建议启用 | 保存 SQLite 独立备份 |

### 3.2 地域选择

- 面向中国内地长期运营：选择杭州、上海等中国内地地域，并提前办理 ICP 备案。
- 希望先快速验证：可选择中国香港地域，不需要中国内地 ICP 备案，但中国内地访问质量可能较弱。
- ECS、ACR 和 OSS 尽量选择同一地域，使用内网地址传输镜像和备份。

### 3.3 安全组

| 端口 | 来源 | 用途 |
| --- | --- | --- |
| 22 | 管理员固定公网 IP | SSH 运维 |
| 80 | `0.0.0.0/0` | HTTP 跳转 HTTPS、证书验证 |
| 443 | `0.0.0.0/0` | HTTPS 服务 |
| 3000 | 不开放 | 仅 Docker 内网访问 |
| 8000 | 不开放 | 仅 Docker 内网访问 |

不要将 SSH 的 `22` 端口长期对全网开放。优先使用密钥登录，并关闭密码登录和 root 远程登录。

## 4. 上线前的代码改造

以下改造应在创建生产镜像之前完成。

### 4.1 将前端切换到标准 Next.js Node 运行时

当前 `frontend/vite.config.ts`、`frontend/worker/index.ts` 和前端脚本偏向 Cloudflare Worker。ECS 上建议使用 Next.js 的 Node.js 生产服务器。

将 `frontend/package.json` 的生产脚本调整为：

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start -H 0.0.0.0 -p 3000",
    "lint": "eslint . --ignore-pattern dist --ignore-pattern .next"
  }
}
```

现有 `frontend/tests/rendered-html.test.mjs` 直接加载 Vinext 生成的 `dist/server/index.js`，不能继续作为 Node.js 部署测试。切换运行时后，需要将它迁移为针对 `next start` 的 HTTP 页面测试；在迁移完成前，至少执行下面的构建和启动检查。

在 `frontend/next.config.ts` 中启用独立输出：

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
```

完成后必须在本地验证：

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm lint
pnpm build
pnpm start
```

另开一个终端检查页面：

```bash
curl --fail http://127.0.0.1:3000/dashboard
curl --fail http://127.0.0.1:3000/agents
```

只有 `next build` 和页面检查通过后，才能继续制作 ECS 镜像。Cloudflare 专用文件可以暂时保留，但生产构建不能再依赖 Wrangler 或 Miniflare。

### 4.2 添加后端 Dockerfile

在仓库根目录创建 `Dockerfile.backend`：

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/agent.db

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .
RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "agent_hub.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

不要增加 `--workers`。SQLite 阶段必须保持一个进程。

### 4.3 添加前端 Dockerfile

在仓库根目录创建 `Dockerfile.frontend`：

```dockerfile
FROM node:22-bookworm-slim AS dependencies
WORKDIR /app
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-bookworm-slim AS builder
WORKDIR /app
RUN corepack enable
COPY --from=dependencies /app/node_modules ./node_modules
COPY frontend/ ./
RUN pnpm build

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app

RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV HOSTNAME=0.0.0.0 PORT=3000

CMD ["node", "server.js"]
```

### 4.4 添加 `.dockerignore`

在仓库根目录创建 `.dockerignore`：

```text
.git
.venv
node_modules
frontend/node_modules
frontend/.next
frontend/.wrangler
data
*.db
*.log
.env
.env.*
frontend/.env*
```

环境变量和数据库文件不能打进镜像。

### 4.5 本地构建验证

```bash
docker build -f Dockerfile.backend -t agent-hub-backend:local .
docker build -f Dockerfile.frontend -t agent-hub-frontend:local .
```

如果开发电脑是 Apple Silicon，而 ECS 是 x86_64，推送 ACR 时必须构建 `linux/amd64` 镜像：

```bash
docker buildx build --platform linux/amd64 \
  -f Dockerfile.backend \
  -t <ACR地址>/agent-hub/backend:<Git提交号> \
  --push .

docker buildx build --platform linux/amd64 \
  -f Dockerfile.frontend \
  -t <ACR地址>/agent-hub/frontend:<Git提交号> \
  --push .
```

不要使用可变的 `latest` 作为生产发布版本。镜像标签使用 Git commit ID，例如 `a31f08d`。

## 5. ECS 初始化

### 5.1 登录服务器

```bash
ssh -i /path/to/key.pem <管理员用户>@<ECS公网IP>
```

### 5.2 安装 Docker

Docker 的安装源和包名可能随镜像变化。可以购买带 Docker 的官方/可信镜像，或者按 Docker 官方 Ubuntu 文档安装 Docker Engine 和 Compose 插件。

安装完成后检查：

```bash
sudo docker version
sudo docker compose version
```

### 5.3 创建部署目录

```bash
sudo mkdir -p /srv/agent-hub/data
sudo mkdir -p /srv/agent-hub/backups
sudo mkdir -p /srv/agent-hub/nginx/conf.d
sudo mkdir -p /srv/agent-hub/ssl
sudo chown -R <管理员用户>:<管理员用户> /srv/agent-hub
cd /srv/agent-hub
```

数据和备份目录必须位于 ECS 云盘上，不要使用容器临时层。

## 6. 生产配置

### 6.1 镜像版本文件

在 `/srv/agent-hub/.env` 中保存非敏感的发布版本：

```env
BACKEND_IMAGE=<ACR地址>/agent-hub/backend:a31f08d
FRONTEND_IMAGE=<ACR地址>/agent-hub/frontend:a31f08d
```

### 6.2 应用环境变量

创建 `/srv/agent-hub/app.env`：

```env
AGENT_HUB_DEMO_MODE=false
AGENT_HUB_API_URL=http://backend:8000
DATABASE_PATH=/data/agent.db
```

设置文件权限：

```bash
chmod 600 /srv/agent-hub/app.env
```

不要把 `app.env` 提交到 Git。如果后续加入第三方 API Key，优先迁移到阿里云 KMS 或其他密钥管理服务。

### 6.3 Docker Compose

创建 `/srv/agent-hub/compose.yaml`：

```yaml
services:
  backend:
    image: ${BACKEND_IMAGE}
    restart: unless-stopped
    env_file:
      - app.env
    volumes:
      - /srv/agent-hub/data:/data
      - /srv/agent-hub/backups:/backups
    expose:
      - "8000"
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
      interval: 30s
      timeout: 5s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: 20m
        max-file: "5"

  frontend:
    image: ${FRONTEND_IMAGE}
    restart: unless-stopped
    env_file:
      - app.env
    depends_on:
      backend:
        condition: service_healthy
    expose:
      - "3000"
    logging:
      driver: json-file
      options:
        max-size: 20m
        max-file: "5"

  nginx:
    image: nginx:1.28-alpine
    restart: unless-stopped
    depends_on:
      - frontend
      - backend
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /srv/agent-hub/nginx/conf.d:/etc/nginx/conf.d:ro
      - /srv/agent-hub/ssl:/etc/nginx/ssl:ro
    logging:
      driver: json-file
      options:
        max-size: 20m
        max-file: "5"
```

不要给 `backend` 和 `frontend` 配置宿主机 `ports`。它们只通过 Compose 内网访问。

### 6.4 Nginx 配置

将证书文件保存为：

```text
/srv/agent-hub/ssl/fullchain.pem
/srv/agent-hub/ssl/private.key
```

私钥权限设为仅管理员可读：

```bash
chmod 600 /srv/agent-hub/ssl/private.key
```

创建 `/srv/agent-hub/nginx/conf.d/agent-hub.conf`，将 `agent.example.com` 替换成真实域名：

```nginx
server {
    listen 80;
    server_name agent.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name agent.example.com;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/private.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 10m;

    location /platform/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/v1/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /health {
        proxy_pass http://backend:8000/health;
    }

    location = /openapi.json {
        proxy_pass http://backend:8000/openapi.json;
    }

    location = /docs {
        proxy_pass http://backend:8000/docs;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://frontend:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

生产环境可以关闭 `/docs` 和 `/openapi.json` 的公网代理。

### 6.5 管理后台访问保护

当前应用没有完整登录认证。上线初期至少启用以下一种保护：

- Nginx Basic Auth。
- 只允许办公室或 VPN 出口 IP。
- 通过零信任网关访问。

IP 白名单示例，可添加到第二个 `server` 块中：

```nginx
allow 203.0.113.10;
deny all;
```

如果用户来源 IP 不固定，使用 Basic Auth 或零信任方案，不要为了方便而完全取消保护。

## 7. 首次发布

### 7.1 登录 ACR

在 ECS 上使用阿里云控制台给出的登录命令：

```bash
sudo docker login <ACR地址>
```

不要把 ACR 密码写入 Compose 或 Git。

### 7.2 拉取并启动

```bash
cd /srv/agent-hub
sudo docker compose config
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
```

### 7.3 查看日志

```bash
sudo docker compose logs --tail=100 backend
sudo docker compose logs --tail=100 frontend
sudo docker compose logs --tail=100 nginx
```

### 7.4 域名解析

在阿里云 DNS 创建 A 记录：

```text
主机记录：agent
记录类型：A
记录值：ECS 公网 IP
```

等待解析生效后再验证 HTTPS。

## 8. 上线验收

### 8.1 健康检查

```bash
curl --fail https://agent.example.com/health
```

预期返回类似：

```json
{"status":"ok","registered_agents":1}
```

### 8.2 API 验证

```bash
curl --fail https://agent.example.com/platform/v1/agents \
  -H 'X-Actor: deployment-check'
```

### 8.3 页面验证

依次检查：

- 控制台首页可正常打开。
- Agent 列表来自真实后端，不是演示数据。
- 来源、职位和审计页面能正常读取。
- 浏览器控制台没有混合内容或跨域错误。
- `/api/invoke` 能由前端转发到后端。
- 重启容器后已有数据仍然存在。

重启持久化验证：

```bash
cd /srv/agent-hub
sudo docker compose restart backend
sudo docker compose ps
```

## 9. 数据备份

### 9.1 SQLite 一致性备份

不要在数据库正在写入时直接使用 `cp` 复制 `agent.db`。使用 SQLite backup API 生成一致性备份：

```bash
cd /srv/agent-hub
sudo docker compose exec -T backend python -c "import datetime, sqlite3; stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'); src=sqlite3.connect('/data/agent.db'); dst=sqlite3.connect('/backups/agent-' + stamp + '.db'); src.backup(dst); dst.close(); src.close()"
```

确认备份文件：

```bash
ls -lh /srv/agent-hub/backups
```

建议每天执行一次，并将备份同步到 OSS。保留策略可以设置为：

- 每日备份保留 14 天。
- 每周备份保留 8 周。
- 发布前额外保留一个手动备份。

### 9.2 ECS 自动快照

在阿里云控制台为承载 `/srv/agent-hub` 的云盘绑定自动快照策略：

- 每天低峰期一次。
- 至少保留 7～14 天。
- 重大升级前创建手动快照。

数据库备份和云盘快照应同时配置。快照用于整盘恢复，SQLite 备份用于快速恢复单个数据库文件。

## 10. 日常发布和回滚

### 10.1 发布新版本

1. 在 CI 或开发机完成测试。
2. 构建 `linux/amd64` 镜像并推送 ACR。
3. 在 ECS 上执行一次 SQLite 备份。
4. 修改 `/srv/agent-hub/.env` 中的镜像标签。
5. 拉取并重建容器。
6. 执行健康检查和页面验收。

```bash
cd /srv/agent-hub
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
curl --fail https://agent.example.com/health
```

### 10.2 应用回滚

将 `.env` 中的镜像标签改回上一版本，然后执行：

```bash
cd /srv/agent-hub
sudo docker compose pull
sudo docker compose up -d
```

### 10.3 数据回滚

只有应用回滚不能解决数据兼容问题时，才恢复数据库：

1. 停止后端容器。
2. 保存当前数据库副本。
3. 使用验证过的 SQLite 备份恢复。
4. 启动后端并验证健康状态。

数据库恢复会覆盖新数据，执行前必须确认恢复点和业务影响。

## 11. 监控和告警

第一阶段至少配置：

- ECS CPU、内存、磁盘使用率告警。
- 云盘剩余空间低于 20% 告警。
- `https://agent.example.com/health` 外部探测。
- Docker 容器退出检查。
- Nginx `5xx` 日志检查。
- 备份任务失败告警。

建议阈值：

| 指标 | 告警条件 |
| --- | --- |
| CPU | 连续 10 分钟高于 80% |
| 内存 | 连续 10 分钟高于 85% |
| 磁盘 | 使用率高于 80% |
| 健康检查 | 连续 3 次失败 |
| HTTP 5xx | 5 分钟内持续出现 |

## 12. 生产化升级路线

当出现以下任一情况时，应启动 PostgreSQL 改造：

- 需要运行两个或更多后端实例。
- SQLite 锁等待或写入延迟明显增加。
- 需要零停机发布。
- 数据量和查询复杂度显著增加。
- 业务要求数据库高可用和时间点恢复。

目标架构：

```text
WAF / SLB
    │
    ├── 前端服务
    └── 多实例 FastAPI
             │
             ▼
       RDS PostgreSQL
```

迁移 PostgreSQL 不是简单替换环境变量。需要新增 PostgreSQL Repository、结构化表和迁移脚本，并重新实现事务幂等、连接池、备份和恢复流程。

## 13. 实施检查清单

### 代码与镜像

- [ ] 前端已切换为标准 Next.js Node 生产构建。
- [ ] Python 测试通过。
- [ ] 前端 lint、build 和页面测试通过。
- [ ] 前后端镜像均为 `linux/amd64`。
- [ ] 镜像使用不可变 Git commit 标签。
- [ ] 镜像中没有 `.env`、证书或 SQLite 文件。

### 阿里云

- [ ] ECS、ACR、OSS 位于预期地域。
- [ ] 中国内地网站已完成所需备案。
- [ ] 安全组只开放 22、80 和 443。
- [ ] SSH 仅允许管理员 IP 和密钥登录。
- [ ] DNS 已指向 ECS 公网 IP。
- [ ] HTTPS 证书有效且已配置续期提醒。
- [ ] ECS 自动快照已启用。

### 应用

- [ ] `AGENT_HUB_DEMO_MODE=false`。
- [ ] `AGENT_HUB_API_URL=http://backend:8000`。
- [ ] `DATABASE_PATH=/data/agent.db`。
- [ ] 后端只有一个实例和一个 worker。
- [ ] `3000` 和 `8000` 没有映射到公网。
- [ ] 管理后台已启用认证、IP 白名单或零信任访问。
- [ ] 健康检查、页面和动作调用验证通过。

### 运维

- [ ] SQLite 一致性备份任务已启用。
- [ ] 已完成一次实际恢复演练。
- [ ] 日志已配置大小和文件数限制。
- [ ] CPU、内存、磁盘和健康检查告警已配置。
- [ ] 上一版本镜像标签和回滚步骤已记录。

## 14. 阿里云官方参考

- [容器镜像服务 ACR](https://help.aliyun.com/zh/acr/)
- [中国内地网站 ICP 备案快速入门](https://help.aliyun.com/zh/icp-filing/basic-icp-service/getting-started/quick-start-for-icp-filing-for-personal-websites)
- [ECS 快照概述](https://help.aliyun.com/zh/ecs/user-guide/snapshot-overview/)
- [为云盘设置自动快照策略](https://help.aliyun.com/zh/ecs/user-guide/configure-multiple-automatic-snapshot-policies-for-a-cloud-disk-whitelist)
