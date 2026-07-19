import type { AgentManifest } from './types';

export const demoAgent: AgentManifest = {
  agent_id: 'global-part-time',
  name: '全球兼职职位匹配 Agent',
  version: '0.2.0',
  description: '从已批准 Feed 同步职位，并为主动订阅的候选人生成可审计推荐。',
  tags: ['jobs', 'matching', 'compliance'],
  owner: 'local',
  actions: [
    { name: 'list_sources', description: '列出已登记来源', mode: 'read', risk_level: 'low', requires_idempotency_key: false, input_schema: {} },
    { name: 'sync_source', description: '同步一个已批准的结构化职位 Feed', mode: 'write', risk_level: 'medium', requires_idempotency_key: true, input_schema: { required: ['source_id', 'jobs'] } },
    { name: 'validate_job', description: '读取确定性风险与质量校验结果', mode: 'read', risk_level: 'low', requires_idempotency_key: false, input_schema: { required: ['job_id'] } },
    { name: 'find_matches', description: '为已订阅候选人执行硬过滤和匹配排序', mode: 'write', risk_level: 'low', requires_idempotency_key: true, input_schema: { required: ['candidate_id'] } },
    { name: 'draft_digest', description: '生成最多五个职位的通知草稿', mode: 'write', risk_level: 'medium', requires_idempotency_key: true, input_schema: { required: ['candidate_id', 'match_ids'] } },
    { name: 'request_approval', description: '为高风险动作创建人工审批任务', mode: 'write', risk_level: 'high', requires_idempotency_key: true, input_schema: { required: ['action', 'target_id'] } },
    { name: 'send_digest', description: '发送已经批准的通知草稿', mode: 'write', risk_level: 'high', requires_idempotency_key: true, input_schema: { required: ['notification_id'] } },
  ],
};
