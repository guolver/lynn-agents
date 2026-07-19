import Link from 'next/link';
import { getAgents } from '../../../lib/agent-hub';

export const metadata = { title: 'Agent 目录' };

export default async function AgentsPage() {
  const agents = await getAgents();
  return (
    <>
      <div className="page-header">
        <h1>Agent 目录</h1>
        <p className="page-description">统一发现和治理业务 Agent</p>
      </div>
      <section className="agent-grid">
        {agents.map((agent) => (
          <Link className="agent-card" href={`/agents/${agent.agent_id}`} key={agent.agent_id}>
            <span className="agent-code">PT</span>
            <h2 className="agent-name">{agent.name}</h2>
            <p className="agent-description">{agent.description}</p>
            <div className="tag-list">
              {agent.tags.map((tag) => (
                <span className="tag" key={tag}>
                  {tag}
                </span>
              ))}
            </div>
            <div className="agent-footer">
              <span>
                v{agent.version} · {agent.owner}
              </span>
              <strong>查看能力 →</strong>
            </div>
          </Link>
        ))}
      </section>
    </>
  );
}
