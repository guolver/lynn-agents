# 注册/登录设计（自建轻量认证服务）

> 状态：已确认设计
> 日期：2026-07-19
> 范围：在应用内实现真实的用户注册/登录，替代第一阶段假设的“外部网关认证”

## 1. 背景与目标

第一阶段（`docs/superpowers/specs/2026-07-19-phase-one-security-workflows-design.md`）已经
建立了 `Principal`、RBAC、租户隔离和 `trusted_gateway`/`development` 两种身份解析模式，但
明确把“应用内实现 OAuth/OIDC 登录与 token 签发”列为非目标，假设身份由外部网关完成认证。
实际上项目目前既没有外部网关，前端各代理路由也只是硬编码 `X-Actor: chat-user`。

本阶段目标：实现真实的邮箱+密码注册/登录，签发和校验应用自己的 token，同时**完全复用**
第一阶段已经做好且测试过的 `Principal`/RBAC/租户隔离，不重写这部分。

面向对象是未来的 toC 用户（求职者自助注册），当前先做单租户场景，为后续扩展手机号/社交
登录和多租户自注册预留结构，但不在本期实现。

## 2. 已确认决策

- 认证自建（argon2id 密码哈希 + 自签 JWT），不接第三方托管认证服务。
- 本期只支持邮箱 + 密码；手机号/短信验证码、第三方社交登录留到后续阶段。
- 单租户：所有新注册用户进入现有 `default` 租户，角色默认 `user`；`admin`/`operator` 仍由
  平台方手动提升，本期不做租户自注册。
- 本期不做邮箱验证、不做密码重置（项目目前没有邮件发送基础设施）；`users.email_verified`
  预留字段，默认 `false`，不影响登录可用性。
- access token 用无状态 JWT；refresh token 用有状态、可吊销的随机字符串，两者机制不同。
- JWT 校验作为 `IdentityMiddleware` 的一条新增独立路径（Bearer token），不改动、不影响现有
  `trusted_gateway` 和 `development` 两种模式。
- 密码规则只校验长度（≥8 位），不强制大小写/数字/符号复杂度（参考 NIST 800-63B）。

## 3. 模块划分

新增 `agent_hub/identity/`，与 `agents/global_part_time/` 同级，沿用项目既有分层：

- `domain.py`：邮箱格式、密码长度校验（纯函数）
- `repository.py`：`users`、`refresh_tokens` 表的读写，遵循 `RepositoryProtocol` 同款的
  显式 tenant 参数约束
- `service.py`：`register()`、`login()`、`refresh()`、`logout()` 用例；内部完成 argon2 哈希
  与验证、JWT 签发与校验、Redis 登录限流
- `http_api.py`：`POST /auth/register`、`/auth/login`、`/auth/refresh`、`/auth/logout`

这四个路径加入 `IdentityMiddleware._BYPASS_PATHS`（注册登录发生在身份建立之前，不需要、也
不能要求先有已验证身份）。

## 4. 身份校验集成：Bearer JWT 路径

`IdentityMiddleware.dispatch` 新增独立分支，优先于现有 `mode` 判断：

```text
若请求携带 Authorization: Bearer <token>：
    用 AUTH_JWT_SECRET 校验签名与过期时间
    成功 → 从 claims 构造 Principal(actor_id=sub, tenant_id, roles, trusted=True)
    失败（签名错误/过期）→ 401
否则：
    走现有 mode 判断（trusted_gateway / development），逻辑不变
```

`AUTH_JWT_SECRET` 是独立于 `TRUSTED_GATEWAY_SECRET` 的新密钥，生产环境缺失时应用拒绝启动
（与 `trusted_gateway` 模式对 `TRUSTED_GATEWAY_SECRET` 的 fail-fast 处理一致）。

这一设计不修改任何现有 mode 的行为，`trusted_gateway`/`development` 的既有测试不受影响；
未来若接入真实上游网关，两条路径可以并存。

## 5. 数据模型

新增 Alembic 迁移，`down_revision` 接在 `20260719_0007` 之后。

**`users`**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(36) | UUID 主键 |
| tenant_id | String(100) | 默认 `"default"`，非空 |
| email | String(255) | 登录名 |
| password_hash | String(255) | argon2id 哈希 |
| roles | String(100) | 逗号分隔，复用 `security.py` 的 `parse_roles()`；注册默认 `"user"` |
| email_verified | Boolean | 默认 `false`，本期不使用，为后续邮件服务预留 |
| created_at / updated_at | DateTime(timezone=True) | 与项目现有表一致的时间戳约定 |

唯一约束：`(tenant_id, email)`（`uq_users_tenant_email`）。

**`refresh_tokens`**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(36) | UUID 主键 |
| user_id | String(36) | 外键 → `users.id` |
| tenant_id | String(100) | 冗余存储，便于按租户查询与清理 |
| token_hash | String(64) | refresh token 的 SHA-256 哈希，不存明文 |
| expires_at | DateTime(timezone=True) | 30 天有效期 |
| revoked_at | DateTime(timezone=True) | 可空；登出、改密或轮换时置位 |
| created_at | DateTime(timezone=True) | 时间戳 |

索引：`(token_hash)` 唯一索引用于登录校验；`(user_id)` 索引用于登出/改密时批量吊销。

access token 不落库：JWT 内容为 `{sub: user_id, tenant_id, roles, iat, exp}`，有效期 15
分钟，`AUTH_JWT_SECRET` HS256 签名。refresh token 用有状态设计是因为它需要“可吊销”能力
（登出、检测到泄露时作废），纯无状态 JWT 做不到这点。

## 6. 认证流程

### 6.1 注册 `POST /auth/register {email, password}`

1. `domain.py` 校验邮箱格式、密码长度 ≥ 8。
2. 查 `(tenant_id="default", email)` 是否已存在 → 存在返回 `409`。
3. argon2id 哈希密码，写入 `users`（`roles="user"`, `email_verified=false`），写审计日志
   （复用现有 `repository.audit()`）。
4. 成功后直接签发 access/refresh token 并返回（免登录跳转）。

### 6.2 登录 `POST /auth/login {email, password}`

1. 查 Redis 限流计数器 `login_fail:{tenant_id}:{email}`，15 分钟窗口内失败次数 ≥5 直接返回
   `429`，不再查库或验密码。Redis 复用现有 `CELERY_BROKER_URL`/`CHAT_STREAM_REDIS_URL` 同一
   实例，无需新增基础设施。
2. 查用户并校验密码。“邮箱不存在”与“密码错误”统一返回同一个 `401 invalid email or
   password`，不做区分，防止被用于枚举已注册邮箱。
3. 失败：计数器 `INCR` 并设置/续期 TTL。成功：清零计数器，签发新的 access/refresh token，
   写审计日志。

### 6.3 刷新 `POST /auth/refresh {refresh_token}`

1. 对提交的 token 取 SHA-256，查 `refresh_tokens` 中匹配、未过期、未吊销的记录；不满足则
   `401`。
2. 签发新 access token；同时**轮换** refresh token：旧记录标记 `revoked_at`，签发新
   refresh token 并落库。即使旧 token 泄露，被使用一次后立即失效，可用于检测重放（旧 token
   再次出现即视为异常，可选之后扩展为吊销该用户全部 token，本期先满足基本轮换）。

### 6.4 登出 `POST /auth/logout {refresh_token}`

对提交的 refresh token 取哈希后匹配记录，标记 `revoked_at`。access token 本身无法主动失效
（无状态），15 分钟后自然过期，可接受。

## 7. 前端集成

- 新增 `frontend/app/api/auth/{register,login,refresh,logout}/route.ts`，代理到 FastAPI 对应
  的 `/auth/*` 端点。
- 登录/注册成功后，BFF 将 `access_token`、`refresh_token` 写为 `httpOnly + Secure(生产环境)
  + SameSite=Lax` cookie。浏览器 JS 不可读取，降低 XSS 场景下 token 被窃取的风险。
- 现有代理路由（`chat/sessions/route.ts`、`chat/sessions/[id]/upload/route.ts` 等）中硬编码
  的 `X-Actor: chat-user` 改为：服务端读取 `access_token` cookie，转发
  `Authorization: Bearer <token>` 给 FastAPI。这些分散的转发逻辑收敛进
  `frontend/lib` 下新增的统一 Agent Hub 客户端，集中处理身份头转发、超时与错误——第一阶段
  设计文档里已经把这两项列为待办，本阶段一并完成。
- 该统一客户端捕获 FastAPI 返回的 `401`（access token 过期），用 `refresh_token` cookie 调
  `/api/auth/refresh` 静默换新后重试一次；refresh 也失败则清 cookie 并跳转 `/login`。
- 新增 `/login`、`/register` 页面，以及 `middleware.ts` 保护 `(console)` 路由组，未登录跳转
  `/login`。第一阶段设计中“本阶段不实现前端登录页面”这条在本阶段被显式取代。

## 8. 安全清单

- 密码：argon2id 哈希，绝不明文存储或记录到日志/审计详情。
- 密码规则：仅校验长度 ≥8，不强制复杂度规则。
- Token：`AUTH_JWT_SECRET` 生产环境缺失时拒绝启动；access token 只签名校验，不落库；
  refresh token 有状态、可吊销、登录时轮换。
- 传输：token 只放 httpOnly cookie，不进 localStorage 或任何 JS 可读存储。
- 防爆破：Redis 登录失败限流，窗口期内锁定。
- 防枚举：登录失败统一错误信息，不区分邮箱不存在与密码错误。
- 审计：注册、登录成功/失败、刷新、登出均写入现有审计日志，记录 tenant/actor/时间，不记录
  密码或 token 原文。

## 9. 测试策略

延续项目现有测试驱动习惯：

- `domain.py`：邮箱格式、密码长度边界用例。
- `service.py`：重复邮箱注册冲突、登录成功/失败/限流锁定、refresh 轮换与旧 token 使用后
  被拒绝、登出后该 refresh token 失效。
- `IdentityMiddleware`：新增 Bearer JWT 路径的有效/无效签名/过期 token 用例；现有
  `trusted_gateway`/`development` 两种模式测试保持零回归。
- Repository 契约测试：覆盖 `users`/`refresh_tokens` 的增删查与唯一约束。
- 迁移测试：比照现有 `tests/test_tenant_migration.py` 风格。
- 前端：不引入新测试框架，沿用现有 `pnpm test`（build + `node --test` 冒烟检查）覆盖登录/
  注册页面渲染；深度覆盖仍以 Python 侧为主。

## 10. 非目标

- 邮箱验证、密码重置（下一阶段，依赖邮件发送基础设施）。
- 手机号/短信验证码登录、第三方社交登录（微信/Google 等）。
- 多租户自注册创建新 tenant（维持单一 `default` 租户）。
- MFA/二次验证。
- 账号封禁/管理后台、登录设备管理。
- 替换或修改第一阶段已实现的 `trusted_gateway`/`development` 模式行为。

## 11. 完成标准

1. 用户可以通过邮箱+密码完成注册、登录、刷新、登出全流程，且密码从不以明文形式存储或
   传输落盘。
2. 生产环境缺失 `AUTH_JWT_SECRET` 时应用拒绝启动。
3. 登录接口对暴力破解有限流保护，错误信息不泄露账号是否存在。
4. refresh token 可靠轮换与吊销，登出后旧 token 立即失效。
5. 前端全部代理路由使用真实登录态转发身份，不再有硬编码 `X-Actor`。
6. 新增身份、限流、token 生命周期测试通过，第一阶段既有安全与隔离测试无回归。
