"""Compara a ORDEM dos acordes detectados com uma cifra sem tempos (eval/references/*.chart.json).

Uso: python compare_chart.py chords.json cifra.chart.json

Limites (importante): a cifra nao tem tempos, entao isto NAO e uma metrica por segundo (use
score_chords.py com .lab para isso). Mede se a progressao sai na ordem certa, por alinhamento
de distancia de edicao entre as duas sequencias (repeticoes consecutivas colapsadas).
Equivalencias da cifra: C2 -> C/Csus2/Cadd9; A#9 -> Bb (add9); F/A -> F (baixo nao e avaliado).
Dois niveis: 'raiz' (so a nota) e 'triade' (raiz + maior/menor).
"""
import json
import re
import sys

FLAT = {"A#": "Bb", "C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab"}


def parse(ch):
    m = re.match(r"^([A-G][#b]?)(.*)$", ch)
    if not m:
        return None
    root, rest = m.groups()
    root = FLAT.get(root, root)
    rest = rest.split("/")[0]
    minor = rest.startswith("m") and not rest.startswith("maj")
    return root, ("m" if minor else "M")


def collapse(seq):
    out = []
    for x in seq:
        if x and (not out or out[-1] != x):
            out.append(x)
    return out


def edit_alignment(a, b):
    n, m = len(a), len(b)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    i, j, match = n, m, 0
    while i and j:
        if a[i - 1] == b[j - 1] and d[i][j] == d[i - 1][j - 1]:
            match, i, j = match + 1, i - 1, j - 1
        elif d[i][j] == d[i - 1][j - 1] + 1:
            i, j = i - 1, j - 1
        elif d[i][j] == d[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return d[n][m], match


def align_pairs(a, b):
    """Pares (i, j) de itens iguais no alinhamento de distância de edição entre as listas a e b."""
    n, m = len(a), len(b)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    i, j, pairs = n, m, []
    while i and j:
        if a[i - 1] == b[j - 1] and d[i][j] == d[i - 1][j - 1]:
            pairs.append((i - 1, j - 1)); i, j = i - 1, j - 1
        elif d[i][j] == d[i - 1][j - 1] + 1:
            i, j = i - 1, j - 1
        elif d[i][j] == d[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def bass_report(det, ref):
    """Inversões: nos acordes alinhados por ordem, compara baixo da cifra (F/A) com o baixo estimado.
    Alinha pelas raízes (sem colapsar); só vale como verificação de ordem, sem tempos."""
    pr = [parse(c) for c in ref]
    ref_root = [p[0] if p else None for p in pr]
    ref_bass = []
    for c in ref:
        m = re.match(r"^[A-G][#b]?[^/]*/([A-G][#b]?)$", c)
        ref_bass.append(FLAT.get(m.group(1), m.group(1)) if m else None)
    det_root = [(parse(c["chord"]) or (None,))[0] for c in det]
    pairs = align_pairs(det_root, ref_root)
    tp = fn = fp = tn = raw_ok = n_slash = 0
    for j_det, i_ref in pairs:
        s = det[j_det]
        if "bass" not in s:
            continue
        inv = s.get("inversion")
        inv_bass = FLAT.get(inv.split("/")[1], inv.split("/")[1]) if inv else None
        est_note = FLAT.get(s["bass"]["note"], s["bass"]["note"])
        if ref_bass[i_ref]:
            n_slash += 1
            raw_ok += est_note == ref_bass[i_ref]
            tp += inv_bass == ref_bass[i_ref]
            fn += inv_bass != ref_bass[i_ref]
        else:
            fp += inv_bass is not None
            tn += inv_bass is None
    return {"pares_alinhados": len(pairs), "cifra_com_baixo_invertido": n_slash,
            "baixo_estimado_igual_ao_da_cifra_nos_invertidos": raw_ok,
            "inversoes_corretas": tp, "inversoes_perdidas": fn, "inversoes_falsas": fp, "sem_inversao_corretos": tn}


def main(chords_path, chart_path):
    det = json.load(open(chords_path))["segments"]
    chart = json.load(open(chart_path))
    ref = [c for s in chart["sections"] for c in s["chords"]]
    out = {"cifra_total": len(ref), "detectados_total": len(det)}
    for level in ("raiz", "triade"):
        pick = (lambda p: p[0]) if level == "raiz" else (lambda p: p[0] + p[1])
        a = collapse([pick(p) if (p := parse(c)) else None for c in ref])
        b = collapse([pick(p) if (p := parse(c["chord"])) else None for c in det])
        dist, match = edit_alignment(b, a)
        out[level] = {
            "cifra_colapsada": len(a), "detectada_colapsada": len(b), "distancia_edicao": dist,
            "acordes_da_cifra_encontrados_em_ordem": match,
            "cobertura_da_cifra": round(match / len(a), 3),
            "precisao_da_detectada": round(match / len(b), 3),
        }
    out["baixo"] = bass_report(det, ref)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
