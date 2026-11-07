import test from 'node:test';
import assert from 'node:assert/strict';
import { styleChord } from './notation.js';

test('grafia brasileira para 7ª maior', () => {
  assert.equal(styleChord('C#maj7'), 'C#7M');
  assert.equal(styleChord('Dbmaj7/Ab'), 'Db7M/Ab');
  assert.equal(styleChord('CmM7'), 'Cm7M');
});

test('não altera outros acordes nem o estilo en', () => {
  for (const c of ['C', 'F#m7', 'Bb7', 'Gm7(b5)', 'N', 'Dsus4']) assert.equal(styleChord(c), c);
  assert.equal(styleChord('Cmaj7', 'en'), 'Cmaj7');
});
