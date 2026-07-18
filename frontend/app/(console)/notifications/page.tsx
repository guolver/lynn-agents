import Link from 'next/link';
import { PageHeader } from '../../../components/page-header';
import { getNotifications } from '../../../lib/agent-hub';
import { demoNotifications } from '../../../lib/demo-data';

export const metadata = { title: '通知中心' };

const filters = [
  { label: '全部', status: undefined },
  { label: '待审批', status: 'pending_approval' },
  { label: '已批准', status: 'approved' },
  { label: '已发送', status: 'sent' },
  { label: '已拒绝', status: 'rejected' },
];

const statusLabel: Record<string, string> = {
  pending_approval: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  sent: '已发送',
};

const statusClass: Record<string, string> = {
  pending_approval: 'pending',
  approved: 'approved',
  rejected: 'rejected',
  sent: 'active',
};

export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const notifications = await getNotifications(status);

  return (
    <>
      <PageHeader
        eyebrow="Notification center"
        title="通知中心"
        description="管理所有候选人通知的生命周期：生成草稿、人工审批、批准发送。每一步都留有审计记录。"
      />
      <div className="toolbar">
        <input className="search-box" aria-label="搜索通知" placeholder="搜索通知…" />
        <div className="filter-group">
          {filters.map((f) => {
            const count = f.status
              ? demoNotifications.filter((n) => n.status === f.status).length
              : demoNotifications.length;
            const active = status === f.status || (!status && !f.status);
            const href = f.status ? `/notifications?status=${f.status}` : '/notifications';
            return (
              <Link key={href} href={href} className={`filter-chip${active ? ' active' : ''}`}>
                {f.label} {count}
              </Link>
            );
          })}
        </div>
      </div>
      <section className="panel table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>通知 ID</th>
              <th>候选人</th>
              <th>职位数</th>
              <th>状态</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            {notifications.map((n) => (
              <tr key={n.id} className="clickable-row">
                <td>
                  <Link href={`/notifications/${n.id}`} className="cell-link">
                    <div className="cell-primary">{n.id}</div>
                  </Link>
                </td>
                <td>
                  <Link href={`/candidates/${n.candidate_id}`} className="detail-link">
                    {n.candidate_id}
                  </Link>
                </td>
                <td>{n.entries.length}</td>
                <td>
                  <span className={`status-badge ${statusClass[n.status] ?? 'pending'}`}>
                    {statusLabel[n.status] ?? n.status}
                  </span>
                </td>
                <td>{n.created_at ? new Date(n.created_at).toLocaleString('zh-CN') : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
