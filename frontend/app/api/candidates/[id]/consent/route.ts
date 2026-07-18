import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== 'false';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = (await request.json()) as { opted_in?: boolean };

  if (typeof body.opted_in !== 'boolean') {
    return Response.json({ detail: 'opted_in (boolean) is required' }, { status: 422 });
  }

  if (DEMO_MODE) {
    return Response.json({
      mode: 'demo',
      candidate_id: id,
      consent_status: body.opted_in ? 'opted_in' : 'opted_out',
      message: '演示模式：授权状态已更新。',
    });
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/candidates/${id}/consent`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Actor': 'frontend-console',
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify({ opted_in: body.opted_in, policy_version: 'mvp-1' }),
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
