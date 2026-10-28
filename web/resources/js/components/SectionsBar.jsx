import { formatTime } from '../lib/transpose.js';

const COLORS = [
  'bg-indigo-400', 'bg-emerald-400', 'bg-amber-400', 'bg-rose-400',
  'bg-sky-400', 'bg-violet-400', 'bg-lime-500', 'bg-orange-400', 'bg-teal-400', 'bg-fuchsia-400',
];

export const groupColor = (g) => COLORS[(g - 1) % COLORS.length];

export default function SectionsBar({ sections, duration, time, activeIndex, onSeek }) {
  return (
    <div>
      <div className="relative flex h-10 overflow-hidden rounded-lg">
        {sections.map((s, i) => (
          <button
            key={s.index}
            type="button"
            onClick={() => onSeek(s.start)}
            title={`${s.label}${s.occurrences_total > 1 ? ` · ocorrência ${s.occurrence}/${s.occurrences_total}` : ''} · ${formatTime(s.start)}–${formatTime(s.end)}`}
            style={{ width: `${((s.end - s.start) / duration) * 100}%` }}
            className={`${groupColor(s.repeat_group)} border-r border-white/70 text-xs font-semibold text-stone-900 ${
              i === activeIndex ? 'ring-2 ring-inset ring-stone-900' : 'opacity-80 hover:opacity-100'
            }`}
          >
            {s.index}
          </button>
        ))}
        <div className="pointer-events-none absolute top-0 h-full w-0.5 bg-stone-900" style={{ left: `${(time / duration) * 100}%` }} />
      </div>
      <p className="mt-2 text-xs text-stone-500">
        Cores iguais indicam trechos acusticamente parecidos. Os nomes (estrofe, refrão, solo…) não são inferidos automaticamente.
      </p>
    </div>
  );
}
