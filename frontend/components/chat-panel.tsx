'use client';

import { useEffect, useRef, useState } from 'react';
import { ChatMessage } from './chat-message';

type Message = {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolData?: { name: string; result?: Record<string, unknown> };
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
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load history on mount
  useEffect(() => {
    fetch(`/api/chat/sessions/${sessionId}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.messages) {
          setMessages(
            data.messages
              .filter((m: Record<string, unknown>) => m.role !== 'tool')
              .map((m: Record<string, unknown>) => ({
                id: m.id,
                role: m.role,
                content: m.content,
              })),
          );
        }
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

  async function handleSend() {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');

    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);

    await streamAssistant(text);
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
      if (res.ok) {
        const userMsg: Message = {
          id: crypto.randomUUID(),
          role: 'user',
          content: `已上传简历: ${file.name}`,
        };
        setMessages((prev) => [...prev, userMsg]);
        await streamAssistant(
          'I just uploaded my resume. Please use the parse_resume tool on the resume text from my previous message to extract my profile, then run_matches to find suitable jobs.',
        );
      } else {
        const data = await res.json();
        alert(data.detail ?? 'Upload failed');
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
              <p>有什么可以帮你的？</p>
            </div>
          )}
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              role={msg.role}
              content={msg.content}
              toolData={msg.toolData}
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
