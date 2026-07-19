import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../components/chat-message.tsx', import.meta.url), 'utf8');

test('chat match cards render optional summaries and deterministic reasons separately', () => {
  assert.match(source, /recommendation_summary\?: string;/);
  assert.match(source, /m\.recommendation_summary &&/);
  assert.match(source, /reasons=\{m\.reasons \?\? \[\]\}/);
});
