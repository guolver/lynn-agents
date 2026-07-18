import Link from 'next/link';
import { PageHeader } from '../../../components/page-header';
import { getAudits, getCandidates, getJobs, getNotifications } from '../../../lib/agent-hub';

export const metadata = { title: '运行总览' };

export default async function DashboardPage() {
  const [jobs, candidates, notifications, audits] = await Promise.all([
    getJobs(),
    getCandidates(),
    getNotifications(),
    getAudits(),
  ]);

  const activeJobs = jobs.filter((j) => j.status === 'active').length;
  const totalCandidates = candidates.length;
  const optedInCount = candidates.filter((c) => c.consent_status === 'opted_in').length;
  const optedInRate = totalCandidates > 0 ? Math.round((optedInCount / totalCandidates) * 100) : 0;
  const pendingApproval = notifications.filter((n) => n.status === 'pending_approval').length;

  const lowRisk = jobs.filter((j) => j.risk_level === 'low').length;
  const medRisk = jobs.filter((j) => j.risk_level === 'medium').length;
  const highRisk = jobs.filter((j) => j.risk_level === 'high').length;
  const totalRiskJobs = lowRisk + medRisk + highRisk;
  const lowPct = totalRiskJobs > 0 ? Math.round((lowRisk / totalRiskJobs) * 100) : 0;
  const medPct = totalRiskJobs > 0 ? Math.round((medRisk / totalRiskJobs) * 100) : 0;
  const highPct = totalRiskJobs > 0 ? Math.round((highRisk / totalRiskJobs) * 100) : 0;

  const pendingReview = jobs.filter((j) => j.status === 'pending_review').length;
  const matchPool = activeJobs;

  const metrics = [
    { label: '已注册 Agent', value: '01', delta: '平台运行正常', code: 'AGT' },
    { label: '活跃职位', value: activeJobs.toLocaleString(), delta: `共 ${jobs.length} 条职位`, code: 'JOB' },
    { label: '候选人', value: totalCandidates.toString(), delta: `${optedInRate}% 已主动订阅`, code: 'USR' },
    { label: '待人工审批', value: pendingApproval.toString(), delta: `${pendingReview} 条职位待审核`, code: 'APR' },
  ];

  const funnelData = [
    { label: '同步总数', value: jobs.length, width: 100 },
    { label: '通过风险检查', value: lowRisk + medRisk, width: totalRiskJobs > 0 ? Math.round(((lowRisk + medRisk) / totalRiskJobs) * 100) : 0 },
    { label: '进入匹配池', value: matchPool, width: totalRiskJobs > 0 ? Math.round((matchPool / totalRiskJobs) * 100) : 0 },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Platform overview"
        title="把每个 Agent 的运行状态看清楚"
        description="集中查看职位处理、风险判断、候选匹配和通知发送链路。数据从 Agent Hub API 实时获取。"
        action={<Link className="button" href="/agents/global-part-time">打开 Agent 控制台</Link>}
      />
      <section className="metrics-grid" aria-label="核心指标">
        {metrics.map((metric) => (
          <article className="metric-card" key={metric.label}>
            <div className="metric-top">
              <span className="metric-label">{metric.label}</span>
              <span className="metric-code">{metric.code}</span>
            </div>
            <div className="metric-value">{metric.value}</div>
            <div className="metric-delta">{metric.delta}</div>
          </article>
        ))}
      </section>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">职位处理漏斗</h2>
              <p className="panel-subtitle">从来源同步到进入匹配池的转化</p>
            </div>
            <Link className="panel-link" href="/matches">查看匹配详情 →</Link>
          </div>
          <div className="panel-body funnel">
            {funnelData.map((item) => (
              <div className="funnel-row" key={item.label}>
                <span>{item.label}</span>
                <div className="funnel-track">
                  <div className="funnel-fill" style={{ width: `${item.width}%` }} />
                </div>
                <span className="funnel-value">{item.value.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">风险分布</h2>
              <p className="panel-subtitle">已同步职位的确定性规则结果</p>
            </div>
          </div>
          <div className="panel-body">
            <div className="risk-overview">
              <div className="risk-ring" style={{ background: `conic-gradient(var(--green) 0 ${lowPct}%, var(--amber) ${lowPct}% ${lowPct + medPct}%, var(--red) ${lowPct + medPct}% 100%)` }}>
                <div className="risk-ring-value">
                  <strong>{lowPct}%</strong>
                  <span>低风险职位</span>
                </div>
              </div>
            </div>
            <div className="legend">
              <div className="legend-row">
                <span className="legend-name"><span className="legend-dot" style={{ background: 'var(--green)' }} />低风险 · 自动进入</span>
                <strong>{lowRisk}</strong>
              </div>
              <div className="legend-row">
                <span className="legend-name"><span className="legend-dot" style={{ background: 'var(--amber)' }} />中风险 · 等待审批</span>
                <strong>{medRisk}</strong>
              </div>
              <div className="legend-row">
                <span className="legend-name"><span className="legend-dot" style={{ background: 'var(--red)' }} />高风险 · 已拒绝</span>
                <strong>{highRisk}</strong>
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* Quick links */}
      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-header">
          <div>
            <h2 className="panel-title">快捷导航</h2>
            <p className="panel-subtitle">快速访问管道各环节</p>
          </div>
        </div>
        <div className="panel-body">
          <div className="action-list">
            <Link href="/candidates" className="action-row" style={{ textDecoration: 'none' }}>
              <div>
                <div className="action-name">候选人管理</div>
                <div className="action-description">{totalCandidates} 个候选人，{optedInCount} 个已订阅</div>
              </div>
              <div className="action-meta"><span className="panel-link">查看 →</span></div>
            </Link>
            <Link href="/notifications" className="action-row" style={{ textDecoration: 'none' }}>
              <div>
                <div className="action-name">通知中心</div>
                <div className="action-description">{pendingApproval} 条待审批通知</div>
              </div>
              <div className="action-meta"><span className="panel-link">查看 →</span></div>
            </Link>
            <Link href="/workflows" className="action-row" style={{ textDecoration: 'none' }}>
              <div>
                <div className="action-name">工作流监控</div>
                <div className="action-description">查看异步任务执行状态</div>
              </div>
              <div className="action-meta"><span className="panel-link">查看 →</span></div>
            </Link>
          </div>
        </div>
      </section>

      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-header">
          <div>
            <h2 className="panel-title">最近运行事件</h2>
            <p className="panel-subtitle">关键操作均保留 actor、实体和处理结果</p>
          </div>
          <Link className="panel-link" href="/audit">进入审计中心 →</Link>
        </div>
        <div className="activity-list">
          {audits.slice(0, 5).map((item) => (
            <div className="activity-row" key={item.id}>
              <span className="activity-icon">{item.entity_kind.slice(0, 2).toUpperCase()}</span>
              <div>
                <div className="activity-title">{item.event}</div>
                <div className="activity-meta">{item.entity_kind} · {item.entity_id} · {item.actor}</div>
              </div>
              <span className="activity-time">{new Date(item.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
