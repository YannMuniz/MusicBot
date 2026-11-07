import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeReliability } from './reliability.js';

test('média ponderada pela duração e faixas', () => {
  const r = summarizeReliability([
    { start: 0, end: 3, p: 0.9 },
    { start: 3, end: 4, p: 0.3, ambiguous: true },
  ]);
  assert.ok(Math.abs(r.mean - (0.9 * 3 + 0.3) / 4) < 1e-9);
  assert.equal(r.high, 0.75);
  assert.equal(r.low, 0.25);
  assert.equal(r.ambiguous, 0.25);
});

test('ignora pausas e trechos sem p; vazio devolve null', () => {
  assert.equal(summarizeReliability([{ start: 0, end: 2, kind: 'rest', p: 0.9 }, { start: 2, end: 3 }]), null);
  assert.equal(summarizeReliability(null), null);
});
