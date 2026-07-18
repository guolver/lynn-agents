'use client';

import { useEffect, useRef, useState } from 'react';
import { ChatMessage } from './chat-message';

import { EMPTY_STATE_SUGGESTIONS } from '../lib/chat-suggestions';

type Message = {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolData?: { name: string; result?: Record<string, unknown> };
};

type AnalysisResult = {
  summary?: string;
  matches?: Array<Record<string, unknown>>;
};

// Parse a streamed SSE body frame-by-frame.
async function readSSE(
  body: ReadableStream<Uint8Array>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onEvent: (event: string, data: any) => void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      let eventType = '';
      let dataStr = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) eventType = line.slice(7).trim();
        else if (line.startsWith('data: ')) dataStr += line.slice(6);
      }
      if (!dataStr) continue;

      try {
        onEvent(eventType, JSON.parse(dataStr));
      } catch {
        // ignore malformed frame
      }
    }
  }
}

const TOOL_LABELS: Record<string, string> = {
  run_matches: '正在匹配岗位...',
  parse_resume: '正在解析简历...',
  search_jobs: '正在搜索岗位...',
  get_job_detail: '正在加载岗位详情...',
  update_preferences: '正在更新偏好...',
  get_my_profile: '正在获取档案...',
};

export function ChatPanel({ sessionId }: { sessionId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [, setSelectedJobId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load history on mount. Tool messages carrying run_matches results are not
  // rendered directly; instead their match cards are re-attached to the
  // preceding assistant message so cards survive a page refresh.
  useEffect(() => {
    fetch(`/api/chat/sessions/${sessionId}`)
      .then((r) => r.json())
      .then((data) => {
        if (!Array.isArray(data.messages)) return;
        const rebuilt: Message[] = [];
        for (const m of data.messages as Array<Record<string, unknown>>) {
          if (m.role === 'tool') {
            try {
              const parsed = JSON.parse(m.content as string);
              const matches = parsed?.result?.matches;
              if (parsed?.name === 'run_matches' && Array.isArray(matches) && matches.length) {
                for (let i = rebuilt.length - 1; i >= 0; i--) {
                  if (rebuilt[i].role === 'assistant') {
                    rebuilt[i] = { ...rebuilt[i], toolData: { name: 'run_matches', result: { matches } } };
                    break;
                  }
                }
              }
            } catch {
              // ignore malformed tool payloads
            }
            continue;
          }
          rebuilt.push({
            id: m.id as string,
            role: m.role as Message['role'],
            content: m.content as string,
          });
        }
        setMessages(rebuilt);
      })
      .catch(() => {});
  }, [sessionId]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
    }
  }, [input]);

  async function streamAssistant(text: string) {
    setIsStreaming(true);
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }]);

    try {
      const response = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      });

      if (!response.ok) {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, content: 'Error: request failed' } : m)),
        );
        setIsStreaming(false);
        return;
      }

      if (response.body) {
        await readSSE(response.body, (eventType, data) => {
          if (eventType === 'delta') {
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + data.content } : m)),
            );
          } else if (eventType === 'tool_call') {
            const label = TOOL_LABELS[data.name] || 'Processing...';
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: m.content || label } : m)),
            );
          } else if (eventType === 'tool_result') {
            if (data.name === 'run_matches' && data.result?.matches) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: '', toolData: { name: data.name, result: data.result } }
                    : m,
                ),
              );
            }
          } else if (eventType === 'error') {
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: `Error: ${data.detail}` } : m)),
            );
          }
        });
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, content: '网络错误，请重试。' } : m)),
      );
    } finally {
      setIsStreaming(false);
    }
  }

  async function sendPrompt(text: string) {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || isUploading) return;

    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: trimmed };
    setMessages((prev) => [...prev, userMsg]);

    await streamAssistant(trimmed);
  }

  async function handleSend() {
    const text = input.trim();
    if (!text) return;
    setInput('');
    await sendPrompt(text);
  }

  // Render a completed analysis (summary text + match cards) into the placeholder.
  function applyAnalysisResult(assistantId: string, result: AnalysisResult | undefined) {
    const matches = result?.matches;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === assistantId
          ? {
              ...m,
              content: result?.summary ?? '匹配完成。',
              toolData:
                matches && matches.length
                  ? { name: 'run_matches', result: { matches } }
                  : undefined,
            }
          : m,
      ),
    );
  }

  function setAssistantText(assistantId: string, text: string) {
    setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: text } : m)));
  }

  // Poll the async resume-analysis task until it succeeds or fails.
  async function pollAnalysis(taskId: string, assistantId: string) {
    const intervalMs = 3000;
    const maxAttempts = 120; // ~6 min, matches the backend Celery time limit
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      await new Promise((r) => setTimeout(r, intervalMs));
      let data: { status?: string; result?: AnalysisResult; error?: string } | null = null;
      try {
        const r = await fetch(`/api/chat/tasks/${taskId}`);
        data = await r.json();
      } catch {
        continue; // transient network error — keep polling
      }
      const status = data?.status;
      if (status === 'SUCCESS') {
        applyAnalysisResult(assistantId, data?.result);
        return;
      }
      if (status === 'FAILURE') {
        setAssistantText(assistantId, `分析失败：${data?.error ?? '未知错误'}`);
        return;
      }
      // PENDING / STARTED / RETRY → keep waiting
    }
    setAssistantText(assistantId, '分析超时，请稍后重试。');
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`/api/chat/sessions/${sessionId}/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert(data.detail ?? '上传失败');
        return;
      }

      const data = await res.json();
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: `已上传简历：${file.name}`,
      };
      const assistantId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: assistantId, role: 'assistant', content: '正在解析简历并匹配岗位，请稍候…' },
      ]);
      setIsStreaming(true);
      try {
        if (data.status === 'completed' && data.result) {
          applyAnalysisResult(assistantId, data.result); // synchronous fallback (no Celery)
        } else if (data.task_id) {
          await pollAnalysis(data.task_id, assistantId);
        } else {
          setAssistantText(assistantId, '无法启动分析任务。');
        }
      } finally {
        setIsStreaming(false);
      }
    } catch {
      alert('上传失败');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="gpt-chat">
      {/* Messages */}
      <div className="gpt-messages">
        <div className="gpt-messages-inner">
          {messages.length === 0 && (
            <div className="gpt-empty">
              <div className="gpt-empty-logo">AH</div>
              <h2 className="gpt-empty-title">我是 Agent Hub 求职助手</h2>
              <p className="gpt-empty-sub">上传简历、搜索岗位、智能匹配、管理求职偏好 —— 有什么可以帮你的？</p>
              <div className="gpt-empty-cards">
                {EMPTY_STATE_SUGGESTIONS.map((s) => (
                  <button
                    key={s.label}
                    className="gpt-empty-card"
                    disabled={isStreaming || isUploading}
                    onClick={() =>
                      s.action === 'upload' ? fileInputRef.current?.click() : sendPrompt(s.prompt!)
                    }
                  >
                    <span className="gpt-empty-card-icon">{s.icon}</span>
                    <span>{s.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              role={msg.role}
              content={msg.content}
              toolData={msg.toolData}
              onCardClick={setSelectedJobId}
              isStreaming={
                isStreaming && msg.id === messages[messages.length - 1]?.id && msg.role === 'assistant'
              }
            />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      <div className="gpt-input-wrap">
        <div className="gpt-input-box">
          <input
            type="file"
            accept=".pdf"
            ref={fileInputRef}
            onChange={handleUpload}
            style={{ display: 'none' }}
          />
          <button
            className="gpt-attach-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={isStreaming || isUploading}
            title="上传简历 PDF"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path
                d="M21.44 11.05l-9.19 9.19a5.64 5.64 0 01-7.98-7.98l9.19-9.19a3.76 3.76 0 015.32 5.32L9.6 17.57a1.88 1.88 0 01-2.66-2.66l8.38-8.38"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            className="gpt-textarea"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="给 Agent Hub 发送消息..."
            disabled={isStreaming}
            rows={1}
          />
          <button
            className="gpt-send-btn"
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            title="发送"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        <div className="gpt-disclaimer">Agent Hub 可能会出错。请核实重要信息。</div>
      </div>

    </div>
  );
}
