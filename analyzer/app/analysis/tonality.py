"""Estimativa de tonalidade: média do chroma correlacionada com perfis de Krumhansl-Kessler (1990)."""
import numpy as np

NOTES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
# Tônicas cuja grafia usual usa bemóis
_FLAT_MAJOR = {5, 10, 3, 8, 1, 6}
_FLAT_MINOR = {2, 7, 0, 5, 10, 3}
AMBIGUITY_MARGIN = 0.10  # heurístico, não calibrado


def prefers_flats(tonic: int, mode: str) -> bool:
    return tonic in (_FLAT_MAJOR if mode == "major" else _FLAT_MINOR)


def note_name(pc: int, flats: bool) -> str:
    return (NOTES_FLAT if flats else NOTES_SHARP)[pc % 12]


def estimate_key(chroma: np.ndarray) -> dict:
    mean = chroma.mean(axis=1)
    cands = []
    for tonic in range(12):
        for mode, prof in (("major", KK_MAJOR), ("minor", KK_MINOR)):
            r = float(np.corrcoef(mean, np.roll(prof, tonic))[0, 1])
            cands.append((r, tonic, mode))
    cands.sort(reverse=True)
    (r1, t1, m1), (r2, t2, m2) = cands[0], cands[1]
    flats = prefers_flats(t1, m1)
    rel_t, rel_m = ((t1 + 9) % 12, "minor") if m1 == "major" else ((t1 + 3) % 12, "major")
    margin = r1 - r2
    warnings = []
    if margin < AMBIGUITY_MARGIN:
        warnings.append(
            f"Tonalidade ambígua: {note_name(t1, flats)} {m1} e {note_name(t2, prefers_flats(t2, m2))} {m2} "
            f"têm correlação próxima (margem {margin:.3f})."
        )
    if (t2, m2) == (rel_t, rel_m):
        warnings.append("A segunda candidata é a tonalidade relativa; maior/menor relativos compartilham as mesmas notas.")
    return {
        "tonic": note_name(t1, flats), "tonic_pc": t1, "mode": m1,
        "name": f"{note_name(t1, flats)} {m1}",
        "relative": {"tonic": note_name(rel_t, prefers_flats(rel_t, rel_m)), "mode": rel_m},
        "correlation": round(r1, 3),
        "margin_to_second": round(margin, 3),
        "alternatives": [{"name": f"{note_name(t, prefers_flats(t, m))} {m}", "correlation": round(r, 3)} for r, t, m in cands[1:4]],
        "prefers_flats": flats,
        "confidence_note": "Correlação com perfis tonais; não é uma probabilidade calibrada.",
        "warnings": warnings,
    }
