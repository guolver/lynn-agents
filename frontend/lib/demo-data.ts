import type { AgentManifest, AuditEvent, Job, Source } from "./types";

export const demoAgent: AgentManifest = {
  agent_id: "global-part-time",
  name: "全球兼职职位匹配 Agent",
  version: "0.2.0",
  description: "从已批准 Feed 同步职位，并为主动订阅的候选人生成可审计推荐。",
  tags: ["jobs", "matching", "compliance"],
  owner: "local",
  actions: [
    { name: "list_sources", description: "列出已登记来源", mode: "read", risk_level: "low", requires_idempotency_key: false, input_schema: {} },
    { name: "sync_source", description: "同步一个已批准的结构化职位 Feed", mode: "write", risk_level: "medium", requires_idempotency_key: true, input_schema: { required: ["source_id", "jobs"] } },
    { name: "validate_job", description: "读取确定性风险与质量校验结果", mode: "read", risk_level: "low", requires_idempotency_key: false, input_schema: { required: ["job_id"] } },
    { name: "find_matches", description: "为已订阅候选人执行硬过滤和匹配排序", mode: "write", risk_level: "low", requires_idempotency_key: true, input_schema: { required: ["candidate_id"] } },
    { name: "draft_digest", description: "生成最多五个职位的通知草稿", mode: "write", risk_level: "medium", requires_idempotency_key: true, input_schema: { required: ["candidate_id", "match_ids"] } },
    { name: "request_approval", description: "为高风险动作创建人工审批任务", mode: "write", risk_level: "high", requires_idempotency_key: true, input_schema: { required: ["action", "target_id"] } },
    { name: "send_digest", description: "发送已经批准的通知草稿", mode: "write", risk_level: "high", requires_idempotency_key: true, input_schema: { required: ["notification_id"] } },
  ],
};

export const demoSources: Source[] = [
  { id: "src_001", name: "Remote AI Partner Feed", source_type: "partner_feed", base_url: "https://feed.example.com", review_status: "approved", enabled: true, rate_limit: "60/hour", updated_at: "2026-07-15T09:42:00Z" },
  { id: "src_002", name: "Greenhouse Public ATS", source_type: "ats", base_url: "https://boards.greenhouse.io", review_status: "approved", enabled: true, rate_limit: "30/hour", updated_at: "2026-07-15T09:18:00Z" },
  { id: "src_003", name: "Design Studio Careers", source_type: "company_page", base_url: "https://design.example.org", review_status: "pending", enabled: false, rate_limit: "12/hour", updated_at: "2026-07-15T08:56:00Z" },
  { id: "src_004", name: "APAC Contract RSS", source_type: "rss", base_url: "https://jobs.example.net/rss", review_status: "approved", enabled: true, rate_limit: "24/hour", updated_at: "2026-07-15T08:31:00Z" },
];

export const demoJobs: Job[] = [
  {
    id: "job_001",
    title_original: "AI Evaluation Specialist",
    title_zh: "AI 评估专家",
    company_name: "Northstar Labs",
    description_original: "评估 AI 模型输出，按照书面标准记录问题并提供清晰、可复核的反馈。",
    employment_type: "part_time",
    work_mode: "remote",
    countries_allowed: ["CN", "SG"],
    timezone_requirements: ["UTC+08:00"],
    languages: ["中文", "English"],
    skills: ["AI evaluation", "Quality assurance", "Written communication"],
    categories: ["AI", "Data quality"],
    hours_per_week_min: 10,
    hours_per_week_max: 20,
    risk_level: "low",
    risk_score: 0.08,
    quality_score: 0.94,
    status: "active",
    compensation_min: 18,
    compensation_max: 26,
    compensation_currency: "USD",
    compensation_period: "hour",
    canonical_url: "https://example.com/jobs/ai-evaluation-specialist",
    published_at: "2026-07-15T09:20:00Z",
    source_id: "src_001",
  },
  { id: "job_002", title_original: "Python Data Reviewer", company_name: "Atlas Data Co.", work_mode: "remote", countries_allowed: ["GLOBAL"], risk_level: "low", risk_score: 0.11, quality_score: 0.89, status: "active", compensation_min: 16, compensation_max: 24, compensation_currency: "USD" },
  { id: "job_003", title_original: "Bilingual Content Analyst", company_name: "LinguaWorks", work_mode: "remote", countries_allowed: ["CN", "JP"], risk_level: "medium", risk_score: 0.32, quality_score: 0.73, status: "pending_review", compensation_min: 14, compensation_max: 20, compensation_currency: "USD" },
  { id: "job_004", title_original: "Part-time Product Designer", company_name: "Studio Commons", work_mode: "hybrid", countries_allowed: ["SG"], risk_level: "low", risk_score: 0.06, quality_score: 0.91, status: "active", compensation_min: 28, compensation_max: 40, compensation_currency: "USD" },
  { id: "job_005", title_original: "Remote Task Assistant", company_name: "Unknown Merchant", work_mode: "remote", countries_allowed: ["GLOBAL"], risk_level: "high", risk_score: 0.81, quality_score: 0.28, status: "rejected", compensation_min: 60, compensation_max: 100, compensation_currency: "USD" },
];

export const demoAudits: AuditEvent[] = [
  { id: 71, event: "notification.sent", entity_kind: "notification", entity_id: "ntf_2401", actor: "scheduler", details: { provider: "simulation" }, created_at: "2026-07-15T09:46:00Z" },
  { id: 70, event: "matches.run", entity_kind: "candidate", entity_id: "cand_0188", actor: "scheduler", details: { matched: 12, filtered: 31 }, created_at: "2026-07-15T09:41:00Z" },
  { id: 69, event: "job.reviewed", entity_kind: "job", entity_id: "job_003", actor: "operator@agenthub.local", details: { approved: false }, created_at: "2026-07-15T09:34:00Z" },
  { id: 68, event: "source.synced", entity_kind: "source", entity_id: "src_001", actor: "worker", details: { received: 48 }, created_at: "2026-07-15T09:22:00Z" },
  { id: 67, event: "job.imported", entity_kind: "job", entity_id: "job_0902", actor: "worker", details: { risk: "low" }, created_at: "2026-07-15T09:20:00Z" },
  { id: 66, event: "approval.requested", entity_kind: "approval", entity_id: "apr_084", actor: "operator", details: { action: "send_digest" }, created_at: "2026-07-15T09:08:00Z" },
];

export const dashboardMetrics = [
  { label: "已注册 Agent", value: "01", delta: "平台运行正常", code: "AGT" },
  { label: "活跃职位", value: "1,284", delta: "+48 今日同步", code: "JOB" },
  { label: "候选人", value: "342", delta: "89% 已主动订阅", code: "USR" },
  { label: "待人工审批", value: "16", delta: "4 项高优先级", code: "APR" },
];

export const funnelData = [
  { label: "同步原始职位", value: 1642, width: 100 },
  { label: "通过风险检查", value: 1487, width: 91 },
  { label: "进入匹配池", value: 1284, width: 78 },
  { label: "产生高质匹配", value: 326, width: 42 },
  { label: "推荐已发送", value: 218, width: 29 },
];
