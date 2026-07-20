import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  accessTokenCookieOptions,
  refreshTokenCookieOptions,
} from '../../../../lib/auth-cookies';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export async function POST() {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) {
    return Response.json({ detail: '未登录' }, { status: 401 });
  }

  let upstream: Response;
  let tokens: TokenResponse;
  try {
    upstream = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: AbortSignal.timeout(5000),
    });
    if (!upstream.ok) {
      return new Response(await upstream.text(), {
        status: upstream.status,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    tokens = (await upstream.json()) as TokenResponse;
  } catch {
    return Response.json({ detail: 'API 不可用' }, { status: 503 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, accessTokenCookieOptions(tokens.expires_in));
  response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, refreshTokenCookieOptions());
  return response;
}
