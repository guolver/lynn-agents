'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

export function CandidateActionPanel({
  candidateId,
  consentStatus,
}: {
  candidateId: string;
  consentStatus: string;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState<string | null>(null);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  async function pollTaskStatus(taskId: string) {
    let polls = 0;
    const maxPolls = 60;

    pollingRef.current = setInterval(async () => {
      polls++;
      if (polls > maxPolls) {
        stopPolling();
        setLoading(null);
        setResult({ success: false, message: '匹配超时，请稍后查看结果' });
        return;
      }

      try {
        const res = await fetch(`/api/tasks/${taskId}`);
        const data = await res.json();

        if (data.status === 'SUCCESS') {
          stopPolling();
          const matchResult = data.result;
          const count = matchResult?.matches?.length ?? matchResult?.matched ?? '?';
          setLoading(null);
          setResult({ success: true, message: `匹配完成 — 找到 ${count} 个匹配结果` });
          router.refresh();
        } else if (data.status === 'FAILURE') {
          stopPolling();
          setLoading(null);
          setResult({ success: false, message: `匹配失败: ${data.error ?? '未知错误'}` });
        }
        // PENDING / STARTED — keep polling
      } catch {
        // Network error during poll, keep trying
      }
    }, 2000);
  }

  async function handleConsent(optedIn: boolean) {
    setLoading('consent');
    setResult(null);
    try {
      const res = await fetch(`/api/candidates/${candidateId}/consent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ opted_in: optedIn }),
      });
      const data = await res.json();
      if (res.ok) {
        setResult({ success: true, message: `授权状态已更新 — ${optedIn ? '已订阅' : '已退出'}` });
        router.refresh();
      } else {
        setResult({ success: false, message: data.detail ?? '操作失败' });
      }
    } catch {
      setResult({ success: false, message: '网络错误，请稍后重试' });
    } finally {
      setLoading(null);
    }
  }

  async function handleRunMatches() {
    setLoading('match');
    setResult(null);
    try {
      const res = await fetch(`/api/candidates/${candidateId}/run-matches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();

      if (res.status === 202 && data.celery_task_id) {
        // Async task dispatched — start polling
        setResult({ success: true, message: '匹配任务已提交，正在后台处理…' });
        pollTaskStatus(data.celery_task_id);
      } else if (res.ok) {
        // Sync result
        const count = data.matched ?? data.matches?.length ?? '?';
        setLoading(null);
        setResult({ success: true, message: `匹配完成 — 找到 ${count} 个匹配结果` });
        router.refresh();
      } else {
        setLoading(null);
        setResult({ success: false, message: data.detail ?? '匹配请求失败' });
      }
    } catch {
      setLoading(null);
      setResult({ success: false, message: '网络错误，请稍后重试' });
    }
  }

  async function handleDelete() {
    if (!confirm('确定要删除该候选人吗？此操作不可撤销。')) return;
    setLoading('delete');
    setResult(null);
    try {
      const res = await fetch(`/api/candidates/${candidateId}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (res.ok) {
        setResult({ success: true, message: '候选人已删除' });
        router.push('/candidates');
      } else {
        setResult({ success: false, message: data.detail ?? '删除失败' });
      }
    } catch {
      setResult({ success: false, message: '网络错误，请稍后重试' });
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="panel-body" style={{ borderTop: '1px solid var(--line)' }}>
      <h3 className="job-detail-heading">操作</h3>
      <div className="review-actions">
        {consentStatus !== 'opted_in' ? (
          <button className="button" disabled={loading !== null} onClick={() => handleConsent(true)}>
            {loading === 'consent' ? '处理中…' : '订阅 (Opt In)'}
          </button>
        ) : (
          <button className="button secondary" disabled={loading !== null} onClick={() => handleConsent(false)}>
            {loading === 'consent' ? '处理中…' : '退订 (Opt Out)'}
          </button>
        )}
        <button className="button secondary" disabled={loading !== null || consentStatus !== 'opted_in'} onClick={handleRunMatches}>
          {loading === 'match' ? '匹配中…' : '运行匹配'}
        </button>
        <button className="button danger" disabled={loading !== null} onClick={handleDelete}>
          {loading === 'delete' ? '删除中…' : '删除候选人'}
        </button>
      </div>
      {result && (
        <div className={`review-result ${result.success ? 'success' : 'error'}`}>{result.message}</div>
      )}
    </div>
  );
}
