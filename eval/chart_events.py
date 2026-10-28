"""Avaliação por EVENTO contra uma referência prata (cifra alinhada por raiz).

Uso: python chart_events.py chords.json referencia.silver.lab.meta.json [--out resultado.json]

Por que por evento: acordes consecutivos de mesma raiz na cifra (A4 A, E6 E, A A4 A) não têm fronteira recuperável
pelo alinhamento por raiz. Então agrupamos esses acordes e perguntamos, para cada acorde da cifra, o que o sistema
produziu dentro do intervalo do GRUPO. Isto mede 'o rótulo da cifra apareceu?', não precisão por segundo.
Por rótulo da cifra: n eventos; raiz_certa; rotulo_exato (algum segmento sobreposto tem o mesmo rótulo final);
na_alternativa (o rótulo está nas 3 alternativas do modelo em algum segmento); so_triade (o sistema deu só a tríade
da mesma raiz); dica_de_cor (possible_additions sugeriu esse rótulo, evidência fraca).
Limites: depende da cifra estar certa e do alinhamento; uma só música não generaliza.
"""
import argparse
import json
import re
from collections import defaultdict

FLAT = {"A#": "Bb", "C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab"}


def base(label):
    return label.split("/")[0]


def root(label):
    m = re.match(r"^([A-G][#b]?)", label)
    return FLAT.get(m.group(1), m.group(1))


def norm(label):
    """Normaliza só a grafia da raiz/baixo (A# -> Bb) para comparar rótulos."""
    head, _, bass = label.partition("/")
    m = re.match(r"^([A-G][#b]?)(.*)$", head)
    if not m:
        return label
    out = FLAT.get(m.group(1), m.group(1)) + m.group(2)
    if bass:
        out += "/" + FLAT.get(bass, bass)
    return out


def main(chords_path, meta_path, out=None):
    segs = json.load(open(chords_path, encoding="utf-8"))["segments"]
    spans = json.load(open(meta_path, encoding="utf-8"))["spans"]
    groups, cur = [], []
    for sp in spans:
        if cur and root(sp["label"]) != root(cur[-1]["label"]):
            groups.append(cur); cur = []
        cur.append(sp)
    if cur:
        groups.append(cur)
    stats = defaultdict(lambda: defaultdict(int))
    rows = []
    for g in groups:
        a, b = g[0]["start"], g[-1]["end"]
        over = [s for s in segs if min(b, s["end"]) - max(a, s["start"]) > 0.3 * min(b - a, s["end"] - s["start"]) and s["root"] is not None]
        finals = {norm(s["chord"]) for s in over}
        harmonics = {norm(s.get("harmonic_label", s["chord"])) for s in over}
        alts = {norm(x["chord"]) for s in over for x in s.get("alternatives", [])}
        hints = {norm(x["label"].replace("(", "").replace("?)", "")) for s in over for x in s.get("possible_additions", [])}
        roots = {root(s["chord"]) for s in over}
        for sp in g:
            lab, st = norm(sp["label"]), stats[sp["cifra"]]
            st["n"] += 1
            st["raiz_certa"] += root(lab) in roots
            exact = lab in finals
            st["rotulo_exato"] += exact
            st["na_alternativa"] += (not exact) and lab in alts
            plain = {root(lab), root(lab) + "m"}
            st["so_triade"] += (not exact) and bool(finals & plain) and finals <= plain | {lab}
            st["dica_de_cor"] += lab in hints
            rows.append({"cifra": sp["cifra"], "label": lab, "grupo": [round(a, 1), round(b, 1)], "sistema": sorted(finals),
                         "exato": exact})
    res = {"eventos_por_rotulo_da_cifra": {k: dict(v) for k, v in sorted(stats.items())}, "eventos": rows}
    if out:
        json.dump(res, open(out, "w"), indent=1, ensure_ascii=False)
    print(f"{'cifra':6s} {'n':>3s} {'raiz':>5s} {'exato':>6s} {'alt':>4s} {'triade':>7s} {'dica':>5s}")
    for k, v in sorted(stats.items()):
        print(f"{k:6s} {v['n']:3d} {v['raiz_certa']:5d} {v['rotulo_exato']:6d} {v['na_alternativa']:4d} {v['so_triade']:7d} {v['dica_de_cor']:5d}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("chords"); ap.add_argument("meta"); ap.add_argument("--out")
    a = ap.parse_args()
    main(a.chords, a.meta, a.out)
