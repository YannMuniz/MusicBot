"""Avalia notas transcritas contra a sequência de uma tablatura (referência por ORDEM, sem tempos).

Alinhamento local (Smith-Waterman) entre a sequência de alturas detectadas e a da tablatura. Reporta, por tolerância
(exata; ±1 semitom; dobrando oitavas), quantas notas da tablatura aparecem em ordem na transcrição (revocação) e que fração
das notas detectadas DENTRO do trecho alinhado corresponde à tablatura (precisão). Também a semelhança de histograma de
classes de altura. Não é uma métrica de tempo/duração. Referência prata: tablatura de usuário.
"""
import numpy as np

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _eq(a, b, tol, fold):
    if fold:
        d = (a - b) % 12
        return min(d, 12 - d) <= tol
    return abs(a - b) <= tol


def local_align(det, ref, tol=0, fold=False, match=2, miss=-1, gap=-1):
    n, m = len(det), len(ref)
    H = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = match if _eq(det[i - 1], ref[j - 1], tol, fold) else miss
            H[i, j] = max(0, H[i - 1, j - 1] + s, H[i - 1, j] + gap, H[i, j - 1] + gap)
    i, j = (int(v) for v in np.unravel_index(np.argmax(H), H.shape))
    end_i = i
    pairs = []
    while i > 0 and j > 0 and H[i, j] > 0:
        s = match if _eq(det[i - 1], ref[j - 1], tol, fold) else miss
        if H[i, j] == H[i - 1, j - 1] + s:
            if s == match:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif H[i, j] == H[i - 1, j] + gap:
            i -= 1
        else:
            j -= 1
    return pairs, i, end_i


def score(det_pitches: list, ref_pitches: list) -> dict:
    out = {"n_detected": len(det_pitches), "n_reference": len(ref_pitches)}
    for name, tol, fold in (("exact", 0, False), ("within_1_semitone", 1, False), ("pitch_class", 0, True)):
        pairs, start_i, end_i = local_align(det_pitches, ref_pitches, tol, fold)
        window = max(end_i - start_i, 1)
        out[name] = {"reference_notes_found_in_order": len(pairs), "recall": round(len(pairs) / max(len(ref_pitches), 1), 3),
                     "precision_in_aligned_window": round(len(pairs) / window, 3), "aligned_window_detected_notes": int(window)}
    h = lambda p: np.bincount(np.array(p) % 12, minlength=12) / max(len(p), 1)  # noqa: E731
    a, b = h(det_pitches), h(ref_pitches)
    out["pitch_class_histogram_cosine"] = round(float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)), 3)
    return out
