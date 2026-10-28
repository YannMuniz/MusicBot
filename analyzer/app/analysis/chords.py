"""Acordes maiores/menores: templates + similaridade cosseno por batida + Viterbi (permanência alta)."""
import librosa
import numpy as np

from .tonality import note_name

STAY = 0.9  # probabilidade de manter o acorde entre batidas
TEMPERATURE = 8.0


def _templates():
    ts, meta = [], []
    for root in range(12):
        for quality, iv in (("maj", (0, 4, 7)), ("min", (0, 3, 7))):
            t = np.zeros(12)
            t[[(root + i) % 12 for i in iv]] = 1.0
            ts.append(t / np.linalg.norm(t))
            meta.append((root, quality))
    return np.array(ts), meta


def chord_name(root: int, quality: str, flats: bool) -> str:
    return note_name(root, flats) + ("m" if quality == "min" else "")


def detect_chords(chroma_sync: np.ndarray, edges_s: np.ndarray, flats: bool) -> list:
    """chroma_sync: (12, n); edges_s: n+1 tempos de fronteira. Retorna segmentos fundidos."""
    templates, meta = _templates()
    norm = np.linalg.norm(chroma_sync, axis=0, keepdims=True)
    norm[norm == 0] = 1.0
    sim = templates @ (chroma_sync / norm)
    emis = np.exp(sim * TEMPERATURE)
    emis /= emis.sum(axis=0, keepdims=True)
    n = len(meta)
    trans = np.full((n, n), (1 - STAY) / (n - 1))
    np.fill_diagonal(trans, STAY)
    path = librosa.sequence.viterbi(emis, trans)

    segs = []
    for i, c in enumerate(path):
        a, b, sc = float(edges_s[i]), float(edges_s[i + 1]), float(emis[c, i])
        root, quality = meta[c]
        if segs and segs[-1]["root"] == root and segs[-1]["quality"] == quality:
            s = segs[-1]
            s["_w"] += b - a
            s["_sum"] += sc * (b - a)
            s["end"] = round(b, 3)
        else:
            segs.append({"start": round(a, 3), "end": round(b, 3), "chord": chord_name(root, quality, flats),
                         "root": root, "quality": quality, "_w": b - a, "_sum": sc * (b - a)})
    for s in segs:
        s["score"] = round(s.pop("_sum") / max(s.pop("_w"), 1e-9), 3)
    return segs


def segments_from_runs(runs, frame_s: float, duration: float, flats: bool, post=None) -> list:
    """Converte as corridas do decodificador neural em segmentos {start,end,chord,root,quality,score}."""
    from .btc_engine import SUFFIX, class_to_chord, describe_runs

    def name_of(idx):
        r, q = class_to_chord(idx)
        return "N" if r is None else note_name(r, flats) + SUFFIX[q]

    extra = describe_runs(post, runs, name_of) if post is not None else [None] * len(runs)
    segs = []
    for (c, a, b, sc), ex in zip(runs, extra):
        start, end = a * frame_s, min(b * frame_s, duration)
        if end <= start:
            continue
        root, quality = class_to_chord(c)
        name = "N" if root is None else note_name(root, flats) + SUFFIX[quality]
        segs.append({"start": round(start, 3), "end": round(end, 3), "chord": name,
                     "root": root, "quality": quality, "score": round(sc, 3), **(ex or {})})
    if segs:
        segs[0]["start"] = 0.0
        segs[-1]["end"] = round(duration, 3)
    return segs
