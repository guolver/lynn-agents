'use client';

import { useEffect, useState, useCallback } from 'react';

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
  published_at?: string;
};

type JobDetail = Job & {
  description_original?: string;
  description_zh?: string;
  employment_type?: string;
  countries_allowed?: string[];
  languages?: string[];
  categories?: string[];
  hours_per_week_min?: number;
  hours_per_week_max?: number;
  canonical_url?: string;
};

type JobsResponse = {
  total: number;
  offset: number;
  limit: number;
  jobs: Job[];
};

type Lang = 'original' | 'zh' | 'bilingual';

const PAGE_SIZE = 25;
const WORK_MODES = ['', 'remote', 'hybrid', 'onsite'] as const;
const WORK_MODE_LABELS: Record<string, string> = {
  '': '全部',
  remote: 'Remote',
  hybrid: 'Hybrid',
  onsite: 'Onsite',
};
const LANG_LABELS: Record<Lang, string> = {
  original: '原文',
  zh: '中文',
  bilingual: '双语',
};

function formatComp(job: Job) {
  if (!job.compensation_max) return null;
  const min = job.compensation_min ? `${job.compensation_min}–` : '';
  const period = job.compensation_period === 'hour' ? '/h' : job.compensation_period === 'month' ? '/mo' : '';
  return `${job.compensation_currency ?? ''} ${min}${job.compensation_max}${period}`.trim();
}

function timeAgo(dateStr?: string) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86400000);
  if (days < 1) return '今天';
  if (days === 1) return '1 天前';
  if (days < 30) return `${days} 天前`;
  return `${Math.floor(days / 30)} 个月前`;
}

function formatHours(j: JobDetail) {
  if (!j.hours_per_week_min && !j.hours_per_week_max) return null;
  if (j.hours_per_week_min && j.hours_per_week_max) return `${j.hours_per_week_min}–${j.hours_per_week_max} h/week`;
  return `${j.hours_per_week_min ?? j.hours_per_week_max} h/week`;
}

function getInitialLang(): Lang {
  if (typeof window === 'undefined') return 'original';
  return (localStorage.getItem('jobs-lang') as Lang) || 'original';
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
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [lang, setLang] = useState<Lang>('original');
  const [translating, setTranslating] = useState(false);

  // Hydrate lang from localStorage after mount
  useEffect(() => {
    setLang(getInitialLang());
  }, []);

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
          // Auto-select first job if none selected
          if (data.jobs.length > 0 && !selectedJobId) {
            setSelectedJobId(data.jobs[0].id);
          }
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

  // Load detail when selection changes
  useEffect(() => {
    if (!selectedJobId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    async function loadDetail() {
      setDetailLoading(true);
      try {
        const res = await fetch(`/api/jobs/${selectedJobId}`);
        if (!cancelled && res.ok) {
          const loaded: JobDetail = await res.json();
          setDetail(loaded);
          // Auto-translate if lang is non-original and no cached translation
          const currentLang = (localStorage.getItem('jobs-lang') as Lang) || 'original';
          if (currentLang !== 'original' && !loaded.title_zh) {
            translateJob(selectedJobId, loaded);
          }
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    }
    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedJobId]);

  async function translateJob(jobId: string, job: JobDetail) {
    if (job.title_zh && job.description_zh) return;
    setTranslating(true);
    try {
      const res = await fetch(`/api/jobs/${jobId}/translate`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setDetail((prev) =>
          prev && prev.id === jobId ? { ...prev, title_zh: data.title_zh, description_zh: data.description_zh } : prev,
        );
      }
    } catch {
      // ignore
    } finally {
      setTranslating(false);
    }
  }

  function handleLangChange(newLang: Lang) {
    setLang(newLang);
    localStorage.setItem('jobs-lang', newLang);
    if (newLang !== 'original' && detail && selectedJobId && !detail.title_zh) {
      translateJob(selectedJobId, detail);
    }
  }

  function handleSearch() {
    setQuery(searchInput);
    setPage(0);
    setSelectedJobId(null);
  }

  function handleFilterChange(mode: string) {
    setWorkMode(mode);
    setPage(0);
    setSelectedJobId(null);
  }

  function renderTitle(d: JobDetail) {
    const original = d.title_original || 'Unknown';
    const zh = d.title_zh;
    if (lang === 'zh' && zh) return zh;
    if (lang === 'bilingual' && zh) {
      return (
        <>
          <span>{zh}</span>
          <span className="jh-bilingual-sub">{original}</span>
        </>
      );
    }
    return original;
  }

  function renderDescription(d: JobDetail) {
    const original = d.description_original || '';
    const zh = d.description_zh || '';
    if (lang === 'zh' && zh) return zh;
    if (lang === 'bilingual' && zh) {
      return `${zh}<hr class="jh-bilingual-hr"/>${original}`;
    }
    return original;
  }

  return (
    <div className="jh-layout">
      {/* Left panel: search + list */}
      <div className="jh-left">
        {/* Search bar */}
        <div className="jh-toolbar">
          <div className="jh-search">
            <svg className="jh-search-icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
              <path
                fillRule="evenodd"
                d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.45 4.39l3.58 3.58a.75.75 0 11-1.06 1.06l-3.58-3.58A7 7 0 012 9z"
                clipRule="evenodd"
              />
            </svg>
            <input
              type="text"
              className="jh-search-input"
              placeholder="搜索岗位或公司..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          {/* Filter tags */}
          <div className="jh-filters">
            {WORK_MODES.map((mode) => (
              <button
                key={mode}
                className={`jh-filter-btn${workMode === mode ? ' active' : ''}`}
                onClick={() => handleFilterChange(mode)}
              >
                {WORK_MODE_LABELS[mode]}
              </button>
            ))}
          </div>
        </div>

        {/* Results header */}
        <div className="jh-results-header">
          <span className="jh-results-count">
            {total.toLocaleString()} 个岗位
            {query && <span className="jh-results-query"> · &ldquo;{query}&rdquo;</span>}
          </span>
          <span className="jh-page-indicator">
            {page + 1}/{totalPages}
          </span>
        </div>

        {/* Job list */}
        <div className="jh-list">
          {loading ? (
            <div className="jh-empty">加载中...</div>
          ) : jobs.length === 0 ? (
            <div className="jh-empty">没有找到匹配的岗位</div>
          ) : (
            jobs.map((job) => (
              <div
                key={job.id}
                className={`jh-item${selectedJobId === job.id ? ' active' : ''}`}
                onClick={() => setSelectedJobId(job.id)}
              >
                <div className="jh-item-main">
                  <div className="jh-item-title">{job.title_zh || job.title_original || 'Unknown'}</div>
                  <div className="jh-item-company">{job.company_name}</div>
                  <div className="jh-item-meta">
                    {job.work_mode && <span className="jh-badge">{job.work_mode}</span>}
                    {formatComp(job) && <span className="jh-badge comp">{formatComp(job)}</span>}
                    {job.skills &&
                      job.skills.slice(0, 2).map((s) => (
                        <span className="jh-badge skill" key={s}>
                          {s}
                        </span>
                      ))}
                  </div>
                </div>
                {job.published_at && <div className="jh-item-time">{timeAgo(job.published_at)}</div>}
              </div>
            ))
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="jh-pagination">
            <button className="jh-page-btn" disabled={page === 0} onClick={() => setPage(page - 1)}>
              ‹
            </button>
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              let p: number;
              if (totalPages <= 7) {
                p = i;
              } else if (page < 4) {
                p = i;
              } else if (page > totalPages - 5) {
                p = totalPages - 7 + i;
              } else {
                p = page - 3 + i;
              }
              return (
                <button
                  key={p}
                  className={`jh-page-num${page === p ? ' active' : ''}`}
                  onClick={() => setPage(p)}
                >
                  {p + 1}
                </button>
              );
            })}
            <button className="jh-page-btn" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>
              ›
            </button>
          </div>
        )}
      </div>

      {/* Right panel: detail */}
      <div className="jh-right">
        {!selectedJobId ? (
          <div className="jh-detail-empty">
            <p>选择左侧岗位查看详情</p>
          </div>
        ) : detailLoading ? (
          <div className="jh-detail-empty">
            <p>加载中...</p>
          </div>
        ) : detail ? (
          <div className="jh-detail">
            <div className="jh-detail-header">
              {/* Language toggle */}
              <div className="jh-lang-toggle">
                {(['original', 'zh', 'bilingual'] as Lang[]).map((l) => (
                  <button
                    key={l}
                    className={`jh-lang-btn${lang === l ? ' active' : ''}`}
                    onClick={() => handleLangChange(l)}
                  >
                    {LANG_LABELS[l]}
                  </button>
                ))}
              </div>

              <h1 className="jh-detail-title">
                {translating && lang !== 'original' ? '翻译中...' : renderTitle(detail)}
              </h1>
              <div className="jh-detail-company">{detail.company_name}</div>
              <div className="jh-detail-tags">
                {detail.work_mode && <span className="jh-badge">{detail.work_mode}</span>}
                {detail.employment_type && <span className="jh-badge">{detail.employment_type}</span>}
                {formatComp(detail) && <span className="jh-badge comp">{formatComp(detail)}</span>}
                {formatHours(detail) && <span className="jh-badge">{formatHours(detail)}</span>}
              </div>
              {detail.canonical_url && (
                <a href={detail.canonical_url} target="_blank" rel="noopener noreferrer" className="jh-apply-btn">
                  查看原文 & 申请 →
                </a>
              )}
            </div>

            {detail.skills && detail.skills.length > 0 && (
              <div className="jh-detail-section">
                <h3 className="jh-detail-label">技能要求</h3>
                <div className="jh-detail-tags">
                  {detail.skills.map((s) => (
                    <span className="jh-badge skill" key={s}>
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {detail.languages && detail.languages.length > 0 && (
              <div className="jh-detail-section">
                <h3 className="jh-detail-label">语言</h3>
                <div className="jh-detail-tags">
                  {detail.languages.map((l) => (
                    <span className="jh-badge" key={l}>
                      {l}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {detail.countries_allowed && detail.countries_allowed.length > 0 && (
              <div className="jh-detail-section">
                <h3 className="jh-detail-label">地区</h3>
                <div className="jh-detail-tags">
                  {detail.countries_allowed.map((c) => (
                    <span className="jh-badge" key={c}>
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {(detail.description_zh || detail.description_original) && (
              <div className="jh-detail-section">
                <h3 className="jh-detail-label">职位描述</h3>
                {translating && lang !== 'original' ? (
                  <div className="jh-translating">翻译中...</div>
                ) : (
                  <div
                    className="jh-detail-desc"
                    dangerouslySetInnerHTML={{ __html: renderDescription(detail) }}
                  />
                )}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
