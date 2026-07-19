import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const qs = searchParams.toString();
  const url = `${API_URL}/api/v1/jobs${qs ? `?${qs}` : ''}`;
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(10000) });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
