import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

// Poll a chat analysis task (resume parse + match). Forwards to the real
// backend Celery task-status endpoint — no demo mode here, chat needs live data.
export async function GET(_request: NextRequest, { params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;

  try {
    const response = await fetch(`${API_URL}/api/v1/tasks/${taskId}/status`, {
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
