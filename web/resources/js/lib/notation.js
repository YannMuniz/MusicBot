// Grafia dos acordes só para exibição: o dado guardado continua em forma canônica (maj7, mM7).
// 'br' = cifra brasileira (C7M, Cm7M); 'en' = como o analisador escreve (Cmaj7, CmM7).
export function styleChord(chord, style = 'br') {
  if (style !== 'br') return chord;
  const m = /^([A-G][#b]?)([^/]*)(\/[A-G][#b]?)?$/.exec(chord || '');
  if (!m) return chord;
  const suffix = m[2]
    .replace(/^mM7/, 'm7M')
    .replace(/^maj7/, '7M')
    .replace(/^maj9/, '9M');
  return m[1] + suffix + (m[3] || '');
}
