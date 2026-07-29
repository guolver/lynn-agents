import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// 公开路由（无需登录）
const PUBLIC_ROUTES = ['/login', '/register'];

// 静态资源和 API 路由前缀（跳过检查）
const SKIP_PREFIXES = ['/_next', '/api', '/favicon.ico'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 跳过静态资源和 API 路由
  if (SKIP_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return NextResponse.next();
  }

  // 公开路由直接放行
  if (PUBLIC_ROUTES.includes(pathname)) {
    return NextResponse.next();
  }

  // 检查是否有认证 cookie
  const accessToken = request.cookies.get('access_token')?.value;
  const refreshToken = request.cookies.get('refresh_token')?.value;

  // 未登录则跳转到登录页
  if (!accessToken && !refreshToken) {
    const loginUrl = new URL('/login', request.url);
    // 保存原始路径，登录后可跳回
    if (pathname !== '/') {
      loginUrl.searchParams.set('redirect', pathname);
    }
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // 匹配所有路由，除了 _next 静态文件
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
