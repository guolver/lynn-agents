import Link from 'next/link';
import { notFound } from 'next/navigation';
import { NotificationReviewPanel } from '../../../../components/notification-review-panel';
import { PageHeader } from '../../../../components/page-header';
import { getNotification } from '../../../../lib/agent-hub';

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

export default async function NotificationDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const notification = await getNotification(id);
  if (!notification) notFound();

  return (
    <>
      <PageHeader
        eyebrow={`Notification · ${notification.candidate_id}`}
        title={notification.id}
        description={`包含 ${notification.entries.length} 个职位推荐`}
        action={
          <span className={`status-badge ${statusClass[notification.status] ?? 'pending'}`}>
            {statusLabel[notification.status] ?? notification.status}
          </span>
        }
      />

      <div className="split-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">通知内容预览</h2>
              <p className="panel-subtitle">候选人将收到的职位推荐列表</p>
            </div>
          </div>
          <div className="panel-body">
            <div className="action-list">
              {notification.entries.map((entry) => (
                <div className="action-row" key={entry.job_id}>
                  <div>
                    <div className="action-name">{entry.job_title}</div>
                    <div className="action-description">
                      {entry.company_name} · 匹配分 {Math.round(entry.score * 100)}%
                    </div>
                    <div className="tag-list" style={{ marginTop: 6 }}>
                      {entry.reasons.map((r) => (
                        <span className="tag" key={r}>
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="action-meta">
                    <span className="status-badge approved">{Math.round(entry.score * 100)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">通知元数据</h2>
              <p className="panel-subtitle">状态、审批和发送记录</p>
            </div>
          </div>
          <div className="panel-body">
            <dl className="detail-grid">
              <dt>候选人</dt>
              <dd>
                <Link href={`/candidates/${notification.candidate_id}`} className="detail-link">
                  {notification.candidate_id}
                </Link>
              </dd>

              <dt>状态</dt>
              <dd>
                <span className={`status-badge ${statusClass[notification.status] ?? 'pending'}`}>
                  {statusLabel[notification.status] ?? notification.status}
                </span>
              </dd>

              <dt>职位数</dt>
              <dd>{notification.entries.length}</dd>

              {notification.approved_by && (
                <>
                  <dt>审批人</dt>
                  <dd>{notification.approved_by}</dd>
                </>
              )}

              {notification.approved_at && (
                <>
                  <dt>审批时间</dt>
                  <dd>{new Date(notification.approved_at).toLocaleString('zh-CN')}</dd>
                </>
              )}

              {notification.sent_at && (
                <>
                  <dt>发送时间</dt>
                  <dd>{new Date(notification.sent_at).toLocaleString('zh-CN')}</dd>
                </>
              )}

              {notification.created_at && (
                <>
                  <dt>创建时间</dt>
                  <dd>{new Date(notification.created_at).toLocaleString('zh-CN')}</dd>
                </>
              )}
            </dl>
          </div>

          <NotificationReviewPanel notificationId={notification.id} status={notification.status} />
        </section>
      </div>

      <div className="job-detail-footer">
        <Link className="detail-link" href="/notifications">
          ← 返回通知列表
        </Link>
      </div>
    </>
  );
}
