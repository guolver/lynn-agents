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
