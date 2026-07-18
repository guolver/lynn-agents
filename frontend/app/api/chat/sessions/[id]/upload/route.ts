import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const formData = await request.formData();

  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions/${id}/upload`, {
      method: 'POST',
      headers: { 'X-Actor': 'chat-user' },
      body: formData,
      signal: AbortSignal.timeout(30000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
