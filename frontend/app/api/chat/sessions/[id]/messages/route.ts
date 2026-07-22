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

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const accessToken = await getAccessToken();
  if (!accessToken) {
    return Response.json({ detail: '未登录' }, { status: 401 });
  }

  const body = await request.json();

  try {
    // 不设整体超时：SSE 流的时长由生成决定；客户端断开时跟随中止（生成端不受影响，
    // 可通过 GET /stream 重连续传）。
    const response = await fetch(`${API_URL}/api/v1/chat/sessions/${id}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(body),
      signal: request.signal,
    });

    if (!response.ok) {
      return new Response(await response.text(), {
        status: response.status,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Stream-through the SSE response
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
