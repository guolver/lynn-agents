'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

type UploadResult = {
  success: boolean;
  message: string;
  candidateId?: string;
  matchesCount?: number;
  parsedFields?: {
    country?: string;
    skills?: { name: string; level: number }[];
    desired_roles?: string[];
  };
};

const POLL_INTERVAL = 2000;
const MAX_POLLS = 60; // 2s * 60 = 最多轮询 2 分钟

export function ResumeUploadPanel() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    pollCountRef.current = 0;
    setPolling(false);
  }, []);

  // 清理轮询
  useEffect(() => stopPolling, [stopPolling]);

  function handleResult(data: { candidate?: { id?: string }; matches_count?: number; parsed_fields?: UploadResult['parsedFields'] }) {
    const candidateId = data.candidate?.id;
    const matchesCount = data.matches_count ?? 0;
    const parsedFields = data.parsed_fields;
    setResult({
      success: true,
      message: `简历解析成功 — 创建候选人，匹配到 ${matchesCount} 个职位`,
      candidateId,
      matchesCount,
      parsedFields,
    });
    router.refresh();
  }

  function startPolling(taskId: string) {
    setPolling(true);
    pollCountRef.current = 0;

    pollRef.current = setInterval(async () => {
      pollCountRef.current += 1;
      if (pollCountRef.current > MAX_POLLS) {
        stopPolling();
        setLoading(false);
        setResult({ success: false, message: '解析超时，请稍后在候选人列表查看结果' });
        return;
      }

      try {
        const res = await fetch(`/api/tasks/${taskId}`);
        const data = await res.json();

        if (data.status === 'SUCCESS') {
          stopPolling();
          setLoading(false);
          handleResult(data.result);
        } else if (data.status === 'FAILURE') {
          stopPolling();
          setLoading(false);
          setResult({ success: false, message: data.error ?? '解析失败' });
        }
        // PENDING / STARTED → 继续轮询
      } catch {
        // 网络抖动，继续轮询
      }
    }, POLL_INTERVAL);
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setLoading(true);
    setResult(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/candidates/upload-resume', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (res.status === 202 && data.celery_task_id) {
        // 异步模式：后台任务已提交，开始轮询
        setResult({ success: true, message: '简历已上传，正在后台解析…' });
        startPolling(data.celery_task_id);
      } else if (res.ok) {
        // 同步模式：直接返回结果
        setLoading(false);
        handleResult(data);
      } else {
        setLoading(false);
        setResult({ success: false, message: data.detail ?? '上传失败' });
      }
    } catch {
      setLoading(false);
      setResult({ success: false, message: '网络错误，请稍后重试' });
    } finally {
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  const busy = loading || polling;

  return (
    <div>
      <input ref={fileRef} type="file" accept=".pdf" onChange={handleFileChange} style={{ display: 'none' }} />
      <button className="button" disabled={busy} onClick={() => fileRef.current?.click()}>
        {polling ? '后台解析中…' : loading ? '上传中…' : '上传简历'}
      </button>

      {result && (
        <div style={{ marginTop: '1rem' }}>
          <div className={`review-result ${result.success ? 'success' : 'error'}`}>{result.message}</div>
          {result.success && result.parsedFields && (
            <div className="panel-body" style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
              {result.parsedFields.country && (
                <p>
                  <strong>国家：</strong>
                  {result.parsedFields.country}
                </p>
              )}
              {result.parsedFields.skills && result.parsedFields.skills.length > 0 && (
                <div className="tag-list" style={{ marginTop: '0.25rem' }}>
                  {result.parsedFields.skills.map((s) => (
                    <span className="tag" key={s.name}>
                      {s.name}
                    </span>
                  ))}
                </div>
              )}
              {result.candidateId && (
                <p style={{ marginTop: '0.5rem' }}>
                  <a href={`/candidates/${result.candidateId}`} className="cell-link">
                    查看候选人详情 &rarr;
                  </a>
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
