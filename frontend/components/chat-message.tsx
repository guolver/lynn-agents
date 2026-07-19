import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { MatchCard } from './match-card';

type ToolData = {
  name: string;
  result?: {
    matches?: Array<{
      job_id?: string;
      job_title?: string;
      company_name?: string;
      score?: number;
      reasons?: string[];
      work_mode?: string;
      compensation_max?: number;
      compensation_currency?: string;
    }>;
  };
};

type FileData = {
  name: string;
  size: number;
  type: string;
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ChatMessage({
  role,
  content,
  toolData,
  fileData,
  isStreaming,
  onCardClick,
}: {
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolData?: ToolData;
  fileData?: FileData;
  isStreaming?: boolean;
  onCardClick?: (jobId: string) => void;
}) {
  if (role === 'tool') return null;

  const isUser = role === 'user';

  const matchCards =
    toolData?.name === 'run_matches' && toolData.result?.matches ? toolData.result.matches.slice(0, 5) : null;

  return (
    <div className={`chat-msg ${isUser ? 'chat-msg-user' : 'chat-msg-assistant'}`}>
      <div className="chat-msg-row">
        <div className={`chat-avatar ${isUser ? 'chat-avatar-user' : 'chat-avatar-ai'}`}>
          {isUser ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="2" />
              <path d="M4 20c0-4 4-7 8-7s8 3 8 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          ) : (
            <span className="chat-avatar-text">AH</span>
          )}
        </div>
        <div className="chat-msg-body">
          <div className="chat-msg-name">{isUser ? 'You' : 'Agent Hub'}</div>
          {fileData && (
            <div className="chat-file-card">
              <div className="chat-file-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path d="M14 2v6h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div className="chat-file-info">
                <div className="chat-file-name">{fileData.name}</div>
                {fileData.size > 0 && <div className="chat-file-meta">{formatFileSize(fileData.size)}</div>}
              </div>
            </div>
          )}
          {content &&
            (isUser ? (
              <div className="chat-msg-content">{content}</div>
            ) : (
              <div className="chat-msg-content chat-msg-md">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
              </div>
            ))}
          {matchCards && (
            <div className="chat-msg-matches">
              {matchCards.map((m, i) => (
                <MatchCard
                  key={i}
                  title={m.job_title ?? 'Unknown'}
                  company={m.company_name ?? ''}
                  score={m.score ?? 0}
                  reasons={m.reasons ?? []}
                  workMode={m.work_mode}
                  compensation={
                    m.compensation_max ? `$${m.compensation_max}/h ${m.compensation_currency ?? ''}` : undefined
                  }
                  onClick={m.job_id && onCardClick ? () => onCardClick(m.job_id!) : undefined}
                />
              ))}
            </div>
          )}
          {isStreaming && <span className="chat-cursor" />}
        </div>
      </div>
    </div>
  );
}
