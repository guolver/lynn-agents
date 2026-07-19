import { notFound } from 'next/navigation';
import { getAgent } from '../../../../lib/agent-hub';

export default async function AgentDetailPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = await params;
  const agent = await getAgent(agentId);
  if (!agent) notFound();
  const actions = agent.actions ?? [];
  return (
    <>
      <div className="page-header">
        <p className="page-eyebrow">
          {agent.agent_id} · v{agent.version}
        </p>
        <h1>{agent.name}</h1>
        <p className="page-description">{agent.description}</p>
      </div>
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">公开动作</h2>
            <p className="panel-subtitle">Manifest 中声明的动作列表</p>
          </div>
          <span className="metric-code">{actions.length} ACTIONS</span>
        </div>
        <div className="panel-body action-list">
          {actions.map((action) => (
            <div className="action-row" key={action.name}>
              <div>
                <div className="action-name">{action.name}</div>
                <div className="action-description">{action.description}</div>
              </div>
              <div className="action-meta">
                <span className={`risk-badge ${action.risk_level}`}>{action.risk_level}</span>
                <span className={`status-badge ${action.mode === 'write' ? 'pending' : 'approved'}`}>{action.mode}</span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
