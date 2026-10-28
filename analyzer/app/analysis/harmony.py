"""Representação harmônica estruturada por segmento e rótulo final.

Cada segmento guarda, sem perder informação mesmo que a interface mostre um nome simplificado:
  model_label     rótulo bruto do BTC (ex.: "A")
  harmonic_label  acorde harmônico normalizado (igual ao model_label no BTC; nunca recebe baixo)
  chord           rótulo FINAL exibido: harmônico + "/baixo" quando a evidência de baixo passa nos critérios de bass.py
  structure       {root, quality, intervals, bass, inversion{...}, added[]}
  bass            diagnóstico do baixo (nota, votos, motivo de aceitar/recusar inversão)
  possible_additions  notas de cor com ALGUMA evidência no cromagrama (fraca, não validada; NÃO altera 'chord')

Convenção do projeto (cifras populares brasileiras são ambíguas): o sistema nunca escreve "2" nem "4" no rótulo.
sus2/sus4 só saem quando o BTC os prevê (terça substituída). Se o cromagrama indica 2ª/4ª COM a terça presente, o
nome sugerido é add9/add4; sem terça, sus2/sus4. Sempre como 'possible_additions', nunca como certeza.
Para referências (.lab) use rótulos explícitos (Dsus2, Dadd9); "D2"/"A4" são rejeitados na avaliação por serem ambíguos.
"""
import numpy as np

from .bass import CHORD_TONES
from .tonality import note_name

COLOR_TONES = {2: "2", 5: "4", 9: "6", 10: "b7", 11: "maj7"}   # intervalo (semitons) -> grau
MIN_COLOR_REL = 0.8          # força relativa mínima (heurística a priori, não calibrada)
MIN_COLOR_SEG_S = 1.0
THIRD_PRESENT_REL = 0.5
INVERSION_DEGREE = {3: "1", 4: "1", 6: "2", 7: "2", 8: "2", 9: "3", 10: "3", 11: "3"}


def _name_for(interval: int, third_present: bool) -> str:
    if interval == 2:
        return "add9" if third_present else "sus2"
    if interval == 5:
        return "add4" if third_present else "sus4"
    return {9: "6", 10: "7", 11: "maj7"}[interval]


def tone_evidence(segs: list, chroma: np.ndarray, frame_s: float) -> None:
    """Mede a energia de 2ª/4ª/6ª/7ª em relação às notas do acorde previsto (cromagrama harmônico, 60 % central do segmento)."""
    for s in segs:
        q = s.get("quality")
        if s["root"] is None or q not in CHORD_TONES:
            continue
        d = s["end"] - s["start"]
        i0 = int((s["start"] + 0.2 * d) / frame_s)
        i1 = max(int((s["end"] - 0.2 * d) / frame_s), i0 + 1)
        if i0 >= chroma.shape[1]:
            continue
        v = chroma[:, i0:i1].mean(axis=1)
        tones = CHORD_TONES[q]
        base = float(np.mean([v[(s["root"] + t) % 12] for t in tones]))
        if base <= 0:
            continue
        rel = {COLOR_TONES[k]: round(float(v[(s["root"] + k) % 12] / base), 2) for k in COLOR_TONES if k not in tones}
        third = (3 if q in ("min", "min7", "min6", "minmaj7", "dim", "dim7", "hdim7") else 4)
        third_rel = float(v[(s["root"] + third) % 12] / base) if third in tones else 0.0
        s.setdefault("evidence", {})["tones"] = {"relative_to_chord_tones": rel, "third": round(third_rel, 2)}
        if q not in ("maj", "min") or d < MIN_COLOR_SEG_S:
            continue
        adds = []
        for k, deg in COLOR_TONES.items():
            r = float(v[(s["root"] + k) % 12] / base)
            if k not in tones and r >= MIN_COLOR_REL:
                adds.append({"degree": deg, "strength": round(r, 2), "label": (s.get("harmonic_label") or s["chord"].split("/")[0]) + "(" + _name_for(k, third_rel >= THIRD_PRESENT_REL) + "?)"})
        if adds:
            s["possible_additions"] = adds


def finalize(segs: list, flats: bool) -> None:
    """Preenche model_label/harmonic_label/structure e define 'chord' (com baixo, se houver inversão aceita)."""
    for s in segs:
        label = s["chord"]
        s["model_label"] = s["harmonic_label"] = label
        if s["root"] is None:
            s["structure"] = {"root": None, "quality": None, "intervals": [], "bass": None, "inversion": None, "added": []}
            continue
        bass = s.get("bass") or {}
        inv = None
        if s.get("inversion"):
            b = s["inversion"].split("/")[1]
            inv_interval = None
            for pc in range(12):
                if note_name(pc, flats) == b:
                    inv_interval = (pc - s["root"]) % 12
            inv = {"bass": b, "interval": inv_interval, "degree": INVERSION_DEGREE.get(inv_interval)}
        s["structure"] = {"root": note_name(s["root"], flats), "quality": s["quality"],
                          "intervals": list(CHORD_TONES.get(s["quality"], ())), "added": [],
                          "bass": (inv or {}).get("bass") or bass.get("note") or note_name(s["root"], flats),
                          "inversion": inv}
        if inv:
            s["chord"] = s["inversion"]      # rótulo final: A/C#; o harmônico (A) continua em harmonic_label
