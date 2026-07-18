import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== 'false';

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  if (DEMO_MODE) {
    return Response.json({
      mode: 'demo',
      workflow_id: id,
      status: 'running',
      message: '演示模式：重试已触发。',
    });
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/workflows/${id}/retry`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Actor': 'frontend-console',
      },
      signal: AbortSignal.timeout(8000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'Agent Hub API 当前不可用。' }, { status: 503 });
  }
}
