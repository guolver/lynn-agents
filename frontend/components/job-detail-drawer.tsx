'use client';

import { useEffect, useState } from 'react';

type Job = {
  title_original?: string;
  title_zh?: string;
  company_name?: string;
  description_original?: string;
  description_zh?: string;
  work_mode?: string;
  employment_type?: string;
  compensation_min?: number;
  compensation_max?: number;
  compensation_currency?: string;
  compensation_period?: string;
  countries_allowed?: string[];
  languages?: string[];
  skills?: string[];
  categories?: string[];
  hours_per_week_min?: number;
  hours_per_week_max?: number;
  canonical_url?: string;
  published_at?: string;
};

export function JobDetailDrawer({
  jobId,
  onClose,
  onGenerateKit,
}: {
  jobId: string;
  onClose: () => void;
  onGenerateKit?: (title: string) => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError('');
      setJob(null);
      try {
        const r = await fetch(`/api/jobs/${jobId}`);
        if (!r.ok) throw new Error('Not found');
        const data = await r.json();
        if (!cancelled) {
          setJob(data);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setError('无法加载岗位详情');
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  function formatComp(j: Job) {
    if (!j.compensation_max) return null;
    const min = j.compensation_min ? `${j.compensation_min}–` : '';
    const period = j.compensation_period === 'hour' ? '/h' : j.compensation_period === 'month' ? '/mo' : '';
    return `${j.compensation_currency ?? ''} ${min}${j.compensation_max}${period}`.trim();
  }

  function formatHours(j: Job) {
    if (!j.hours_per_week_min && !j.hours_per_week_max) return null;
    if (j.hours_per_week_min && j.hours_per_week_max) return `${j.hours_per_week_min}–${j.hours_per_week_max} h/week`;
    return `${j.hours_per_week_min ?? j.hours_per_week_max} h/week`;
  }

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="job-drawer">
        <div className="drawer-header">
          <span className="drawer-title">{loading ? '加载中...' : '岗位详情'}</span>
          <button className="drawer-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="job-drawer-body">
          {loading && <div className="job-drawer-placeholder">Loading...</div>}
          {error && <div className="job-drawer-placeholder">{error}</div>}
          {job && (
            <>
              <h2 className="job-drawer-title">{job.title_zh || job.title_original || 'Unknown'}</h2>
              {job.company_name && <div className="job-drawer-company">{job.company_name}</div>}

              <div className="job-drawer-tags">
                {job.work_mode && <span className="tag">{job.work_mode}</span>}
                {job.employment_type && <span className="tag">{job.employment_type}</span>}
                {formatComp(job) && <span className="tag">{formatComp(job)}</span>}
                {formatHours(job) && <span className="tag">{formatHours(job)}</span>}
              </div>

              {job.skills && job.skills.length > 0 && (
                <div className="job-drawer-section">
                  <h3 className="job-drawer-label">Skills</h3>
                  <div className="job-drawer-tags">
                    {job.skills.map((s) => (
                      <span className="tag" key={s}>
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {job.languages && job.languages.length > 0 && (
                <div className="job-drawer-section">
                  <h3 className="job-drawer-label">Languages</h3>
                  <div className="job-drawer-tags">
                    {job.languages.map((l) => (
                      <span className="tag" key={l}>
                        {l}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {job.countries_allowed && job.countries_allowed.length > 0 && (
                <div className="job-drawer-section">
                  <h3 className="job-drawer-label">Regions</h3>
                  <div className="job-drawer-tags">
                    {job.countries_allowed.map((c) => (
                      <span className="tag" key={c}>
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {(job.description_zh || job.description_original) && (
                <div className="job-drawer-section">
                  <h3 className="job-drawer-label">Description</h3>
                  <div
                    className="job-drawer-desc"
                    dangerouslySetInnerHTML={{ __html: job.description_zh || job.description_original || '' }}
                  />
                </div>
              )}

              {onGenerateKit && (
                <div className="job-drawer-section">
                  <button
                    className="match-card-kit-btn"
                    onClick={() => onGenerateKit(job.title_zh || job.title_original || '')}
                  >
                    ✍️ 生成申请材料
                  </button>
                </div>
              )}

              {job.canonical_url && (
                <div className="job-drawer-section">
                  <a
                    href={job.canonical_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="job-drawer-apply"
                  >
                    View Original Posting →
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
}
