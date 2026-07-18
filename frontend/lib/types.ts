export type ActionDefinition = {
  name: string;
  description: string;
  mode: "read" | "write";
  risk_level: "low" | "medium" | "high";
  requires_idempotency_key: boolean;
  input_schema: { required?: string[] };
};

export type AgentManifest = {
  agent_id: string;
  name: string;
  version: string;
  description: string;
  tags: string[];
  owner: string;
  actions?: ActionDefinition[];
};

export type Source = {
  id: string;
  name: string;
  source_type: string;
  base_url: string;
  review_status: "approved" | "pending" | "rejected";
  enabled: boolean;
  rate_limit: string;
  updated_at: string;
};

export type Job = {
  id: string;
  title_original: string;
  title_zh?: string | null;
  company_name: string;
  description_original?: string;
  description_zh?: string | null;
  employment_type?: string;
  work_mode: string;
  countries_allowed: string[];
  timezone_requirements?: string[];
  languages?: string[];
  skills?: string[];
  categories?: string[];
  hours_per_week_min?: number | null;
  hours_per_week_max?: number | null;
  risk_level: "low" | "medium" | "high";
  risk_score: number;
  quality_score: number;
  status: string;
  compensation_min?: number | null;
  compensation_max?: number | null;
  compensation_currency?: string | null;
  compensation_period?: string | null;
  canonical_url?: string | null;
  application_deadline?: string | null;
  published_at?: string | null;
  source_id?: string;
  created_at?: string;
  review_status?: 'pending' | 'approved' | 'rejected' | 'not_required';
  reviewed_by?: string;
  reviewed_at?: string;
  review_note?: string;
  risk_signals?: string[];
};

export type SkillGraphNode = {
  id: string;
  type: 'category' | 'skill' | 'alias';
};

export type SkillGraphLink = {
  source: string;
  target: string;
  type: 'CHILD_OF' | 'ALIAS_OF';
};

export type SkillGraphData = {
  nodes: SkillGraphNode[];
  links: SkillGraphLink[];
};

export type Language = {
  code: string;
  level: string;
};

export type Skill = {
  name: string;
  level: number;
};

export type Money = {
  amount: number;
  currency: string;
};

export type Candidate = {
  id: string;
  country: string;
  timezone: string;
  email?: string | null;
  languages: Language[];
  skills: Skill[];
  desired_roles: string[];
  minimum_hourly_rate?: Money | null;
  availability_hours_per_week: number;
  allowed_work_modes: string[];
  notification_channels: string[];
  notification_frequency: 'daily' | 'weekly' | 'paused';
  excluded_companies: string[];
  consent_status: 'opted_in' | 'opted_out' | 'not_requested';
  created_at?: string;
};

export type MatchResult = {
  id: string;
  candidate_id: string;
  job_id: string;
  job_title: string;
  company_name: string;
  total_score: number;
  dimension_scores: {
    skills: number;
    semantic: number;
    language: number;
    location: number;
    compensation: number;
    availability: number;
    preference: number;
    freshness: number;
  };
  reasons: string[];
  feedback?: string | null;
  created_at?: string;
};

export type NotificationEntry = {
  job_id: string;
  job_title: string;
  company_name: string;
  score: number;
  reasons: string[];
};

export type Notification = {
  id: string;
  candidate_id: string;
  status: 'pending_approval' | 'approved' | 'rejected' | 'sent';
  entries: NotificationEntry[];
  approved_by?: string | null;
  approved_at?: string | null;
  sent_at?: string | null;
  created_at?: string;
};

export type WorkflowStep = {
  step_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  retry_count: number;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type WorkflowRun = {
  id: string;
  workflow_type: 'source_sync' | 'matching' | 'notification' | 'notification_send';
  target_id: string;
  status: 'running' | 'completed' | 'failed' | 'manual_review';
  actor: string;
  celery_task_id?: string | null;
  steps: WorkflowStep[];
  created_at?: string;
  completed_at?: string | null;
};

export type AuditEvent = {
  id: number;
  event: string;
  entity_kind: string;
  entity_id: string;
  actor: string;
  details: Record<string, unknown>;
  created_at: string;
};
