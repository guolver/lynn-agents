import { cookies } from 'next/headers';
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  accessTokenCookieOptions,
  expiredCookieOptions,
  refreshTokenCookieOptions,
} from './auth-cookies';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';

export class UnauthenticatedError extends Error {
  constructor() {
    super('no valid session');
  }
}

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

async function fetchWithToken(
  path: string,
  init: RequestInit,
  accessToken: string,
  timeoutMs: number,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${accessToken}`);
  return fetch(`${API_URL}${path}`, { ...init, headers, signal: AbortSignal.timeout(timeoutMs) });
}

async function refreshTokens(refreshToken: string): Promise<TokenResponse | null> {
  try {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    return (await response.json()) as TokenResponse;
  } catch {
    return null;
  }
}

/**
 * Proxies a request to the Agent Hub API with the caller's Bearer token.
 * If there's no access token cookie (it expired client-side — its maxAge
 * matches the access token's own 15-minute TTL, so this is the routine case,
 * not an edge case) or the backend rejects it with a 401, transparently
 * refreshes once via the refresh_token cookie and retries, rotating both
 * cookies in the process. Throws UnauthenticatedError when there is no
 * session or refresh fails (and clears both cookies in that case) —
 * callers should catch this and return a 401 to the browser.
 */
export async function callAgentHub(path: string, init: RequestInit = {}, timeoutMs = 10000): Promise<Response> {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;

  if (accessToken) {
    const first = await fetchWithToken(path, init, accessToken, timeoutMs);
    if (first.status !== 401) return first;
  }

  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) {
    cookieStore.set(ACCESS_TOKEN_COOKIE, '', expiredCookieOptions());
    cookieStore.set(REFRESH_TOKEN_COOKIE, '', expiredCookieOptions());
    throw new UnauthenticatedError();
  }

  const refreshed = await refreshTokens(refreshToken);
  if (!refreshed) {
    cookieStore.set(ACCESS_TOKEN_COOKIE, '', expiredCookieOptions());
    cookieStore.set(REFRESH_TOKEN_COOKIE, '', expiredCookieOptions());
    throw new UnauthenticatedError();
  }

  cookieStore.set(ACCESS_TOKEN_COOKIE, refreshed.access_token, accessTokenCookieOptions(refreshed.expires_in));
  cookieStore.set(REFRESH_TOKEN_COOKIE, refreshed.refresh_token, refreshTokenCookieOptions());

  return fetchWithToken(path, init, refreshed.access_token, timeoutMs);
}

/**
 * Extracts the `sub` claim from the access token cookie for the `X-Actor`
 * header some backend write routes require for audit attribution. Only
 * decodes the JWT payload (no signature check) — the backend has already
 * verified the token via the Bearer header; this is just a label.
 */
export async function getActorId(): Promise<string> {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) return 'console-ui';
  try {
    const payload = accessToken.split('.')[1];
    const decoded = JSON.parse(Buffer.from(payload, 'base64url').toString('utf-8'));
    return typeof decoded.sub === 'string' ? decoded.sub : 'console-ui';
  } catch {
    return 'console-ui';
  }
}
