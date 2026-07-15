import Link from "next/link";
import { PageHeader } from "../../../components/page-header";
import { dashboardMetrics, demoAudits, funnelData } from "../../../lib/demo-data";

export const metadata = { title: "运行总览" };

export default function DashboardPage() {
  return (
    <>
      <PageHeader eyebrow="Platform overview" title="把每个 Agent 的运行状态看清楚" description="集中查看职位处理、风险判断、候选匹配和通知发送链路。当前页面使用演示数据，可通过环境配置连接现有 Agent Hub API。" action={<Link className="button" href="/agents/global-part-time">打开 Agent 控制台</Link>} />
      <section className="metrics-grid" aria-label="核心指标">
        {dashboardMetrics.map((metric) => (
          <article className="metric-card" key={metric.label}>
            <div className="metric-top"><span className="metric-label">{metric.label}</span><span className="metric-code">{metric.code}</span></div>
            <div className="metric-value">{metric.value}</div>
            <div className="metric-delta">{metric.delta}</div>
          </article>
        ))}
      </section>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-header"><div><h2 className="panel-title">职位处理漏斗</h2><p className="panel-subtitle">从来源同步到推荐发送的完整转化</p></div><Link className="panel-link" href="/matches">查看匹配详情 →</Link></div>
          <div className="panel-body funnel">
            {funnelData.map((item) => <div className="funnel-row" key={item.label}><span>{item.label}</span><div className="funnel-track"><div className="funnel-fill" style={{ width: `${item.width}%` }} /></div><span className="funnel-value">{item.value.toLocaleString()}</span></div>)}
          </div>
        </section>
        <section className="panel">
          <div className="panel-header"><div><h2 className="panel-title">风险分布</h2><p className="panel-subtitle">最近同步职位的确定性规则结果</p></div></div>
          <div className="panel-body">
            <div className="risk-overview"><div className="risk-ring"><div className="risk-ring-value"><strong>78%</strong><span>低风险职位</span></div></div></div>
            <div className="legend">
              <div className="legend-row"><span className="legend-name"><span className="legend-dot" style={{ background: "var(--green)" }} />低风险 · 自动进入</span><strong>1,284</strong></div>
              <div className="legend-row"><span className="legend-name"><span className="legend-dot" style={{ background: "var(--amber)" }} />中风险 · 等待审批</span><strong>155</strong></div>
              <div className="legend-row"><span className="legend-name"><span className="legend-dot" style={{ background: "var(--red)" }} />高风险 · 已拒绝</span><strong>98</strong></div>
            </div>
          </div>
        </section>
      </div>
      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-header"><div><h2 className="panel-title">最近运行事件</h2><p className="panel-subtitle">关键操作均保留 actor、实体和处理结果</p></div><Link className="panel-link" href="/audit">进入审计中心 →</Link></div>
        <div className="activity-list">
          {demoAudits.slice(0, 5).map((item) => <div className="activity-row" key={item.id}><span className="activity-icon">{item.entity_kind.slice(0, 2).toUpperCase()}</span><div><div className="activity-title">{item.event}</div><div className="activity-meta">{item.entity_kind} · {item.entity_id} · {item.actor}</div></div><span className="activity-time">{new Date(item.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span></div>)}
        </div>
      </section>
    </>
  );
}
