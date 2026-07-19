export function MatchCard({
  title,
  company,
  score,
  reasons,
  workMode,
  compensation,
  onClick,
}: {
  title: string;
  company: string;
  score: number;
  reasons: string[];
  workMode?: string;
  compensation?: string;
  onClick?: () => void;
}) {
  const pct = Math.round(score * 100);
  return (
    <div
      className={`match-card${onClick ? ' match-card-clickable' : ''}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <div className="match-card-header">
        <div>
          <div className="match-card-title">{title}</div>
          <div className="match-card-company">{company}</div>
        </div>
        <div className="match-card-score">{pct}%</div>
      </div>
      <div className="match-card-bar">
        <div className="match-card-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="match-card-meta">
        {workMode && <span className="tag">{workMode}</span>}
        {compensation && <span className="tag">{compensation}</span>}
      </div>
      {reasons.length > 0 && (
        <div className="match-card-reasons">
          {reasons.map((r) => (
            <span className="tag" key={r}>
              {r}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
