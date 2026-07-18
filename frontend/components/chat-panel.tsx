'use client';

import { useEffect, useRef, useState } from 'react';
import { ChatMessage } from './chat-message';

type Message = {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolData?: { name: string; result?: Record<string, unknown> };
};

export function ChatPanel({ sessionId }: { sessionId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  async function handleSend() {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');

    // Add user message
    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);

    // Start streaming
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

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let eventType = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              const dataStr = line.slice(6);
              try {
                const data = JSON.parse(dataStr);

                if (eventType === 'delta') {
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId ? { ...m, content: m.content + data.content } : m,
                    ),
                  );
                } else if (eventType === 'tool_call') {
                  // Show loading indicator
                  const toolLabel =
                    data.name === 'run_matches'
                      ? 'Matching jobs...'
                      : data.name === 'parse_resume'
                        ? 'Parsing resume...'
                        : data.name === 'search_jobs'
                          ? 'Searching...'
                          : data.name === 'get_job_detail'
                            ? 'Loading job...'
                            : 'Processing...';
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId ? { ...m, content: m.content || toolLabel } : m,
                    ),
                  );
                } else if (eventType === 'tool_result') {
                  // If it's a match result, attach the data
                  if (data.name === 'run_matches' && data.result?.matches) {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantId
                          ? { ...m, content: '', toolData: { name: data.name, result: data.result } }
                          : m,
                      ),
                    );
                  }
                } else if (eventType === 'done') {
                  // Complete
                } else if (eventType === 'error') {
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId ? { ...m, content: `Error: ${data.detail}` } : m,
                    ),
                  );
                }
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: 'Network error. Please retry.' } : m,
        ),
      );
    } finally {
      setIsStreaming(false);
    }
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
        // After upload, send a message to trigger resume parsing
        setInput('');
        const userMsg: Message = {
          id: crypto.randomUUID(),
          role: 'user',
          content: `I uploaded my resume: ${file.name}. Please analyze it and find matching jobs for me.`,
        };
        setMessages((prev) => [...prev, userMsg]);

        // Trigger LLM to process the resume
        setIsStreaming(true);
        const assistantId = crypto.randomUUID();
        setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }]);

        const response = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            content:
              'I just uploaded my resume. Please use the parse_resume tool on the resume text from my previous message to extract my profile, then run_matches to find suitable jobs.',
          }),
        });

        if (response.ok && response.body) {
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            let eventType = '';
            for (const line of lines) {
              if (line.startsWith('event: ')) {
                eventType = line.slice(7).trim();
              } else if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6));
                  if (eventType === 'delta') {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantId ? { ...m, content: m.content + data.content } : m,
                      ),
                    );
                  } else if (eventType === 'tool_result' && data.name === 'run_matches') {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantId
                          ? {
                              ...m,
                              content: '',
                              toolData: { name: data.name, result: data.result },
                            }
                          : m,
                      ),
                    );
                  }
                } catch {}
              }
            }
          }
        }
        setIsStreaming(false);
      } else {
        const data = await res.json();
        alert(data.detail ?? 'Upload failed');
      }
    } catch {
      alert('Upload failed');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <h2>Agent Hub Assistant</h2>
            <p>Upload your resume or describe your skills to get started.</p>
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
      <div className="chat-input-area">
        <input
          type="file"
          accept=".pdf"
          ref={fileInputRef}
          onChange={handleUpload}
          style={{ display: 'none' }}
        />
        <button
          className="chat-upload-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={isStreaming || isUploading}
          title="Upload Resume PDF"
        >
          {isUploading ? '...' : '\u{1F4CE}'}
        </button>
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder="Type a message..."
          disabled={isStreaming}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={!input.trim() || isStreaming}
        >
          Send
        </button>
      </div>
    </div>
  );
}
