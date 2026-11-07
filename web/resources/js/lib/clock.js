// Tempo no formato do player/cifra (m:ss) <-> segundos.

/** 148.4 -> "2:28.4" ; decimals=0 -> "2:28". */
export function formatClock(t, decimals = 1) {
  const f = 10 ** decimals;
  const total = Math.round(Math.max(0, Number(t) || 0) * f) / f; // arredonda ANTES de separar (59,96 s -> 1:00, nunca 0:60)
  const m = Math.floor(total / 60);
  const [i, d] = (total - m * 60).toFixed(decimals).split('.');
  return `${m}:${i.padStart(2, '0')}${d ? `.${d}` : ''}`;
}

/**
 * Aceita "2:28", "2:28.4", "2:28,4", "1:02:05" (h:mm:ss) ou só segundos ("148", "148,5").
 * Retorna segundos (número) ou null se inválido.
 */
export function parseClock(text) {
  if (typeof text === 'number') return Number.isFinite(text) && text >= 0 ? text : null;
  const t = String(text ?? '').trim().replace(',', '.');
  if (!t) return null;
  const parts = t.split(':');
  if (parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null;
  const nums = parts.map(Number);
  if (nums.length > 1 && nums.slice(1).some((n) => n >= 60)) return null; // segundos/minutos < 60
  return nums.reduce((acc, n) => acc * 60 + n, 0);
}
