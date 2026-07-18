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

export type AuditEvent = {
  id: number;
  event: string;
  entity_kind: string;
  entity_id: string;
  actor: string;
  details: Record<string, unknown>;
  created_at: string;
};
