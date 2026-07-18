'use client';

import { useEffect, useState } from 'react';
import { ChatPanel } from '../../../components/chat-panel';

type SessionItem = {
  id: string;
  status?: string;
  created_at?: string;
};

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);

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

  async function handleNewSession() {
    try {
      const res = await fetch('/api/chat/sessions', { method: 'POST' });
      const data = await res.json();
      if (data.id) {
        setSessionId(data.id);
        setSessions((prev) => [data, ...prev]);
      }
    } catch {
      alert('Failed to create session');
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
      <div className="gpt-layout">
        <div className="gpt-main">
          <div className="gpt-loading">Loading...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="gpt-layout">
      {/* Sidebar */}
      <aside className={`gpt-sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
        <div className="gpt-sidebar-header">
          <button className="gpt-new-chat" onClick={handleNewSession}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            New Chat
          </button>
          <button className="gpt-sidebar-toggle" onClick={() => setSidebarOpen(false)} title="Close sidebar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M3 4h18M3 12h18M3 20h18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="gpt-history">
          {sessions.map((s) => (
            <button
              key={s.id}
              className={`gpt-history-item ${s.id === sessionId ? 'active' : ''}`}
              onClick={() => setSessionId(s.id)}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="gpt-history-icon">
                <path
                  d="M2 4h12M2 8h12M2 12h8"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
              <span className="gpt-history-label">
                {formatDate(s.created_at)} 对话
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* Toggle sidebar button (visible when sidebar is closed) */}
      {!sidebarOpen && (
        <button className="gpt-sidebar-open" onClick={() => setSidebarOpen(true)} title="Open sidebar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M3 4h18M3 12h18M3 20h18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
      )}

      {/* Main chat area */}
      <div className="gpt-main">
        {sessionId ? (
          <ChatPanel sessionId={sessionId} />
        ) : (
          <div className="gpt-welcome">
            <div className="gpt-welcome-logo">AH</div>
            <h1>Agent Hub 助手</h1>
            <p className="gpt-welcome-sub">上传简历或描述你的技能，我来帮你匹配最合适的远程岗位</p>
            <div className="gpt-suggestions">
              <button className="gpt-suggestion" onClick={handleNewSession}>
                <span className="gpt-suggestion-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M12 5v14M5 12h14"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                  </svg>
                </span>
                <span>开始新对话</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
