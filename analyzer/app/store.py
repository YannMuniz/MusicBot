"""Armazenamento por música: storage/songs/{id}/. O serviço é o único escritor.

original.<ext> imutável; metadata.json (estático); status.json (estado do job);
analysis.json / chords.json / sections.json / report.txt = análise ATUAL;
history/{run_id}/ = análises anteriores (reprocessamento); chords.edited.json = correções do usuário.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ID_RE = re.compile(r"^[0-9a-f]{32}$")
RESULT_FILES = ("analysis.json", "chords.json", "chords.raw.json", "sections.json", "report.txt")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_display_name(name: Optional[str]) -> str:
    """Só para exibição; o nome nunca é usado como caminho."""
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f]", "", base).strip()
    return (base or "sem-nome")[:200]


class SongStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # -- caminhos -----------------------------------------------------------------
    def dir(self, song_id: str) -> Path:
        if not ID_RE.match(song_id or ""):
            raise KeyError(song_id)
        d = self.root / song_id
        if not d.is_dir():
            raise KeyError(song_id)
        return d

    def original_path(self, song_id: str) -> Path:
        meta = self.read(song_id, "metadata.json")
        return self.dir(song_id) / f"original.{meta['extension']}"

    # -- E/S atômica ---------------------------------------------------------------
    def write(self, song_id: str, name: str, data) -> None:
        d = self.dir(song_id)
        tmp = d / f".{name}.{uuid.uuid4().hex}.tmp"
        tmp.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, d / name)

    def read(self, song_id: str, name: str):
        p = self.dir(song_id) / name
        if not p.is_file():
            raise FileNotFoundError(name)
        txt = p.read_text(encoding="utf-8")
        return txt if name.endswith(".txt") else json.loads(txt)

    def exists(self, song_id: str, name: str) -> bool:
        return (self.dir(song_id) / name).is_file()

    # -- ciclo de vida -------------------------------------------------------------
    def create(self, tmp_file: Path, extension: str, display_name: str, audio_info: dict) -> str:
        """Move o upload (já validado) para um diretório novo com ID único; nunca sobrescreve."""
        song_id = uuid.uuid4().hex
        d = self.root / song_id
        d.mkdir(parents=True, exist_ok=False)
        dest = d / f"original.{extension}"
        shutil.move(str(tmp_file), dest)
        os.chmod(dest, 0o640)
        h = hashlib.sha256()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        self.write(song_id, "metadata.json", {
            "id": song_id, "original_filename": display_name, "extension": extension,
            "size_bytes": dest.stat().st_size, "sha256": h.hexdigest(), "created_at": now(), **audio_info,
        })
        self.set_status(song_id, "pending")
        return song_id

    def set_status(self, song_id: str, status: str, **extra) -> dict:
        with self._lock:
            try:
                cur = self.read(song_id, "status.json")
            except FileNotFoundError:
                cur = {"runs": 0}
            cur = {**cur, "status": status, "updated_at": now(), **extra}
            self.write(song_id, "status.json", cur)
            return cur

    def archive_current(self, song_id: str) -> Optional[str]:
        """Move a análise atual para history/{run_id}/ antes de gravar uma nova."""
        if not self.exists(song_id, "analysis.json"):
            return None
        d = self.dir(song_id)
        run_id = self.read(song_id, "analysis.json").get("run_id", uuid.uuid4().hex[:12])
        dest = d / "history" / run_id
        dest.mkdir(parents=True, exist_ok=True)
        for f in RESULT_FILES:
            if (d / f).is_file():
                shutil.move(str(d / f), dest / f)
        return run_id

    def list(self) -> list:
        out = []
        for p in self.root.iterdir():
            if p.is_dir() and ID_RE.match(p.name):
                try:
                    out.append(self.summary(p.name))
                except (FileNotFoundError, KeyError, json.JSONDecodeError):
                    continue
        return sorted(out, key=lambda s: s["created_at"], reverse=True)

    def summary(self, song_id: str) -> dict:
        meta, st = self.read(song_id, "metadata.json"), self.read(song_id, "status.json")
        s = {**meta, "status": st["status"], "stage": st.get("stage"), "error": st.get("error"),
             "updated_at": st["updated_at"], "runs": st.get("runs", 0)}
        if self.exists(song_id, "analysis.json"):
            a = self.read(song_id, "analysis.json")
            s["key"] = a["key"]["name"]
            s["run_id"] = a["run_id"]
        return s

    def history(self, song_id: str) -> list:
        h = self.dir(song_id) / "history"
        runs = []
        if h.is_dir():
            for p in sorted(h.iterdir()):
                if (p / "analysis.json").is_file():
                    a = json.loads((p / "analysis.json").read_text(encoding="utf-8"))
                    runs.append({"run_id": a["run_id"], "created_at": a["created_at"], "algorithm": a["algorithm"], "key": a["key"]["name"]})
        return runs
