import Link from 'next/link';
import { notFound } from 'next/navigation';
import { CandidateActionPanel } from '../../../../components/candidate-action-panel';
import { PageHeader } from '../../../../components/page-header';
import { getCandidate, getCandidateMatches } from '../../../../lib/agent-hub';

const consentLabel: Record<string, string> = {
  opted_in: '已订阅',
  opted_out: '已退出',
  not_requested: '未请求',
};

export default async function CandidateDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const candidate = await getCandidate(id);
  if (!candidate) notFound();

  const matches = await getCandidateMatches(id);

  return (
    <>
      <PageHeader
        eyebrow={`${candidate.country} · ${candidate.timezone}`}
        title={candidate.id}
        description={candidate.email ?? '未提供邮箱'}
        action={
          <span
            className={`status-badge ${candidate.consent_status === 'opted_in' ? 'approved' : candidate.consent_status === 'opted_out' ? 'rejected' : 'pending'}`}
          >
            {consentLabel[candidate.consent_status] ?? candidate.consent_status}
          </span>
        }
      />

      <div className="split-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">候选人详情</h2>
              <p className="panel-subtitle">基本信息与匹配偏好</p>
            </div>
          </div>
          <div className="panel-body">
            <dl className="detail-grid">
              <dt>国家</dt>
              <dd>{candidate.country}</dd>

              <dt>时区</dt>
              <dd>{candidate.timezone}</dd>

              <dt>可用工时</dt>
              <dd>{candidate.availability_hours_per_week}h/week</dd>

              <dt>工作模式</dt>
              <dd>{(candidate.allowed_work_modes ?? []).join(', ') || '—'}</dd>

              {candidate.minimum_hourly_rate && (
                <>
                  <dt>最低时薪</dt>
                  <dd>
                    {candidate.minimum_hourly_rate.amount} {candidate.minimum_hourly_rate.currency}
                  </dd>
                </>
              )}

              <dt>通知频率</dt>
              <dd>{candidate.notification_frequency}</dd>

              <dt>通知渠道</dt>
              <dd>{(candidate.notification_channels ?? []).join(', ') || '—'}</dd>

              {(candidate.excluded_companies ?? []).length > 0 && (
                <>
                  <dt>排除公司</dt>
                  <dd>{(candidate.excluded_companies ?? []).join(', ')}</dd>
                </>
              )}

              {candidate.created_at && (
                <>
                  <dt>创建时间</dt>
                  <dd>{new Date(candidate.created_at).toLocaleString('zh-CN')}</dd>
                </>
              )}
            </dl>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">技能与偏好</h2>
              <p className="panel-subtitle">候选人技能画像与期望角色</p>
            </div>
          </div>
          <div className="panel-body">
            {(candidate.skills ?? []).length > 0 && (
              <div className="job-detail-section">
                <h3 className="job-detail-heading">技能</h3>
                <div className="tag-list job-detail-tags">
                  {(candidate.skills ?? []).map((s) => (
                    <span className="tag" key={s.name}>
                      {s.name} (Lv.{s.level})
                    </span>
                  ))}
                </div>
              </div>
            )}

            {(candidate.desired_roles ?? []).length > 0 && (
              <div className="job-detail-section">
                <h3 className="job-detail-heading">期望角色</h3>
                <div className="tag-list job-detail-tags">
                  {(candidate.desired_roles ?? []).map((role) => (
                    <span className="tag" key={role}>
                      {role}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {(candidate.languages ?? []).length > 0 && (
              <div className="job-detail-section">
                <h3 className="job-detail-heading">语言能力</h3>
                <div className="tag-list job-detail-tags">
                  {(candidate.languages ?? []).map((lang) => (
                    <span className="tag" key={lang.code}>
                      {lang.code} · {lang.level}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <CandidateActionPanel candidateId={candidate.id} consentStatus={candidate.consent_status} />
        </section>
      </div>

      {/* Existing match results */}
      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-header">
          <div>
            <h2 className="panel-title">匹配结果</h2>
            <p className="panel-subtitle">
              {matches.length > 0
                ? `共 ${matches.length} 个匹配，${matches.filter((m) => m.total_score >= 0.7).length} 个高质量 (≥70%)`
                : '暂无匹配结果'}
            </p>
          </div>
          {matches.length > 0 && (
            <Link className="button secondary" href={`/matches?candidate_id=${id}`}>
              查看详情
            </Link>
          )}
        </div>
        {matches.length === 0 ? (
          <div className="panel-body">
            <div className="empty-state">
              <strong>暂无匹配结果</strong>
              <p>点击右侧「运行匹配」按钮开始匹配。</p>
            </div>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>职位</th>
                  <th>公司</th>
                  <th>总分</th>
                  <th>推荐理由</th>
                </tr>
              </thead>
              <tbody>
                {matches
                  .sort((a, b) => b.total_score - a.total_score)
                  .slice(0, 10)
                  .map((match) => (
                    <tr key={match.id}>
                      <td>
                        <Link href={`/jobs/${match.job_id}`} className="cell-primary detail-link">
                          {match.job_title}
                        </Link>
                      </td>
                      <td>{match.company_name}</td>
                      <td>
                        <strong>{Math.round(match.total_score * 100)}%</strong>
                      </td>
                      <td>
                        <div className="tag-list" style={{ marginTop: 0 }}>
                          {match.reasons.slice(0, 3).map((r) => (
                            <span className="tag" key={r}>
                              {r}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {matches.length > 10 && (
              <div className="panel-body" style={{ textAlign: 'center', padding: '12px 0' }}>
                <Link className="detail-link" href={`/matches?candidate_id=${id}`}>
                  查看全部 {matches.length} 个匹配 →
                </Link>
              </div>
            )}
          </div>
        )}
      </section>

      <div className="job-detail-footer">
        <Link className="detail-link" href="/candidates">
          ← 返回候选人列表
        </Link>
      </div>
    </>
  );
}
