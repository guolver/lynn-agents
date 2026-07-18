import Link from 'next/link';
import { notFound } from 'next/navigation';
import { WorkflowRetryPanel } from '../../../../components/workflow-retry-panel';
import { PageHeader } from '../../../../components/page-header';
import { getWorkflow } from '../../../../lib/agent-hub';

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

const stepDotColor: Record<string, string> = {
  completed: 'var(--green)',
  running: 'var(--blue)',
  failed: 'var(--red)',
  pending: 'var(--line)',
  skipped: '#999',
};

export default async function WorkflowDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const workflow = await getWorkflow(id);
  if (!workflow) notFound();

  return (
    <>
      <PageHeader
        eyebrow={`Workflow · ${typeLabel[workflow.workflow_type] ?? workflow.workflow_type}`}
        title={workflow.id}
        description={`目标: ${workflow.target_id}`}
        action={
          <span className={`status-badge ${statusClass[workflow.status] ?? 'pending'}`}>
            {statusLabel[workflow.status] ?? workflow.status}
          </span>
        }
      />

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">工作流详情</h2>
            <p className="panel-subtitle">基本信息与执行上下文</p>
          </div>
        </div>
        <div className="panel-body">
          <dl className="detail-grid">
            <dt>类型</dt>
            <dd>
              <span className="tag">{typeLabel[workflow.workflow_type] ?? workflow.workflow_type}</span>
            </dd>

            <dt>目标 ID</dt>
            <dd>{workflow.target_id}</dd>

            <dt>状态</dt>
            <dd>
              <span className={`status-badge ${statusClass[workflow.status] ?? 'pending'}`}>
                {statusLabel[workflow.status] ?? workflow.status}
              </span>
            </dd>

            <dt>操作人</dt>
            <dd>{workflow.actor}</dd>

            {workflow.celery_task_id && (
              <>
                <dt>Celery Task ID</dt>
                <dd style={{ fontFamily: 'var(--font-geist-mono)', fontSize: 10 }}>{workflow.celery_task_id}</dd>
              </>
            )}

            {workflow.created_at && (
              <>
                <dt>创建时间</dt>
                <dd>{new Date(workflow.created_at).toLocaleString('zh-CN')}</dd>
              </>
            )}

            {workflow.completed_at && (
              <>
                <dt>完成时间</dt>
                <dd>{new Date(workflow.completed_at).toLocaleString('zh-CN')}</dd>
              </>
            )}
          </dl>
        </div>
      </section>

      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-header">
          <div>
            <h2 className="panel-title">执行步骤</h2>
            <p className="panel-subtitle">任务执行时间线</p>
          </div>
        </div>
        <div className="panel-body">
          <div className="timeline">
            {workflow.steps.map((step, i) => (
              <div className="timeline-item" key={i}>
                <div className="timeline-time">
                  {step.started_at
                    ? new Date(step.started_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                    : '—'}
                </div>
                <div className="timeline-axis">
                  <div className="timeline-dot" style={{ background: stepDotColor[step.status] ?? 'var(--line)' }} />
                </div>
                <div>
                  <div className="timeline-title">
                    {step.step_name}
                    <span className={`status-badge ${statusClass[step.status] ?? 'pending'}`} style={{ marginLeft: 8 }}>
                      {step.status}
                    </span>
                  </div>
                  <div className="timeline-detail">
                    {step.retry_count > 0 && `重试 ${step.retry_count} 次`}
                    {step.error && (
                      <div style={{ color: 'var(--red)', marginTop: 4 }}>{step.error}</div>
                    )}
                  </div>
                </div>
                <div className="timeline-actor">
                  {step.completed_at
                    ? new Date(step.completed_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                    : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <WorkflowRetryPanel workflowId={workflow.id} status={workflow.status} />

      <div className="job-detail-footer">
        <Link className="detail-link" href="/workflows">
          ← 返回工作流列表
        </Link>
      </div>
    </>
  );
}
