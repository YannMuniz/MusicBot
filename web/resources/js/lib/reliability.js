// Resumo da confiança do modelo na cifra detectada. NÃO é taxa de acerto: `p` é a
// probabilidade do BTC para cada trecho, sem calibração contra uma referência humana.
export function summarizeReliability(segments, { high = 0.8, low = 0.5 } = {}) {
  let total = 0, weighted = 0, hi = 0, mid = 0, lo = 0, ambiguous = 0;
  for (const s of segments || []) {
    if (s.kind === 'rest' || typeof s.p !== 'number') continue;
    const d = Math.max(0, (s.end ?? 0) - (s.start ?? 0));
    if (!d) continue;
    total += d;
    weighted += s.p * d;
    if (s.p >= high) hi += d; else if (s.p >= low) mid += d; else lo += d;
    if (s.ambiguous) ambiguous += d;
  }
  if (!total) return null;
  return { mean: weighted / total, high: hi / total, mid: mid / total, low: lo / total, ambiguous: ambiguous / total, seconds: total };
}
