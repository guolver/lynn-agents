import { NextRequest } from 'next/server';

const API_URL = process.env.AGENT_HUB_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_MODE = process.env.AGENT_HUB_DEMO_MODE !== 'false';

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const file = formData.get('file');

  if (!file || typeof file === 'string') {
    return Response.json({ detail: '请选择 PDF 文件' }, { status: 422 });
  }

  if (file instanceof File && !file.name.toLowerCase().endsWith('.pdf')) {
    return Response.json({ detail: '仅支持 PDF 文件' }, { status: 422 });
  }

  if (DEMO_MODE) {
    return Response.json(
      {
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
          availability_hours_per_week: 20,
          allowed_work_modes: ['remote'],
        },
      },
      { status: 201 }
    );
  }

  try {
    const backendForm = new FormData();
    backendForm.append('file', file);

    const response = await fetch(`${API_URL}/api/v1/candidates/upload-resume`, {
      method: 'POST',
      headers: { 'X-Actor': 'frontend-console' },
      body: backendForm,
    });
    const text = await response.text();
    return new Response(text, {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return Response.json({ detail: `后端不可用: ${message}` }, { status: 503 });
  }
}
