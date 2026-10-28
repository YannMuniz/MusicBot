export default function TransposeControls({ semitones, setSemitones, preference, setPreference, keyLabel }) {
  const btn = 'rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm hover:bg-stone-100 disabled:opacity-40';
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-2">
        <button type="button" className={btn} disabled={semitones <= -11} onClick={() => setSemitones(semitones - 1)} aria-label="Descer um semitom">−</button>
        <span className="w-24 text-center text-sm font-medium tabular-nums">
          {semitones > 0 ? `+${semitones}` : semitones} semitons
        </span>
        <button type="button" className={btn} disabled={semitones >= 11} onClick={() => setSemitones(semitones + 1)} aria-label="Subir um semitom">+</button>
        <button type="button" className={btn} disabled={semitones === 0} onClick={() => setSemitones(0)}>Original</button>
      </div>
      <label className="flex items-center gap-2 text-sm">
        Notação
        <select value={preference} onChange={(e) => setPreference(e.target.value)} className="rounded-lg border border-stone-300 bg-white px-2 py-1.5">
          <option value="auto">Automática (pelo tom)</option>
          <option value="sharps">Sustenidos (C#)</option>
          <option value="flats">Bemóis (Db)</option>
        </select>
      </label>
      <span className="text-sm text-stone-600">Tom exibido: <strong>{keyLabel}</strong></span>
    </div>
  );
}
