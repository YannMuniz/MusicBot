"""Fila interna: um worker (análise é pesada em CPU/RAM). O estado vive em disco (status.json),
então jobs pendentes/interrompidos são reenfileirados ao reiniciar."""
import logging
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from .analysis.pipeline import build_report, run_analysis
from .audio import AudioError
from .store import SongStore, now

log = logging.getLogger("analyzer.jobs")


class JobRunner:
    def __init__(self, store: SongStore, workers: int = 1):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="analysis")

    def submit(self, song_id: str) -> None:
        self.store.set_status(song_id, "pending", stage=None, error=None)
        self.pool.submit(self._run, song_id)

    def recover(self) -> int:
        n = 0
        for s in self.store.list():
            if s["status"] in ("pending", "processing"):
                self.submit(s["id"])
                n += 1
        return n

    def _run(self, song_id: str) -> None:
        st = self.store
        try:
            runs = st.read(song_id, "status.json").get("runs", 0)
            st.set_status(song_id, "processing", stage="starting", started_at=now(), error=None)
            meta = st.read(song_id, "metadata.json")
            result = run_analysis(st.original_path(song_id), progress=lambda s: st.set_status(song_id, "processing", stage=s))
            run_id = uuid.uuid4().hex[:12]
            result.update(run_id=run_id, created_at=now(), song_id=song_id)
            st.archive_current(song_id)
            st.write(song_id, "chords.json", {"run_id": run_id, "segments": result["chords"]})
            st.write(song_id, "chords.raw.json", {"run_id": run_id, "note": "segmentos do modelo ANTES do pós-processamento temporal (modo detalhado)", "segments": result["raw_chords"]})
            st.write(song_id, "sections.json", {"run_id": run_id, "sections": result["sections"]})
            st.write(song_id, "report.txt", build_report(meta["original_filename"], result))
            summary = {k: v for k, v in result.items() if k not in ("chords", "raw_chords", "sections")}
            st.write(song_id, "analysis.json", summary)  # por último: marca a análise como completa
            st.set_status(song_id, "completed", stage=None, runs=runs + 1, finished_at=now(), run_id=run_id)
            log.info("song %s analisada em %ss", song_id, result["processing_seconds"])
        except AudioError as e:
            log.warning("song %s falhou: %s", song_id, e.message)
            st.set_status(song_id, "failed", stage=None, error={"code": e.code, "message": e.message})
        except Exception:  # noqa: BLE001
            log.error("song %s erro inesperado:\n%s", song_id, traceback.format_exc())
            st.set_status(song_id, "failed", stage=None,
                          error={"code": "internal_error", "message": "Erro interno ao analisar o áudio. Veja os logs do serviço."})
