import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== 'false';

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  if (DEMO_MODE) {
    return Response.json({
      mode: 'demo',
      candidate_id: id,
      message: '演示模式：候选人已删除。',
    });
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/candidates/${id}`, {
      method: 'DELETE',
      headers: {
        'X-Actor': 'frontend-console',
        'Idempotency-Key': crypto.randomUUID(),
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
