import { cookies } from 'next/headers';
import { NextRequest } from 'next/server';
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  accessTokenCookieOptions,
  expiredCookieOptions,
  refreshTokenCookieOptions,
} from '../../../../../../lib/auth-cookies';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

async function getAccessToken(): Promise<string | null> {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;
  if (accessToken) return accessToken;

  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) {
    cookieStore.set(ACCESS_TOKEN_COOKIE, '', expiredCookieOptions());
    cookieStore.set(REFRESH_TOKEN_COOKIE, '', expiredCookieOptions());
    return null;
  }

  try {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      cookieStore.set(ACCESS_TOKEN_COOKIE, '', expiredCookieOptions());
      cookieStore.set(REFRESH_TOKEN_COOKIE, '', expiredCookieOptions());
      return null;
    }
    const data = (await response.json()) as {
      access_token: string;
      refresh_token: string;
      expires_in: number;
    };
    cookieStore.set(ACCESS_TOKEN_COOKIE, data.access_token, accessTokenCookieOptions(data.expires_in));
    cookieStore.set(REFRESH_TOKEN_COOKIE, data.refresh_token, refreshTokenCookieOptions());
    return data.access_token;
  } catch {
    return null;
  }
}

// 恢复进行中的回答：后端有活跃流则重放 + 续传 SSE，否则 204。
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const accessToken = await getAccessToken();
  if (!accessToken) {
    return Response.json({ detail: '未登录' }, { status: 401 });
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/chat/sessions/${id}/stream`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      signal: request.signal,
    });

    if (response.status === 204) {
      return new Response(null, { status: 204 });
    }
    if (!response.ok) {
      return new Response(await response.text(), {
        status: response.status,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    return new Response(response.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    });
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }
}
