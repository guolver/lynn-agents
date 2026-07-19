'use client';

import { useEffect, useState } from 'react';
import { JobDetailDrawer } from '@/components/job-detail-drawer';

type Job = {
  id: string;
  title_original?: string;
  title_zh?: string;
  company_name?: string;
  work_mode?: string;
  skills?: string[];
  compensation_min?: number;
  compensation_max?: number;
  compensation_currency?: string;
  compensation_period?: string;
};

type JobsResponse = {
  total: number;
  offset: number;
  limit: number;
  jobs: Job[];
};

const PAGE_SIZE = 20;
const WORK_MODES = ['', 'remote', 'hybrid', 'onsite'] as const;
const WORK_MODE_LABELS: Record<string, string> = {
  '': '全部',
  remote: 'Remote',
  hybrid: 'Hybrid',
  onsite: 'Onsite',
};

function formatComp(job: Job) {
  if (!job.compensation_max) return null;
  const min = job.compensation_min ? `${job.compensation_min}–` : '';
  const period = job.compensation_period === 'hour' ? '/h' : job.compensation_period === 'month' ? '/mo' : '';
  return `${job.compensation_currency ?? ''} ${min}${job.compensation_max}${period}`.trim();
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [workMode, setWorkMode] = useState('');
  const [page, setPage] = useState(0);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (workMode) params.set('work_mode', workMode);
      params.set('offset', String(page * PAGE_SIZE));
      params.set('limit', String(PAGE_SIZE));
      try {
        const res = await fetch(`/api/jobs?${params}`);
        if (!cancelled && res.ok) {
          const data: JobsResponse = await res.json();
          setJobs(data.jobs);
          setTotal(data.total);
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [query, workMode, page]);

  function handleSearch() {
    setQuery(searchInput);
    setPage(0);
  }

  function handleFilterChange(mode: string) {
    setWorkMode(mode);
    setPage(0);
  }

  return (
    <div className="page-content">
      <div className="page-header">
        <p className="page-eyebrow">Browse</p>
        <h1>岗位大厅</h1>
        <p className="page-description">浏览全部远程岗位，搜索关键词或按工作模式筛选</p>
      </div>

      {/* Search bar */}
      <div className="jobs-search">
        <input
          type="text"
          className="jobs-search-input"
          placeholder="搜索岗位标题或公司名..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button className="jobs-search-btn" onClick={handleSearch}>
          搜索
        </button>
      </div>

      {/* Filter tags */}
      <div className="jobs-filters">
        {WORK_MODES.map((mode) => (
          <button
            key={mode}
            className={`jobs-filter-btn${workMode === mode ? ' active' : ''}`}
            onClick={() => handleFilterChange(mode)}
          >
            {WORK_MODE_LABELS[mode]}
          </button>
        ))}
      </div>

      {/* Stats */}
      <p className="jobs-stats">
        共 {total} 个岗位{query && `，关键词「${query}」`}
        {workMode && `，模式 ${WORK_MODE_LABELS[workMode]}`}
      </p>

      {/* Job grid */}
      {loading ? (
        <div className="jobs-stats" style={{ textAlign: 'center', padding: '48px 0' }}>
          加载中...
        </div>
      ) : jobs.length === 0 ? (
        <div className="jobs-stats" style={{ textAlign: 'center', padding: '48px 0' }}>
          没有找到匹配的岗位
        </div>
      ) : (
        <div className="agent-grid">
          {jobs.map((job) => (
            <div key={job.id} className="job-card" onClick={() => setSelectedJobId(job.id)}>
              <div className="job-card-title">{job.title_zh || job.title_original || 'Unknown'}</div>
              <div className="job-card-company">{job.company_name}</div>
              <div className="job-card-meta">
                {job.work_mode && <span className="tag">{job.work_mode}</span>}
                {formatComp(job) && <span className="tag">{formatComp(job)}</span>}
              </div>
              {job.skills && job.skills.length > 0 && (
                <div className="job-card-skills">
                  {job.skills.slice(0, 3).map((s) => (
                    <span className="job-card-skill-tag" key={s}>
                      {s}
                    </span>
                  ))}
                  {job.skills.length > 3 && (
                    <span className="job-card-skill-tag">+{job.skills.length - 3}</span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="jobs-pagination">
          <button className="jobs-page-btn" disabled={page === 0} onClick={() => setPage(page - 1)}>
            ← 上一页
          </button>
          <span className="jobs-page-info">
            {page + 1} / {totalPages}
          </span>
          <button className="jobs-page-btn" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>
            下一页 →
          </button>
        </div>
      )}

      {/* Job detail drawer */}
      {selectedJobId && <JobDetailDrawer jobId={selectedJobId} onClose={() => setSelectedJobId(null)} />}
    </div>
  );
}
