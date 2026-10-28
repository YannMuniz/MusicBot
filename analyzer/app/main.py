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
from . import corrections
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

    app = FastAPI(title="Harmonia AI — Analyzer", version="0.2.0", lifespan=lifespan)
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
        store.write(song_id, "chords.edited.json", doc)  # a detecção automática nunca é sobrescrita
        corrections.record(store, song_id, body.base_run_id, doc["segments"])  # trilha de auditoria p/ treino futuro
        return doc

    @app.get("/v1/songs/{song_id}/corrections", dependencies=[Depends(auth)])
    def get_corrections(song_id: str):
        song_or_404(song_id)
        return store.read(song_id, corrections.FILE) if store.exists(song_id, corrections.FILE) else {"corrections": []}

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
