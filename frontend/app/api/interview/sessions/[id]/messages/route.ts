import { NextRequest } from 'next/server';
import { callAgentHub, UnauthenticatedError } from '../../../../../../lib/agent-hub-authed-fetch';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const body = await request.text();
    const response = await callAgentHub(`/api/v1/interview/sessions/${id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    });

    // Stream the SSE response
    if (!response.body) {
      return Response.json({ detail: '无响应体' }, { status: 502 });
    }

    return new Response(response.body, {
      status: response.status,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    });
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return Response.json({ detail: '未登录' }, { status: 401 });
    }
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
