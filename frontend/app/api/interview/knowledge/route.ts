import { NextRequest } from 'next/server';
import { callAgentHub, UnauthenticatedError } from '../../../../lib/agent-hub-authed-fetch';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const category = searchParams.get('category');
    const limit = searchParams.get('limit') || '100';
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    params.set('limit', limit);

    const response = await callAgentHub(`/api/v1/interview/knowledge?${params.toString()}`);
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
    const formData = await request.formData();
    const response = await callAgentHub('/api/v1/interview/knowledge', {
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
