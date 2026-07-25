'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';

type Session = {
  id: string;
  target_role: string;
  difficulty: string;
  status: string;
  summary: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

type Message = {
  id: string;
  role: string;
  content: string;
  created_at: string;
};

const DIFFICULTY_LABELS: Record<string, string> = {
  easy: '初级',
  medium: '中级',
  hard: '高级',
};

export default function InterviewPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // New session modal
  const [showNewSession, setShowNewSession] = useState(false);
  const [newRole, setNewRole] = useState('');
  const [newDifficulty, setNewDifficulty] = useState('medium');
  const [creating, setCreating] = useState(false);

  // Chat state
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // End session state
  const [ending, setEnding] = useState(false);

  async function loadSession(sessionId: string) {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/interview/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        setCurrentSession(data.session);
        setMessages(data.messages || []);
      } else {
        setError('加载会话失败');
      }
    } catch {
      setError('API 不可用');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/interview/sessions');
        if (cancelled) return;
        if (res.ok) {
          const data: Session[] = await res.json();
          setSessions(data);
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  function openNewSessionModal() {
    setNewRole('');
    setNewDifficulty('medium');
    setShowNewSession(true);
  }

  function closeNewSessionModal() {
    if (creating) return;
    setShowNewSession(false);
  }

  async function handleCreateSession(e: React.FormEvent) {
    e.preventDefault();
    if (!newRole.trim()) return;
    setCreating(true);
    try {
      const res = await fetch('/api/interview/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_role: newRole.trim(),
          difficulty: newDifficulty,
        }),
      });
      if (res.ok) {
        const session: Session = await res.json();
        setShowNewSession(false);
        setSessions((prev) => [session, ...prev]);
        loadSession(session.id);
      }
    } finally {
      setCreating(false);
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || !currentSession || sending) return;

    const userMessage = input.trim();
    setInput('');
    setSending(true);
    setStreamingContent('');

    // Add user message immediately
    const userMsg: Message = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: userMessage,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const res = await fetch(`/api/interview/sessions/${currentSession.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: userMessage }),
      });

      if (!res.ok || !res.body) {
        throw new Error('发送失败');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let assistantContent = '';
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.content) {
                assistantContent += data.content;
                setStreamingContent(assistantContent);
              }
            } catch {
              // ignore parse errors
            }
          }
        }
      }

      // Add assistant message
      if (assistantContent) {
        const assistantMsg: Message = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: assistantContent,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      }
    } catch (err) {
      console.error('Send error:', err);
    } finally {
      setSending(false);
      setStreamingContent('');
    }
  }

  async function handleEndSession() {
    if (!currentSession || ending) return;
    if (!confirm('确定要结束这场面试吗？结束后将生成综合评价报告。')) return;

    setEnding(true);
    try {
      const res = await fetch(`/api/interview/sessions/${currentSession.id}/end`, {
        method: 'POST',
      });
      if (res.ok) {
        const updated: Session = await res.json();
        setCurrentSession(updated);
        setSessions((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      }
    } finally {
      setEnding(false);
    }
  }

  async function handleDeleteSession(sessionId: string) {
    if (!confirm('确定要删除这个面试会话吗？')) return;
    try {
      const res = await fetch(`/api/interview/sessions/${sessionId}`, { method: 'DELETE' });
      if (res.ok) {
        setSessions((prev) => prev.filter((s) => s.id !== sessionId));
        if (currentSession?.id === sessionId) {
          setCurrentSession(null);
          setMessages([]);
        }
      }
    } catch {
      // ignore
    }
  }

  function formatDate(dateStr: string) {
    if (!dateStr) return '';
    return new Date(dateStr).toLocaleDateString('zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  const summary = currentSession?.summary as Record<string, unknown> | undefined;

  return (
    <div className="iv-layout">
      {/* Sidebar */}
      <aside className="iv-sidebar">
        <div className="iv-sidebar-header">
          <button className="iv-new-btn" type="button" onClick={openNewSessionModal}>
            + 新面试
          </button>
          <Link className="iv-kb-link" href="/interview/knowledge">
            知识库
          </Link>
        </div>
        <div className="iv-session-list">
          {loading && <div style={{ padding: '12px', color: '#78716c', fontSize: '13px' }}>加载中...</div>}
          {!loading && sessions.map((session) => (
            <div
              key={session.id}
              className={`iv-session-item${currentSession?.id === session.id ? ' active' : ''}`}
              onClick={() => loadSession(session.id)}
            >
              <div className="iv-session-title">{session.target_role}</div>
              <div className="iv-session-meta">
                <span className={`iv-status iv-status-${session.status}`}>
                  {session.status === 'completed' ? '已完成' : '进行中'}
                </span>
                <span>{DIFFICULTY_LABELS[session.difficulty] || session.difficulty}</span>
              </div>
              <button
                className="iv-session-delete"
                title="删除"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteSession(session.id);
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* Main content */}
      <main className="iv-main">
        {error ? (
          <div className="iv-empty">
            <p>{error}</p>
          </div>
        ) : !currentSession ? (
          <div className="iv-empty">
            <p>选择一个面试会话或创建新的面试</p>
            <button className="iv-start-btn" type="button" onClick={openNewSessionModal}>
              开始新面试
            </button>
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="iv-chat-header">
              <div>
                <h2 className="iv-chat-title">{currentSession.target_role}</h2>
                <span className="iv-chat-meta">
                  {DIFFICULTY_LABELS[currentSession.difficulty]} · {formatDate(currentSession.created_at)}
                </span>
              </div>
              {currentSession.status !== 'completed' && (
                <button className="iv-end-btn" type="button" disabled={ending} onClick={handleEndSession}>
                  {ending ? '生成报告中...' : '结束面试'}
                </button>
              )}
            </div>

            {/* Summary (if completed) */}
            {currentSession.status === 'completed' && summary && (
              <div className="iv-summary">
                <h3 className="iv-summary-title">面试评估报告</h3>
                <div className="iv-summary-grid">
                  <div className="iv-summary-score">
                    <span className="iv-score-value">{String(summary.overall_score ?? '—')}</span>
                    <span className="iv-score-label">总分</span>
                  </div>
                  <div className="iv-summary-recommendation">
                    <span className={`iv-rec iv-rec-${String(summary.recommendation ?? '').includes('通过') ? 'pass' : 'fail'}`}>
                      {String(summary.recommendation ?? '—')}
                    </span>
                  </div>
                </div>
                {summary.strengths && Array.isArray(summary.strengths) && (
                  <div className="iv-summary-section">
                    <h4>优势</h4>
                    <ul>
                      {(summary.strengths as string[]).map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {summary.improvements && Array.isArray(summary.improvements) && (
                  <div className="iv-summary-section">
                    <h4>改进建议</h4>
                    <ul>
                      {(summary.improvements as string[]).map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Messages */}
            <div className="iv-messages">
              {messages.map((msg) => (
                <div key={msg.id} className={`iv-message iv-message-${msg.role}`}>
                  <div className="iv-message-avatar">{msg.role === 'assistant' ? '面' : '我'}</div>
                  <div className="iv-message-content">
                    <pre className="iv-message-text">{msg.content}</pre>
                  </div>
                </div>
              ))}
              {streamingContent && (
                <div className="iv-message iv-message-assistant">
                  <div className="iv-message-avatar">面</div>
                  <div className="iv-message-content">
                    <pre className="iv-message-text">{streamingContent}</pre>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            {currentSession.status !== 'completed' && (
              <form className="iv-input-form" onSubmit={handleSend}>
                <textarea
                  className="iv-input"
                  placeholder="输入你的回答..."
                  rows={3}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend(e);
                    }
                  }}
                />
                <button className="iv-send-btn" type="submit" disabled={sending || !input.trim()}>
                  {sending ? '发送中...' : '发送'}
                </button>
              </form>
            )}
          </>
        )}
      </main>

      {/* New Session Modal */}
      {showNewSession && (
        <div className="iv-modal-backdrop" onClick={closeNewSessionModal}>
          <div
            className="iv-modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="iv-modal-header">
              <h2 className="iv-modal-title">开始新面试</h2>
              <button className="iv-modal-close" type="button" onClick={closeNewSessionModal}>
                ×
              </button>
            </div>
            <form className="iv-form" onSubmit={handleCreateSession}>
              <label className="iv-field">
                <span className="iv-field-label">目标职位</span>
                <input
                  className="iv-field-input"
                  required
                  placeholder="例如：高级前端工程师"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                />
              </label>
              <label className="iv-field">
                <span className="iv-field-label">难度</span>
                <select
                  className="iv-field-input"
                  value={newDifficulty}
                  onChange={(e) => setNewDifficulty(e.target.value)}
                >
                  <option value="easy">初级</option>
                  <option value="medium">中级</option>
                  <option value="hard">高级</option>
                </select>
              </label>
              <div className="iv-form-actions">
                <button className="iv-cancel-btn" type="button" disabled={creating} onClick={closeNewSessionModal}>
                  取消
                </button>
                <button className="iv-submit-btn" type="submit" disabled={creating}>
                  {creating ? '创建中...' : '开始面试'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
