import { Head, Link } from '@inertiajs/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ChordsPanel from '../../components/ChordsPanel.jsx';
import Layout from '../../components/Layout.jsx';
import SectionsBar from '../../components/SectionsBar.jsx';
import LearningCard from '../../components/LearningCard.jsx';
import SoloPanel from '../../components/SoloPanel.jsx';
import StatusBadge, { STAGES } from '../../components/StatusBadge.jsx';
import TransposeControls from '../../components/TransposeControls.jsx';
import { api } from '../../lib/api.js';
import { styleChord } from '../../lib/notation.js';
import { summarizeReliability } from '../../lib/reliability.js';
import {
  formatTime, resolveFlats, segmentIndexAt, transposeChord, transposedKeyName,
} from '../../lib/transpose.js';

// Solos/tablaturas ficam ocultos por enquanto (código e API preservados).
const SHOW_SOLOS = false;

const Card = ({ title, children, right }) => (
  <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-base font-semibold">{title}</h2>
      {right}
    </div>
    {children}
  </section>
);

export default function Show({ song: initial }) {
  const [song, setSong] = useState(initial);
  const [reachable, setReachable] = useState(true);
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [time, setTime] = useState(0);
  const [semitones, setSemitones] = useState(0);
  const [preference, setPreference] = useState('auto');
  const [source, setSource] = useState('auto'); // 'auto' | 'detected' | 'edited'
  const [draft, setDraft] = useState(null); // lista em edição (null = não editando)
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);
  const [follow, setFollow] = useState(() => {
    try { return localStorage.getItem('harmonia.follow') !== '0'; } catch { return true; }
  });
  const toggleFollow = () => setFollow((f) => {
    try { localStorage.setItem('harmonia.follow', f ? '0' : '1'); } catch { /* sem armazenamento: só nesta sessão */ }
    return !f;
  });
  const [viewMode, setViewMode] = useState('cifra'); // 'cifra' | 'corrida' | 'detalhado' (acordes brutos, antes da suavização)
  const [notation, setNotationState] = useState(() => {
    try { return localStorage.getItem('harmonia.notation') === 'en' ? 'en' : 'br'; } catch { return 'br'; }
  });
  const setNotation = (v) => { setNotationState(v); try { localStorage.setItem('harmonia.notation', v); } catch { /* sem armazenamento */ } };
  const audioRef = useRef(null);
  const reliability = useMemo(() => summarizeReliability(data?.chords), [data]);
  const raf = useRef(0);

  // Acompanha o estado enquanto a análise não terminou.
  useEffect(() => {
    if (song.status === 'completed' || song.status === 'failed') return undefined;
    const t = setInterval(async () => {
      try {
        const r = await api(`/songs/${song.id}/status`);
        setSong(r.song);
        setReachable(r.analyzer_reachable);
      } catch {
        setReachable(false);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [song.id, song.status]);

  const loadData = useCallback(async () => {
    try {
      setLoadError(null);
      setData(await api(`/songs/${song.id}/data`));
    } catch (e) {
      setLoadError(e.message);
    }
  }, [song.id]);

  useEffect(() => {
    if (song.status === 'completed') loadData();
  }, [song.status, song.id, loadData]);

  // Relógio do player (rAF enquanto toca → destaque do acorde atual sem atraso perceptível).
  const tick = useCallback(() => {
    if (audioRef.current) setTime(audioRef.current.currentTime);
    raf.current = requestAnimationFrame(tick);
  }, []);
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  const seek = (t) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = t;
    setTime(t);
    a.play().catch(() => {});
  };

  const key = data?.analysis.key;
  const detected = data?.chords ?? [];
  const edited = data?.edited?.segments ?? null;
  const effectiveSource = source === 'auto' ? (edited ? 'edited' : 'detected') : source;
  const detailedView = viewMode === 'detalhado' && data?.chords_raw;
  const baseSegments = detailedView ? data.chords_raw : effectiveSource === 'edited' && edited ? edited : detected;
  const segments = draft ?? baseSegments;
  const editing = draft !== null;

  const flats = key ? resolveFlats(preference, key.tonic_pc, key.mode, semitones) : false;
  const display = (c) => styleChord(semitones === 0 && preference === 'auto' ? c : transposeChord(c, semitones, flats), notation);
  const keyLabel = key ? transposedKeyName(key.tonic_pc, key.mode, semitones, flats) : '';

  const activeIdx = useMemo(() => segmentIndexAt(segments, time), [segments, time]);
  const activeSection = data ? data.sections.findIndex((s) => time >= s.start && time < s.end) : -1;
  const view = useMemo(() => segments.map((seg, idx) => ({ seg, idx })), [segments]);

  const startEdit = () => {
    setSaveMsg(null);
    setDraft(baseSegments.map(({ start, end, chord }) => ({ start, end, chord })));
  };
  const changeDraft = (i, chord) => setDraft((d) => d.map((s, k) => (k === i ? { ...s, chord } : s)));
  const removeDraft = (i) =>
    setDraft((d) => {
      if (d.length <= 1) return d;
      const out = d.map((s) => ({ ...s }));
      const [gone] = out.splice(i, 1);
      if (i > 0) out[i - 1].end = gone.end;
      else out[0].start = gone.start;
      return out;
    });
  const saveDraft = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const doc = await api(`/songs/${song.id}/chords`, {
        method: 'PUT',
        body: { base_run_id: data.analysis.run_id, segments: draft },
      });
      setData((d) => ({ ...d, edited: doc }));
      setSource('edited');
      setDraft(null);
      setSaveMsg({ ok: true, text: 'Correções salvas. A detecção automática original foi preservada.' });
    } catch (e) {
      setSaveMsg({ ok: false, text: e.message });
    } finally {
      setSaving(false);
    }
  };

  const reanalyze = async () => {
    if (!confirm('Reprocessar esta música? A análise atual será guardada no histórico.')) return;
    try {
      const r = await api(`/songs/${song.id}/reanalyze`, { method: 'POST' });
      setData(null);
      setDraft(null);
      setSong(r.song);
    } catch (e) {
      alert(e.message);
    }
  };

  const inProgress = song.status === 'pending' || song.status === 'processing';
  const btn = 'rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm hover:bg-stone-100 disabled:opacity-40';

  return (
    <Layout>
      <Head title={song.title} />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link href="/" className="text-sm text-indigo-700 hover:underline">← Todas as músicas</Link>
          <h1 className="mt-1 truncate text-2xl font-semibold">{song.title}</h1>
          <p className="text-xs text-stone-500">{song.original_filename}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={song.status} />
          <button type="button" className={btn} disabled={inProgress} onClick={reanalyze}>Reprocessar</button>
        </div>
      </div>

      {!reachable && (
        <p className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          Não foi possível consultar o serviço de análise agora. Tentando novamente…
        </p>
      )}

      {inProgress && (
        <Card title="Análise em andamento">
          <p className="text-sm text-stone-700">
            {song.status === 'pending' ? 'Aguardando na fila…' : STAGES[song.stage] ?? 'Processando…'}
          </p>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-stone-200">
            <div className="h-full w-1/3 animate-pulse rounded-full bg-indigo-500" />
          </div>
          <p className="mt-2 text-xs text-stone-500">Uma música de 4 minutos leva cerca de 2 minutos. Você pode sair e voltar depois pelo histórico.</p>
        </Card>
      )}

      {song.status === 'failed' && (
        <Card title="A análise falhou">
          <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{song.error?.message ?? 'Erro desconhecido.'}</p>
          {song.error?.code && <p className="mt-2 text-xs text-stone-500">Código: {song.error.code}</p>}
        </Card>
      )}

      {loadError && <p className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{loadError}</p>}

      {song.status === 'completed' && (
        <div className="space-y-5">
          <div className="sticky top-0 z-30 -mx-1 rounded-xl border border-stone-200 bg-white/95 px-3 py-2 shadow-md backdrop-blur">
            <audio
              ref={audioRef}
              controls
              preload="metadata"
              src={`/songs/${song.id}/audio`}
              className="w-full"
              onPlay={() => { cancelAnimationFrame(raf.current); raf.current = requestAnimationFrame(tick); }}
              onPause={() => cancelAnimationFrame(raf.current)}
              onEnded={() => cancelAnimationFrame(raf.current)}
              onSeeked={() => audioRef.current && setTime(audioRef.current.currentTime)}
            />
            {data && (
              <div className="mt-2">
                <SectionsBar sections={data.sections} duration={data.analysis.duration} time={time} activeIndex={activeSection} onSeek={seek} />
              </div>
            )}
          </div>

          {!data && !loadError && <p className="text-sm text-stone-500">Carregando resultados…</p>}

          {data && (
            <>
              <div className="grid gap-5 lg:grid-cols-3">
                <Card title="Tonalidade estimada">
                  <p className="text-3xl font-semibold">{key.name.replace('major', 'maior').replace('minor', 'menor')}</p>
                  <p className="mt-1 text-sm text-stone-600">
                    Relativo: {key.relative.tonic} {key.relative.mode === 'minor' ? 'menor' : 'maior'} · {data.analysis.tempo_bpm} BPM · {formatTime(data.analysis.duration)}
                  </p>
                  <p className="mt-3 text-xs text-stone-500">
                    Correlação {key.correlation} · margem p/ 2ª candidata {key.margin_to_second}. Não é uma probabilidade.
                  </p>
                  <ul className="mt-2 text-xs text-stone-600">
                    {key.alternatives.map((a) => <li key={a.name}>Alternativa: {a.name.replace('major', 'maior').replace('minor', 'menor')} ({a.correlation})</li>)}
                  </ul>
                </Card>
                <div className="lg:col-span-2">
                  <Card title="Avisos e limitações">
                    <ul className="list-disc space-y-1 pl-5 text-sm text-stone-700">
                      {data.analysis.warnings.map((w) => <li key={w}>{w}</li>)}
                    </ul>
                    <p className="mt-3 text-xs text-stone-500">
                      Algoritmo: {data.analysis.algorithm.name} {data.analysis.algorithm.version} · análise {data.analysis.run_id}
                      {data.history.length > 0 && ` · ${data.history.length} análise(s) anterior(es) no histórico`}
                    </p>
                  </Card>
                </div>
              </div>

              <Card
                title="Acordes"
                right={
                  <div className="flex flex-wrap items-center gap-2">
                    {edited && !editing && (
                      <select value={effectiveSource} onChange={(e) => setSource(e.target.value)} className="rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm">
                        <option value="edited">Versão corrigida</option>
                        <option value="detected">Detecção automática</option>
                      </select>
                    )}
                    <button type="button" onClick={toggleFollow} aria-pressed={follow} title="Rola a cifra automaticamente até o acorde que está tocando"
                      className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${follow ? 'border-indigo-600 bg-indigo-50 text-indigo-800' : 'border-stone-300 bg-white text-stone-600'}`}>
                      Acompanhar cifra: {follow ? 'ligado' : 'desligado'}
                    </button>
                    <select value={notation} onChange={(e) => setNotation(e.target.value)} className="rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm" aria-label="Notação dos acordes" title="Só muda a escrita na tela">
                      <option value="br">Notação: C7M</option>
                      <option value="en">Notação: Cmaj7</option>
                    </select>
                    {!editing && (
                      <select value={viewMode} onChange={(e) => setViewMode(e.target.value)} className="rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm" aria-label="Modo de exibição">
                        <option value="cifra">Cifra por seções</option>
                        <option value="corrida">Cifra corrida</option>
                        {data?.chords_raw && <option value="detalhado">Detalhado (antes da suavização)</option>}
                      </select>
                    )}
                    {editing ? (
                      <>
                        <button type="button" className={btn} onClick={() => setDraft(null)} disabled={saving}>Cancelar</button>
                        <button type="button" className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50" onClick={saveDraft} disabled={saving}>
                          {saving ? 'Salvando…' : 'Salvar correções'}
                        </button>
                      </>
                    ) : (
                      <button type="button" className={btn} onClick={startEdit} disabled={semitones !== 0 || detailedView} title={detailedView ? 'Volte ao modo "Cifra" para editar' : semitones !== 0 ? 'Volte para 0 semitons para editar' : ''}>
                        Corrigir acordes
                      </button>
                    )}
                  </div>
                }
              >
                {reliability && (
                  <div className="mb-4 rounded-lg border border-stone-200 bg-stone-50 p-3 text-sm">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="font-medium text-stone-800">Confiança do modelo na cifra: {Math.round(reliability.mean * 100)}%</span>
                      <span className="text-xs text-stone-500">
                        alta {Math.round(reliability.high * 100)}% · média {Math.round(reliability.mid * 100)}% · baixa {Math.round(reliability.low * 100)}% do tempo
                        {reliability.ambiguous > 0 && ` · ${Math.round(reliability.ambiguous * 100)}% marcado como ambíguo`}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-stone-500">
                      É a probabilidade que o próprio modelo atribui aos acordes detectados (média pelo tempo), não a taxa de acerto: ela não foi calibrada contra cifras revisadas. Serve para saber onde conferir primeiro.
                    </p>
                  </div>
                )}
                <div className="mb-4">
                  <TransposeControls semitones={semitones} setSemitones={setSemitones} preference={preference} setPreference={setPreference} keyLabel={keyLabel} />
                </div>
                {saveMsg && (
                  <p className={`mb-3 rounded-lg p-3 text-sm ${saveMsg.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>{saveMsg.text}</p>
                )}
                {editing && (
                  <p className="mb-3 text-sm text-stone-600">
                    Edite os nomes (ex.: F, Bb, Dm7, Gsus4, C/E). “×” remove o acorde e estende o anterior. Os tempos não mudam.
                  </p>
                )}
                {effectiveSource === 'edited' && !editing && (
                  <p className="mb-3 text-xs text-stone-500">Exibindo a versão corrigida por você. Salva em {data.edited?.saved_at}.</p>
                )}
                <ChordsPanel
                  view={view}
                  sections={data.sections}
                  activeIdx={activeIdx}
                  display={display}
                  editing={editing}
                  mode={viewMode === 'corrida' ? 'corrida' : 'cifra'}
                  follow={follow}
                  onSeek={seek}
                  onChange={changeDraft}
                  onRemove={removeDraft}
                />
              </Card>

              {SHOW_SOLOS && (
                <Card title="Solos e tablaturas">
                  <SoloPanel songId={song.id} duration={data.analysis.duration} sections={data.sections} audioRef={audioRef} time={time} seek={seek} />
                </Card>
              )}

              <Card title="Aprendizado pelas correções">
                <LearningCard songId={song.id} refreshKey={data.edited?.saved_at} />
              </Card>

              <Card title="Relatório técnico">
                <details>
                  <summary className="cursor-pointer text-sm text-indigo-700">Ver relatório da análise</summary>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-lg bg-stone-100 p-3 text-xs">{data.report}</pre>
                </details>
              </Card>
            </>
          )}
        </div>
      )}
    </Layout>
  );
}
