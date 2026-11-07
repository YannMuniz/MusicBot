import test from 'node:test';
import assert from 'node:assert/strict';
import { formatClock, parseClock } from './clock.js';

test('formata segundos como m:ss', () => {
  assert.equal(formatClock(148.4), '2:28.4');
  assert.equal(formatClock(148.4, 0), '2:28');
  assert.equal(formatClock(0), '0:00.0');
  assert.equal(formatClock(59.96, 0), '1:00');
  assert.equal(formatClock(3725, 0), '62:05');
});

test('interpreta m:ss, decimais com ponto ou vírgula, e segundos puros', () => {
  assert.equal(parseClock('2:28'), 148);
  assert.equal(parseClock('2:28.4'), 148.4);
  assert.equal(parseClock('2:28,4'), 148.4);
  assert.equal(parseClock(' 0:05 '), 5);
  assert.equal(parseClock('148'), 148);
  assert.equal(parseClock('148,5'), 148.5);
  assert.equal(parseClock('1:02:05'), 3725);
});

test('rejeita entradas inválidas', () => {
  for (const bad of ['', 'abc', '2:75', '1:2:3:4', '-3', '2:-1', '2:', ':30', '1.2.3']) assert.equal(parseClock(bad), null, bad);
});

test('ida e volta preserva o valor', () => {
  for (const v of [0, 5.3, 148.4, 195.3, 600]) assert.ok(Math.abs(parseClock(formatClock(v)) - v) < 0.05);
});
