"""PoC Harmonia AI: tonalidade + acordes (baseline librosa) a partir de um arquivo de audio real.

Uso (dentro do container): analyze.py /data/arquivo.mp3 [--out /out/resultado.json]
Metodo:
  - tom: chromagrama CQT (componente harmonica) agregado + perfis de Krumhansl-Schmuckler
  - acordes: chroma sincronizado nas batidas + templates maior/menor + Viterbi (permanencia alta)
Nada aqui e aleatorio nem predefinido: tudo e inferido do sinal.
"""
import argparse
import json
import sys
import time

import librosa
import numpy as np

SR = 22050
HOP = 512
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Perfis de Krumhansl-Kessler (1990)
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def estimate_key(chroma: np.ndarray) -> dict:
    mean = chroma.mean(axis=1)
    scores = []
    for tonic in range(12):
        for mode, prof in (("major", KK_MAJOR), ("minor", KK_MINOR)):
            r = np.corrcoef(mean, np.roll(prof, tonic))[0, 1]
            scores.append((float(r), NOTES[tonic], mode))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    margin = best[0] - second[0]
    out = {
        "tonic": best[1],
        "mode": best[2],
        "correlation": round(best[0], 3),
        "margin_to_second": round(margin, 3),
        "alternatives": [{"key": f"{n} {m}", "correlation": round(r, 3)} for r, n, m in scores[1:4]],
        "warnings": [],
    }
    if margin < 0.05:
        out["warnings"].append("Tonalidade ambigua: margem pequena entre as duas melhores candidatas.")
    return out


def chord_templates():
    labels, templates = [], []
    for root in range(12):
        for suffix, intervals in (("", (0, 4, 7)), ("m", (0, 3, 7))):
            t = np.zeros(12)
            t[[(root + i) % 12 for i in intervals]] = 1.0
            labels.append(NOTES[root] + suffix)
            templates.append(t / np.linalg.norm(t))
    return labels, np.array(templates)


def detect_chords(y: np.ndarray, chroma: np.ndarray, tempo_stay: float = 0.9):
    y_perc = librosa.effects.percussive(y)
    onset_env = librosa.onset.onset_strength(y=y_perc, sr=SR, hop_length=HOP)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=SR, hop_length=HOP)
    tempo = float(np.atleast_1d(tempo)[0])
    sync = librosa.util.sync(chroma, beats, aggregate=np.median)  # (12, n_beats-ish)
    bounds = np.concatenate([[0], beats, [chroma.shape[1]]])
    bounds = np.unique(bounds)
    times = librosa.frames_to_time(bounds, sr=SR, hop_length=HOP)

    labels, templates = chord_templates()
    norm = np.linalg.norm(sync, axis=0, keepdims=True)
    norm[norm == 0] = 1.0
    sim = templates @ (sync / norm)  # (24, T) similaridade cosseno
    # emissao: softmax da similaridade
    emis = np.exp(sim * 8.0)
    emis /= emis.sum(axis=0, keepdims=True)

    n = len(labels)
    trans = np.full((n, n), (1 - tempo_stay) / (n - 1))
    np.fill_diagonal(trans, tempo_stay)
    path = librosa.sequence.viterbi(emis, trans)

    segs = []
    for i, c in enumerate(path):
        start, end = float(times[i]), float(times[i + 1])
        conf = float(emis[c, i])
        if segs and segs[-1]["chord"] == labels[c]:
            s = segs[-1]
            d_old = s["end"] - s["start"]
            s["confidence"] = round((s["confidence"] * d_old + conf * (end - start)) / (end - s["start"]), 3)
            s["end"] = round(end, 3)
        else:
            segs.append({"start": round(start, 3), "end": round(end, 3), "chord": labels[c], "confidence": round(conf, 3)})
    return segs, tempo, beats


def fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def detect_sections(y, chroma, beats, segs, duration):
    """Estrutura: fronteiras por agrupamento aglomerativo (beat-sync, chroma+MFCC); letras por similaridade."""
    from scipy.cluster.hierarchy import fcluster, linkage

    mfcc = librosa.feature.mfcc(y=y, sr=SR, hop_length=HOP, n_mfcc=13)
    feats = np.vstack([librosa.util.normalize(chroma, axis=0), librosa.util.normalize(mfcc[1:], axis=0)])
    sync = librosa.util.sync(feats, beats, aggregate=np.mean)
    sync = (sync - sync.mean(axis=1, keepdims=True)) / (sync.std(axis=1, keepdims=True) + 1e-9)
    k = int(np.clip(round(duration / 25), 4, 12))
    # suaviza no tempo para nao quebrar em variacoes curtas
    from scipy.ndimage import uniform_filter1d
    sm = uniform_filter1d(sync, size=8, axis=1)
    bidx = librosa.segment.agglomerative(sm, k)
    btimes = librosa.frames_to_time(np.unique(np.concatenate([[0], beats[np.clip(bidx - 1, 0, len(beats) - 1)]])), sr=SR, hop_length=HOP)
    edges = np.unique(np.concatenate([[0.0], btimes, [duration]]))
    # une trechos muito curtos (<8 s) ao anterior
    keep = [edges[0]]
    for e in edges[1:-1]:
        if e - keep[-1] >= 8.0 and duration - e >= 8.0:
            keep.append(e)
    keep.append(duration)

    bt = librosa.frames_to_time(beats, sr=SR, hop_length=HOP)
    vecs = []
    for a, b in zip(keep[:-1], keep[1:]):
        m = (bt >= a) & (bt < b)
        n = min(sync.shape[1], len(m))
        sel = sync[:, :n][:, m[:n]]
        vecs.append(sel.mean(axis=1) if sel.shape[1] else np.zeros(sync.shape[0]))
    vecs = np.array(vecs)
    if len(vecs) > 1:
        Z = linkage(vecs, method="average", metric="cosine")
        cl = fcluster(Z, t=0.45, criterion="distance")
    else:
        cl = np.array([1])
    letters, order = {}, []
    for c in cl:
        if c not in letters:
            letters[c] = chr(ord("A") + len(letters))
    out = []
    for i, (a, b) in enumerate(zip(keep[:-1], keep[1:])):
        chords = [x for x in segs if x["end"] > a and x["start"] < b]
        prog = []
        for x in chords:
            if not prog or prog[-1] != x["chord"]:
                prog.append(x["chord"])
        hint = "intro (sugestao pela posicao)" if i == 0 else ("final (sugestao pela posicao)" if i == len(keep) - 2 else None)
        out.append({"index": i + 1, "label": letters[cl[i]], "start": round(float(a), 2), "end": round(float(b), 2),
                    "hint": hint, "progression": prog})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--out")
    args = ap.parse_args()

    t0 = time.time()
    try:
        y, _ = librosa.load(args.audio, sr=SR, mono=True)
    except Exception as e:  # decodificacao falhou
        print(json.dumps({"status": "failed", "error": f"decode_error: {e}"}, ensure_ascii=False))
        return 2
    duration = len(y) / SR
    if duration < 5 or float(np.max(np.abs(y))) < 1e-4:
        print(json.dumps({"status": "failed", "error": "audio muito curto ou silencioso"}))
        return 2

    y_harm = librosa.effects.harmonic(y)
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=SR, hop_length=HOP)
    key = estimate_key(chroma)
    segs, tempo, beats = detect_chords(y, chroma)
    sections = detect_sections(y, chroma, beats, segs, duration)

    result = {
        "status": "completed",
        "engine": {"name": "librosa-baseline", "librosa": librosa.__version__, "vocabulary": "maj/min"},
        "duration": round(duration, 2),
        "tempo_bpm": round(tempo, 1),
        "key": key,
        "sections": sections,
        "segments": segs,
        "processing_seconds": round(time.time() - t0, 1),
    }
    lines = [f"Tom: {key['tonic']} {key['mode']}  |  {duration:.0f}s  |  {tempo:.0f} BPM", ""]
    for sec in sections:
        lines.append(f"[{sec['index']}] secao {sec['label']}  {fmt(sec['start'])} - {fmt(sec['end'])}" + (f"  <{sec['hint']}>" if sec['hint'] else ""))
        lines.append("      " + " | ".join(sec["progression"]))
    report = "\n".join(lines)
    print(report, file=sys.stderr)
    if args.out:
        with open(args.out.replace(".json", ".txt"), "w", encoding="utf-8") as f:
            f.write(report + "\n")
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
