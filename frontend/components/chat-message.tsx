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

  // Check if content has match results embedded (from tool_result)
  const matchCards =
    toolData?.name === 'run_matches' && toolData.result?.matches
      ? toolData.result.matches.slice(0, 5)
      : null;

  return (
    <div className={`chat-message ${isUser ? 'chat-message-user' : 'chat-message-assistant'}`}>
      <div className="chat-bubble">
        {content && <div className="chat-content">{content}</div>}
        {matchCards && (
          <div className="chat-matches">
            {matchCards.map((m, i) => (
              <MatchCard
                key={i}
                title={m.job_title ?? 'Unknown'}
                company={m.company_name ?? ''}
                score={m.score ?? 0}
                reasons={m.reasons ?? []}
                workMode={m.work_mode}
                compensation={
                  m.compensation_max
                    ? `$${m.compensation_max}/h ${m.compensation_currency ?? ''}`
                    : undefined
                }
              />
            ))}
          </div>
        )}
        {isStreaming && <span className="chat-cursor" />}
      </div>
    </div>
  );
}
