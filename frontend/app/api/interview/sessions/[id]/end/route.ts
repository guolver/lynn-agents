import { NextRequest } from 'next/server';
import { callAgentHub, UnauthenticatedError } from '../../../../../../lib/agent-hub-authed-fetch';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const response = await callAgentHub(`/api/v1/interview/sessions/${id}/end`, {
      method: 'POST',
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return Response.json({ detail: '未登录' }, { status: 401 });
    }
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
