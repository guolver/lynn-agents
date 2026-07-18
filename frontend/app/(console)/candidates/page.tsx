import Link from 'next/link';
import { PageHeader } from '../../../components/page-header';
import { ResumeUploadPanel } from '../../../components/resume-upload-panel';
import { getCandidates } from '../../../lib/agent-hub';
import { demoCandidates } from '../../../lib/demo-data';

export const metadata = { title: '候选人管理' };

const filters = [
  { label: '全部', consent: undefined },
  { label: '已订阅', consent: 'opted_in' },
  { label: '未授权', consent: 'opted_out' },
  { label: '未请求', consent: 'not_requested' },
];

const consentLabel: Record<string, string> = {
  opted_in: '已订阅',
  opted_out: '已退出',
  not_requested: '未请求',
};

export default async function CandidatesPage({
  searchParams,
}: {
  searchParams: Promise<{ consent?: string }>;
}) {
  const { consent } = await searchParams;
  const allCandidates = await getCandidates();
  const candidates = consent ? allCandidates.filter((c) => c.consent_status === consent) : allCandidates;

  return (
    <>
      <PageHeader
        eyebrow="Candidate management"
        title="候选人管理"
        description="查看和管理所有候选人，包括授权状态、技能画像、通知偏好。只有主动订阅的候选人才会进入匹配流程。"
        action={<ResumeUploadPanel />}
      />
      <div className="toolbar">
        <input className="search-box" aria-label="搜索候选人" placeholder="搜索候选人…" />
        <div className="filter-group">
          {filters.map((f) => {
            const count = f.consent
              ? demoCandidates.filter((c) => c.consent_status === f.consent).length
              : demoCandidates.length;
            const active = consent === f.consent || (!consent && !f.consent);
            const href = f.consent ? `/candidates?consent=${f.consent}` : '/candidates';
            return (
              <Link key={href} href={href} className={`filter-chip${active ? ' active' : ''}`}>
                {f.label} {count}
              </Link>
            );
          })}
        </div>
      </div>
      <section className="panel table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>候选人</th>
              <th>技能</th>
              <th>可用工时</th>
              <th>授权状态</th>
              <th>通知频率</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={c.id} className="clickable-row">
                <td>
                  <Link href={`/candidates/${c.id}`} className="cell-link">
                    <div className="cell-primary">
                      {c.id} · {c.country}
                    </div>
                    <div className="cell-secondary">{c.timezone}</div>
                  </Link>
                </td>
                <td>
                  <div className="tag-list" style={{ marginTop: 0 }}>
                    {c.skills.slice(0, 3).map((s) => (
                      <span className="tag" key={s.name}>
                        {s.name}
                      </span>
                    ))}
                    {c.skills.length > 3 && <span className="tag">+{c.skills.length - 3}</span>}
                  </div>
                </td>
                <td>{c.availability_hours_per_week}h/week</td>
                <td>
                  <span
                    className={`status-badge ${c.consent_status === 'opted_in' ? 'approved' : c.consent_status === 'opted_out' ? 'rejected' : 'pending'}`}
                  >
                    {consentLabel[c.consent_status] ?? c.consent_status}
                  </span>
                </td>
                <td>{c.notification_frequency}</td>
                <td>{c.created_at ? new Date(c.created_at).toLocaleDateString('zh-CN') : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
