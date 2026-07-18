import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== 'false';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = (await request.json()) as { approved?: boolean; note?: string };

  if (typeof body.approved !== 'boolean') {
    return Response.json({ detail: 'approved (boolean) is required' }, { status: 422 });
  }

  if (DEMO_MODE) {
    return Response.json({
      mode: 'demo',
      job_id: id,
      review_status: body.approved ? 'approved' : 'rejected',
      reviewed_by: 'frontend-console',
      reviewed_at: new Date().toISOString(),
      review_note: body.note ?? '',
      message: '演示审核已完成；关闭 DEMO_MODE 后将转发至 Agent Hub。',
    });
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/jobs/${id}/review`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Actor': 'frontend-console',
        'X-Request-Id': crypto.randomUUID(),
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify({ approved: body.approved, note: body.note ?? '' }),
      signal: AbortSignal.timeout(8000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'Agent Hub API 当前不可用，请检查 AGENT_HUB_API_URL。' }, { status: 503 });
  }
}
