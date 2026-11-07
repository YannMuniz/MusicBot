"""Anotações TIPADAS do usuário além de acordes: limites de solo, instrumento do solo, notas e tablatura.

Cada tipo tem seu esquema; um tipo nunca é interpretado como outro (uma correção de nota não é correção de acorde, e vice-versa).
Correções de acorde/baixo ficam em corrections.json (corrections.py). Tipos reservados para o futuro, ainda sem UI:
'section_label' (classificação de seção) e 'chord_boundary' (limite temporal de acorde).
Cada registro preserva o valor ORIGINAL (automático), o corrigido, a data, a versão do analisador e o estado de validação.
"""
import hashlib
import json
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

from .store import SongStore, now
from .version import ANALYZER_VERSION

FILE = "annotations.json"
INSTRUMENTS = ("guitar", "bass", "keyboard", "other", "indeterminate")
CATEGORIES = ("solo", "riff", "intro", "interlude", "outro", "instrumental")


class SoloBounds(BaseModel):
    type: Literal["solo_bounds"] = "solo_bounds"
    solo_id: str = Field(pattern=r"^s\d{1,3}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class SoloInstrument(BaseModel):
    type: Literal["solo_instrument"] = "solo_instrument"
    solo_id: str = Field(pattern=r"^s\d{1,3}$")
    instrument: Literal["guitar", "bass", "keyboard", "other", "indeterminate"]
    category: Optional[Literal["solo", "riff", "intro", "interlude", "outro", "instrumental"]] = None


class NoteEdit(BaseModel):
    type: Literal["note"] = "note"
    solo_id: str = Field(pattern=r"^s\d{1,3}$")
    index: int = Field(ge=0, le=5000)
    pitch: Optional[int] = Field(default=None, ge=20, le=110)
    start: Optional[float] = Field(default=None, ge=0)
    end: Optional[float] = Field(default=None, gt=0)
    string: Optional[int] = Field(default=None, ge=1, le=8)
    fret: Optional[int] = Field(default=None, ge=0, le=30)
    deleted: bool = False


class TabSettings(BaseModel):
    type: Literal["tab"] = "tab"
    solo_id: str = Field(pattern=r"^s\d{1,3}$")
    tuning: list = Field(min_length=4, max_length=8)
    max_fret: int = Field(default=22, ge=5, le=30)


Annotation = Union[SoloBounds, SoloInstrument, NoteEdit, TabSettings]


def record(store: SongStore, song_id: str, ann: Annotation, original, run_id: Optional[str] = None) -> dict:
    """Acrescenta (nunca sobrescreve) uma anotação tipada. O original automático fica preservado em 'original'."""
    try:
        doc = store.read(song_id, FILE)
    except FileNotFoundError:
        doc = {"annotations": []}
    payload = ann.model_dump()
    aid = hashlib.sha1(json.dumps([song_id, payload, now()], sort_keys=True).encode()).hexdigest()[:16]
    rec = {"id": aid, "type": ann.type, "target": ann.solo_id, "original": original, "corrected": payload, "created_at": now(),
           "source": "ui", "origin": "user", "analyzer_version": ANALYZER_VERSION, "run_id": run_id, "validation_status": "unreviewed"}
    doc["annotations"].append(rec)
    store.write(song_id, FILE, doc)
    return rec
