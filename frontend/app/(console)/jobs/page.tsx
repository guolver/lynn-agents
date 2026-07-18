import Link from 'next/link';
import { PageHeader } from '../../../components/page-header';
import { getJobs } from '../../../lib/agent-hub';
import { demoJobs } from '../../../lib/demo-data';

export const metadata = { title: '职位中心' };

const filters = [
  { label: '全部', status: undefined },
  { label: '低风险', status: 'active', countFn: (j: { risk_level: string }) => j.risk_level === 'low' },
  { label: '待审核', status: 'pending_review' },
];

export default async function JobsPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status } = await searchParams;
  const jobs = await getJobs(status);

  return (
    <>
      <PageHeader
        eyebrow="Job intelligence"
        title="职位质量与风险一屏可见"
        description="每条职位保留来源、规范化结果、确定性风险分和质量分。中高风险内容不会绕过人工审核。"
      />
      <div className="toolbar">
        <input className="search-box" aria-label="搜索职位" placeholder="搜索职位或公司…" />
        <div className="filter-group">
          {filters.map((f) => {
            const count = f.countFn
              ? demoJobs.filter(f.countFn).length
              : f.status
                ? demoJobs.filter((j) => j.status === f.status).length
                : demoJobs.length;
            const active = status === f.status || (!status && !f.status);
            const href = f.status ? `/jobs?status=${f.status}` : '/jobs';
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
              <th>职位</th>
              <th>工作方式</th>
              <th>地区</th>
              <th>薪酬</th>
              <th>风险</th>
              <th>质量分</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id} className="clickable-row">
                <td>
                  <Link href={`/jobs/${job.id}`} className="cell-link">
                    <div className="cell-primary">{job.title_original}</div>
                    <div className="cell-secondary">
                      {job.company_name} · {job.id}
                    </div>
                  </Link>
                </td>
                <td>{job.work_mode}</td>
                <td>{job.countries_allowed.join(', ')}</td>
                <td>
                  {job.compensation_min ?? '?'}–{job.compensation_max ?? '?'} {job.compensation_currency ?? ''}
                </td>
                <td>
                  <span className={`risk-badge ${job.risk_level}`}>
                    {job.risk_level} · {Math.round(job.risk_score * 100)}%
                  </span>
                </td>
                <td>{Math.round(job.quality_score * 100)}%</td>
                <td>
                  <span
                    className={`status-badge ${job.status === 'active' ? 'active' : job.status === 'rejected' ? 'rejected' : 'pending'}`}
                  >
                    {job.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
