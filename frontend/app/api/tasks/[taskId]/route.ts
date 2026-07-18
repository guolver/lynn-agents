import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== 'false';

export async function GET(_request: NextRequest, { params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;

  if (DEMO_MODE) {
    return Response.json({
      task_id: taskId,
      status: 'SUCCESS',
      result: {
        candidate: {
          id: `cand_demo_${Date.now()}`,
          country: 'CN',
          timezone: 'UTC+08:00',
          email: 'demo@example.com',
          languages: [
            { code: 'zh', level: 'native' },
            { code: 'en', level: 'fluent' },
          ],
          skills: [
            { name: 'Python', level: 4 },
            { name: 'React', level: 3 },
            { name: 'Data Analysis', level: 3 },
          ],
          desired_roles: ['Full Stack Developer', 'Data Analyst'],
          minimum_hourly_rate: { amount: 20, currency: 'USD' },
          availability_hours_per_week: 20,
          allowed_work_modes: ['remote'],
          consent_status: 'opted_in',
          created_at: new Date().toISOString(),
        },
        matches_count: 3,
        parsed_fields: {
          country: 'CN',
          skills: [
            { name: 'Python', level: 4 },
            { name: 'React', level: 3 },
            { name: 'Data Analysis', level: 3 },
          ],
        },
      },
    });
  }

  try {
    const response = await fetch(`${API_URL}/api/v1/tasks/${taskId}/status`, {
      signal: AbortSignal.timeout(8000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json({ detail: 'Agent Hub API 当前不可用。' }, { status: 503 });
  }
}
