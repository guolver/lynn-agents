import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== 'false';

export async function POST(request: NextRequest) {
  const body = (await request.json()) as { notification_id?: string };

  if (!body.notification_id) {
    return Response.json({ detail: 'notification_id is required' }, { status: 422 });
  }

  if (DEMO_MODE) {
    return Response.json({
      mode: 'demo',
      notification_id: body.notification_id,
      status: 'sent',
      message: '演示模式：通知已发送。',
    });
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/notifications/send`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Actor': 'frontend-console',
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify({ notification_id: body.notification_id }),
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
