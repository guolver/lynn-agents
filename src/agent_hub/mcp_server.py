"""MCP server：把 Agent 平台的白名单动作暴露为 MCP 工具。

设计原则：本模块是平台 API 的瘦客户端，不复制任何治理逻辑——动作白名单、
参数校验、风险分级、审批与审计全部仍由平台层（``api/platform.py`` +
``AgentRegistry``）执行。工具清单在启动时从 ``GET /platform/v1/agents``
动态发现，新 Agent 注册后本模块无需改动。

安全默认值：仅暴露 read 动作；写动作需显式设置 ``MCP_EXPOSE_WRITE=1``，
且高风险写动作仍受平台侧人工审批流程约束。

运行（stdio 传输，供 Claude Code / Claude Desktop 等 MCP 客户端接入）::

    AGENT_HUB_API_URL=http://localhost:8000 python -m agent_hub.mcp_server

环境变量：
    AGENT_HUB_API_URL  平台 API 地址（默认 http://localhost:8000）
    MCP_ACTOR          写入审计日志的操作者标识（默认 mcp-client）
    MCP_EXPOSE_WRITE   设为 1 时才暴露 mode=write 的动作（默认只读）
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_TOOL_NAME_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


class PlatformUnavailableError(RuntimeError):
    """平台 API 不可达或返回非业务错误。"""


class PlatformInvocationError(RuntimeError):
    """平台拒绝了本次动作调用（白名单/校验/审批等业务错误）。"""


def sanitize_tool_name(raw: str) -> str:
    """MCP 工具名只允许 ``[a-zA-Z0-9_-]``；其余字符替换为下划线。"""
    return _TOOL_NAME_SAFE.sub("_", raw)[:64]


def normalize_input_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """把 manifest 里的宽松 schema 规整为合法的 JSON Schema 对象。"""
    normalized: dict[str, Any] = dict(schema or {})
    normalized.setdefault("type", "object")
    normalized.setdefault("properties", {})
    return normalized


@dataclass(frozen=True)
class ToolSpec:
    """一个 MCP 工具与其背后平台动作的映射。"""

    name: str
    description: str
    agent_id: str
    action: str
    requires_idempotency_key: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)


def build_tool_specs(agents: list[dict[str, Any]], *, expose_write: bool = False) -> list[ToolSpec]:
    """从 ``registry.describe`` 的输出构建 MCP 工具清单。

    默认只暴露 read 动作（最小权限）；``expose_write=True`` 时补充写动作，
    并在描述中标注 mode 与 risk_level，让 MCP 客户端侧的模型可见风险等级。
    """
    specs: list[ToolSpec] = []
    for agent in agents:
        agent_id = agent["agent_id"]
        for action in agent.get("actions", []):
            mode = action.get("mode", "read")
            if mode == "write" and not expose_write:
                continue
            risk = action.get("risk_level", "low")
            description = f"[{agent_id}] {action['description']} (mode={mode}, risk={risk})"
            specs.append(
                ToolSpec(
                    name=sanitize_tool_name(f"{agent_id}__{action['name']}"),
                    description=description,
                    agent_id=agent_id,
                    action=action["name"],
                    requires_idempotency_key=action.get("requires_idempotency_key", False),
                    input_schema=normalize_input_schema(action.get("input_schema")),
                )
            )
    return specs


class PlatformClient:
    """平台 API 的最小 HTTP 客户端（urllib，无额外依赖）。"""

    def __init__(self, base_url: str, actor: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.actor = actor
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any]:
        request = Request(
            f"{self.base_url}{path}",
            method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise PlatformInvocationError(f"HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise PlatformUnavailableError(f"platform API unreachable: {exc.reason}") from exc

    def list_agent_ids(self) -> list[str]:
        manifests = self._request("GET", "/platform/v1/agents")
        return [m["agent_id"] for m in manifests]

    def describe_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("GET", f"/platform/v1/agents/{agent_id}")

    def invoke(
        self,
        agent_id: str,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"X-Actor": self.actor}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return self._request(
            "POST",
            f"/platform/v1/agents/{agent_id}/actions/{action}",
            body={"payload": payload},
            headers=headers,
        )


async def _serve() -> None:
    import asyncio

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    base_url = os.getenv("AGENT_HUB_API_URL", "http://localhost:8000")
    actor = os.getenv("MCP_ACTOR", "mcp-client")
    expose_write = os.getenv("MCP_EXPOSE_WRITE", "0") == "1"

    client = PlatformClient(base_url, actor)
    agents = [client.describe_agent(agent_id) for agent_id in client.list_agent_ids()]
    specs = build_tool_specs(agents, expose_write=expose_write)
    by_name = {spec.name: spec for spec in specs}
    logger.info(
        "agent-hub mcp: %d tools from %d agents (write=%s)", len(specs), len(agents), expose_write
    )

    server = Server("agent-hub")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=spec.name, description=spec.description, inputSchema=spec.input_schema)
            for spec in specs
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        spec = by_name.get(name)
        if spec is None:
            raise ValueError(f"unknown tool: {name}")
        # 每次调用生成新幂等键：MCP 客户端的一次工具调用就是一次业务意图，
        # 传输层重试由平台幂等记录去重。
        idempotency_key = str(uuid.uuid4()) if spec.requires_idempotency_key else None
        try:
            result = await asyncio.to_thread(
                client.invoke, spec.agent_id, spec.action, arguments or {}, idempotency_key
            )
        except (PlatformInvocationError, PlatformUnavailableError) as exc:
            # 平台的拒绝原因原样透传给模型，让它能自行修正参数或改换动作。
            raise ValueError(str(exc)) from exc
        return [
            TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, default=str, indent=2),
            )
        ]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
