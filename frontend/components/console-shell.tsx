"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const platformNav = [
  { href: "/dashboard", label: "运行总览", glyph: "01" },
  { href: "/agents", label: "Agent 目录", glyph: "02" },
  { href: "/audit", label: "审计中心", glyph: "03" },
];

const businessNav = [
  { href: "/sources", label: "职位来源", glyph: "A" },
  { href: "/jobs", label: "职位中心", glyph: "B" },
  { href: "/matches", label: "匹配与推荐", glyph: "C" },
];

function NavGroup({ label, items }: { label: string; items: typeof platformNav }) {
  const pathname = usePathname();
  return (
    <section className="nav-section">
      <div className="nav-label">{label}</div>
      <nav className="nav-list" aria-label={label}>
        {items.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link className={`nav-item${active ? " active" : ""}`} href={item.href} key={item.href}>
              <span className="nav-glyph">{item.glyph}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
    </section>
  );
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const activeLabel = [...platformNav, ...businessNav].find((item) => pathname.startsWith(item.href))?.label ?? "Agent Hub";

  return (
    <div className="console-shell">
      <aside className="sidebar">
        <Link className="brand" href="/dashboard">
          <span className="brand-mark">AH</span>
          <span>
            <span className="brand-title">Agent Hub</span>
            <span className="brand-subtitle">Operations Console</span>
          </span>
        </Link>
        <NavGroup label="平台" items={platformNav} />
        <NavGroup label="兼职匹配 Agent" items={businessNav} />
        <div className="sidebar-foot">
          <div className="environment-card">
            <div className="environment-row">
              <span>System healthy</span>
              <span className="status-dot" aria-label="运行正常" />
            </div>
            <p className="environment-note">单进程 MVP · 1 个 Agent 已注册</p>
          </div>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <div className="breadcrumb"><span>Agent Hub</span><span>/</span><strong>{activeLabel}</strong></div>
          <div className="top-actions">
            <span className="mode-badge">演示数据</span>
            <span className="user-chip" title="operator@agenthub.local">OP</span>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
