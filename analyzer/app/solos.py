"""Solos/trechos instrumentais marcados pelo usuário e sua transcrição → tablatura.

POR QUE MANUAL: a detecção automática de voz/solo por características clássicas não generalizou entre músicas
(AUC 0,54–0,60; docs/avaliacao.md). Então o sistema não afirma onde há solo; o usuário marca ou confirma o trecho (a partir de uma
seção sugerida) e declara categoria/instrumento ('indeterminate' é permitido). Tudo a jusante (transcrição, tab, correções) vale
para qualquer intervalo escolhido.

Arquivos por música (sobrevivem a reprocessamentos): solos.json (registro), transcriptions/{id}.json (resultado automático),
transcriptions/{id}.edited.json (correções do usuário), annotations.json (trilha tipada com o original preservado).
"""
import json
import logging
import traceback
from pathlib import Path
from typing import Optional

from . import annotations as ann
from .analysis import tabs, transcription
from .audio import SR as AUDIO_SR
from .audio import load_audio
from .store import SongStore, now

log = logging.getLogger("analyzer.solos")
FILE = "solos.json"
MAX_SOLO_S = 180.0
MIN_SOLO_S = 2.0
STATES = ("not_started", "processing", "completed", "low_confidence", "failed")


def _read(store: SongStore, song_id: str) -> dict:
    return store.read(song_id, FILE) if store.exists(song_id, FILE) else {"solos": []}


def list_solos(store: SongStore, song_id: str) -> list:
    out = []
    for s in _read(store, song_id)["solos"]:
        s = dict(s)
        s["transcription_state"] = transcription_state(store, song_id, s["id"])
        out.append(s)
    return out


def transcription_state(store: SongStore, song_id: str, solo_id: str) -> str:
    p = store.dir(song_id) / "transcriptions" / f"{solo_id}.json"
    if not p.is_file():
        return "not_started"
    return json.loads(p.read_text(encoding="utf-8")).get("state", "not_started")


def create_solo(store: SongStore, song_id: str, start: float, end: float, category: str, instrument: str, duration: float) -> dict:
    if not (0 <= start < end <= duration + 0.01):
        raise ValueError("Intervalo fora da duração da música.")
    if not (MIN_SOLO_S <= end - start <= MAX_SOLO_S):
        raise ValueError(f"O trecho precisa ter entre {MIN_SOLO_S:.0f} e {MAX_SOLO_S:.0f} s.")
    doc = _read(store, song_id)
    n = 1 + max([int(s["id"][1:]) for s in doc["solos"]] or [0])
    solo = {"id": f"s{n}", "start": round(start, 3), "end": round(end, 3), "category": category, "instrument": instrument,
            "instrument_confidence": None, "confidence": None, "source": "user", "verified": True,
            "audio_ref": {"file": "original", "start": round(start, 3), "end": round(end, 3)}, "created_at": now()}
    doc["solos"].append(solo)
    store.write(song_id, FILE, doc)
    ann.record(store, song_id, ann.SoloBounds(solo_id=solo["id"], start=start, end=end), original=None)
    return solo


def update_solo(store: SongStore, song_id: str, solo_id: str, duration: float, start=None, end=None, instrument=None, category=None) -> dict:
    doc = _read(store, song_id)
    solo = next((s for s in doc["solos"] if s["id"] == solo_id), None)
    if solo is None:
        raise KeyError(solo_id)
    before = {k: solo[k] for k in ("start", "end", "instrument", "category")}
    ns, ne = (solo["start"] if start is None else start), (solo["end"] if end is None else end)
    if not (0 <= ns < ne <= duration + 0.01 and MIN_SOLO_S <= ne - ns <= MAX_SOLO_S):
        raise ValueError("Intervalo inválido.")
    if (ns, ne) != (solo["start"], solo["end"]):
        ann.record(store, song_id, ann.SoloBounds(solo_id=solo_id, start=ns, end=ne), original={"start": before["start"], "end": before["end"]})
        solo.update(start=round(ns, 3), end=round(ne, 3), audio_ref={"file": "original", "start": round(ns, 3), "end": round(ne, 3)})
    if instrument is not None or category is not None:
        ann.record(store, song_id, ann.SoloInstrument(solo_id=solo_id, instrument=instrument or solo["instrument"], category=category),
                   original={"instrument": before["instrument"], "category": before["category"]})
        solo["instrument"] = instrument or solo["instrument"]
        solo["category"] = category or solo["category"]
    store.write(song_id, FILE, doc)
    return solo


def delete_solo(store: SongStore, song_id: str, solo_id: str) -> None:
    doc = _read(store, song_id)
    doc["solos"] = [s for s in doc["solos"] if s["id"] != solo_id]
    store.write(song_id, FILE, doc)


# --- transcrição (job) ---------------------------------------------------------------------------------------
def write_atomic(path: Path, text: str) -> None:
    import os
    import uuid
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _tpath(store: SongStore, song_id: str, name: str) -> Path:
    d = store.dir(song_id) / "transcriptions"
    d.mkdir(exist_ok=True)
    return d / name


def run_transcription(store: SongStore, song_id: str, solo_id: str, preprocess: str = "foreground", tuning: Optional[list] = None,
                      max_fret: int = 22) -> None:
    """Executa (em thread de fundo) e grava transcriptions/{id}.json. Estados: processing → completed | low_confidence | failed."""
    out = _tpath(store, song_id, f"{solo_id}.json")
    solo = next((s for s in _read(store, song_id)["solos"] if s["id"] == solo_id), None)
    base = {"solo_id": solo_id, "started_at": now(), "preprocess": preprocess}
    try:
        if solo is None:
            raise KeyError(solo_id)
        write_atomic(out, json.dumps({**base, "state": "processing"}))
        y = load_audio(store.original_path(song_id))
        a, b = int(solo["start"] * AUDIO_SR), int(solo["end"] * AUDIO_SR)
        res = transcription.transcribe(y[a:b], start_s=solo["start"], mode=preprocess)
        tab = tabs.to_tab(res["notes"], tuning, max_fret)
        for i, n in enumerate(tab["notes"]):
            n["src"] = i                                   # índice da nota automática (liga correções ao original)
        doc = {**base, **{k: res[k] for k in ("state", "mean_confidence", "voiced_ratio", "method", "monophonic_only")},
               "finished_at": now(), "solo_range": [solo["start"], solo["end"]], "tuning": tab["tuning"], "max_fret": tab["max_fret"],
               "notes": tab["notes"], "disclaimer": tab["disclaimer"],
               "limits": ["transcrição monofônica (uma nota por vez); em mistura densa pode seguir voz/baixo",
                          "corda/casa são uma digitação plausível, não a usada na gravação",
                          "técnicas são INFERIDAS (vibrato, glissando) e podem estar erradas; bend/hammer/pull-off não são reconhecidos"]}
        write_atomic(out, json.dumps(doc, ensure_ascii=False, indent=1))
        log.info("solo %s/%s transcrito: %d notas, estado %s", song_id, solo_id, len(res["notes"]), res["state"])
    except Exception:  # noqa: BLE001
        log.error("transcrição falhou:\n%s", traceback.format_exc())
        write_atomic(out, json.dumps({**base, "state": "failed", "error": "Erro interno ao transcrever. Veja os logs do serviço."}))


def get_tab(store: SongStore, song_id: str, solo_id: str) -> dict:
    p = _tpath(store, song_id, f"{solo_id}.json")
    if not p.is_file():
        raise FileNotFoundError(solo_id)
    auto = json.loads(p.read_text(encoding="utf-8"))
    e = _tpath(store, song_id, f"{solo_id}.edited.json")
    auto["edited"] = json.loads(e.read_text(encoding="utf-8")) if e.is_file() else None
    return auto


def save_tab_edit(store: SongStore, song_id: str, solo_id: str, notes: list, tuning: list, max_fret: int) -> dict:
    """Guarda a versão corrigida; a transcrição automática fica intacta e cada nota alterada gera uma anotação 'note' tipada."""
    auto = get_tab(store, song_id, solo_id)
    if auto.get("state") == "processing":
        raise ValueError("A transcrição ainda está em andamento.")
    orig = auto["notes"]
    clean = []
    for n in notes:
        if n.get("deleted"):
            continue
        s, f = n.get("string"), n.get("fret")
        if s is not None and f is not None:
            if not (1 <= s <= len(tuning) and 0 <= f <= max_fret):
                raise ValueError("Corda/casa fora do instrumento configurado.")
            if tuning[s - 1] + f != n["pitch"]:
                n = {**n, "pitch": tuning[s - 1] + f}        # a posição manda: altura = corda + casa
        if not (n["end"] > n["start"] >= 0):
            raise ValueError("Cada nota precisa ter end > start.")
        clean.append(n)
    # trilha de auditoria: só o que mudou em relação ao automático (por índice de origem 'src')
    for n in clean:
        i = n.get("src")
        if i is not None and i < len(orig):
            o = orig[i]
            if any(n.get(k) != o.get(k) for k in ("pitch", "start", "end", "string", "fret")):
                ann.record(store, song_id, ann.NoteEdit(solo_id=solo_id, index=i, pitch=n["pitch"], start=n["start"], end=n["end"],
                                                         string=n.get("string"), fret=n.get("fret")),
                           original={k: o.get(k) for k in ("pitch", "start", "end", "string", "fret")})
    kept = {n.get("src") for n in clean}
    for i, o in enumerate(orig):
        if i not in kept:
            ann.record(store, song_id, ann.NoteEdit(solo_id=solo_id, index=i, deleted=True),
                       original={k: o.get(k) for k in ("pitch", "start", "end", "string", "fret")})
    doc = {"solo_id": solo_id, "saved_at": now(), "tuning": tuning, "max_fret": max_fret, "notes": clean}
    write_atomic(_tpath(store, song_id, f"{solo_id}.edited.json"), json.dumps(doc, ensure_ascii=False, indent=1))
    return doc
