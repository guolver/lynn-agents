import Link from 'next/link';
import { MatchActionPanel } from '../../../components/match-action-panel';
import { PageHeader } from '../../../components/page-header';
import { getCandidateMatches, getCandidates } from '../../../lib/agent-hub';
import { demoMatches } from '../../../lib/demo-data';

export const metadata = { title: '匹配与推荐' };

const dimensionLabels: Record<string, string> = {
  skills: '技能匹配',
  semantic: '语义相似度',
  language: '语言匹配',
  location: '地区与时区',
  compensation: '薪资匹配',
  availability: '时间可用性',
  preference: '用户偏好',
  freshness: '新鲜度与质量',
};

export default async function MatchesPage({
  searchParams,
}: {
  searchParams: Promise<{ candidate_id?: string }>;
}) {
  const { candidate_id } = await searchParams;
  const candidates = await getCandidates();
  const optedInCandidates = candidates.filter((c) => c.consent_status === 'opted_in');

  const matches = candidate_id ? await getCandidateMatches(candidate_id) : [];
  const selectedCandidate = candidate_id ? candidates.find((c) => c.id === candidate_id) : null;

  // Compute funnel from real match data
  const allMatches = candidate_id ? matches : demoMatches;
  const totalJobs = allMatches.length;
  const highQuality = allMatches.filter((m) => m.total_score >= 0.7).length;

  return (
    <>
      <PageHeader
        eyebrow="Matching engine"
        title="先硬过滤，再做可解释排序"
        description="地区、时区、语言、薪资和授权任一不满足都会被排除；进入排序的职位按版本化权重生成匹配理由。"
      />

      {!candidate_id ? (
        <>
          <section className="panel">
            <div className="panel-header">
              <div>
                <h2 className="panel-title">选择候选人</h2>
                <p className="panel-subtitle">选择一个已订阅的候选人查看匹配结果</p>
              </div>
            </div>
            <div className="panel-body">
              {optedInCandidates.length === 0 ? (
                <div className="empty-state">
                  <strong>暂无已订阅候选人</strong>
                  <p>候选人需要先完成订阅 (Opt In) 才能进入匹配流程。</p>
                </div>
              ) : (
                <div className="action-list">
                  {optedInCandidates.map((c) => (
                    <Link href={`/matches?candidate_id=${c.id}`} key={c.id} className="action-row" style={{ textDecoration: 'none' }}>
                      <div>
                        <div className="action-name">{c.id}</div>
                        <div className="action-description">
                          {c.country} · {c.skills.map((s) => s.name).join(', ')}
                        </div>
                      </div>
                      <div className="action-meta">
                        <span className="status-badge approved">已订阅</span>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </section>

          {/* Funnel from demo data */}
          <section className="panel" style={{ marginTop: 16 }}>
            <div className="panel-header">
              <div>
                <h2 className="panel-title">处理转化（总览）</h2>
                <p className="panel-subtitle">所有候选人的匹配概况</p>
              </div>
            </div>
            <div className="panel-body funnel">
              <div className="funnel-row">
                <span>匹配总数</span>
                <div className="funnel-track">
                  <div className="funnel-fill" style={{ width: '100%' }} />
                </div>
                <span className="funnel-value">{demoMatches.length}</span>
              </div>
              <div className="funnel-row">
                <span>高质量匹配</span>
                <div className="funnel-track">
                  <div
                    className="funnel-fill"
                    style={{ width: `${demoMatches.length ? (demoMatches.filter((m) => m.total_score >= 0.7).length / demoMatches.length) * 100 : 0}%` }}
                  />
                </div>
                <span className="funnel-value">{demoMatches.filter((m) => m.total_score >= 0.7).length}</span>
              </div>
            </div>
          </section>
        </>
      ) : (
        <>
          <div className="toolbar">
            <Link className="detail-link" href="/matches">
              ← 返回候选人选择
            </Link>
            {selectedCandidate && (
              <div className="filter-group">
                <span className="filter-chip active">
                  {selectedCandidate.id} · {selectedCandidate.country}
                </span>
              </div>
            )}
          </div>

          {/* Funnel for selected candidate */}
          <section className="panel">
            <div className="panel-header">
              <div>
                <h2 className="panel-title">处理转化</h2>
                <p className="panel-subtitle">{candidate_id} 的匹配链路</p>
              </div>
            </div>
            <div className="panel-body funnel">
              <div className="funnel-row">
                <span>匹配结果</span>
                <div className="funnel-track">
                  <div className="funnel-fill" style={{ width: '100%' }} />
                </div>
                <span className="funnel-value">{totalJobs}</span>
              </div>
              <div className="funnel-row">
                <span>高质量 (≥70%)</span>
                <div className="funnel-track">
                  <div className="funnel-fill" style={{ width: `${totalJobs ? (highQuality / totalJobs) * 100 : 0}%` }} />
                </div>
                <span className="funnel-value">{highQuality}</span>
              </div>
            </div>
          </section>

          {/* Match results table */}
          <MatchActionPanel candidateId={candidate_id} matches={matches} dimensionLabels={dimensionLabels} />
        </>
      )}
    </>
  );
}
