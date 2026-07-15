import { PageHeader } from "../../../components/page-header";
import { getSources } from "../../../lib/agent-hub";

export const metadata = { title: "职位来源" };

export default async function SourcesPage() {
  const sources = await getSources();
  return (
    <>
      <PageHeader eyebrow="Source governance" title="每一个来源都先授权，再同步" description="集中查看来源类型、审批状态、速率限制和最近同步时间。未批准来源不会被 Agent 调用。" action={<button className="button">登记新来源</button>} />
      <div className="toolbar"><input className="search-box" aria-label="搜索来源" placeholder="搜索来源名称或域名…" /><div className="filter-group"><button className="filter-chip">全部 {sources.length}</button><button className="filter-chip">已批准 {sources.filter((s) => s.review_status === "approved").length}</button><button className="filter-chip">待审批 {sources.filter((s) => s.review_status === "pending").length}</button></div></div>
      <section className="panel table-wrap"><table className="data-table"><thead><tr><th>来源</th><th>类型</th><th>审批状态</th><th>速率限制</th><th>最近更新</th><th>运行状态</th></tr></thead><tbody>{sources.map((source) => <tr key={source.id}><td><div className="cell-primary">{source.name}</div><div className="cell-secondary">{source.base_url}</div></td><td>{source.source_type}</td><td><span className={`status-badge ${source.review_status}`}>{source.review_status}</span></td><td>{source.rate_limit}</td><td>{new Date(source.updated_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</td><td><span className={`status-badge ${source.enabled ? "approved" : "pending"}`}>{source.enabled ? "enabled" : "paused"}</span></td></tr>)}</tbody></table></section>
    </>
  );
}
