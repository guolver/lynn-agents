import Link from 'next/link';
import { notFound } from 'next/navigation';
import { JobReviewPanel } from '../../../../components/job-review-panel';
import { PageHeader } from '../../../../components/page-header';
import { getJob } from '../../../../lib/agent-hub';

export default async function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const job = await getJob(id);
  if (!job) notFound();

  const salary =
    job.compensation_min != null || job.compensation_max != null
      ? `${job.compensation_min ?? '?'}–${job.compensation_max ?? '?'} ${job.compensation_currency ?? ''} / ${job.compensation_period ?? 'hour'}`
      : null;

  return (
    <>
      <PageHeader
        eyebrow={`${job.company_name} · ${job.work_mode} · ${job.employment_type ?? 'part_time'}`}
        title={job.title_zh ?? job.title_original}
        description={job.title_zh ? `${job.title_original}${salary ? ` · ${salary}` : ''}` : (salary ?? '')}
        action={
          <span
            className={`status-badge ${job.status === 'active' ? 'active' : job.status === 'rejected' ? 'rejected' : 'pending'}`}
          >
            {job.status}
          </span>
        }
      />

      <div className="split-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">岗位详情</h2>
              <p className="panel-subtitle">核心要求与来源信息</p>
            </div>
            <span className={`risk-badge ${job.risk_level}`}>
              {job.risk_level} · {Math.round(job.risk_score * 100)}%
            </span>
          </div>
          <div className="panel-body">
            <dl className="detail-grid">
              <dt>质量分</dt>
              <dd>{Math.round(job.quality_score * 100)}%</dd>

              <dt>可工作地区</dt>
              <dd>{job.countries_allowed.join(', ') || '未指定'}</dd>

              {job.timezone_requirements && job.timezone_requirements.length > 0 && (
                <>
                  <dt>时区要求</dt>
                  <dd>{job.timezone_requirements.join(', ')}</dd>
                </>
              )}

              {job.languages && job.languages.length > 0 && (
                <>
                  <dt>语言要求</dt>
                  <dd>{job.languages.join(', ')}</dd>
                </>
              )}

              {(job.hours_per_week_min != null || job.hours_per_week_max != null) && (
                <>
                  <dt>每周工时</dt>
                  <dd>
                    {job.hours_per_week_min ?? '?'}–{job.hours_per_week_max ?? '?'} 小时
                  </dd>
                </>
              )}

              {job.published_at && (
                <>
                  <dt>发布日期</dt>
                  <dd>{new Date(job.published_at).toLocaleDateString('zh-CN')}</dd>
                </>
              )}

              {job.source_id && (
                <>
                  <dt>来源</dt>
                  <dd className="cell-secondary">{job.source_id}</dd>
                </>
              )}

              {job.canonical_url && (
                <>
                  <dt>原始链接</dt>
                  <dd>
                    <a className="detail-link" href={job.canonical_url} target="_blank" rel="noopener noreferrer">
                      查看原始职位 →
                    </a>
                  </dd>
                </>
              )}
            </dl>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">技能与职位描述</h2>
              <p className="panel-subtitle">岗位标签和完整职责说明</p>
            </div>
          </div>
          <div className="panel-body">
            {job.skills && job.skills.length > 0 && (
              <div className="job-detail-section">
                <h3 className="job-detail-heading">技能</h3>
                <div className="tag-list job-detail-tags">
                  {job.skills.map((skill) => (
                    <span className="tag" key={skill}>
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {job.categories && job.categories.length > 0 && (
              <div className="job-detail-section">
                <h3 className="job-detail-heading">类别</h3>
                <div className="tag-list job-detail-tags">
                  {job.categories.map((cat) => (
                    <span className="tag" key={cat}>
                      {cat}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {(job.description_zh || job.description_original) && (
              <div className="job-detail-section">
                <h3 className="job-detail-heading">职位描述</h3>
                <div className="job-description">{job.description_zh || job.description_original}</div>
              </div>
            )}
          </div>

          {job.risk_signals && job.risk_signals.length > 0 && (
            <div className="panel-body" style={{ borderTop: '1px solid var(--line)' }}>
              <h3 className="job-detail-heading">风险信号</h3>
              <div className="risk-signal-list">
                {job.risk_signals.map((signal) => (
                  <span className="risk-signal-tag" key={signal}>
                    {signal}
                  </span>
                ))}
              </div>
            </div>
          )}

          {job.review_status && job.review_status !== 'pending' && job.review_status !== 'not_required' && (
            <div className="panel-body" style={{ borderTop: '1px solid var(--line)' }}>
              <h3 className="job-detail-heading">审核记录</h3>
              <dl className="detail-grid" style={{ marginTop: 12 }}>
                <dt>审核结果</dt>
                <dd>
                  <span className={`status-badge ${job.review_status === 'approved' ? 'approved' : 'rejected'}`}>
                    {job.review_status === 'approved' ? '已通过' : '已拒绝'}
                  </span>
                </dd>
                {job.reviewed_by && (
                  <>
                    <dt>审核人</dt>
                    <dd>{job.reviewed_by}</dd>
                  </>
                )}
                {job.reviewed_at && (
                  <>
                    <dt>审核时间</dt>
                    <dd>{new Date(job.reviewed_at).toLocaleString('zh-CN')}</dd>
                  </>
                )}
                {job.review_note && (
                  <>
                    <dt>审核备注</dt>
                    <dd>{job.review_note}</dd>
                  </>
                )}
              </dl>
            </div>
          )}

          <JobReviewPanel jobId={job.id} reviewStatus={job.review_status ?? 'not_required'} />
        </section>
      </div>

      <div className="job-detail-footer">
        <Link className="detail-link" href="/jobs">
          ← 返回职位列表
        </Link>
      </div>
    </>
  );
}
