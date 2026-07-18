'use client';

import Link from 'next/link';
import { useState } from 'react';
import type { MatchResult } from '../lib/types';

const dimensionKeys = [
  'skills',
  'semantic',
  'language',
  'location',
  'compensation',
  'availability',
  'preference',
  'freshness',
] as const;

export function MatchActionPanel({
  candidateId,
  matches,
  dimensionLabels,
}: {
  candidateId: string;
  matches: MatchResult[];
  dimensionLabels: Record<string, string>;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  function toggleSelect(matchId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(matchId)) next.delete(matchId);
      else if (next.size < 5) next.add(matchId);
      return next;
    });
  }

  async function handleGenerateNotification() {
    if (selected.size === 0) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch('/api/matches/generate-notification', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_id: candidateId, match_ids: Array.from(selected) }),
      });
      const data = await res.json();
      if (res.ok) {
        setResult({ success: true, message: `通知草稿已生成 — ${data.notification_id ?? data.id ?? ''}` });
        setSelected(new Set());
      } else {
        setResult({ success: false, message: data.detail ?? '生成失败' });
      }
    } catch {
      setResult({ success: false, message: '网络错误，请稍后重试' });
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel" style={{ marginTop: 16 }}>
      <div className="panel-header">
        <div>
          <h2 className="panel-title">匹配结果</h2>
          <p className="panel-subtitle">勾选匹配项生成通知草稿（最多 5 项）</p>
        </div>
        <button className="button" disabled={selected.size === 0 || loading} onClick={handleGenerateNotification}>
          {loading ? '生成中…' : `生成通知草稿 (${selected.size})`}
        </button>
      </div>
      {result && (
        <div style={{ padding: '0 20px' }}>
          <div className={`review-result ${result.success ? 'success' : 'error'}`}>{result.message}</div>
        </div>
      )}
      {matches.length === 0 ? (
        <div className="panel-body">
          <div className="empty-state">
            <strong>暂无匹配结果</strong>
            <p>请先运行匹配，或检查候选人是否已订阅。</p>
          </div>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 40 }}></th>
                <th>职位</th>
                <th>总分</th>
                {dimensionKeys.map((key) => (
                  <th key={key}>{dimensionLabels[key]}</th>
                ))}
                <th>推荐理由</th>
              </tr>
            </thead>
            <tbody>
              {matches.map((match) => (
                <tr key={match.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(match.id)}
                      onChange={() => toggleSelect(match.id)}
                      disabled={!selected.has(match.id) && selected.size >= 5}
                    />
                  </td>
                  <td>
                    <Link href={`/jobs/${match.job_id}`} className="cell-primary detail-link">
                      {match.job_title}
                    </Link>
                    <div className="cell-secondary">{match.company_name}</div>
                  </td>
                  <td>
                    <strong>{Math.round(match.total_score * 100)}%</strong>
                  </td>
                  {dimensionKeys.map((key) => {
                    const score = match.dimension_scores[key];
                    return (
                      <td key={key}>
                        <div className="bar-track" style={{ width: 60 }}>
                          <div className="bar-fill" style={{ width: `${score * 100}%` }} />
                        </div>
                        <span style={{ fontSize: 9, marginLeft: 4 }}>{Math.round(score * 100)}%</span>
                      </td>
                    );
                  })}
                  <td>
                    <div className="tag-list" style={{ marginTop: 0 }}>
                      {match.reasons.map((r) => (
                        <span className="tag" key={r}>
                          {r}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
