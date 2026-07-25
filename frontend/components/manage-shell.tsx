'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

const navItems = [
  {
    href: '/manage/jobs',
    label: '岗位大厅',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="10" />
        <path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
      </svg>
    ),
  },
  {
    href: '/manage/sources',
    label: '数据来源',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
        <path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3" />
      </svg>
    ),
  },
  {
    href: '/manage/knowledge',
    label: '知识库',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
        <path d="M8 7h8M8 11h6" strokeLinecap="round" />
      </svg>
    ),
  },
];

export function ManageShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="manage-shell">
      {/* Header */}
      <header className="manage-header">
        <Link className="manage-brand" href="/">
          <span className="manage-brand-mark">AH</span>
          <span className="manage-brand-name">Agent Hub</span>
        </Link>
        <div className="manage-header-right">
          <span className="manage-avatar" title="User">
            U
          </span>
        </div>
      </header>

      <div className="manage-body">
        {/* Sidebar */}
        <aside className="manage-sidebar">
          <div className="manage-sidebar-title">管理中心</div>
          <nav className="manage-nav">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`manage-nav-item${pathname.startsWith(item.href) ? ' active' : ''}`}
              >
                <span className="manage-nav-icon">{item.icon}</span>
                <span className="manage-nav-label">{item.label}</span>
              </Link>
            ))}
          </nav>
        </aside>

        {/* Main content */}
        <main className="manage-main">{children}</main>
      </div>
    </div>
  );
}
