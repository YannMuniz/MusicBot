import { Head, Link, router, useForm } from '@inertiajs/react';
import { useEffect, useRef } from 'react';
import Layout from '../../components/Layout.jsx';
import StatusBadge from '../../components/StatusBadge.jsx';
import { formatTime } from '../../lib/transpose.js';

function Upload({ maxUploadMb }) {
  const form = useForm({ file: null, title: '' });
  const input = useRef(null);

  const submit = (e) => {
    e.preventDefault();
    if (!form.data.file) return;
    form.post('/songs', { forceFormData: true });
  };

  return (
    <form onSubmit={submit} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold">Analisar uma música</h2>
      <p className="mt-1 text-sm text-stone-600">
        Envie um arquivo MP3 ou WAV (até {maxUploadMb} MB). A análise começa automaticamente.
      </p>
      <div
        className="mt-4 cursor-pointer rounded-xl border-2 border-dashed border-stone-300 p-6 text-center hover:border-indigo-400"
        onClick={() => input.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          form.setData('file', e.dataTransfer.files[0] ?? null);
        }}
      >
        <input
          ref={input}
          type="file"
          accept=".mp3,.wav,audio/mpeg,audio/wav"
          className="hidden"
          onChange={(e) => form.setData('file', e.target.files[0] ?? null)}
        />
        {form.data.file ? (
          <span className="font-medium">{form.data.file.name}</span>
        ) : (
          <span className="text-stone-500">Clique ou arraste o arquivo aqui</span>
        )}
      </div>
      <input
        type="text"
        placeholder="Título (opcional)"
        maxLength={200}
        value={form.data.title}
        onChange={(e) => form.setData('title', e.target.value)}
        className="mt-3 w-full rounded-lg border border-stone-300 px-3 py-2 text-sm"
      />
      {form.errors.file && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{form.errors.file}</p>}
      {form.errors.title && <p className="mt-2 text-sm text-red-700">{form.errors.title}</p>}
      {form.progress && (
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-stone-200">
          <div className="h-full bg-indigo-600" style={{ width: `${form.progress.percentage}%` }} />
        </div>
      )}
      <button
        type="submit"
        disabled={!form.data.file || form.processing}
        className="mt-4 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {form.processing ? 'Enviando…' : 'Enviar e analisar'}
      </button>
    </form>
  );
}

export default function Index({ songs, maxUploadMb }) {
  const busy = songs.some((s) => s.status === 'pending' || s.status === 'processing');
  useEffect(() => {
    if (!busy) return undefined;
    const t = setInterval(() => router.reload({ only: ['songs'] }), 3000);
    return () => clearInterval(t);
  }, [busy]);

  return (
    <Layout>
      <Head title="Músicas" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Upload maxUploadMb={maxUploadMb} />
        <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold">Histórico</h2>
          {songs.length === 0 ? (
            <p className="mt-3 text-sm text-stone-500">Nenhuma música analisada ainda.</p>
          ) : (
            <ul className="mt-3 divide-y divide-stone-100">
              {songs.map((s) => (
                <li key={s.id}>
                  <Link href={`/songs/${s.id}`} className="flex items-center justify-between gap-3 py-3 hover:bg-stone-50">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{s.title}</p>
                      <p className="text-xs text-stone-500">
                        {s.key_name ? `Tom: ${s.key_name} · ` : ''}
                        {s.duration ? `${formatTime(s.duration)} · ` : ''}
                        {new Date(s.created_at).toLocaleString('pt-BR')}
                      </p>
                    </div>
                    <StatusBadge status={s.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Layout>
  );
}
