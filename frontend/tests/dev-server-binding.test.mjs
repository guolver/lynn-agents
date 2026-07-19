import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const packageJson = JSON.parse(
  await readFile(new URL('../package.json', import.meta.url), 'utf8')
);

test('development server binds to all interfaces for Docker port publishing', () => {
  assert.match(packageJson.scripts.dev, /vinext dev --hostname 0\.0\.0\.0/);
});
