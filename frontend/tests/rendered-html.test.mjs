import assert from "node:assert/strict";
import test from "node:test";

async function render(pathname) {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Agent Hub dashboard", async () => {
  const response = await render("/dashboard");
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /Agent Hub/);
  assert.match(html, /把每个 Agent 的运行状态看清楚/);
  assert.match(html, /职位处理漏斗/);
  assert.match(html, /风险分布/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("server-renders the Agent catalog", async () => {
  const response = await render("/agents");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /统一发现和治理业务 Agent/);
  assert.match(html, /全球兼职职位匹配 Agent/);
});

test("job catalog links to individual job details", async () => {
  const response = await render("/jobs");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /href="\/jobs\/job_001"/);
  assert.match(html, /AI Evaluation Specialist/);
});

test("server-renders an individual job detail", async () => {
  const response = await render("/jobs/job_001");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /岗位详情/);
  assert.match(html, /职位描述/);
  assert.match(html, /评估 AI 模型输出/);
  assert.match(html, /返回职位列表/);
});

test("does not substitute demo data when the live job API is unavailable", async () => {
  const previousDemoMode = process.env.AGENT_HUB_DEMO_MODE;
  const previousApiUrl = process.env.AGENT_HUB_API_URL;
  process.env.AGENT_HUB_DEMO_MODE = "false";
  process.env.AGENT_HUB_API_URL = "http://127.0.0.1:9";

  try {
    const response = await render("/jobs/job_001");
    assert.equal(response.status, 404);
  } finally {
    if (previousDemoMode === undefined) delete process.env.AGENT_HUB_DEMO_MODE;
    else process.env.AGENT_HUB_DEMO_MODE = previousDemoMode;
    if (previousApiUrl === undefined) delete process.env.AGENT_HUB_API_URL;
    else process.env.AGENT_HUB_API_URL = previousApiUrl;
  }
});
