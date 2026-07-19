import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const packageJson = JSON.parse(
  await readFile(new URL('../package.json', import.meta.url), 'utf8')
);
const composeFile = await readFile(new URL('../../docker-compose.yml', import.meta.url), 'utf8');
const nextConfig = await readFile(new URL('../next.config.ts', import.meta.url), 'utf8');

test('development server binds to all interfaces for Docker port publishing', () => {
  assert.match(packageJson.scripts.dev, /vinext dev --hostname 0\.0\.0\.0/);
});

test('Docker frontend proxies API calls through the host gateway for Workerd', () => {
  assert.match(composeFile, /AGENT_HUB_API_URL=http:\/\/host\.docker\.internal:8000/);
});

test('Vinext exposes the server API URL to Workerd routes', () => {
  assert.match(nextConfig, /AGENT_HUB_API_URL:\s*process\.env\.AGENT_HUB_API_URL/);
});
