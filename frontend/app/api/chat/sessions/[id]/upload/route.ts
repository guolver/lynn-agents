import { NextRequest } from 'next/server';
import { callAgentHub, UnauthenticatedError } from '../../../../../../lib/agent-hub-authed-fetch';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const formData = await request.formData();

  try {
    const response = await callAgentHub(`/api/v1/chat/sessions/${id}/upload`, {
      method: 'POST',
      body: formData,
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
