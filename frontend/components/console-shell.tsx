'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="topbar-left">
          <Link className="app-brand" href="/">
            <span className="app-brand-mark">AH</span>
            <span className="app-brand-name">Agent Hub</span>
          </Link>
          <div className="topbar-divider" />
          <Link className={`topbar-link${pathname.startsWith('/chat') ? ' active' : ''}`} href="/chat">
            AI 助手
          </Link>
          <Link className={`topbar-link${pathname.startsWith('/jobs') ? ' active' : ''}`} href="/jobs">
            岗位大厅
          </Link>
          <Link className={`topbar-link${pathname.startsWith('/sources') ? ' active' : ''}`} href="/sources">
            数据来源
          </Link>
          <Link className={`topbar-link${pathname.startsWith('/interview') ? ' active' : ''}`} href="/interview">
            模拟面试
          </Link>
        </div>
        <div className="topbar-right">
          <span className="topbar-avatar" title="User">U</span>
        </div>
      </header>
      <div className="app-content">{children}</div>
    </div>
  );
}
