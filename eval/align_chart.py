"""Alinha a SEQUÊNCIA de uma cifra (sem tempos) ao áudio e gera um .lab 'prata' (início fim acorde).

Uso (dentro do container do analisador): PYTHONPATH=analyzer python eval/align_chart.py audio.mp3 chart.json saida.lab

Método: HMM esquerda→direita (cada acorde da cifra, na ordem, com 'N' opcional no começo e no fim), Viterbi sobre a
posterior de RAIZ do BTC (soma das 14 qualidades daquela raiz). Só a raiz entra no alinhamento, de propósito: a
QUALIDADE (6ª, sus, maior/menor) que será avaliada depois não influencia os tempos, evitando viés a favor do BTC.
É uma referência PRATA, não ouro: os rótulos vêm da cifra (humana), mas os tempos são estimados e a cifra pode divergir
da gravação. Fronteiras têm incerteza de ~0,1–0,5 s. Resultado e qualidade do alinhamento vão num .json ao lado.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

NOTES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def chart_chords(chart):
    resolve = chart.get("resolve", {})
    out = []
    for si, sec in enumerate(chart["sections"]):
        for c in sec["chords"]:
            label = resolve.get(c, c)
            m = re.match(r"^([A-G][#b]?)", c)
            out.append({"cifra": c, "label": label, "root": NOTES[m.group(1)], "section": sec["name"], "section_index": si})
    return out


def align(post, chords, frame_s):
    """post: (170, T). Retorna lista de (índice_do_acorde|None, início_quadro, fim_quadro)."""
    T, K = post.shape[1], len(chords)
    floor = 1e-3
    emis = np.empty((K + 2, T))
    emis[0] = emis[K + 1] = np.log(post[169] + floor)                  # N inicial/final
    for k, c in enumerate(chords):
        emis[k + 1] = np.log(post[c["root"] * 14:(c["root"] + 1) * 14].sum(axis=0) + floor)
    p_adv = min(0.5, (K + 2) / T)
    stay, adv = np.log(1 - p_adv), np.log(p_adv)
    dp = np.full((K + 2, T), -np.inf)
    bp = np.zeros((K + 2, T), dtype=np.int16)
    dp[0, 0] = emis[0, 0]
    dp[1, 0] = emis[1, 0] + adv - np.log(2)
    for t in range(1, T):
        for s in range(K + 2):
            a = dp[s, t - 1] + stay
            b = dp[s - 1, t - 1] + adv if s > 0 else -np.inf
            if b > a:
                dp[s, t], bp[s, t] = b + emis[s, t], s - 1
            else:
                dp[s, t], bp[s, t] = a + emis[s, t], s
    s = int(np.argmax([dp[K, T - 1], dp[K + 1, T - 1]])) + K
    path = [0] * T
    for t in range(T - 1, -1, -1):
        path[t] = s
        s = bp[s, t]
    runs, start = [], 0
    for t in range(1, T + 1):
        if t == T or path[t] != path[start]:
            st = path[start]
            runs.append((None if st in (0, K + 1) else int(st) - 1, start, t))
            start = t
    return runs


def main(audio, chart_path, out_lab):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyzer"))
    from app.analysis.btc_engine import FRAME_S, BtcEngine
    from app.audio import load_audio
    chart = json.load(open(chart_path, encoding="utf-8"))
    chords = chart_chords(chart)
    y = load_audio(Path(audio))
    post = BtcEngine(Path("/opt/models/btc_large_voca.pt")).posteriors(y)
    runs = align(post, chords, FRAME_S)
    dur = len(y) / 22050
    lines, spans = [], []
    for k, a, b in runs:
        st, en = a * FRAME_S, min(b * FRAME_S, dur)
        if en <= st:
            continue
        lab = "N" if k is None else chords[k]["label"]
        lines.append(f"{st:.3f} {en:.3f} {lab}")
        if k is not None:
            root_p = float(post[chords[k]["root"] * 14:(chords[k]["root"] + 1) * 14, a:b].sum(axis=0).mean())
            spans.append({"index": k, "cifra": chords[k]["cifra"], "label": lab, "section": chords[k]["section"], "section_index": chords[k]["section_index"],
                          "start": round(st, 3), "end": round(en, 3), "root_posterior": round(root_p, 3)})
    Path(out_lab).write_text("\n".join(lines) + "\n", encoding="utf-8")
    short = [s for s in spans if s["end"] - s["start"] < 0.5]
    low = [s for s in spans if s["root_posterior"] < 0.5]
    meta = {"kind": "silver", "method": "forced alignment by BTC root marginals", "chart": chart_path, "audio": audio,
            "chords_in_chart": len(chords), "chords_placed": len(spans), "mean_root_posterior": round(float(np.mean([s["root_posterior"] for s in spans])), 3),
            "spans_shorter_than_0_5s": len(short), "spans_with_root_posterior_below_0_5": len(low), "spans": spans}
    Path(str(out_lab) + ".meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if k != "spans"}, ensure_ascii=False))


if __name__ == "__main__":
    main(*sys.argv[1:4])
