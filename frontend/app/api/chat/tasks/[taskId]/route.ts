import { NextRequest } from 'next/server';
import { callAgentHub, UnauthenticatedError } from '../../../../../lib/agent-hub-authed-fetch';

// Poll a chat analysis task (resume parse + match). Forwards to the real
// backend Celery task-status endpoint — no demo mode here, chat needs live data.
export async function GET(_request: NextRequest, { params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;

  try {
    const response = await callAgentHub(`/api/v1/tasks/${taskId}/status`, {}, 8000);
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return Response.json({ detail: '未登录' }, { status: 401 });
    }
    return Response.json({ detail: 'Agent Hub API 当前不可用。' }, { status: 503 });
  }
}
