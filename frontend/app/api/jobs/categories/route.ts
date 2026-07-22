import { callAgentHub, UnauthenticatedError } from '../../../../lib/agent-hub-authed-fetch';

export async function GET() {
  try {
    const response = await callAgentHub('/api/v1/jobs/categories');
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
