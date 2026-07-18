const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export async function POST() {
  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions`, {
      method: 'POST',
      headers: {
        'X-Actor': 'chat-user',
      },
      signal: AbortSignal.timeout(5000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}

export async function GET() {
  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions`, {
      signal: AbortSignal.timeout(5000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json([], { status: 200 });
  }
}
