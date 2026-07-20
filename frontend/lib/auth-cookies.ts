export const ACCESS_TOKEN_COOKIE = 'access_token';
export const REFRESH_TOKEN_COOKIE = 'refresh_token';
const REFRESH_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days, matches backend REFRESH_TOKEN_TTL

type CookieOptions = {
  httpOnly: true;
  secure: boolean;
  sameSite: 'lax';
  path: '/';
  maxAge: number;
};

function baseCookieOptions(maxAge: number): CookieOptions {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    maxAge,
  };
}

export function accessTokenCookieOptions(expiresInSeconds: number): CookieOptions {
  return baseCookieOptions(expiresInSeconds);
}

export function refreshTokenCookieOptions(): CookieOptions {
  return baseCookieOptions(REFRESH_TOKEN_MAX_AGE_SECONDS);
}

export function expiredCookieOptions(): CookieOptions {
  return baseCookieOptions(0);
}
