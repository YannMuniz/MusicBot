"""Memória de exemplos REVISADOS: recuperação por semelhança para corrigir previsões em músicas futuras.

NÃO é treinamento: os pesos do BTC não mudam. É uma consulta a rótulos humanos de outras gravações, com salvaguardas.

Fonte: músicas marcadas como revisadas (review.json). Para cada segmento dessas músicas o rótulo confiável é a correção
do usuário que o cobre (chords.edited.json) ou, se não houve correção, a própria previsão (um "negativo" confirmado: é o que
impede transformar todo D em Dsus2). Cada exemplo guarda a TUPLA de rótulo relativa à raiz prevista
(deslocamento da raiz, sufixo, intervalo do baixo), e o vetor de características de segfeatures.py.

Aplicação (todas as condições):
  • ≥ MIN_N vizinhos com semelhança ≥ SIM_MIN e MESMA tupla prevista que a atual (mesma "confusão"), de ≥ MIN_SONGS músicas;
  • a tupla corrigida vencedora tem ≥ AGREE dos votos (ponderados pela semelhança) e difere da prevista;
  • a previsão atual não é quase certa (p < P_MAX).
Senão a previsão é mantida; se havia vizinhos, o motivo fica em seg["memory"] (auditável). Exemplos da mesma música ou da
mesma gravação (mesmo SHA-256 do áudio) são excluídos: evita vazamento (a correção já vale na própria música pela camada
de edição).
"""
import json
import re
from pathlib import Path
from typing import Optional

import numpy as np

from .analysis import segfeatures
from .analysis.tonality import note_name

SIM_MIN = 0.90
MIN_N = 3
MIN_SONGS = 2
AGREE = 0.80
P_MAX = 0.97
LABEL_RE = re.compile(r"^([A-G][#b]?)([^/]*)(?:/([A-G][#b]?))?$")
PC = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def parse_label(label: str):
    """'A/C#' -> (9, '', 1) ; 'Dsus2' -> (2, 'sus2', None); 'N' -> None. Raiz em pitch class, baixo em pitch class."""
    m = LABEL_RE.match(label or "")
    if not m:
        return None
    return PC[m.group(1)], m.group(2), (PC[m.group(3)] if m.group(3) else None)


def label_tuple(label: str, predicted_root: int):
    """Tupla relativa à raiz PREVISTA: (deslocamento da raiz, sufixo, intervalo do baixo ou None)."""
    p = parse_label(label)
    if p is None:
        return None
    root, suffix, bass = p
    return ((root - predicted_root) % 12, suffix, None if bass is None else (bass - root) % 12)


def tuple_to_label(t, predicted_root: int, flats: bool) -> str:
    rel, suffix, bass_rel = t
    root = (predicted_root + rel) % 12
    out = note_name(root, flats) + suffix
    return out + (f"/{note_name((root + bass_rel) % 12, flats)}" if bass_rel is not None else "")


class ReviewedMemory:
    def __init__(self, store, exclude_song_id: Optional[str] = None, exclude_sha: Optional[str] = None):
        self.examples = []
        self.skipped = {"same_song": 0, "same_recording": 0, "not_reviewed": 0, "no_features": 0}
        for d in sorted(store.root.iterdir()):
            if not d.is_dir() or not re.match(r"^[0-9a-f]{32}$", d.name):
                continue
            if d.name == exclude_song_id:
                self.skipped["same_song"] += 1
                continue
            try:
                meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
                if exclude_sha and meta.get("sha256") == exclude_sha:
                    self.skipped["same_recording"] += 1
                    continue
                rev = d / "review.json"
                if not rev.is_file() or not json.loads(rev.read_text(encoding="utf-8")).get("reviewed"):
                    self.skipped["not_reviewed"] += 1
                    continue
                feats = json.loads((d / "segment_features.json").read_text(encoding="utf-8"))["features"]
            except (FileNotFoundError, KeyError, json.JSONDecodeError):
                self.skipped["no_features"] += 1
                continue
            edited = []
            if (d / "chords.edited.json").is_file():
                edited = json.loads((d / "chords.edited.json").read_text(encoding="utf-8")).get("segments", [])
            for k, f in enumerate(feats):
                if f is None:
                    continue
                final = self._final_label(f, edited)
                pt, ft = label_tuple(f["chord"], f["root"]), label_tuple(final, f["root"])
                if pt is None or ft is None:
                    continue
                self.examples.append({"id": f"{d.name[:8]}:{k}", "song": d.name, "pred": pt, "final": ft, "vec": segfeatures.vector(f),
                                      "start": f["start"], "end": f["end"], "corrected": pt != ft})

    @staticmethod
    def _final_label(f: dict, edited: list) -> str:
        best, best_ov = None, 0.0
        for e in edited:
            ov = min(f["end"], e["end"]) - max(f["start"], e["start"])
            if ov > best_ov:
                best, best_ov = e["chord"], ov
        return best if best is not None and best_ov >= 0.5 * (f["end"] - f["start"]) else f["chord"]

    def summary(self) -> dict:
        return {"examples": len(self.examples), "songs": len({e["song"] for e in self.examples}),
                "corrected_examples": sum(e["corrected"] for e in self.examples), "skipped": self.skipped}

    def suggest(self, feat: dict, p: Optional[float]) -> Optional[dict]:
        """Sugestão auditável para um segmento. Retorna None se não houver vizinhos relevantes."""
        pred = label_tuple(feat["chord"], feat["root"])
        if pred is None or not self.examples:
            return None
        v = segfeatures.vector(feat)
        near = [(float(e["vec"] @ v), e) for e in self.examples if e["pred"] == pred]
        near = [(s, e) for s, e in near if s >= SIM_MIN]
        if not near:
            return None
        votes = {}
        for s, e in near:
            votes[e["final"]] = votes.get(e["final"], 0.0) + s
        win, wv = max(votes.items(), key=lambda kv: kv[1])
        agree = wv / sum(votes.values())
        songs = {e["song"] for _, e in near}
        info = {"neighbors": len(near), "songs": len(songs), "agreement": round(agree, 3), "mean_similarity": round(float(np.mean([s for s, _ in near])), 3),
                "example_ids": [e["id"] for _, e in sorted(near, key=lambda t: -t[0])[:5]], "winner": list(win), "applied": False}
        if win == pred:
            info["reason"] = "neighbors_confirm_prediction"
        elif len(near) < MIN_N or len(songs) < MIN_SONGS:
            info["reason"] = "insufficient_examples"
        elif agree < AGREE:
            info["reason"] = "examples_disagree"
        elif p is not None and p >= P_MAX:
            info["reason"] = "prediction_nearly_certain"
        else:
            info["applied"] = True
        return info


def apply_memory(segs: list, feats: list, memory: ReviewedMemory, flats: bool) -> dict:
    """Aplica sugestões que passam em todas as condições; devolve contagens. Preserva model_label e registra a auditoria."""
    n_applied = n_considered = 0
    for s, f in zip(segs, feats):
        if f is None:
            continue
        info = memory.suggest(f, s.get("p"))
        if info is None:
            continue
        n_considered += 1
        info["from_label"] = s["chord"]
        if info["applied"]:
            new = tuple_to_label(tuple(info["winner"]), s["root"], flats)
            info["to_label"] = new
            parsed = parse_label(new)
            s["chord"] = new
            s["harmonic_label"] = note_name(parsed[0], flats) + parsed[1]
            s["root"] = parsed[0]
            s.setdefault("structure", {})["quality"] = parsed[1] or "maj"
            n_applied += 1
        s["memory"] = info
    return {"considered": n_considered, "applied": n_applied}
