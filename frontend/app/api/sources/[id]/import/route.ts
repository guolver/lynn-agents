import { NextRequest } from 'next/server';
import { callAgentHub, getActorId, UnauthenticatedError } from '../../../../../lib/agent-hub-authed-fetch';

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const actor = await getActorId();
    const response = await callAgentHub(
      `/api/v1/sources/${id}/import`,
      {
        method: 'POST',
        headers: {
          'X-Actor': actor,
          'Idempotency-Key': crypto.randomUUID(),
        },
      },
      30000,
    );
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return Response.json({ detail: '未登录' }, { status: 401 });
    }
    return Response.json({ detail: '导入服务不可用' }, { status: 503 });
  }
}
