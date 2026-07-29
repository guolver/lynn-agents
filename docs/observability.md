# LLM 可观测性：Langfuse 追踪

> 模块：`agent_hub/observability.py`，埋点位置：`chat_service.stream_response`。
> 把对话 Agent 的每轮 LLM 调用、工具执行、token 用量上报 Langfuse，用于调试、成本核算与质量分析。

## 追踪结构

一次用户消息 = 一条 trace（按 `session_id` 归组成会话视图）：

```
chat-turn                       ← root span：用户消息、最终回答、错误状态
├── llm-round-1                 ← generation：模型、完整输入消息、输出、token 用量
├── tool:run_matches            ← span：参数、结果摘要（截断 2000 字符）、耗时
├── llm-round-2                 ← generation
└── ...（最多 5 轮）
```

记录的关键字段：

| 字段 | 来源 | 用途 |
|---|---|---|
| session_id / user_id | 会话与 actor | 按会话/用户聚合查看 |
| token 用量（input/output/total） | 流式响应 `include_usage` 末尾 chunk | 成本核算（Langfuse 可按模型价格算钱） |
| 每轮完整输入消息 | 发送给 API 的 messages 快照 | 复现"模型当时看到了什么" |
| 工具参数与结果摘要 | execute_tool 前后 | 排查工具选择与参数错误 |
| interrupted / ERROR 标记 | finally 兜底 | 区分正常完成、报错、客户端中途放弃 |

## 设计原则：观测是旁路

与向量层、图谱层的降级策略一致——**观测永远不能影响主流程**：

- 未配置 key → `NoopTracer`，所有埋点是空方法调用，零网络开销；
- SDK 缺失 / 初始化失败 / 上报异常 → 记 warning 日志，聊天照常；
- trace 收尾放在 `finally`：即便客户端断开（GeneratorExit）也不会产生悬空 trace，
  而是标记为 `interrupted`；
- 上报由 Langfuse SDK 后台批量发送，不阻塞流式输出。

## 启用方式

默认关闭。启用只需三个环境变量（`.env` 或 shell）：

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com   # 或自托管地址
```

获取 key 的两种方式：

1. **Langfuse Cloud（推荐起步）**：https://cloud.langfuse.com 免费注册，建项目拿 key；
2. **自托管**：`git clone https://github.com/langfuse/langfuse && docker compose up`
   （v3 自托管栈含 ClickHouse/MinIO 等组件，故未并入本项目 compose，按官方仓库独立起）。

docker compose 已透传三个变量到 api/worker 容器；本地 `uvicorn` 开发从 `.env` 读取。

## 测试

`tests/test_observability.py`（5 个用例，不依赖网络与 langfuse 服务）：

- 无 key 时返回 no-op tracer、单例缓存、no-op 接口完整性；
- 用伪造 OpenAI 客户端跑完整两轮循环，断言埋点序列
  `turn → generation → tool → generation → turn_end`、token 用量提取、最终输出记录；
- 生成器被提前放弃时 trace 以 `interrupted` 收尾。

## 面试要点

- **为什么自己写薄封装而不是直接用 langfuse 的 `@observe` 装饰器？**
  流式生成器 + 多轮循环的埋点边界（每轮一个 generation、finally 收尾）装饰器表达不了；
  薄封装同时给了 no-op 降级点，langfuse 换成 OTel 后端时业务代码零改动。
- **token 用量怎么拿的？** 流式模式默认不返回用量，开 `stream_options.include_usage`
  后最后一个 chunk 携带（该 chunk 的 choices 为空，需要在 delta 处理前捕获）。
- **观测挂了怎么办？** 同一套答案：降级、记录、不阻塞主流程。
