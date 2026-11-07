import { useEffect, useRef, useState } from 'react';
import { formatTime } from '../lib/transpose.js';
import { groupColor } from './SectionsBar.jsx';

/**
 * view: [{ seg, idx }] (idx = posição na lista de origem); sections agrupam pelos inícios.
 * Em modo de edição os nomes são editáveis (somente sem transposição).
 */
/** Texto do tooltip: explica a previsão sem afirmar certeza (probabilidades do modelo NÃO são calibradas). */
function detail(seg) {
  if (seg.p == null) return seg.score != null ? `score do modelo: ${seg.score}` : 'acorde editado';
  const parts = [`probabilidade do modelo: ${seg.p}${seg.ambiguous ? ' (ambíguo)' : ''}`];
  if (seg.alternatives?.length) parts.push('alternativas: ' + seg.alternatives.map((a) => `${a.chord} ${a.p}`).join(', '));
  if (seg.harmonic_label && seg.harmonic_label !== seg.chord) parts.push(`harmonia: ${seg.harmonic_label}; baixo: ${seg.bass?.note}`);
  else if (seg.bass?.reason === 'weak_evidence') parts.push(`baixo ${seg.bass.note} com evidência fraca: inversão não registrada`);
  if (seg.possible_additions?.length) {
    parts.push('notas de cor possíveis (evidência fraca, não validada): ' + seg.possible_additions.map((a) => a.label).join(', '));
  }
  return parts.join(' | ');
}

const isRest = (seg) => seg.kind === 'rest' || seg.chord === 'N';

/**
 * Estrutura: seções (partes) recolhíveis, com ocorrência (ex.: Parte B · 2/3), acordes sincronizados dentro de cada uma.
 * Pausas ('N') viram marcador discreto, não acorde. mode: 'cifra' (chips com tempo) | 'corrida' (cifra contínua, sem tempos).
 * Em modo de edição os nomes são editáveis (somente sem transposição).
 */
export default function ChordsPanel({ view, sections, activeIdx, display, editing, onSeek, onChange, onRemove, mode = 'cifra', follow = true }) {
  const activeRef = useRef(null);
  const [collapsed, setCollapsed] = useState(() => new Set());
  useEffect(() => {
    const el = activeRef.current;
    if (!follow || editing || mode !== 'cifra' || !el) return;
    el.style.scrollMarginTop = '9rem'; // não deixa o acorde ativo ficar sob o player fixo
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [activeIdx, editing, mode, follow]);

  const toggle = (i) => setCollapsed((c) => { const n = new Set(c); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const allCollapsed = collapsed.size >= sections.length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-stone-600">
        <span>Estrutura:</span>
        {sections.map((sec) => (
          <span key={sec.index} className={`rounded px-1.5 py-0.5 font-semibold text-stone-900 ${groupColor(sec.repeat_group)}`}
            title={`${sec.label} · ${formatTime(sec.start)}–${formatTime(sec.end)}`}>
            {sec.label.replace('Parte ', '')}
          </span>
        ))}
        <button type="button" className="ml-auto text-indigo-700 underline" onClick={() => setCollapsed(allCollapsed ? new Set() : new Set(sections.map((s) => s.index)))}>
          {allCollapsed ? 'Expandir tudo' : 'Recolher tudo'}
        </button>
      </div>
      {sections.map((sec) => {
        const items = view.filter(({ seg }) => seg.start >= sec.start && seg.start < sec.end);
        if (!items.length) return null;
        const open = !collapsed.has(sec.index);
        const repeat = sec.occurrences_total > 1 ? ` · ${sec.occurrence}/${sec.occurrences_total}` : '';
        return (
          <div key={sec.index}>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <button type="button" onClick={() => toggle(sec.index)} className="flex items-center gap-2" aria-expanded={open}>
                <span className="w-3 text-stone-500">{open ? '▾' : '▸'}</span>
                <span className={`inline-block h-3 w-3 rounded-sm ${groupColor(sec.repeat_group)}`} />
                {sec.label}{repeat}
              </button>
              <span className="font-normal text-stone-500">{formatTime(sec.start)}–{formatTime(sec.end)}</span>
              {sec.occurrences_total > 1 && <span className="rounded bg-stone-100 px-1.5 text-xs font-normal text-stone-600">repete {sec.occurrences_total}×</span>}
            </h3>
            {open && mode === 'corrida' && !editing && (
              <p className="rounded-lg bg-stone-50 p-3 text-base font-semibold leading-relaxed">
                {items.filter(({ seg }) => !isRest(seg)).map(({ seg, idx }) => (
                  <button key={idx} type="button" onClick={() => onSeek(seg.start)}
                    className={`mr-3 inline-block rounded px-1 hover:bg-indigo-50 ${idx === activeIdx ? 'bg-indigo-600 text-white hover:bg-indigo-600' : ''}`}>
                    {display(seg.chord)}
                  </button>
                ))}
              </p>
            )}
            {open && (mode !== 'corrida' || editing) && (
            <div className="flex flex-wrap gap-2">
              {items.map(({ seg, idx }) => {
                const active = idx === activeIdx;
                if (isRest(seg) && !editing) {
                  return (
                    <button key={idx} ref={active ? activeRef : null} type="button" onClick={() => onSeek(seg.start)}
                      title={`pausa/sem acorde · ${formatTime(seg.start)}`}
                      className={`self-center rounded-full border border-dashed px-2 py-0.5 text-xs ${active ? 'border-indigo-600 bg-indigo-100 text-indigo-800' : 'border-stone-300 text-stone-400 hover:bg-stone-50'}`}>
                      pausa
                    </button>
                  );
                }
                return editing ? (
                  <div key={idx} className="flex items-center rounded-lg border border-stone-300 bg-white">
                    <span className="px-2 text-xs text-stone-500">{formatTime(seg.start)}</span>
                    <input
                      value={seg.chord}
                      onChange={(e) => onChange(idx, e.target.value)}
                      className="w-20 border-l border-stone-200 px-2 py-1.5 text-sm font-semibold"
                      aria-label={`Acorde em ${formatTime(seg.start)}`}
                      placeholder="ex.: A/C#"
                    />
                    <button type="button" onClick={() => onRemove(idx)} className="px-2 text-stone-400 hover:text-red-600" title="Remover (estende o anterior)">×</button>
                  </div>
                ) : (
                  <button
                    key={idx}
                    ref={active ? activeRef : null}
                    type="button"
                    onClick={() => onSeek(seg.start)}
                    title={detail(seg)}
                    className={`rounded-lg border px-3 py-1.5 text-left ${
                      active ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-stone-300 bg-white hover:bg-indigo-50'
                    }`}
                  >
                    <span className="block text-base font-semibold leading-tight">
                      {display(seg.chord)}
                      {seg.possible_additions?.some((a) => a.degree === 'maj7') && (
                        <span className="ml-1 align-top text-xs font-normal opacity-80" title="Há energia da 7ª maior neste acorde (evidência fraca, não validada). Confira ao ouvir e corrija se for 7M.">
                          ({display('Cmaj7').replace(/^[A-G][#b]?/, '')}?)
                        </span>
                      )}
                      {seg.ambiguous && <span className="ml-0.5 align-top text-xs opacity-70" aria-label="previsão ambígua">?</span>}
                    </span>
                    <span className={`text-xs ${active ? 'text-indigo-100' : 'text-stone-500'}`}>{formatTime(seg.start)}</span>
                  </button>
                );
              })}
            </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
