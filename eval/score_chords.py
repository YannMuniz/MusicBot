"""Avalia acordes detectados contra uma referência (arquivo .lab: "inicio fim acorde" por linha).

Uso:  python score_chords.py <chords.json de uma música> <referencia.lab> [--out resultado.json]
Aceita rótulos Harte (C:min7) ou a notação do sistema (Cm7, Bbmaj7, F#dim, C/E ...).
Métricas (mir_eval.chord): root, majmin, sevenths, mirex, thirds, triads, tetrads = fração do tempo certo.
Só tem valor se a referência for confiável; nunca rode contra um rótulo produzido pelo próprio sistema.
"""
import argparse
import json
import re
import sys

import mir_eval
import numpy as np

SUFFIX_TO_HARTE = {"": "maj", "m": "min", "6": "maj6", "m6": "min6", "7": "7", "maj7": "maj7", "m7": "min7",
                   "mM7": "minmaj7", "dim": "dim", "dim7": "dim7", "m7(b5)": "hdim7", "aug": "aug",
                   "sus2": "sus2", "sus4": "sus4", "5": "5",
                   "9": "9", "m9": "min9", "maj9": "maj9", "add9": "maj(9)", "m(add9)": "min(9)",
                   "11": "11", "m11": "min11", "13": "13", "m13": "min13", "maj13": "maj13",
                   "7sus4": "sus4(b7)", "7(b9)": "7(b9)", "7(#9)": "7(#9)", "7(#5)": "aug(b7)", "7(b5)": "7(b5)"}


def to_harte(label: str) -> str:
    label = label.strip()
    if label in ("N", "X") or ":" in label:
        return label
    m = re.match(r"^([A-G][#b]?)([^/]*)(?:/(.+))?$", label)
    if not m:
        return label
    root, suffix, bass = m.groups()
    if suffix in ("2", "4"):
        raise ValueError(f"Rótulo ambíguo {label!r}: em cifras populares '{suffix}' pode ser sus{suffix} ou add{ {'2': 9, '4': 4}[suffix] }. "
                         "Escreva explicitamente (ex.: Dsus2, Dadd9, Asus4, Aadd4) na referência.")
    q = SUFFIX_TO_HARTE.get(suffix)
    if q is None:
        raise ValueError(f"Acorde não suportado na avaliação: {label!r}")
    return f"{root}:{q}" + (f"/{bass}" if bass else "")


def load_lab(path):
    iv, lb = [], []
    for line in open(path, encoding="utf-8"):
        parts = line.split(None, 2)
        if len(parts) == 3:
            iv.append([float(parts[0]), float(parts[1])])
            lb.append(to_harte(parts[2]))
    return np.array(iv), lb


def load_est(path, harmonic_only=False):
    segs = json.load(open(path, encoding="utf-8"))["segments"]
    lab = [to_harte((s.get("harmonic_label") if harmonic_only else None) or s["chord"]) for s in segs]
    return np.array([[s["start"], s["end"]] for s in segs]), lab


def load_ambiguous(path):
    return [bool(s.get("ambiguous", False)) for s in json.load(open(path, encoding="utf-8"))["segments"]]


def score(est, ref):
    (ei, el), (ri, rl) = est, ref
    # alinha a estimativa à extensão da referência (preenche/recorta com "sem acorde")
    ei, el = mir_eval.util.adjust_intervals(ei, el, ri.min(), ri.max(), mir_eval.chord.NO_CHORD, mir_eval.chord.NO_CHORD)
    return {k: round(float(v), 4) for k, v in mir_eval.chord.evaluate(ri, rl, ei, el).items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chords_json")
    ap.add_argument("reference_lab")
    ap.add_argument("--out")
    ap.add_argument("--detailed", action="store_true", help="métricas por tipo, inversões, fragmentação, ambiguidade")
    ap.add_argument("--harmonic-only", action="store_true", help="ignora o baixo: usa 'harmonic_label' (baseline sem inversões)")
    ap.add_argument("--analysis", help="analysis.json da mesma música: registra algoritmo, parâmetros e tempo de processamento")
    a = ap.parse_args()
    if a.detailed:
        from metrics import detailed
        ei, el = load_est(a.chords_json, a.harmonic_only)
        ri, rl = load_lab(a.reference_lab)
        res = detailed(ei, el, ri, rl, load_ambiguous(a.chords_json))
        if a.analysis:
            an = json.load(open(a.analysis, encoding="utf-8"))
            res["run"] = {"run_id": an.get("run_id"), "algorithm": an["algorithm"]["name"], "version": an["algorithm"]["version"],
                          "parameters": an["algorithm"].get("parameters"), "processing_seconds": an.get("processing_seconds"),
                          "chords_labelled_with_bass": a.harmonic_only is False}
        text = json.dumps(res, indent=2, ensure_ascii=False)
        if a.out:
            open(a.out, "w").write(text)
        print(text)
        return 0
    res = score(load_est(a.chords_json), load_lab(a.reference_lab))
    text = json.dumps(res, indent=2)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
