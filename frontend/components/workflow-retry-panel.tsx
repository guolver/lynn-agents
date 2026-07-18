'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

export function WorkflowRetryPanel({
  workflowId,
  status,
}: {
  workflowId: string;
  status: string;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  if (status !== 'failed' && status !== 'manual_review') {
    return null;
  }

  async function handleRetry() {
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch(`/api/workflows/${workflowId}/retry`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok) {
        setResult({ success: true, message: '重试已触发' });
        router.refresh();
      } else {
        setResult({ success: false, message: data.detail ?? '重试失败' });
      }
    } catch {
      setResult({ success: false, message: '网络错误，请稍后重试' });
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel" style={{ marginTop: 16 }}>
      <div className="panel-body">
        <div className="review-actions">
          <button className="button" disabled={loading} onClick={handleRetry}>
            {loading ? '重试中…' : '重试工作流'}
          </button>
        </div>
        {result && (
          <div className={`review-result ${result.success ? 'success' : 'error'}`}>{result.message}</div>
        )}
      </div>
    </section>
  );
}
