"""Pós-processamento temporal dos segmentos de acorde: remove artefatos, preserva mudanças harmônicas legítimas.

Entra: segmentos do BTC já decodificados (Viterbi + fusão < 0,25 s) com p/alternatives. Regras, nesta ordem, até estabilizar:
  R1  segmentos vizinhos com o MESMO rótulo viram um só (a divisão era artefato).
  R2  "piscada": segmento curto (< blip_s) E de baixa confiança (p < MIN_P ou ambíguo) é absorvido se
      (a) os dois vizinhos têm o mesmo rótulo (X y X -> X), ou
      (b) ele tem a mesma raiz de um vizinho (mesma harmonia com qualidade/baixo duvidoso), ou
      (c) o rótulo de um vizinho está entre as 3 alternativas do próprio modelo para ele.
      Caso contrário a mudança é preservada: nunca se une acordes diferentes só para reduzir a contagem.
  R3  pausa (N) curta (< REST_MIN_S) entre dois acordes é respiração/decaimento: absorvida pelo acorde anterior.
      N no começo e no fim da música é preservado (início/fim reais); N longo no meio também.
Um acorde curto E confiante (p ≥ MIN_P e não ambíguo) nunca é tocado: acordes rápidos legítimos ficam.
blip_s é adaptativo: max(0,5 s, 1 batida), pois a unidade da harmonia é a batida/compasso. Cada segmento ganha kind
("chord"|"rest"). A duração total e os tempos das fronteiras restantes não mudam (só somem fronteiras).
Os limiares são heurísticas fixadas a priori; o efeito é medido em eval/ (docs/avaliacao.md).
"""
MIN_P = 0.65
MIN_BLIP_S = 0.5
REST_MIN_S = 1.0


def _label(s):
    return s["chord"]


def _merge(a, b, keep):
    """Une b em a (a vem antes). 'keep' é o segmento cujo rótulo/probabilidades sobrevivem."""
    da, db = a["end"] - a["start"], b["end"] - b["start"]
    out = dict(keep)
    out["start"], out["end"] = a["start"], b["end"]
    for k in ("p", "score", "root_p"):
        if keep.get(k) is not None and a.get(k) is not None and b.get(k) is not None:
            out[k] = round((a[k] * da + b[k] * db) / (da + db), 3)
    return out


def smooth_chords(segs: list, beat_len_s: float = 0.5) -> tuple:
    blip_s = max(MIN_BLIP_S, beat_len_s)
    segs = [dict(s) for s in segs]
    log = {"merged_same_label": 0, "absorbed_blips": 0, "absorbed_short_rests": 0}
    changed = True
    while changed and len(segs) > 1:
        changed = False
        # R1
        out = [segs[0]]
        for s in segs[1:]:
            if _label(s) == _label(out[-1]):
                out[-1] = _merge(out[-1], s, out[-1])
                log["merged_same_label"] += 1
                changed = True
            else:
                out.append(s)
        segs = out
        # R2/R3: um segmento por varredura (os índices mudam a cada fusão)
        for i, s in enumerate(segs):
            dur = s["end"] - s["start"]
            prev, nxt = (segs[i - 1] if i > 0 else None), (segs[i + 1] if i + 1 < len(segs) else None)
            if s.get("root") is None:                              # R3: pausa
                if prev and nxt and prev.get("root") is not None and nxt.get("root") is not None and dur < REST_MIN_S:
                    segs[i - 1] = dict(prev, end=s["end"])
                    del segs[i]
                    log["absorbed_short_rests"] += 1
                    changed = True
                    break
                continue
            low_conf = s.get("p") is None or s["p"] < MIN_P or s.get("ambiguous", False)
            if dur >= blip_s or not low_conf or not (prev and nxt):
                continue
            if prev.get("root") is None or nxt.get("root") is None:
                continue
            alts = {a["chord"] for a in s.get("alternatives", [])}
            target = None
            if _label(prev) == _label(nxt):
                target = "both"
            else:
                same_root = [n for n in (prev, nxt) if n["root"] == s["root"]]
                if same_root:
                    target = max(same_root, key=lambda n: n["end"] - n["start"])
                else:
                    in_alt = [n for n in (prev, nxt) if _label(n) in alts]
                    if in_alt:
                        target = max(in_alt, key=lambda n: n["end"] - n["start"])
            if target is None:
                continue
            if target == "both":
                merged = _merge(_merge(prev, s, prev), nxt, prev)
                segs[i - 1:i + 2] = [merged]
            elif target is prev:
                segs[i - 1:i + 1] = [_merge(prev, s, prev)]
            else:
                segs[i:i + 2] = [_merge(s, nxt, nxt)]
            log["absorbed_blips"] += 1
            changed = True
            break
    for s in segs:
        s["kind"] = "rest" if s.get("root") is None else "chord"
    return segs, log
