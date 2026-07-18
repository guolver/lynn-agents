'use client';

import { useEffect, useState } from 'react';
import { ChatPanel } from '../../../components/chat-panel';

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<Array<{ id: string; created_at?: string }>>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/chat/sessions')
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setSessions(data);
          // Auto-select the most recent active session
          const active = data.find((s: Record<string, unknown>) => s.status === 'active');
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

  if (loading) {
    return (
      <div className="panel">
        <div className="panel-body">Loading...</div>
      </div>
    );
  }

  return (
    <div className="chat-page">
      <aside className="chat-sidebar">
        <button className="button" onClick={handleNewSession} style={{ width: '100%', marginBottom: 12 }}>
          + New Chat
        </button>
        <div className="chat-session-list">
          {sessions.map((s) => (
            <button
              key={s.id}
              className={`chat-session-item ${s.id === sessionId ? 'active' : ''}`}
              onClick={() => setSessionId(s.id)}
            >
              <span className="chat-session-id">{s.id.slice(0, 8)}...</span>
              {s.created_at && (
                <span className="chat-session-date">
                  {new Date(s.created_at).toLocaleDateString('zh-CN')}
                </span>
              )}
            </button>
          ))}
        </div>
      </aside>
      <div className="chat-main">
        {sessionId ? (
          <ChatPanel sessionId={sessionId} />
        ) : (
          <div className="chat-empty">
            <h2>Agent Hub Assistant</h2>
            <p>Click &quot;+ New Chat&quot; to start a conversation.</p>
          </div>
        )}
      </div>
    </div>
  );
}
