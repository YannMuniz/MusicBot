"""API interna do serviço de análise. Todos os endpoints /v1 exigem X-Internal-Token."""
import hmac
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .audio import AudioError, validate_audio_file
from .config import Settings
from .jobs import JobRunner
from . import annotations as ann_mod
from . import corrections, solos
from .chordnames import canonical
from .analysis import tabs as tabs_mod
from .version import ANALYZER_VERSION
from .store import SongStore, now, safe_display_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class EditedChord(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    chord: str = Field(min_length=1, max_length=16, pattern=r"^(N|[A-G][#b]?[A-Za-z0-9#b+()/\-]*)$")


class EditedChords(BaseModel):
    base_run_id: Optional[str] = None
    segments: List[EditedChord] = Field(max_length=5000)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    if not cfg.internal_token:
        raise RuntimeError("ANALYZER_INTERNAL_TOKEN não definido; recusando iniciar sem autenticação.")
    store = SongStore(cfg.storage_root)
    runner = JobRunner(store)

    @asynccontextmanager
    async def lifespan(_app):
        n = runner.recover()
        if n:
            logging.getLogger("analyzer").info("reenfileiradas %d análises pendentes", n)
        yield

    app = FastAPI(title="Harmonia AI — Analyzer", version=ANALYZER_VERSION, lifespan=lifespan)
    app.state.store, app.state.runner, app.state.settings = store, runner, cfg

    def auth(x_internal_token: str = Header(default="")):
        if not hmac.compare_digest(x_internal_token.encode(), cfg.internal_token.encode()):
            raise HTTPException(401, "Token interno inválido.")

    def song_or_404(song_id: str) -> str:
        try:
            store.dir(song_id)
        except KeyError:
            raise HTTPException(404, "Música não encontrada.")
        return song_id

    def results_or_409(song_id: str, name: str):
        song_or_404(song_id)
        try:
            return store.read(song_id, name)
        except FileNotFoundError:
            raise HTTPException(409, "Análise ainda não concluída para esta música.")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/v1/songs", status_code=202, dependencies=[Depends(auth)])
    def upload(file: UploadFile = File(...), title: Optional[str] = Form(None)):
        name = safe_display_name(file.filename)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        cfg.storage_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cfg.storage_root, prefix=".upload-", delete=False) as tmp:
            tmp_path, size = Path(tmp.name), 0
            try:
                while chunk := file.file.read(1 << 20):
                    size += len(chunk)
                    if size > cfg.max_upload_bytes:
                        raise AudioError("too_large", f"Arquivo maior que {cfg.max_upload_bytes // (1024 * 1024)} MB.", 413)
                    tmp.write(chunk)
            except AudioError as e:
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(e.http_status, {"code": e.code, "message": e.message})
        try:
            info = validate_audio_file(tmp_path, ext, cfg)
        except AudioError as e:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(e.http_status, {"code": e.code, "message": e.message})
        song_id = store.create(tmp_path, ext, safe_display_name(title) if title else name, info)
        runner.submit(song_id)  # análise inicia automaticamente
        return {"id": song_id, "status": "pending"}

    @app.get("/v1/songs", dependencies=[Depends(auth)])
    def list_songs():
        return {"songs": store.list()}

    @app.get("/v1/songs/{song_id}", dependencies=[Depends(auth)])
    def get_song(song_id: str):
        return store.summary(song_or_404(song_id))

    @app.get("/v1/songs/{song_id}/analysis", dependencies=[Depends(auth)])
    def get_analysis(song_id: str):
        return results_or_409(song_id, "analysis.json")

    @app.get("/v1/songs/{song_id}/chords", dependencies=[Depends(auth)])
    def get_chords(song_id: str):
        data = results_or_409(song_id, "chords.json")
        edited = store.read(song_id, "chords.edited.json") if store.exists(song_id, "chords.edited.json") else None
        return {**data, "edited": edited}

    @app.get("/v1/songs/{song_id}/chords/raw", dependencies=[Depends(auth)])
    def get_chords_raw(song_id: str):
        """Modo detalhado: segmentos do modelo antes do pós-processamento temporal."""
        return results_or_409(song_id, "chords.raw.json")

    @app.put("/v1/songs/{song_id}/chords/edited", dependencies=[Depends(auth)])
    def put_edited(song_id: str, body: EditedChords):
        song_or_404(song_id)
        for s in body.segments:
            if s.end <= s.start:
                raise HTTPException(422, "Cada segmento precisa ter end > start.")
        doc = {"base_run_id": body.base_run_id, "saved_at": now(), "segments": [s.model_dump() for s in body.segments]}
        for s in doc["segments"]:
            s["chord"] = canonical(s["chord"])  # "C#7M" == "C#maj7"
        store.write(song_id, "chords.edited.json", doc)  # a detecção automática nunca é sobrescrita
        corrections.record(store, song_id, body.base_run_id, doc["segments"])  # trilha de auditoria p/ treino futuro
        return doc

    @app.get("/v1/songs/{song_id}/corrections", dependencies=[Depends(auth)])
    def get_corrections(song_id: str):
        song_or_404(song_id)
        return store.read(song_id, corrections.FILE) if store.exists(song_id, corrections.FILE) else {"corrections": []}

    class ReviewBody(BaseModel):
        reviewed: bool
        note: Optional[str] = Field(default=None, max_length=300)

    @app.post("/v1/songs/{song_id}/review", dependencies=[Depends(auth)])
    def set_review(song_id: str, body: ReviewBody):
        """Marca a cifra desta música como REVISADA por um humano: só então ela entra como fonte de exemplos para outras músicas."""
        song_or_404(song_id)
        doc = {"reviewed": body.reviewed, "at": now(), "note": body.note, "analyzer_version": ANALYZER_VERSION}
        store.write(song_id, "review.json", doc)
        return doc

    class StatusBody(BaseModel):
        validation_status: str = Field(pattern=r"^(unreviewed|accepted|rejected)$")

    @app.put("/v1/songs/{song_id}/corrections/{cid}/status", dependencies=[Depends(auth)])
    def set_correction_status(song_id: str, cid: str, body: StatusBody):
        song_or_404(song_id)
        if not store.exists(song_id, corrections.FILE):
            raise HTTPException(404, "Correção não encontrada.")
        log = store.read(song_id, corrections.FILE)
        for c in log["corrections"]:
            if c["id"] == cid:
                c["validation_status"] = body.validation_status
                store.write(song_id, corrections.FILE, log)
                return c
        raise HTTPException(404, "Correção não encontrada.")

    @app.get("/v1/songs/{song_id}/learning", dependencies=[Depends(auth)])
    def get_learning(song_id: str):
        """Resumo do aprendizado por correções desta música (sem expor características)."""
        song_or_404(song_id)
        review = store.read(song_id, "review.json") if store.exists(song_id, "review.json") else {"reviewed": False}
        cors = store.read(song_id, corrections.FILE)["corrections"] if store.exists(song_id, corrections.FILE) else []
        influenced = []
        if store.exists(song_id, "chords.json"):
            influenced = [{"start": s["start"], "end": s["end"], "from": s["memory"].get("from_label"), "to": s["memory"].get("to_label"),
                           "neighbors": s["memory"]["neighbors"], "songs": s["memory"]["songs"], "agreement": s["memory"]["agreement"]}
                          for s in store.read(song_id, "chords.json")["segments"] if s.get("memory", {}).get("applied")]
        by_status = {}
        for c in cors:
            if not c.get("superseded"):
                by_status[c["validation_status"]] = by_status.get(c["validation_status"], 0) + 1
        return {"reviewed": review.get("reviewed", False), "reviewed_at": review.get("at"), "corrections": by_status,
                "memory_applied_here": influenced, "has_features": store.exists(song_id, "segment_features.json")}

    # ---- solos, transcrição e tablatura ------------------------------------------------------------------
    class SoloIn(BaseModel):
        start: float = Field(ge=0)
        end: float = Field(gt=0)
        category: str = Field(default="solo", pattern=r"^(solo|riff|intro|interlude|outro|instrumental)$")
        instrument: str = Field(default="indeterminate", pattern=r"^(guitar|bass|keyboard|other|indeterminate)$")

    class SoloPatch(BaseModel):
        start: Optional[float] = Field(default=None, ge=0)
        end: Optional[float] = Field(default=None, gt=0)
        category: Optional[str] = Field(default=None, pattern=r"^(solo|riff|intro|interlude|outro|instrumental)$")
        instrument: Optional[str] = Field(default=None, pattern=r"^(guitar|bass|keyboard|other|indeterminate)$")

    class TranscribeIn(BaseModel):
        preprocess: str = Field(default="foreground", pattern=r"^(foreground|harmonic|raw)$")
        tuning: Optional[List[int]] = Field(default=None, min_length=4, max_length=8)
        max_fret: int = Field(default=22, ge=5, le=30)

    class NoteIn(BaseModel):
        pitch: int = Field(ge=20, le=110)
        start: float = Field(ge=0)
        end: float = Field(gt=0)
        string: Optional[int] = Field(default=None, ge=1, le=8)
        fret: Optional[int] = Field(default=None, ge=0, le=30)
        confidence: Optional[float] = None
        techniques: List[dict] = []
        src: Optional[int] = None
        deleted: bool = False

    class TabEditIn(BaseModel):
        tuning: List[int] = Field(min_length=4, max_length=8)
        max_fret: int = Field(default=22, ge=5, le=30)
        notes: List[NoteIn] = Field(max_length=3000)

    class RetabIn(BaseModel):
        tuning: List[int] = Field(min_length=4, max_length=8)
        max_fret: int = Field(default=22, ge=5, le=30)
        notes: List[NoteIn] = Field(max_length=3000)

    def duration_of(song_id: str) -> float:
        return float(store.read(song_id, "metadata.json")["duration"])

    @app.get("/v1/songs/{song_id}/solos", dependencies=[Depends(auth)])
    def get_solos(song_id: str):
        song_or_404(song_id)
        return {"solos": solos.list_solos(store, song_id), "tunings": tabs_mod.TUNINGS,
                "note": "Os trechos são marcados por você; o sistema não afirma onde há solo (ver docs/avaliacao.md)."}

    @app.post("/v1/songs/{song_id}/solos", status_code=201, dependencies=[Depends(auth)])
    def create_solo(song_id: str, body: SoloIn):
        song_or_404(song_id)
        try:
            return solos.create_solo(store, song_id, body.start, body.end, body.category, body.instrument, duration_of(song_id))
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.patch("/v1/songs/{song_id}/solos/{solo_id}", dependencies=[Depends(auth)])
    def patch_solo(song_id: str, solo_id: str, body: SoloPatch):
        song_or_404(song_id)
        try:
            return solos.update_solo(store, song_id, solo_id, duration_of(song_id), body.start, body.end, body.instrument, body.category)
        except KeyError:
            raise HTTPException(404, "Solo não encontrado.")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.delete("/v1/songs/{song_id}/solos/{solo_id}", status_code=204, dependencies=[Depends(auth)])
    def delete_solo(song_id: str, solo_id: str):
        song_or_404(song_id)
        solos.delete_solo(store, song_id, solo_id)

    @app.post("/v1/songs/{song_id}/solos/{solo_id}/transcribe", status_code=202, dependencies=[Depends(auth)])
    def transcribe_solo(song_id: str, solo_id: str, body: TranscribeIn = TranscribeIn()):
        song_or_404(song_id)
        if not any(s["id"] == solo_id for s in solos.list_solos(store, song_id)):
            raise HTTPException(404, "Solo não encontrado.")
        if solos.transcription_state(store, song_id, solo_id) == "processing":
            raise HTTPException(409, "Já existe uma transcrição em andamento para este solo.")
        solos.write_atomic(solos._tpath(store, song_id, f"{solo_id}.json"), '{"state": "processing"}')   # ANTES de enfileirar
        runner.submit_transcription(song_id, solo_id, body.preprocess, body.tuning, body.max_fret)
        return {"solo_id": solo_id, "state": "processing"}

    @app.get("/v1/songs/{song_id}/solos/{solo_id}/tab", dependencies=[Depends(auth)])
    def get_tab(song_id: str, solo_id: str):
        song_or_404(song_id)
        try:
            return solos.get_tab(store, song_id, solo_id)
        except FileNotFoundError:
            raise HTTPException(404, "Este solo ainda não foi transcrito.")

    @app.put("/v1/songs/{song_id}/solos/{solo_id}/tab", dependencies=[Depends(auth)])
    def put_tab(song_id: str, solo_id: str, body: TabEditIn):
        song_or_404(song_id)
        try:
            return solos.save_tab_edit(store, song_id, solo_id, [n.model_dump() for n in body.notes], body.tuning, body.max_fret)
        except FileNotFoundError:
            raise HTTPException(404, "Este solo ainda não foi transcrito.")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.post("/v1/songs/{song_id}/solos/{solo_id}/retab", dependencies=[Depends(auth)])
    def retab(song_id: str, solo_id: str, body: RetabIn):
        """Recalcula a digitação para outra afinação/extensão (sem gravar). Notas com posição manual não são reposicionadas pela UI."""
        song_or_404(song_id)
        return tabs_mod.retab([n.model_dump() for n in body.notes if not n.deleted], body.tuning, body.max_fret)

    @app.get("/v1/songs/{song_id}/annotations", dependencies=[Depends(auth)])
    def get_annotations(song_id: str):
        song_or_404(song_id)
        return store.read(song_id, ann_mod.FILE) if store.exists(song_id, ann_mod.FILE) else {"annotations": []}

    @app.get("/v1/songs/{song_id}/sections", dependencies=[Depends(auth)])
    def get_sections(song_id: str):
        return results_or_409(song_id, "sections.json")

    @app.get("/v1/songs/{song_id}/report", response_class=PlainTextResponse, dependencies=[Depends(auth)])
    def get_report(song_id: str):
        return results_or_409(song_id, "report.txt")

    @app.get("/v1/songs/{song_id}/history", dependencies=[Depends(auth)])
    def get_history(song_id: str):
        return {"runs": store.history(song_or_404(song_id))}

    @app.get("/v1/songs/{song_id}/audio", dependencies=[Depends(auth)])
    def get_audio(song_id: str):
        song_or_404(song_id)
        meta = store.read(song_id, "metadata.json")
        mt = "audio/mpeg" if meta["extension"] == "mp3" else "audio/wav"
        return FileResponse(store.original_path(song_id), media_type=mt, headers={"Cache-Control": "private, no-store"})

    @app.post("/v1/songs/{song_id}/reanalyze", status_code=202, dependencies=[Depends(auth)])
    def reanalyze(song_id: str):
        song_or_404(song_id)
        if store.read(song_id, "status.json")["status"] in ("pending", "processing"):
            raise HTTPException(409, "Já existe uma análise em andamento.")
        runner.submit(song_id)
        return {"id": song_id, "status": "pending"}

    return app
