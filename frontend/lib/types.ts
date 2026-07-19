export type ActionDefinition = {
  name: string;
  description: string;
  mode: 'read' | 'write';
  risk_level: 'low' | 'medium' | 'high';
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
