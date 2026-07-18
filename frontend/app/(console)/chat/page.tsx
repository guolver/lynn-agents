'use client';

import { useEffect, useState } from 'react';
import { ChatPanel } from '../../../components/chat-panel';
import { EMPTY_STATE_SUGGESTIONS } from '../../../lib/chat-suggestions';

type SessionItem = {
  id: string;
  title?: string;
  status?: string;
  created_at?: string;
};

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pending, setPending] = useState<{ prompt?: string; action?: 'upload' } | null>(null);

  useEffect(() => {
    fetch('/api/chat/sessions')
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setSessions(data);
          const active = data.find((s: SessionItem) => s.status === 'active');
          if (active) setSessionId(active.id);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function handleNewSession(prompt?: string, action?: 'upload') {
    try {
      const res = await fetch('/api/chat/sessions', { method: 'POST' });
      const data = await res.json();
      if (data.id) {
        setPending(prompt || action ? { prompt, action } : null);
        setSessionId(data.id);
        setSessions((prev) => [data, ...prev]);
        setSidebarOpen(false);
      }
    } catch {
      alert('Failed to create session');
    }
  }

  async function handleDeleteSession(id: string) {
    try {
      const res = await fetch(`/api/chat/sessions/${id}`, { method: 'DELETE' });
      if (!res.ok) return;
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (sessionId === id) {
        setSessionId(null);
      }
    } catch {
      // ignore
    }
  }

  function formatDate(iso?: string) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffDays === 0) return '今天';
    if (diffDays === 1) return '昨天';
    if (diffDays < 7) return `${diffDays} 天前`;
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
  }

  if (loading) {
    return (
      <div className="chat-layout">
        <div className="chat-container">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--ink-soft)' }}>
            Loading...
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-layout">
      {/* Mobile sidebar toggle */}
      <button className="sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Toggle history">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path d="M3 6h18M3 12h18M3 18h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>

      {/* Mobile overlay */}
      {sidebarOpen && <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />}

      {/* History sidebar — always visible on desktop, toggleable on mobile */}
      <aside className={`chat-sidebar${sidebarOpen ? ' open' : ''}`}>
        <div className="sidebar-header">
          <span className="sidebar-title">历史对话</span>
          <button className="sidebar-new-btn" onClick={() => handleNewSession()} title="新对话">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="sidebar-list">
          {sessions.map((s) => (
            <div key={s.id} className={`sidebar-item${s.id === sessionId ? ' active' : ''}`}>
              <button
                className="sidebar-item-btn"
                onClick={() => {
                  setPending(null);
                  setSessionId(s.id);
                  setSidebarOpen(false);
                }}
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="sidebar-item-icon">
                  <path d="M2 4h12M2 8h12M2 12h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
                <span className="sidebar-item-label">{s.title || `${formatDate(s.created_at)} 对话`}</span>
              </button>
              <button
                className="sidebar-delete-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteSession(s.id);
                }}
                title="删除对话"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* Chat area */}
      <div className="chat-container">
        {sessionId ? (
          <ChatPanel
            key={sessionId}
            sessionId={sessionId}
            initialPrompt={pending?.prompt}
            initialAction={pending?.action}
            onTitleUpdate={(title) =>
              setSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, title } : s)))
            }
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 16 }}>
            <div className="chat-empty-logo">AH</div>
            <h1 style={{ fontSize: 24, fontWeight: 600, margin: 0 }}>Agent Hub 助手</h1>
            <p style={{ fontSize: 14, color: 'var(--ink-soft)', margin: 0 }}>上传简历或描述你的技能，我来帮你匹配最合适的远程岗位</p>
            <div className="chat-empty-cards">
              {EMPTY_STATE_SUGGESTIONS.map((s) => (
                <button
                  key={s.label}
                  className="chat-empty-card"
                  onClick={() =>
                    s.action === 'upload' ? handleNewSession(undefined, 'upload') : handleNewSession(s.prompt)
                  }
                >
                  <span className="chat-empty-card-icon">{s.icon}</span>
                  <span>{s.label}</span>
                </button>
              ))}
            </div>
            <button className="topbar-btn" onClick={() => handleNewSession()} style={{ marginTop: 12, padding: '10px 20px', fontSize: 14 }}>
              + 开始新对话
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
