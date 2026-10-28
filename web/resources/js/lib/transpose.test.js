import assert from 'node:assert/strict';
import test from 'node:test';
import { keyPrefersFlats, resolveFlats, segmentIndexAt, transposeChord, transposedKeyName } from './transpose.js';

test('transpõe acordes simples e menores', () => {
  assert.equal(transposeChord('C', 2, false), 'D');
  assert.equal(transposeChord('Gm', 2, true), 'Am');
  assert.equal(transposeChord('F#m', 1, false), 'Gm');
  assert.equal(transposeChord('Bb', 2, true), 'C');
});

test('preserva sufixos e baixo (acorde com inversão)', () => {
  assert.equal(transposeChord('Cmaj7', 7, false), 'Gmaj7');
  assert.equal(transposeChord('Dsus4', -2, false), 'Csus4');
  assert.equal(transposeChord('C/E', 2, false), 'D/F#');
  assert.equal(transposeChord('Bb7/D', 2, true), 'C7/E');
});

test('equivalência enarmônica conforme a preferência', () => {
  assert.equal(transposeChord('C', 1, false), 'C#');
  assert.equal(transposeChord('C', 1, true), 'Db');
  assert.equal(transposeChord('Db', 0, false), 'C#');
});

test('semitons negativos e voltas completas', () => {
  assert.equal(transposeChord('C', -1, false), 'B');
  assert.equal(transposeChord('A', 12, false), 'A');
  assert.equal(transposeChord('E', -24, false), 'E');
});

test('texto desconhecido é preservado', () => {
  assert.equal(transposeChord('N', 3, false), 'N');
});

test('ida e volta preserva a sequência', () => {
  const prog = ['F', 'C', 'Gm', 'Bb', 'Dm', 'D', 'Bb7'];
  for (const n of [-11, -5, 3, 7, 11]) {
    const out = prog.map((c) => transposeChord(transposeChord(c, n, false), -n, true));
    assert.deepEqual(out, prog.map((c) => transposeChord(c, 0, true)));
  }
});

test('grafia automática segue a tonalidade de destino', () => {
  assert.equal(keyPrefersFlats(5, 'major'), true); // F maior
  assert.equal(resolveFlats('auto', 5, 'major', 2), false); // G maior
  assert.equal(resolveFlats('auto', 5, 'major', 5), true); // Bb maior
  assert.equal(resolveFlats('sharps', 5, 'major', 0), false);
  assert.equal(transposedKeyName(5, 'major', 5, true), 'Bb maior');
  assert.equal(transposedKeyName(9, 'minor', 3, false), 'C menor');
});

test('segmento ativo por busca binária', () => {
  const segs = [{ start: 0, end: 2 }, { start: 2, end: 5 }, { start: 5, end: 6 }];
  assert.equal(segmentIndexAt(segs, 0), 0);
  assert.equal(segmentIndexAt(segs, 1.99), 0);
  assert.equal(segmentIndexAt(segs, 2), 1);
  assert.equal(segmentIndexAt(segs, 5.5), 2);
  assert.equal(segmentIndexAt(segs, 6), -1);
  assert.equal(segmentIndexAt([], 1), -1);
});
