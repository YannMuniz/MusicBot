import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api.js';
import { formatClock, parseClock } from '../lib/clock.js';
import { formatTime } from '../lib/transpose.js';

const CATEGORIES = { solo: 'Solo', riff: 'Riff', intro: 'Introdução instrumental', interlude: 'Interlúdio', outro: 'Final instrumental', instrumental: 'Trecho instrumental' };
const INSTRUMENTS = { indeterminate: 'Instrumento indeterminado', guitar: 'Guitarra', bass: 'Baixo', keyboard: 'Teclado', other: 'Outro' };
const TUNING_LABELS = { standard: 'Padrão (E A D G B E)', drop_d: 'Drop D', half_step_down: 'Meio tom abaixo', dadgad: 'DADGAD' };
const STATE_TEXT = { not_started: 'Não transcrito', processing: 'Processando…', completed: 'Concluída', low_confidence: 'Baixa confiança', failed: 'Falhou' };
const PX_PER_S = 70;
const ROW = 26;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Campo de tempo em m:ss (aceita também decimais e segundos puros). Só propaga valores válidos. */
function ClockInput({ value, onChange, decimals = 1, className = '', label, required = false, placeholder = 'm:ss' }) {
  const [text, setText] = useState(value === '' || value == null ? '' : formatClock(value, decimals));
  const [bad, setBad] = useState(false);
  useEffect(() => {  // valor mudou por fora (ex.: "= tempo atual"): atualiza, sem atropelar a digitação
    const parsed = parseClock(text);
    if (value === '' || value == null) { if (text !== '' && parsed == null) return; if (text !== '') setText(''); return; }
    if (parsed == null || Math.abs(parsed - value) > 0.0005) { setText(formatClock(value, decimals)); setBad(false); }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <input type="text" inputMode="decimal" required={required} value={text} placeholder={placeholder} aria-label={label} aria-invalid={bad}
      onChange={(e) => {
        setText(e.target.value);
        const p = parseClock(e.target.value);
        setBad(e.target.value.trim() !== '' && p == null);
        if (p != null) onChange(p); else if (e.target.value.trim() === '') onChange('');
      }}
      onBlur={() => { const p = parseClock(text); if (p != null) setText(formatClock(p, decimals)); }}
      className={`${className} ${bad ? 'border-red-500' : ''}`} />
  );
}

/** Tablatura (SVG) sincronizada com o player: posição horizontal proporcional ao tempo real do áudio. */
function TabView({ notes, tuning, solo, time, editing, selected, onSelect, onSeek }) {
  const box = useRef(null);
  const strings = tuning.length;
  const width = Math.max(600, (solo.end - solo.start) * PX_PER_S + 60);
  const x = (t) => 30 + (t - solo.start) * PX_PER_S;
  const playhead = time >= solo.start && time <= solo.end ? x(time) : null;
  useEffect(() => {
    if (playhead != null && box.current && !editing) {
      const el = box.current;
      if (playhead < el.scrollLeft + 40 || playhead > el.scrollLeft + el.clientWidth - 80) el.scrollTo({ left: Math.max(0, playhead - 80), behavior: 'smooth' });
    }
  }, [playhead, editing]);
  const secs = [];
  for (let s = Math.ceil(solo.start); s <= solo.end; s++) secs.push(s);
  return (
    <div ref={box} className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
      <svg width={width} height={strings * ROW + 34} role="img" aria-label="Tablatura">
        {secs.map((s) => (
          <g key={s}>
            <line x1={x(s)} x2={x(s)} y1={14} y2={strings * ROW + 14} stroke="#e7e5e4" strokeDasharray={s % 5 ? '2 4' : ''} />
            {s % 2 === 0 && <text x={x(s) + 2} y={10} fontSize="9" fill="#a8a29e">{formatTime(s)}</text>}
          </g>
        ))}
        {Array.from({ length: strings }, (_, i) => (
          <line key={i} x1={20} x2={width - 10} y1={i * ROW + 14 + ROW / 2} y2={i * ROW + 14 + ROW / 2} stroke="#a8a29e" strokeWidth="1" />
        ))}
        {notes.map((n, i) => {
          if (n.string == null || n.deleted) return null;
          const cx = x(n.start);
          const cy = (n.string - 1) * ROW + 14 + ROW / 2;
          const active = time >= n.start && time < n.end;
          const low = (n.confidence ?? 1) < 0.5;
          const vib = n.techniques?.some((t) => t.type === 'vibrato');
          const gl = n.techniques?.some((t) => t.type === 'glissando');
          return (
            <g key={i} onClick={() => (editing ? onSelect(i) : onSeek(n.start))} style={{ cursor: 'pointer' }} opacity={low ? 0.55 : 1}>
              <rect x={cx - 3} y={cy - 9} width={String(n.fret).length * 8 + 8} height={18} rx={4}
                fill={active ? '#4f46e5' : selected === i ? '#fde68a' : '#fff'} stroke={selected === i ? '#b45309' : '#d6d3d1'} />
              <text x={cx + 1} y={cy + 4} fontSize="12" fontWeight="600" fill={active ? '#fff' : '#1c1917'}>{n.fret}</text>
              {vib && <text x={cx + 2} y={cy - 11} fontSize="10" fill="#7c3aed"><title>vibrato inferido (pode estar errado)</title>~</text>}
              {gl && <text x={cx + 14} y={cy - 11} fontSize="10" fill="#0369a1"><title>glissando inferido (slide ou bend; não distinguível)</title>/</text>}
            </g>
          );
        })}
        {playhead != null && <line x1={playhead} x2={playhead} y1={4} y2={strings * ROW + 20} stroke="#4f46e5" strokeWidth="2" />}
      </svg>
    </div>
  );
}

export default function SoloPanel({ songId, duration, sections, audioRef, time, seek }) {
  const [solos, setSolos] = useState([]);
  const [tunings, setTunings] = useState({});
  const [sel, setSel] = useState(null);
  const [tab, setTab] = useState(null);
  const [msg, setMsg] = useState(null);
  const [form, setForm] = useState({ start: '', end: '', category: 'solo', instrument: 'indeterminate' });
  const [pre, setPre] = useState('foreground');
  const [loop, setLoop] = useState(false);
  const [rate, setRate] = useState(1);
  const [draft, setDraft] = useState(null); // { notes, tuning } em edição
  const [noteIdx, setNoteIdx] = useState(null);
  const [busy, setBusy] = useState(false);

  const solo = solos.find((s) => s.id === sel) || null;
  const loadSolos = useCallback(async () => {
    const r = await api(`/songs/${songId}/solos`);
    setSolos(r.solos);
    setTunings(r.tunings);
    return r.solos;
  }, [songId]);
  useEffect(() => { loadSolos().catch(() => {}); }, [loadSolos]);

  const loadTab = useCallback(async (id) => {
    try { setTab(await api(`/songs/${songId}/solos/${id}/tab`)); } catch { setTab(null); }
  }, [songId]);
  useEffect(() => { setDraft(null); setNoteIdx(null); setTab(null); if (sel) loadTab(sel); }, [sel, loadTab]);
  useEffect(() => {  // sondagem enquanto processa
    if (tab?.state !== 'processing') return undefined;
    const t = setInterval(() => { loadTab(sel); loadSolos(); }, 2500);
    return () => clearInterval(t);
  }, [tab?.state, sel, loadTab, loadSolos]);

  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = rate; }, [rate, audioRef]);
  useEffect(() => {
    if (loop && solo && audioRef.current && time >= solo.end) { audioRef.current.currentTime = solo.start; }
  }, [loop, solo, time, audioRef]);

  const err = (e) => setMsg({ ok: false, text: e.message });
  const create = async (e) => {
    e.preventDefault(); setMsg(null);
    if (form.start === '' || form.end === '' || form.end <= form.start) { setMsg({ ok: false, text: 'Informe início e fim em m:ss (ex.: 2:28 e 3:15), com o fim depois do início.' }); return; }
    try {
      const s = await api(`/songs/${songId}/solos`, { method: 'POST', body: { start: form.start, end: form.end, category: form.category, instrument: form.instrument } });
      await loadSolos(); setSel(s.id); setMsg({ ok: true, text: 'Trecho marcado. Gere a tablatura quando quiser.' });
    } catch (e2) { err(e2); }
  };
  const patch = async (body) => { try { await api(`/songs/${songId}/solos/${sel}`, { method: 'PATCH', body }); await loadSolos(); setMsg(null); } catch (e2) { err(e2); } };
  const remove = async () => {
    if (!confirm('Remover este trecho? A transcrição e as correções deste solo continuam guardadas no histórico de anotações.')) return;
    try { await api(`/songs/${songId}/solos/${sel}`, { method: 'DELETE' }); setSel(null); await loadSolos(); } catch (e2) { err(e2); }
  };
  const transcribe = async () => {
    setMsg(null); setBusy(true);
    try { await api(`/songs/${songId}/solos/${sel}/transcribe`, { method: 'POST', body: { preprocess: pre } }); setTab({ state: 'processing' }); await loadSolos(); } catch (e2) { err(e2); } finally { setBusy(false); }
  };

  const current = useMemo(() => {
    if (!tab || tab.state === 'processing' || tab.state === 'failed' || !tab.notes) return null;
    if (draft) return draft;
    return tab.edited ? { notes: tab.edited.notes, tuning: tab.edited.tuning } : { notes: tab.notes, tuning: tab.tuning };
  }, [tab, draft]);
  const tuningKey = current ? Object.keys(tunings).find((k) => same(tunings[k], current.tuning)) : null;
  const startEdit = () => setDraft({ notes: current.notes.map((n) => ({ ...n })), tuning: current.tuning });
  const changeTuning = async (key) => {
    const tuning = tunings[key];
    try {
      const r = await api(`/songs/${songId}/solos/${sel}/retab`, { method: 'POST', body: { tuning, max_fret: tab.max_fret || 22, notes: current.notes } });
      setDraft({ notes: r.notes, tuning });
    } catch (e2) { err(e2); }
  };
  const setNote = (i, patchObj) => setDraft((d) => ({ ...d, notes: d.notes.map((n, k) => (k === i ? { ...n, ...patchObj } : n)) }));
  const save = async () => {
    setBusy(true);
    try {
      await api(`/songs/${songId}/solos/${sel}/tab`, { method: 'PUT', body: { tuning: draft.tuning, max_fret: tab.max_fret || 22, notes: draft.notes } });
      setDraft(null); setNoteIdx(null); await loadTab(sel); setMsg({ ok: true, text: 'Correções salvas. A transcrição automática original foi preservada.' });
    } catch (e2) { err(e2); } finally { setBusy(false); }
  };
  const n = draft && noteIdx != null ? draft.notes[noteIdx] : null;
  const btn = 'rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-stone-50 disabled:opacity-50';
  const sel2 = 'rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm';

  return (
    <div className="space-y-4 text-sm">
      <p className="text-stone-600">
        Marque o trecho do solo (ou de qualquer parte instrumental). O sistema <b>não</b> afirma onde há solo: a detecção automática de voz/solo não foi confiável nos testes.
        A transcrição é <b>monofônica</b> e a tablatura é uma <b>digitação plausível</b>, não necessariamente a usada na gravação.
      </p>
      {msg && <p className={`rounded-lg p-3 ${msg.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>{msg.text}</p>}

      <form onSubmit={create} className="flex flex-wrap items-end gap-2 rounded-lg bg-stone-50 p-3">
        <label className="text-xs text-stone-600">Início (m:ss)<ClockInput required label="Início do trecho" value={form.start} onChange={(v) => setForm({ ...form, start: v })} className={`${sel2} block w-24`} /></label>
        <button type="button" className={btn} onClick={() => setForm({ ...form, start: Number(time.toFixed(1)) })}>= tempo atual</button>
        <label className="text-xs text-stone-600">Fim (m:ss)<ClockInput required label="Fim do trecho" value={form.end} onChange={(v) => setForm({ ...form, end: v })} className={`${sel2} block w-24`} /></label>
        <button type="button" className={btn} onClick={() => setForm({ ...form, end: Number(time.toFixed(1)) })}>= tempo atual</button>
        <select className={sel2} value="" onChange={(e) => { const s = sections[Number(e.target.value)]; if (s) setForm({ ...form, start: s.start, end: Math.min(s.end, s.start + 180) }); }} aria-label="Usar uma seção">
          <option value="">Usar uma seção…</option>
          {sections.map((s, i) => <option key={s.index} value={i}>{s.label}{s.occurrences_total > 1 ? ` (${s.occurrence}/${s.occurrences_total})` : ''} · {formatTime(s.start)}–{formatTime(s.end)}</option>)}
        </select>
        <select className={sel2} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{Object.entries(CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select className={sel2} value={form.instrument} onChange={(e) => setForm({ ...form, instrument: e.target.value })}>{Object.entries(INSTRUMENTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <button type="submit" className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white">Marcar trecho</button>
      </form>

      {solos.length > 0 && (
        <div>
          <div className="relative mb-2 h-4 rounded bg-stone-100" aria-label="Trechos na linha do tempo">
            {solos.map((s) => (
              <button key={s.id} type="button" onClick={() => setSel(s.id)} title={`${CATEGORIES[s.category]} · ${formatTime(s.start)}–${formatTime(s.end)}`}
                style={{ left: `${(s.start / duration) * 100}%`, width: `${((s.end - s.start) / duration) * 100}%` }}
                className={`absolute top-0 h-4 rounded ${sel === s.id ? 'bg-indigo-600' : 'bg-amber-400 hover:bg-amber-500'}`} />
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {solos.map((s) => (
              <button key={s.id} type="button" onClick={() => setSel(s.id)} className={`rounded-lg border px-3 py-1.5 ${sel === s.id ? 'border-indigo-600 bg-indigo-50' : 'border-stone-300 bg-white'}`}>
                {CATEGORIES[s.category]} · {formatTime(s.start)}–{formatTime(s.end)} <span className="text-xs text-stone-500">({STATE_TEXT[s.transcription_state]})</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {solo && (
        <div className="space-y-3 rounded-lg border border-stone-200 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <b>{CATEGORIES[solo.category]}</b>
            <span className="text-stone-500">{formatTime(solo.start)}–{formatTime(solo.end)} · {solo.source === 'user' ? 'marcado por você' : solo.source}</span>
            <select className={sel2} value={solo.instrument} onChange={(e) => patch({ instrument: e.target.value })} aria-label="Instrumento">{Object.entries(INSTRUMENTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <select className={sel2} value={solo.category} onChange={(e) => patch({ category: e.target.value })} aria-label="Categoria">{Object.entries(CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <button type="button" className={btn} onClick={() => patch({ start: Math.max(0, Number(time.toFixed(1))) })} title="Define o início no tempo atual do player (m:ss)">Início = agora</button>
            <button type="button" className={btn} onClick={() => patch({ end: Number(time.toFixed(1)) })} title="Define o fim no tempo atual do player">Fim = agora</button>
            <button type="button" className={`${btn} text-red-700`} onClick={remove}>Remover</button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={btn} onClick={() => seek(solo.start)}>▶ Ouvir o trecho</button>
            <label className="flex items-center gap-1"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Repetir trecho</label>
            <label className="flex items-center gap-1">Velocidade
              <select className={sel2} value={rate} onChange={(e) => setRate(Number(e.target.value))}>{[0.5, 0.75, 1].map((r) => <option key={r} value={r}>{r}×</option>)}</select>
            </label>
            <span className="mx-1 text-stone-300">|</span>
            <select className={sel2} value={pre} onChange={(e) => setPre(e.target.value)} aria-label="Pré-processamento">
              <option value="foreground">Primeiro plano (recomendado)</option><option value="harmonic">Harmônico</option><option value="raw">Áudio bruto</option>
            </select>
            <button type="button" className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50" disabled={busy || tab?.state === 'processing'} onClick={transcribe}>
              {tab && tab.notes ? 'Gerar novamente' : 'Gerar tablatura'}
            </button>
          </div>

          {tab?.state === 'processing' && <p className="text-stone-600">Transcrevendo… (pode levar de dezenas de segundos a alguns minutos; o resultado fica salvo e não é recalculado ao tocar).</p>}
          {tab?.state === 'failed' && <p className="text-red-700">{tab.error || 'A transcrição falhou.'}</p>}

          {current && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3 text-xs text-stone-600">
                <span className={`rounded px-2 py-0.5 font-semibold ${tab.state === 'low_confidence' ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'}`}>{STATE_TEXT[tab.state]}</span>
                <span>confiança média do rastreador: {tab.mean_confidence} (não calibrada)</span>
                <span>{current.notes.length} notas</span>
                {tab.edited && !draft && <span className="text-indigo-700">exibindo a versão corrigida por você</span>}
              </div>
              {tab.state === 'low_confidence' && <p className="rounded-lg bg-amber-50 p-2 text-amber-800">Baixa confiança: muitas notas podem estar erradas. Confira ouvindo e corrija.</p>}
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1">Afinação
                  <select className={sel2} value={tuningKey || 'custom'} onChange={(e) => e.target.value !== 'custom' && changeTuning(e.target.value)}>
                    {!tuningKey && <option value="custom">Personalizada</option>}
                    {Object.keys(tunings).filter((k) => tunings[k].length === 6).map((k) => <option key={k} value={k}>{TUNING_LABELS[k] || k}</option>)}
                  </select>
                </label>
                {!draft ? <button type="button" className={btn} onClick={startEdit}>Corrigir notas</button> : (
                  <>
                    <button type="button" className={btn} onClick={() => { setDraft(null); setNoteIdx(null); }}>Cancelar</button>
                    <button type="button" className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50" disabled={busy} onClick={save}>Salvar correções</button>
                  </>
                )}
              </div>
              <TabView notes={current.notes} tuning={current.tuning} solo={solo} time={time} editing={!!draft} selected={noteIdx} onSelect={setNoteIdx} onSeek={seek} />
              {n && (
                <div className="flex flex-wrap items-end gap-2 rounded-lg bg-amber-50 p-3">
                  <span className="text-xs text-stone-600">Nota {noteIdx + 1} · {formatClock(n.start, 2)}</span>
                  <label className="text-xs">Corda<select className={sel2} value={n.string ?? ''} onChange={(e) => setNote(noteIdx, { string: Number(e.target.value) })}>{current.tuning.map((_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}</select></label>
                  <label className="text-xs">Casa<input type="number" min="0" max="22" className={`${sel2} w-20`} value={n.fret ?? ''} onChange={(e) => setNote(noteIdx, { fret: Number(e.target.value) })} /></label>
                  <label className="text-xs">Início (m:ss)<ClockInput label="Início da nota" decimals={2} value={n.start} onChange={(v) => v !== '' && setNote(noteIdx, { start: v })} className={`${sel2} block w-24`} /></label>
                  <label className="text-xs">Fim (m:ss)<ClockInput label="Fim da nota" decimals={2} value={n.end} onChange={(v) => v !== '' && setNote(noteIdx, { end: v })} className={`${sel2} block w-24`} /></label>
                  <button type="button" className={`${btn} text-red-700`} onClick={() => { setNote(noteIdx, { deleted: true }); setNoteIdx(null); }}>Remover nota</button>
                </div>
              )}
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-stone-500">
                {(tab.limits || []).map((l) => <li key={l}>{l}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
