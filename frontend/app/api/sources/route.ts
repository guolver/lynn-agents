import { NextRequest } from 'next/server';
import { callAgentHub, getActorId, UnauthenticatedError } from '../../../lib/agent-hub-authed-fetch';

export async function GET() {
  try {
    const response = await callAgentHub('/api/v1/sources');
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
    const actor = await getActorId();
    const body = await request.text();
    const response = await callAgentHub('/api/v1/sources', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Actor': actor,
        'Idempotency-Key': crypto.randomUUID(),
      },
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
