import { NextRequest } from "next/server";

const API_URL = process.env.AGENT_HUB_API_URL ?? "http://127.0.0.1:8000";
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== "false";

export async function POST(request: NextRequest) {
  const body = await request.json() as { agentId?: string; action?: string; payload?: Record<string, unknown> };
  if (!body.agentId || !body.action || !body.payload) {
    return Response.json({ detail: "agentId, action and payload are required" }, { status: 422 });
  }

  if (DEMO_MODE) {
    return Response.json({
      mode: "demo",
      agent_id: body.agentId,
      action: body.action,
      request_id: crypto.randomUUID(),
      result: body.action === "list_sources"
        ? { sources: [{ id: "src_001", name: "Remote AI Partner Feed", review_status: "approved" }] }
        : { accepted: true, message: "演示调用已完成；关闭 DEMO_MODE 后将转发至 Agent Hub。", payload: body.payload },
    });
  }

  try {
    const response = await fetch(`${API_URL}/platform/v1/agents/${body.agentId}/actions/${body.action}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Actor": "frontend-console",
        "X-Request-Id": crypto.randomUUID(),
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ payload: body.payload }),
      signal: AbortSignal.timeout(8000),
    });
    return new Response(await response.text(), { status: response.status, headers: { "Content-Type": "application/json" } });
  } catch {
    return Response.json({ detail: "Agent Hub API 当前不可用，请检查 AGENT_HUB_API_URL。" }, { status: 503 });
  }
}
