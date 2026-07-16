# 开发环境搭建手册

## 前置要求

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| Python | >= 3.10（推荐 3.12） | 后端运行时 |
| Node.js | >= 22.13.0 | 前端运行时 |
| pnpm | 10.12.1 | 前端包管理器，通过 corepack 启用 |

## 一、后端启动

### 1. 创建虚拟环境

```bash
cd /path/to/my-agent
python3 -m venv .venv
source .venv/bin/activate
```

激活成功后，终端提示符前会出现 `(.venv)` 标识。

### 2. 安装依赖

```bash
pip install -e '.[dev]'
```

> **代理问题**：如果你使用了 Clash 等代理工具但未启动，pip 会因为连不上代理而报 `ProxyError`。两种解决方式：
>
> - 启动你的代理软件（确保 7890 端口可用）
> - 安装时绕过代理：`pip install --proxy "" -e '.[dev]'`
>
> 如果系统代理开启（macOS 系统设置 > 网络 > 代理），环境变量 `unset` 无效，必须用 `--proxy ""` 参数。

### 3. 配置环境变量

```bash
cp .env.example .env
```

默认配置：

```env
DATABASE_PATH=./data/agent.db
PUBLIC_BASE_URL=http://localhost:8000
```

### 4. 启动服务

```bash
uvicorn agent_hub.app:app --reload
```

- 服务地址：http://localhost:8000
- API 文档：http://localhost:8000/docs
- `--reload` 开启代码热重载，修改代码后自动重启

### 5. 运行测试

```bash
python -m unittest discover -s tests -v
```

---

## 二、前端启动

### 1. 启用 pnpm

```bash
corepack enable
```

### 2. 安装依赖

```bash
cd frontend
pnpm install
```

### 3. 配置环境变量

```bash
cp .env.example .env.local
```

配置说明：

```env
# true  = 使用内置演示数据，无需启动后端
# false = 连接真实后端 API
AGENT_HUB_DEMO_MODE=true
AGENT_HUB_API_URL=http://127.0.0.1:8000
```

如果只是看前端界面，保持 `AGENT_HUB_DEMO_MODE=true` 即可。要连接后端，改为 `false` 并确保后端已启动。

### 4. 启动开发服务器

```bash
pnpm dev
```

### 5. 其他命令

| 命令 | 说明 |
|------|------|
| `pnpm build` | 构建生产版本 |
| `pnpm start` | 启动生产服务器 |
| `pnpm lint` | ESLint 代码检查 |
| `pnpm test` | 构建并运行测试 |
| `pnpm db:generate` | 生成数据库迁移文件 |

---

## 三、常见问题

### `command not found: python`

macOS 默认没有 `python` 命令，使用 `python3` 代替。或在 `~/.zshrc` 中添加：

```bash
alias python="python3"
alias pip="pip3"
```

添加后执行 `source ~/.zshrc` 生效。

### `Address already in use`

端口 8000 被占用，杀掉占用进程：

```bash
lsof -ti:8000 | xargs kill -9
```

然后重新启动。

### pip 安装报 `ProxyError` / `Connection refused`

代理软件未运行但系统代理已开启。解决方式：

```bash
# 方式一：启动代理软件
# 方式二：绕过代理安装
pip install --proxy "" -e '.[dev]'
```

### 数据库

默认使用 SQLite，数据文件位于 `./data/agent.db`，无需额外配置数据库。
