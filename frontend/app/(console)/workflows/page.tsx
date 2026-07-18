import Link from 'next/link';
import { PageHeader } from '../../../components/page-header';
import { getWorkflows } from '../../../lib/agent-hub';
import { demoWorkflows } from '../../../lib/demo-data';

export const metadata = { title: '工作流监控' };

const statusFilters = [
  { label: '全部', value: undefined },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '失败', value: 'failed' },
  { label: '人工审核', value: 'manual_review' },
];

const typeFilters = [
  { label: '全部类型', value: undefined },
  { label: '来源同步', value: 'source_sync' },
  { label: '匹配', value: 'matching' },
  { label: '通知', value: 'notification' },
];

const statusLabel: Record<string, string> = {
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  manual_review: '人工审核',
};

const statusClass: Record<string, string> = {
  running: 'active',
  completed: 'approved',
  failed: 'rejected',
  manual_review: 'pending',
};

const typeLabel: Record<string, string> = {
  source_sync: '来源同步',
  matching: '匹配',
  notification: '通知',
  notification_send: '通知发送',
};

export default async function WorkflowsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; type?: string }>;
}) {
  const { status, type } = await searchParams;
  const workflows = await getWorkflows(status, type);

  return (
    <>
      <PageHeader
        eyebrow="Workflow monitoring"
        title="工作流监控"
        description="追踪所有异步任务的执行状态，包括来源同步、匹配执行和通知发送。失败的任务可在此重试。"
      />
      <div className="toolbar">
        <div className="filter-group">
          {statusFilters.map((f) => {
            const count = f.value
              ? demoWorkflows.filter((w) => w.status === f.value).length
              : demoWorkflows.length;
            const active = status === f.value || (!status && !f.value);
            const href = f.value
              ? `/workflows?status=${f.value}${type ? `&type=${type}` : ''}`
              : `/workflows${type ? `?type=${type}` : ''}`;
            return (
              <Link key={f.label} href={href} className={`filter-chip${active ? ' active' : ''}`}>
                {f.label} {count}
              </Link>
            );
          })}
        </div>
        <div className="filter-group">
          {typeFilters.map((f) => {
            const active = type === f.value || (!type && !f.value);
            const href = f.value
              ? `/workflows?type=${f.value}${status ? `&status=${status}` : ''}`
              : `/workflows${status ? `?status=${status}` : ''}`;
            return (
              <Link key={f.label} href={href} className={`filter-chip${active ? ' active' : ''}`}>
                {f.label}
              </Link>
            );
          })}
        </div>
      </div>
      <section className="panel table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>工作流 ID</th>
              <th>类型</th>
              <th>目标</th>
              <th>状态</th>
              <th>操作人</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            {workflows.map((w) => (
              <tr key={w.id} className="clickable-row">
                <td>
                  <Link href={`/workflows/${w.id}`} className="cell-link">
                    <div className="cell-primary">{w.id}</div>
                    {w.celery_task_id && <div className="cell-secondary">{w.celery_task_id}</div>}
                  </Link>
                </td>
                <td>
                  <span className="tag">{typeLabel[w.workflow_type] ?? w.workflow_type}</span>
                </td>
                <td>{w.target_id}</td>
                <td>
                  <span className={`status-badge ${statusClass[w.status] ?? 'pending'}`}>
                    {statusLabel[w.status] ?? w.status}
                  </span>
                </td>
                <td>{w.actor}</td>
                <td>{w.created_at ? new Date(w.created_at).toLocaleString('zh-CN') : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
