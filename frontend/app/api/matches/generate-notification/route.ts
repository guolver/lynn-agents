import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== 'false';

export async function POST(request: NextRequest) {
  const body = (await request.json()) as { candidate_id?: string; match_ids?: string[] };

  if (!body.candidate_id || !body.match_ids?.length) {
    return Response.json({ detail: 'candidate_id and match_ids are required' }, { status: 422 });
  }

  if (DEMO_MODE) {
    return Response.json({
      mode: 'demo',
      notification_id: `ntf_demo_${Date.now()}`,
      candidate_id: body.candidate_id,
      match_count: body.match_ids.length,
      message: '演示模式：通知草稿已生成。',
    });
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/notifications/preview`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Actor': 'frontend-console',
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify({ candidate_id: body.candidate_id, match_ids: body.match_ids }),
      signal: AbortSignal.timeout(15000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'Agent Hub API 当前不可用。' }, { status: 503 });
  }
}
