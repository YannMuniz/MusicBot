import { Link } from '@inertiajs/react';

export default function Layout({ children }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link href="/" className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-sm text-white">♪</span>
            Harmonia AI
          </Link>
          <span className="hidden text-sm text-stone-500 sm:block">Análise automática de tom, acordes e seções</span>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-stone-500">
        Os resultados são estimativas automáticas e podem conter erros. Confirme de ouvido e corrija quando necessário.
      </footer>
    </div>
  );
}
