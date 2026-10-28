// Transposição calculada no navegador a partir dos acordes detectados (sem nova análise do áudio).
const SHARP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const FLAT = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
const LETTER = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
// Tônicas cuja grafia usual usa bemóis (mesma regra do analisador)
const FLAT_MAJOR = new Set([5, 10, 3, 8, 1, 6]);
const FLAT_MINOR = new Set([2, 7, 0, 5, 10, 3]);

const mod12 = (n) => ((n % 12) + 12) % 12;

export function parseNote(s) {
  const m = /^([A-G])([#b]?)$/.exec(s);
  return m ? mod12(LETTER[m[1]] + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0)) : null;
}

export function keyPrefersFlats(tonicPc, mode) {
  return (mode === 'minor' ? FLAT_MINOR : FLAT_MAJOR).has(mod12(tonicPc));
}

export function noteName(pc, flats) {
  return (flats ? FLAT : SHARP)[mod12(pc)];
}

/** Transpõe um acorde (ex.: "F#m7", "C/E"). Texto não reconhecido (ex.: "N") é devolvido igual. */
export function transposeChord(chord, semitones, flats) {
  const m = /^([A-G][#b]?)([^/]*)(?:\/([A-G][#b]?))?$/.exec(chord);
  if (!m) return chord;
  const root = parseNote(m[1]);
  if (root === null) return chord;
  const bass = m[3] ? parseNote(m[3]) : null;
  return noteName(root + semitones, flats) + m[2] + (bass !== null ? '/' + noteName(bass + semitones, flats) : '');
}

/** Preferência 'auto' segue a grafia da tonalidade de destino. */
export function resolveFlats(preference, tonicPc, mode, semitones) {
  if (preference === 'flats') return true;
  if (preference === 'sharps') return false;
  return keyPrefersFlats(tonicPc + semitones, mode);
}

export function transposedKeyName(tonicPc, mode, semitones, flats) {
  return `${noteName(tonicPc + semitones, flats)} ${mode === 'minor' ? 'menor' : 'maior'}`;
}

export function formatTime(t) {
  const s = Math.max(0, t);
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

/** Índice do segmento ativo no tempo t (busca binária; -1 se nenhum). */
export function segmentIndexAt(segments, t) {
  let lo = 0;
  let hi = segments.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (t < segments[mid].start) hi = mid - 1;
    else if (t >= segments[mid].end) lo = mid + 1;
    else return mid;
  }
  return -1;
}
