import { demoAgent, demoAudits, demoJobs, demoSources } from "./demo-data";
import type { AgentManifest, AuditEvent, Job, Source } from "./types";

const API_URL = process.env.AGENT_HUB_API_URL ?? "http://127.0.0.1:8000";
export const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== "false";

async function readJson<T>(path: string, fallback: T): Promise<T> {
  if (DEMO_MODE) return fallback;

  try {
    const response = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return fallback;
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

export function getAgents(): Promise<AgentManifest[]> {
  return readJson("/platform/v1/agents", [demoAgent]);
}

export function getAgent(agentId: string): Promise<AgentManifest | null> {
  const fallback = agentId === demoAgent.agent_id ? demoAgent : null;
  return readJson(`/platform/v1/agents/${agentId}`, fallback);
}

export function getSources(): Promise<Source[]> {
  return readJson("/api/v1/sources", demoSources);
}

export function getJobs(): Promise<Job[]> {
  return readJson("/api/v1/jobs", demoJobs);
}

export function getAudits(): Promise<AuditEvent[]> {
  return readJson("/api/v1/audit?limit=100", demoAudits);
}
