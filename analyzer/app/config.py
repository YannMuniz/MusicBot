"""Configuração por variáveis de ambiente (sem segredos no código)."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    storage_root: Path
    internal_token: str
    max_upload_bytes: int
    max_duration_s: float
    min_duration_s: float
    allowed_extensions: tuple

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            storage_root=Path(os.environ.get("ANALYZER_STORAGE_ROOT", "/storage/songs")),
            internal_token=os.environ.get("ANALYZER_INTERNAL_TOKEN", ""),
            max_upload_bytes=int(float(os.environ.get("ANALYZER_MAX_UPLOAD_MB", "100")) * 1024 * 1024),
            max_duration_s=float(os.environ.get("ANALYZER_MAX_DURATION_S", "900")),
            min_duration_s=float(os.environ.get("ANALYZER_MIN_DURATION_S", "5")),
            allowed_extensions=("mp3", "wav"),
        )
