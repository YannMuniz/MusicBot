"""Registro estruturado das correções do usuário, pensado para virar dado de treino no futuro.

Cada correção guarda: música, intervalo, acorde previsto, acorde corrigido, versão do modelo (nome+versão+SHA dos pesos),
data, origem e estado de validação. Nada aqui altera resultados de outras músicas, e nenhuma correção é tratada como
verdade: o estado inicial é 'unreviewed' e só 'accepted' (revisão humana explícita) entra em exportações de treino.
"""
import hashlib
import json
from typing import List, Optional

from .store import SongStore, now

FILE = "corrections.json"
STATUSES = ("unreviewed", "accepted", "rejected")


def _predicted_for(segs: list, start: float, end: float) -> Optional[dict]:
    """Segmento previsto com maior sobreposição ao intervalo corrigido."""
    best, best_ov = None, 0.0
    for s in segs:
        ov = min(end, s["end"]) - max(start, s["start"])
        if ov > best_ov:
            best, best_ov = s, ov
    return best


def _split_bass(label: str):
    """'A/C#' -> ('A', 'C#'); sem barra -> (label, None)."""
    head, _, bass = label.partition("/")
    return head, (bass or None)


def _chords_of_run(store: SongStore, song_id: str, run_id: Optional[str]):
    """(segmentos, analysis) da corrida indicada; None se não existir mais."""
    d = store.dir(song_id)
    cur = store.read(song_id, "analysis.json") if store.exists(song_id, "analysis.json") else None
    if cur and (run_id is None or cur["run_id"] == run_id):
        return store.read(song_id, "chords.json")["segments"], cur
    h = d / "history" / (run_id or "")
    if run_id and (h / "chords.json").is_file():
        return (json.loads((h / "chords.json").read_text(encoding="utf-8"))["segments"],
                json.loads((h / "analysis.json").read_text(encoding="utf-8")))
    return None, None


def record(store: SongStore, song_id: str, base_run_id: Optional[str], edited: List[dict]) -> int:
    """Compara as edições com a previsão da corrida-base e registra as que mudaram o acorde. Retorna nº de novas."""
    segs, analysis = _chords_of_run(store, song_id, base_run_id)
    if segs is None:
        return 0
    alg = analysis["algorithm"]
    model = {"name": alg["name"], "version": alg["version"], "weights_sha256": alg.get("weights_sha256")}
    try:
        log = store.read(song_id, FILE)
    except FileNotFoundError:
        log = {"corrections": []}
    run_id = analysis["run_id"]
    # edições substituem as anteriores da mesma corrida: o que não está mais na lista fica 'superseded'
    new_keys, added = set(), 0
    existing = {c["id"]: c for c in log["corrections"]}
    for e in edited:
        seg = _predicted_for(segs, e["start"], e["end"])
        pred = seg["chord"] if seg else None
        if pred is None or pred == e["chord"]:
            continue
        cid = hashlib.sha1(f"{song_id}|{run_id}|{e['start']:.2f}|{e['end']:.2f}|{e['chord']}".encode()).hexdigest()[:16]
        new_keys.add(cid)
        if cid in existing:
            existing[cid]["superseded"] = False
            continue
        log["corrections"].append({
            "id": cid, "song_id": song_id, "run_id": run_id, "start": round(e["start"], 3), "end": round(e["end"], 3),
            "predicted": pred, "corrected": e["chord"], "model": model,
            "predicted_harmonic": seg.get("harmonic_label", _split_bass(pred)[0]),
            "predicted_bass": (seg.get("bass") or {}).get("note") if "bass" in seg else _split_bass(pred)[1],
            "predicted_confidence": {"p": seg.get("p"), "ambiguous": seg.get("ambiguous")},
            "corrected_harmonic": _split_bass(e["chord"])[0], "corrected_bass": _split_bass(e["chord"])[1], "created_at": now(), "source": "ui",
            "validation_status": "unreviewed", "superseded": False})
        added += 1
    for c in log["corrections"]:
        if c["run_id"] == run_id and c["id"] not in new_keys:
            c["superseded"] = True
    store.write(song_id, FILE, log)
    return added
