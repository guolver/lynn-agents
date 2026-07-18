import { MatchCard } from './match-card';

type ToolData = {
  name: string;
  result?: {
    matches?: Array<{
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

export function ChatMessage({
  role,
  content,
  toolData,
  isStreaming,
}: {
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolData?: ToolData;
  isStreaming?: boolean;
}) {
  if (role === 'tool') return null;

  const isUser = role === 'user';

  const matchCards =
    toolData?.name === 'run_matches' && toolData.result?.matches ? toolData.result.matches.slice(0, 5) : null;

  return (
    <div className={`gpt-msg ${isUser ? 'gpt-msg-user' : 'gpt-msg-assistant'}`}>
      <div className="gpt-msg-row">
        {/* Avatar */}
        <div className={`gpt-avatar ${isUser ? 'gpt-avatar-user' : 'gpt-avatar-ai'}`}>
          {isUser ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="2" />
              <path d="M4 20c0-4 4-7 8-7s8 3 8 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          ) : (
            <span className="gpt-avatar-text">AH</span>
          )}
        </div>

        {/* Content */}
        <div className="gpt-msg-body">
          <div className="gpt-msg-name">{isUser ? 'You' : 'Agent Hub'}</div>
          {content && <div className="gpt-msg-content">{content}</div>}
          {matchCards && (
            <div className="gpt-msg-matches">
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
                />
              ))}
            </div>
          )}
          {isStreaming && <span className="gpt-cursor" />}
        </div>
      </div>
    </div>
  );
}
