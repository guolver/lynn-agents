'use client';

import { useEffect, useState } from 'react';

type Source = {
  id: string;
  name: string;
  source_type: string;
  base_url: string;
  review_status: 'approved' | 'pending' | 'rejected' | string;
  enabled: boolean;
  rate_limit?: string;
  retention_policy?: string;
};

type ImportResult = {
  received?: number;
  imported?: number;
  duplicates?: number;
  rejected?: number;
};

type SourceType = 'api' | 'rss' | 'ats' | 'company_page' | 'partner_feed';

type SourceForm = {
  name: string;
  source_type: SourceType;
  base_url: string;
  authorization_basis: string;
  allowed_paths: string;
  prohibited_actions: string;
  rate_limit: string;
  retention_policy: string;
};

const STATUS_LABELS: Record<string, string> = {
  approved: '已批准',
  pending: '待审核',
  rejected: '已拒绝',
};

const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  api: 'API',
  rss: 'RSS',
  ats: 'ATS',
  company_page: '公司页面',
  partner_feed: '合作 Feed',
};

const EMPTY_FORM: SourceForm = {
  name: '',
  source_type: 'api',
  base_url: '',
  authorization_basis: '',
  allowed_paths: '',
  prohibited_actions: '',
  rate_limit: '60/hour',
  retention_policy: '30 days',
};

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function SourcesContent() {
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [importingId, setImportingId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, ImportResult | string>>({});
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<SourceForm>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch('/api/sources');
        if (cancelled) return;
        if (res.status === 401) {
          setError('未登录');
        } else if (res.status === 403) {
          setError('当前账号没有权限查看数据来源（需要 operator/admin 角色）');
        } else if (!res.ok) {
          setError('加载失败');
        } else {
          const data: Source[] = await res.json();
          setSources(data);
        }
      } catch {
        if (!cancelled) setError('API 不可用');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleImport(source: Source) {
    setImportingId(source.id);
    setResults((prev) => ({ ...prev, [source.id]: undefined as unknown as ImportResult }));
    try {
      const res = await fetch(`/api/sources/${source.id}/import`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        setResults((prev) => ({ ...prev, [source.id]: data.detail || `导入失败 (${res.status})` }));
      } else {
        setResults((prev) => ({ ...prev, [source.id]: data }));
      }
    } catch {
      setResults((prev) => ({ ...prev, [source.id]: 'API 不可用' }));
    } finally {
      setImportingId(null);
    }
  }

  function renderResult(result: ImportResult | string | undefined) {
    if (!result) return null;
    if (typeof result === 'string') {
      return <span className="src-result src-result-error">{result}</span>;
    }
    return (
      <span className="src-result">
        抓取 {result.received ?? 0} · 新增 {result.imported ?? 0} · 去重 {result.duplicates ?? 0} · 过滤{' '}
        {result.rejected ?? 0}
      </span>
    );
  }

  function openCreateModal() {
    setForm(EMPTY_FORM);
    setCreateError(null);
    setShowCreate(true);
  }

  function closeCreateModal() {
    if (creating) return;
    setShowCreate(false);
    setCreateError(null);
  }

  function updateForm<K extends keyof SourceForm>(key: K, value: SourceForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      const res = await fetch('/api/sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(),
          source_type: form.source_type,
          base_url: form.base_url.trim(),
          authorization_basis: form.authorization_basis.trim(),
          allowed_paths: splitList(form.allowed_paths),
          prohibited_actions: splitList(form.prohibited_actions),
          rate_limit: form.rate_limit.trim(),
          retention_policy: form.retention_policy.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) {
        setCreateError('未登录');
      } else if (res.status === 403) {
        setCreateError('当前账号没有权限新增来源（需要 operator/admin 角色）');
      } else if (!res.ok) {
        setCreateError(typeof data.detail === 'string' ? data.detail : '创建失败');
      } else {
        setShowCreate(false);
        setForm(EMPTY_FORM);
        const refreshRes = await fetch('/api/sources');
        if (refreshRes.ok) {
          setSources(await refreshRes.json());
        }
      }
    } catch {
      setCreateError('API 不可用');
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="src-layout">
      <div className="src-header">
        <div>
          <h1 className="src-title">数据来源</h1>
          <p className="src-subtitle">职位数据抓取来源的审核状态与手动导入</p>
        </div>
        {!error && (
          <button className="src-add-btn" type="button" onClick={openCreateModal}>
            新增来源
          </button>
        )}
      </div>

      {error ? (
        <div className="src-empty">{error}</div>
      ) : loading ? (
        <div className="src-empty">加载中...</div>
      ) : (
        <div className="src-table-wrap">
          <table className="src-table">
            <thead>
              <tr>
                <th>名称</th>
                <th>类型</th>
                <th>Base URL</th>
                <th>审核状态</th>
                <th>启用</th>
                <th>频率限制</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => {
                const canImport = source.review_status === 'approved' && source.enabled;
                return (
                  <tr key={source.id}>
                    <td>{source.name}</td>
                    <td>{source.source_type}</td>
                    <td className="src-url" title={source.base_url}>
                      {source.base_url}
                    </td>
                    <td>
                      <span className={`src-badge src-badge-${source.review_status}`}>
                        {STATUS_LABELS[source.review_status] ?? source.review_status}
                      </span>
                    </td>
                    <td>{source.enabled ? '是' : '否'}</td>
                    <td>{source.rate_limit ?? '—'}</td>
                    <td>
                      <button
                        className="src-import-btn"
                        disabled={!canImport || importingId === source.id}
                        title={canImport ? '从来源站点抓取并导入职位' : '仅已批准且启用的来源可导入'}
                        onClick={() => handleImport(source)}
                      >
                        {importingId === source.id ? '导入中...' : '导入'}
                      </button>
                      {renderResult(results[source.id])}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <div className="src-modal-backdrop" onClick={closeCreateModal}>
          <div
            className="src-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="src-create-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="src-modal-header">
              <h2 id="src-create-title" className="src-modal-title">
                新增来源
              </h2>
              <button className="src-modal-close" type="button" aria-label="关闭" onClick={closeCreateModal}>
                ×
              </button>
            </div>
            <form className="src-form" onSubmit={handleCreate}>
              <label className="src-field">
                <span className="src-field-label">名称</span>
                <input
                  className="src-input"
                  required
                  maxLength={200}
                  value={form.name}
                  onChange={(e) => updateForm('name', e.target.value)}
                />
              </label>
              <label className="src-field">
                <span className="src-field-label">类型</span>
                <select
                  className="src-input"
                  value={form.source_type}
                  onChange={(e) => updateForm('source_type', e.target.value as SourceType)}
                >
                  {(Object.keys(SOURCE_TYPE_LABELS) as SourceType[]).map((type) => (
                    <option key={type} value={type}>
                      {SOURCE_TYPE_LABELS[type]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="src-field">
                <span className="src-field-label">Base URL</span>
                <input
                  className="src-input"
                  type="url"
                  required
                  placeholder="https://example.com/"
                  value={form.base_url}
                  onChange={(e) => updateForm('base_url', e.target.value)}
                />
              </label>
              <label className="src-field">
                <span className="src-field-label">授权依据</span>
                <input
                  className="src-input"
                  required
                  minLength={3}
                  placeholder="例如：公开 API 文档、合作伙伴协议"
                  value={form.authorization_basis}
                  onChange={(e) => updateForm('authorization_basis', e.target.value)}
                />
              </label>
              <div className="src-form-row">
                <label className="src-field">
                  <span className="src-field-label">频率限制</span>
                  <input
                    className="src-input"
                    required
                    value={form.rate_limit}
                    onChange={(e) => updateForm('rate_limit', e.target.value)}
                  />
                </label>
                <label className="src-field">
                  <span className="src-field-label">保留策略</span>
                  <input
                    className="src-input"
                    required
                    value={form.retention_policy}
                    onChange={(e) => updateForm('retention_policy', e.target.value)}
                  />
                </label>
              </div>
              <label className="src-field">
                <span className="src-field-label">允许路径（可选，逗号分隔）</span>
                <input
                  className="src-input"
                  placeholder="/jobs, /api/v1/jobs"
                  value={form.allowed_paths}
                  onChange={(e) => updateForm('allowed_paths', e.target.value)}
                />
              </label>
              <label className="src-field">
                <span className="src-field-label">禁止操作（可选，逗号分隔）</span>
                <input
                  className="src-input"
                  placeholder="login automation"
                  value={form.prohibited_actions}
                  onChange={(e) => updateForm('prohibited_actions', e.target.value)}
                />
              </label>
              {createError && <div className="src-form-error">{createError}</div>}
              <p className="src-form-hint">新建来源默认为「待审核」状态，审核通过后方可导入。</p>
              <div className="src-form-actions">
                <button className="src-cancel-btn" type="button" disabled={creating} onClick={closeCreateModal}>
                  取消
                </button>
                <button className="src-submit-btn" type="submit" disabled={creating}>
                  {creating ? '提交中...' : '提交审核'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
