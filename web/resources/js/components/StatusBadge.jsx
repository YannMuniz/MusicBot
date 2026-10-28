const LABELS = {
  pending: ['Na fila', 'bg-amber-100 text-amber-800'],
  processing: ['Analisando', 'bg-sky-100 text-sky-800'],
  completed: ['Concluída', 'bg-emerald-100 text-emerald-800'],
  failed: ['Falhou', 'bg-red-100 text-red-800'],
};

export const STAGES = {
  starting: 'Iniciando',
  decoding: 'Decodificando o áudio',
  separating: 'Separando componentes harmônico e percussivo (etapa mais longa)',
  features: 'Extraindo características musicais',
  tonality: 'Estimando a tonalidade',
  beats: 'Detectando as batidas',
  chords: 'Reconhecendo os acordes',
  sections: 'Detectando as seções',
};

export default function StatusBadge({ status }) {
  const [label, cls] = LABELS[status] ?? [status, 'bg-stone-100 text-stone-700'];
  return <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>{label}</span>;
}
