import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api.js';
import { formatTime } from '../lib/transpose.js';

/**
 * Aprendizado pelas correções: a cifra revisada por você passa a ser fonte de exemplos para OUTRAS gravações.
 * Não retreina o modelo; cada ajuste que um exemplo causar numa análise aparece abaixo, com os números da decisão.
 */
export default function LearningCard({ songId, refreshKey }) {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api(`/songs/${songId}/learning`).then(setInfo).catch(() => setInfo(null)), [songId]);
  useEffect(() => { load(); }, [load, refreshKey]);
  if (!info) return null;
  const toggle = async () => {
    setBusy(true);
    try { setInfo(await api(`/songs/${songId}/review`, { method: 'POST', body: { reviewed: !info.reviewed } })); } finally { setBusy(false); }
  };
  const n = Object.entries(info.corrections || {}).map(([k, v]) => `${v} ${k}`).join(', ') || 'nenhuma';
  return (
    <div className="space-y-3 text-sm">
      <p className="text-stone-600">
        Correções registradas: <b>{n}</b>. {info.reviewed
          ? <>Esta cifra está <b className="text-emerald-700">marcada como revisada</b>: seus trechos (corrigidos e confirmados) servem de exemplo para outras músicas.</>
          : <>Quando você terminar de conferir a cifra, marque como revisada para que ela sirva de exemplo para outras músicas. Sem isso, nada é reutilizado.</>}
      </p>
      <button type="button" disabled={busy} onClick={toggle} className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 font-medium hover:bg-stone-50 disabled:opacity-50">
        {info.reviewed ? 'Desmarcar revisão' : 'Marcar cifra como revisada'}
      </button>
      {info.memory_applied_here?.length > 0 && (
        <div>
          <p className="font-medium">Acordes ajustados por exemplos de outras gravações ({info.memory_applied_here.length}):</p>
          <ul className="mt-1 list-disc pl-5 text-stone-700">
            {info.memory_applied_here.map((m, i) => (
              <li key={i}>{formatTime(m.start)}: {m.from} → <b>{m.to}</b> ({m.neighbors} exemplos de {m.songs} músicas, concordância {Math.round(m.agreement * 100)}%)</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
