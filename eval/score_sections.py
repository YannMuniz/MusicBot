"""Avalia seções detectadas contra a estrutura da cifra (alinhada ao áudio: referência PRATA).

Uso: python score_sections.py sections.json referencia.silver.lab.meta.json duracao_s [--out r.json]
A referência vem das marcações da cifra ([Intro], [Refrão]...) com tempos estimados (±0,5 s): fronteira = início do
primeiro acorde de cada bloco. Métricas (mir_eval.segment): precisão/revocação/F das fronteiras com tolerância de 3 s
e de 0,5 s; F de pares (rótulos: nome da seção na cifra vs. repeat_group do sistema, mede se trechos que se repetem
ficaram no mesmo grupo); contagem e duração mediana. NÃO é objetivo reduzir seções: veja razão est/ref junto com F.
Os nomes da cifra são só o gabarito: o sistema continua usando rótulos neutros.
"""
import argparse
import json
import re

import mir_eval
import numpy as np


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().replace("ã", "a").replace("é", "e")).replace("final", "") or name


def reference(meta_path: str, duration: float):
    spans = json.load(open(meta_path, encoding="utf-8"))["spans"]
    blocks = {}
    for s in spans:
        blocks.setdefault(s["section_index"], []).append(s)
    idx = sorted(blocks)
    starts = [0.0] + [blocks[i][0]["start"] for i in idx[1:]]
    ends = starts[1:] + [duration]
    ivs = np.array(list(zip(starts, ends)))
    labels = [_norm(blocks[i][0]["section"]) for i in idx]
    return ivs, labels


def score(sections: list, meta_path: str, duration: float) -> dict:
    ref_iv, ref_lb = reference(meta_path, duration)
    est_iv = np.array([[s["start"], s["end"]] for s in sections])
    est_lb = [str(s["repeat_group"]) for s in sections]
    est_iv[-1, 1] = max(est_iv[-1, 1], duration)
    out = {"n_ref": len(ref_iv), "n_est": len(est_iv), "ratio_est_to_ref": round(len(est_iv) / len(ref_iv), 2),
           "median_section_s": round(float(np.median(est_iv[:, 1] - est_iv[:, 0])), 1),
           "median_ref_section_s": round(float(np.median(ref_iv[:, 1] - ref_iv[:, 0])), 1)}
    for w in (3.0, 0.5):
        p, r, f = mir_eval.segment.detection(ref_iv, est_iv, window=w, trim=True)
        out[f"boundary_w{w}s"] = {"precision": round(float(p), 3), "recall": round(float(r), 3), "f": round(float(f), 3)}
    p, r, f = mir_eval.segment.pairwise(ref_iv, ref_lb, est_iv, est_lb)
    out["pairwise"] = {"precision": round(float(p), 3), "recall": round(float(r), 3), "f": round(float(f), 3)}
    out["ref_sections"] = [{"name": l, "start": round(float(a), 1), "end": round(float(b), 1)} for (a, b), l in zip(ref_iv, ref_lb)]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sections"); ap.add_argument("meta"); ap.add_argument("duration", type=float); ap.add_argument("--out")
    a = ap.parse_args()
    data = json.load(open(a.sections, encoding="utf-8"))
    res = score(data["sections"], a.meta, a.duration)
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in res.items() if k != "ref_sections"}, ensure_ascii=False))
