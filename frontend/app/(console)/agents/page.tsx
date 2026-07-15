import Link from "next/link";
import { PageHeader } from "../../../components/page-header";
import { getAgents } from "../../../lib/agent-hub";

export const metadata = { title: "Agent 目录" };

export default async function AgentsPage() {
  const agents = await getAgents();
  return (
    <>
      <PageHeader eyebrow="Agent catalog" title="统一发现和治理业务 Agent" description="每个 Agent 都通过 Manifest 描述版本、责任方和动作白名单。没有专属 UI 的 Agent 仍可使用通用动作控制台。" />
      <section className="agent-grid">
        {agents.map((agent) => <Link className="agent-card" href={`/agents/${agent.agent_id}`} key={agent.agent_id}><span className="agent-code">PT</span><h2 className="agent-name">{agent.name}</h2><p className="agent-description">{agent.description}</p><div className="tag-list">{agent.tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div><div className="agent-footer"><span>v{agent.version} · {agent.owner}</span><strong>查看能力 →</strong></div></Link>)}
        <article className="agent-card muted"><span className="agent-code">＋</span><h2 className="agent-name">接入下一个 Agent</h2><p className="agent-description">实现统一 Agent Protocol，通过本地注入或受控 Python entry point 注册，平台会自动生成目录和动作入口。</p><div className="agent-footer"><span>Extension ready</span><strong>等待接入</strong></div></article>
      </section>
    </>
  );
}
