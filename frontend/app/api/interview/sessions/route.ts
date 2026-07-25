import { NextRequest } from 'next/server';
import { callAgentHub, UnauthenticatedError } from '../../../../lib/agent-hub-authed-fetch';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const status = searchParams.get('status');
    const limit = searchParams.get('limit') || '50';
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    params.set('limit', limit);

    const response = await callAgentHub(`/api/v1/interview/sessions?${params.toString()}`);
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

export async function POST(request: NextRequest) {
  try {
    const body = await request.text();
    const response = await callAgentHub('/api/v1/interview/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
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
