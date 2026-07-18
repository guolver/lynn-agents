import {
  demoAgent,
  demoAudits,
  demoCandidates,
  demoJobs,
  demoMatches,
  demoNotifications,
  demoSkillGraph,
  demoSources,
  demoWorkflows,
} from './demo-data';
import type {
  AgentManifest,
  AuditEvent,
  Candidate,
  Job,
  MatchResult,
  Notification,
  SkillGraphData,
  Source,
  WorkflowRun,
} from './types';

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

export function getJobs(status?: string): Promise<Job[]> {
  const query = status ? `?status=${status}` : '';
  const fallback = status ? demoJobs.filter((j) => j.status === status) : demoJobs;
  return readJson(`/api/v1/jobs${query}`, fallback);
}

export async function getJob(jobId: string): Promise<Job | null> {
  const fallback = demoJobs.find((job) => job.id === jobId) ?? null;
  if (DEMO_MODE) return fallback;

  try {
    const response = await fetch(`${API_URL}/api/v1/jobs/${jobId}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (response.status === 404) return fallback;
    if (!response.ok) return fallback;
    return (await response.json()) as Job;
  } catch {
    return fallback;
  }
}

export function getAudits(): Promise<AuditEvent[]> {
  return readJson("/api/v1/audit?limit=100", demoAudits);
}

export function getSkillGraph(): Promise<SkillGraphData> {
  return readJson('/platform/v1/skill-graph', demoSkillGraph);
}

export function getCandidates(): Promise<Candidate[]> {
  return readJson('/api/v1/candidates', demoCandidates);
}

export async function getCandidate(candidateId: string): Promise<Candidate | null> {
  const fallback = demoCandidates.find((c) => c.id === candidateId) ?? null;
  if (DEMO_MODE) return fallback;

  try {
    const response = await fetch(`${API_URL}/api/v1/candidates/${candidateId}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return fallback;
    return (await response.json()) as Candidate;
  } catch {
    return fallback;
  }
}

export async function getCandidateMatches(candidateId: string): Promise<MatchResult[]> {
  const fallback = demoMatches.filter((m) => m.candidate_id === candidateId);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const raw: any[] = await readJson(`/api/v1/candidates/${candidateId}/matches`, fallback);
  return raw.map((m) => ({
    id: m.id,
    candidate_id: m.candidate_id,
    job_id: m.job_id,
    job_title: m.job_title ?? m.title_original ?? '',
    company_name: m.company_name ?? '',
    total_score: m.total_score ?? m.score ?? 0,
    dimension_scores: {
      skills: m.dimension_scores?.skills ?? m.score_breakdown?.skills ?? 0,
      semantic: m.dimension_scores?.semantic ?? m.score_breakdown?.semantic ?? 0.5,
      language: m.dimension_scores?.language ?? m.score_breakdown?.language ?? 0,
      location: m.dimension_scores?.location ?? m.score_breakdown?.location_timezone ?? 0,
      compensation: m.dimension_scores?.compensation ?? m.score_breakdown?.compensation ?? 0,
      availability: m.dimension_scores?.availability ?? m.score_breakdown?.availability ?? 0.5,
      preference: m.dimension_scores?.preference ?? m.score_breakdown?.preference ?? 0,
      freshness: m.dimension_scores?.freshness ?? m.score_breakdown?.freshness_quality ?? 0,
    },
    reasons: m.reasons ?? [],
  }));
}

export function getNotifications(status?: string): Promise<Notification[]> {
  const query = status ? `?status=${status}` : '';
  const fallback = status ? demoNotifications.filter((n) => n.status === status) : demoNotifications;
  return readJson(`/api/v1/notifications${query}`, fallback);
}

export async function getNotification(notificationId: string): Promise<Notification | null> {
  const fallback = demoNotifications.find((n) => n.id === notificationId) ?? null;
  if (DEMO_MODE) return fallback;

  try {
    const response = await fetch(`${API_URL}/api/v1/notifications/${notificationId}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return fallback;
    return (await response.json()) as Notification;
  } catch {
    return fallback;
  }
}

export function getWorkflows(status?: string, workflowType?: string): Promise<WorkflowRun[]> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (workflowType) params.set('workflow_type', workflowType);
  const query = params.toString() ? `?${params.toString()}` : '';
  const fallback = demoWorkflows.filter(
    (w) => (!status || w.status === status) && (!workflowType || w.workflow_type === workflowType)
  );
  return readJson(`/api/v1/workflows${query}`, fallback);
}

export async function getWorkflow(runId: string): Promise<WorkflowRun | null> {
  const fallback = demoWorkflows.find((w) => w.id === runId) ?? null;
  if (DEMO_MODE) return fallback;

  try {
    const response = await fetch(`${API_URL}/api/v1/workflows/${runId}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return fallback;
    return (await response.json()) as WorkflowRun;
  } catch {
    return fallback;
  }
}
