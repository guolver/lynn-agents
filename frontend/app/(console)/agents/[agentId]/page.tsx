import { notFound } from "next/navigation";
import { ActionConsole } from "../../../../components/action-console";
import { PageHeader } from "../../../../components/page-header";
import { getAgent } from "../../../../lib/agent-hub";

export default async function AgentDetailPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = await params;
  const agent = await getAgent(agentId);
  if (!agent) notFound();
  const actions = agent.actions ?? [];
  return (
    <>
      <PageHeader eyebrow={`${agent.agent_id} · v${agent.version}`} title={agent.name} description={agent.description} action={<span className="status-badge approved">已注册 · healthy</span>} />
      <div className="split-grid">
        <section className="panel"><div className="panel-header"><div><h2 className="panel-title">公开动作</h2><p className="panel-subtitle">注册表只允许执行 Manifest 中明确声明的动作</p></div><span className="metric-code">{actions.length} ACTIONS</span></div><div className="panel-body action-list">{actions.map((action) => <div className="action-row" key={action.name}><div><div className="action-name">{action.name}</div><div className="action-description">{action.description}</div></div><div className="action-meta"><span className={`risk-badge ${action.risk_level}`}>{action.risk_level}</span><span className={`status-badge ${action.mode === "write" ? "pending" : "approved"}`}>{action.mode}</span></div></div>)}</div></section>
        <section className="panel"><div className="panel-header"><div><h2 className="panel-title">通用动作控制台</h2><p className="panel-subtitle">根据动作 Schema 组织输入，写动作自动附加幂等键</p></div></div><div className="panel-body"><ActionConsole agentId={agent.agent_id} actions={actions} /></div></section>
      </div>
    </>
  );
}
