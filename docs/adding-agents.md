# 接入新的 Agent

Agent Hub 将“平台能力”和“业务 Agent”分开：平台只负责发现、元数据、动作白名单、调用上下文和错误边界；每个 Agent 自己负责业务状态、输入校验、幂等和风险策略。

## 目录约定

内置 Agent 放在：

```text
agent_hub/agents/<agent_name>/
├── __init__.py
├── agent.py          # 平台适配器：manifest、actions、invoke
├── domain.py         # 无框架依赖的领域规则（可选）
├── repository.py     # 持久化边界（可选）
├── service.py        # 业务用例（可选）
└── http_api.py       # Agent 专属 REST API（可选）
```

不要让一个 Agent 直接导入另一个 Agent 的仓储或 service。跨 Agent 工作流应放入未来的 orchestrator，通过 `AgentRegistry.invoke` 调用公开动作。

## 最小实现

```python
from typing import Any

from agent_hub.core import ActionDefinition, AgentManifest, ExecutionContext


class SummaryAgent:
    manifest = AgentManifest(
        agent_id="summary-agent",
        name="摘要 Agent",
        version="1.0.0",
        description="生成文本摘要",
        tags=("text",),
    )

    def actions(self) -> tuple[ActionDefinition, ...]:
        return (
            ActionDefinition(
                name="summarize",
                description="生成摘要",
                input_schema={"required": ["text"]},
            ),
        )

    def invoke(
        self,
        action: str,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        if action != "summarize":
            raise ValueError("unsupported action")
        return {"summary": payload["text"][:100]}
```

应用可以在启动时注入本地 Agent，不需要修改平台注册表：

```python
from agent_hub.app import create_app

app = create_app(extra_agents=[SummaryAgent()])
```

如果 Agent 位于独立 Python 包，可声明 entry point，从而不修改本仓库：

```toml
[project.entry-points."agent_hub.agents"]
summary = "my_agent_package:build_agent"
```

`build_agent` 是一个无参数工厂。启动时显式启用并限制允许的插件：

```python
app = create_app(load_plugins=True, allowed_plugins={"summary"})
```

插件加载会执行第三方代码，因此默认关闭。生产环境还应使用签名包、allowlist 和隔离 worker。

注册后自动获得：

```text
GET  /platform/v1/agents
GET  /platform/v1/agents/summary-agent
POST /platform/v1/agents/summary-agent/actions/summarize
```

调用示例：

```bash
curl -X POST http://localhost:8000/platform/v1/agents/summary-agent/actions/summarize \
  -H 'Content-Type: application/json' \
  -H 'X-Actor: user-123' \
  -d '{"payload":{"text":"需要总结的内容"}}'
```

## 接入检查清单

- `agent_id` 稳定、唯一，版本单独变化。
- 只在 `actions()` 暴露必要动作，禁止通用脚本执行或任意方法调用。
- 写动作设置 `mode="write"` 和 `requires_idempotency_key=True`。
- 密钥从运行环境或密钥管理系统读取，不能放进 payload、manifest 或日志。
- 高风险动作创建审批任务；不要让模型结果覆盖授权、退订和合规规则。
- 领域规则不依赖 HTTP/LLM SDK，并有独立单元测试。
- 返回结果可 JSON 序列化，日志包含 request_id，但不包含不必要的个人数据。

## 下一阶段平台能力

当前注册表是单进程实现。扩展为生产平台时，可以在不改变 Agent 协议的前提下增加：持久化 Agent 目录、租户与 RBAC、签名插件包、隔离 worker、队列/流式执行、集中审批、密钥托管、配额计费、OpenTelemetry 和远程 Agent RPC。
