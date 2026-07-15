import { PageHeader } from "../../../components/page-header";
import { getAudits } from "../../../lib/agent-hub";

export const metadata = { title: "审计中心" };

export default async function AuditPage() {
  const audits = await getAudits();
  return (
    <>
      <PageHeader eyebrow="Audit trail" title="每次关键处理都能追溯" description="按事件、实体和操作者查看来源审批、风险判断、匹配运行、通知发送和数据删除记录。敏感正文与密钥不进入日志。" />
      <div className="toolbar"><input className="search-box" aria-label="搜索审计事件" placeholder="搜索 event、entity 或 actor…" /><div className="filter-group"><button className="filter-chip">全部事件</button><button className="filter-chip">高风险动作</button><button className="filter-chip">今天</button></div></div>
      <section className="panel"><div className="panel-header"><div><h2 className="panel-title">事件时间线</h2><p className="panel-subtitle">最近 {audits.length} 条演示记录</p></div></div><div className="panel-body timeline">{audits.map((item) => <div className="timeline-item" key={item.id}><time className="timeline-time">{new Date(item.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}<br />07-15</time><div className="timeline-axis"><div className="timeline-dot" /></div><div><div className="timeline-title">{item.event}</div><div className="timeline-detail">{item.entity_kind} · {item.entity_id} · {JSON.stringify(item.details)}</div></div><span className="timeline-actor">{item.actor}</span></div>)}</div></section>
    </>
  );
}
