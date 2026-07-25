# Agent Hub 生产就绪清单

> 当前评分：6.5/10 | 目标：9/10

## 概览

| 维度 | 当前 | 目标 | 优先级 |
|------|------|------|--------|
| CI/CD | 2/10 | 9/10 | P0 |
| 安全性 | 6/10 | 9/10 | P0 |
| 可观测性 | 5/10 | 8/10 | P1 |
| 测试覆盖 | 7/10 | 9/10 | P1 |
| 错误处理 | 8/10 | 9/10 | P2 |
| 配置管理 | 5/10 | 8/10 | P2 |
| 文档 | 7/10 | 9/10 | P1 |

---

## P0：必须完成（部署前）

### 1. CI/CD 管道

- [ ] **GitHub Actions 基础流水线**
  - [ ] PR 触发：lint (ruff, eslint) + 单元测试
  - [ ] main 分支：构建 Docker 镜像 + 推送到 Registry
  - [ ] 版本标签：`v1.0.0` 格式，镜像同步打标

- [ ] **代码质量门禁**
  - [ ] ruff 检查必须通过
  - [ ] ESLint 检查必须通过
  - [ ] 测试覆盖率 >= 80%

- [ ] **安全扫描**
  - [ ] bandit（Python SAST）
  - [ ] npm audit / pnpm audit（依赖漏洞）
  - [ ] trivy（Docker 镜像扫描）

### 2. 输入验证

当前问题：`ActionDefinition.input_schema` 声明了 JSON Schema 但**未强制验证**。

- [ ] **平台层验证中间件**
  - [ ] 在 `platform.py` 的 `invoke_action` 中添加 JSON Schema 验证
  - [ ] 验证失败返回 422 + 详细错误信息
  - [ ] 单元测试覆盖边界情况

- [ ] **API 端点验证**
  - [ ] 审计所有 Pydantic 模型，确保字段约束完整
  - [ ] 添加字符串长度限制、数值范围、枚举值校验

### 3. 安全加固

- [ ] **API 速率限制**
  - [ ] 全局速率限制（如 100 req/min/IP）
  - [ ] 敏感端点额外限制（登录、注册）
  - [ ] 使用 Redis 存储计数器

- [ ] **安全响应头**
  ```python
  # FastAPI middleware
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  X-XSS-Protection: 1; mode=block
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Content-Security-Policy: default-src 'self'
  ```

- [ ] **CORS 配置**
  - [ ] 仅允许前端域名
  - [ ] 生产环境禁用 `allow_origins=["*"]`

- [ ] **敏感数据脱敏**
  - [ ] 日志中过滤密码、token、API key
  - [ ] 错误响应不暴露内部堆栈

- [ ] **SQL 注入审计**
  - [ ] 检查所有原始 SQL 查询
  - [ ] 确保使用参数化查询

### 4. 部署文档

- [ ] **生产环境配置清单** (`docs/production-config.md`)
  - [ ] 必需环境变量列表
  - [ ] 推荐配置值
  - [ ] 秘钥生成方法

- [ ] **部署步骤** (`docs/deployment-guide.md`)
  - [ ] 数据库迁移流程
  - [ ] 零停机部署步骤
  - [ ] 回滚流程

- [ ] **秘钥管理**
  - [ ] JWT_SECRET 生成和轮换
  - [ ] 数据库密码管理
  - [ ] API Key 存储方案

---

## P1：强烈推荐（1-2 周内）

### 5. 可观测性

- [ ] **指标导出**
  - [ ] Prometheus 端点 `/metrics`
  - [ ] 关键指标：请求延迟、错误率、队列深度
  - [ ] Grafana 仪表板模板

- [ ] **分布式追踪**
  - [ ] OpenTelemetry 集成
  - [ ] 请求 ID 透传（X-Request-ID）
  - [ ] Jaeger 或 Tempo 后端

- [ ] **集中日志**
  - [ ] 结构化 JSON 日志格式
  - [ ] ELK Stack 或 CloudWatch 集成
  - [ ] 日志级别：生产环境 INFO，可动态调整

- [ ] **告警规则**
  - [ ] 错误率 > 1% 告警
  - [ ] P99 延迟 > 2s 告警
  - [ ] 队列积压 > 1000 告警
  - [ ] 磁盘/内存使用率告警

### 6. 测试补充

- [ ] **前端单元测试**
  - [ ] Jest + React Testing Library
  - [ ] 关键组件测试覆盖
  - [ ] CI 中运行

- [ ] **E2E 测试**
  - [ ] Playwright 配置
  - [ ] 核心用户流程：登录、岗位搜索、面试
  - [ ] CI 中运行（staging 环境）

- [ ] **性能测试**
  - [ ] k6 或 Locust 脚本
  - [ ] 基准：100 并发用户
  - [ ] 数据库连接池压测

- [ ] **测试覆盖率报告**
  - [ ] pytest-cov 配置
  - [ ] 覆盖率徽章
  - [ ] PR 中显示覆盖率变化

### 7. 运维文档

- [ ] **故障排查指南** (`docs/troubleshooting.md`)
  - [ ] 常见错误码和解决方案
  - [ ] 日志分析方法
  - [ ] 紧急联系人

- [ ] **容量规划** (`docs/capacity-planning.md`)
  - [ ] 数据库连接池大小
  - [ ] Redis 内存估算
  - [ ] Celery worker 数量

- [ ] **灾难恢复** (`docs/disaster-recovery.md`)
  - [ ] 数据库备份策略（每日全量 + 增量）
  - [ ] 恢复步骤和 RTO/RPO
  - [ ] 故障转移流程

---

## P2：长期改进（1-2 月）

### 8. 错误处理增强

- [ ] **断路器模式**
  - [ ] 外部 API 调用（招聘源、LLM）
  - [ ] 失败阈值：5 次失败 / 30 秒
  - [ ] 半开状态探测

- [ ] **任务超时**
  - [ ] Celery task `time_limit` 配置
  - [ ] 默认 5 分钟，长任务可自定义

- [ ] **死信队列**
  - [ ] 失败任务转移到 DLQ
  - [ ] 定期审查和手动处理
  - [ ] 告警通知

### 9. 配置管理

- [ ] **启动时配置验证**
  - [ ] 检查所有必需环境变量
  - [ ] 验证数据库连接
  - [ ] 验证 Redis 连接

- [ ] **特性开关**
  - [ ] 远程配置（如 LaunchDarkly 或自建）
  - [ ] 按租户/用户灰度发布

- [ ] **秘钥轮换**
  - [ ] JWT 密钥轮换脚本
  - [ ] 数据库密码轮换流程
  - [ ] 零停机轮换方案

### 10. 高可用架构

- [ ] **数据库**
  - [ ] 主从复制
  - [ ] 读写分离
  - [ ] 自动故障转移

- [ ] **应用层**
  - [ ] 多实例部署
  - [ ] 负载均衡（健康检查）
  - [ ] 会话无状态

- [ ] **缓存**
  - [ ] Redis 集群模式
  - [ ] 缓存穿透/雪崩防护

---

## 里程碑计划

### Week 1：基础安全
- [ ] CI/CD 基础流水线
- [ ] 输入验证中间件
- [ ] 安全响应头

### Week 2：安全 + 文档
- [ ] 速率限制
- [ ] CORS 配置
- [ ] 部署文档

### Week 3-4：可观测性
- [ ] Prometheus + Grafana
- [ ] 结构化日志
- [ ] 告警规则

### Week 5-6：测试完善
- [ ] 前端测试
- [ ] E2E 测试
- [ ] 性能测试

### Week 7-8：高级特性
- [ ] 断路器
- [ ] 秘钥轮换
- [ ] 灾难恢复演练

---

## 验收标准

生产就绪的最低要求：

1. **CI/CD**：每次提交自动测试，main 分支自动部署到 staging
2. **安全**：通过基础安全扫描，无高危漏洞
3. **可观测**：核心指标可视化，告警配置完成
4. **文档**：部署文档完整，新人可独立操作
5. **测试**：后端覆盖率 >= 80%，E2E 覆盖核心流程

---

## 参考资源

- [The Twelve-Factor App](https://12factor.net/)
- [OWASP Top 10](https://owasp.org/Top10/)
- [Google SRE Book](https://sre.google/sre-book/table-of-contents/)
- [Production Readiness Checklist](https://gruntwork.io/devops-checklist/)
