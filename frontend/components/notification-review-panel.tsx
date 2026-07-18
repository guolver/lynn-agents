'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

export function NotificationReviewPanel({
  notificationId,
  status,
}: {
  notificationId: string;
  status: string;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  async function handleReview(approved: boolean) {
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch(`/api/notifications/${notificationId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved }),
      });
      const data = await res.json();
      if (res.ok) {
        setResult({ success: true, message: `审核已完成 — ${approved ? '已批准' : '已拒绝'}` });
        router.refresh();
      } else {
        setResult({ success: false, message: data.detail ?? '审核失败' });
      }
    } catch {
      setResult({ success: false, message: '网络错误，请稍后重试' });
    } finally {
      setLoading(false);
    }
  }

  async function handleSend() {
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch('/api/notifications/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notification_id: notificationId }),
      });
      const data = await res.json();
      if (res.ok) {
        setResult({ success: true, message: '通知已发送' });
        router.refresh();
      } else {
        setResult({ success: false, message: data.detail ?? '发送失败' });
      }
    } catch {
      setResult({ success: false, message: '网络错误，请稍后重试' });
    } finally {
      setLoading(false);
    }
  }

  if (status === 'sent') {
    return (
      <div className="panel-body" style={{ borderTop: '1px solid var(--line)' }}>
        <div className="review-result success">该通知已发送完成</div>
      </div>
    );
  }

  if (status === 'rejected') {
    return (
      <div className="panel-body" style={{ borderTop: '1px solid var(--line)' }}>
        <div className="review-result error">该通知已被拒绝</div>
      </div>
    );
  }

  return (
    <div className="panel-body" style={{ borderTop: '1px solid var(--line)' }}>
      <h3 className="job-detail-heading">操作</h3>
      <div className="review-actions">
        {status === 'pending_approval' && (
          <>
            <button className="button" disabled={loading} onClick={() => handleReview(true)}>
              {loading ? '处理中…' : '批准'}
            </button>
            <button className="button danger" disabled={loading} onClick={() => handleReview(false)}>
              {loading ? '处理中…' : '拒绝'}
            </button>
          </>
        )}
        {status === 'approved' && (
          <button className="button" disabled={loading} onClick={handleSend}>
            {loading ? '发送中…' : '发送通知'}
          </button>
        )}
      </div>
      {result && (
        <div className={`review-result ${result.success ? 'success' : 'error'}`}>{result.message}</div>
      )}
    </div>
  );
}
