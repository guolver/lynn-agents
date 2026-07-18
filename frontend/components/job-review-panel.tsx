'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

export function JobReviewPanel({ jobId, reviewStatus }: { jobId: string; reviewStatus: string }) {
  const router = useRouter();
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  if (reviewStatus !== 'pending') {
    return null;
  }

  async function submit(approved: boolean) {
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch(`/api/jobs/${jobId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved, note }),
      });
      const data = await res.json();
      if (res.ok) {
        setResult({ success: true, message: `审核已完成 — ${approved ? '通过' : '拒绝'}` });
        router.refresh();
      } else {
        setResult({ success: false, message: data.detail ?? '审核请求失败' });
      }
    } catch {
      setResult({ success: false, message: '网络错误，请稍后重试' });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel-body" style={{ borderTop: '1px solid var(--line)' }}>
      <h3 className="job-detail-heading">审核操作</h3>
      <label className="field-label" style={{ marginTop: 12 }}>
        审核备注
        <textarea
          className="textarea"
          style={{ minHeight: 80 }}
          placeholder="填写审核意见…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={loading}
        />
      </label>
      <div className="review-actions">
        <button className="button" disabled={loading} onClick={() => submit(true)}>
          {loading ? '提交中…' : '通过'}
        </button>
        <button className="button danger" disabled={loading} onClick={() => submit(false)}>
          {loading ? '提交中…' : '拒绝'}
        </button>
      </div>
      {result && (
        <div className={`review-result ${result.success ? 'success' : 'error'}`}>{result.message}</div>
      )}
    </div>
  );
}
