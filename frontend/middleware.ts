import { NextRequest, NextResponse } from 'next/server';
import { ACCESS_TOKEN_COOKIE } from './lib/auth-cookies';

export function middleware(request: NextRequest) {
  const hasSession = Boolean(request.cookies.get(ACCESS_TOKEN_COOKIE)?.value);
  if (hasSession) return NextResponse.next();

  const loginUrl = new URL('/login', request.url);
  loginUrl.searchParams.set('return_to', request.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ['/jobs/:path*', '/chat/:path*', '/agents/:path*'],
};
