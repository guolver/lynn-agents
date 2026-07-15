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
  company_name: string;
  work_mode: string;
  countries_allowed: string[];
  risk_level: "low" | "medium" | "high";
  risk_score: number;
  quality_score: number;
  status: string;
  compensation_min?: number;
  compensation_max?: number;
  compensation_currency?: string;
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
