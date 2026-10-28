"""Validação do arquivo (tipo real via ffprobe, nunca só a extensão) e decodificação."""
import json
import subprocess
from pathlib import Path

import librosa
import numpy as np

from .config import Settings

SR = 22050

_FORMATS = {"mp3": {"mp3"}, "wav": {"wav", "w64"}}


class AudioError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 422):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def _magic_ok(path: Path, ext: str) -> bool:
    head = path.read_bytes()[:12] if path.stat().st_size >= 12 else b""
    if ext == "wav":
        return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    return head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)


def probe(path: Path) -> dict:
    """ffprobe em modo leitura; o arquivo nunca é executado, só inspecionado."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_type,sample_rate,channels",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        raise AudioError("probe_timeout", "Tempo esgotado ao inspecionar o arquivo.")
    if out.returncode != 0:
        raise AudioError("invalid_audio", "Arquivo de áudio inválido ou corrompido.")
    return json.loads(out.stdout or "{}")


def validate_audio_file(path: Path, ext: str, settings: Settings) -> dict:
    """Retorna metadados do áudio ou levanta AudioError."""
    if ext not in settings.allowed_extensions:
        raise AudioError("unsupported_extension", f"Extensão não permitida: .{ext}. Use MP3 ou WAV.", 415)
    if not _magic_ok(path, ext):
        raise AudioError("content_mismatch", "O conteúdo do arquivo não corresponde à extensão informada.", 415)
    info = probe(path)
    fmt = (info.get("format", {}).get("format_name") or "").split(",")
    if not set(fmt) & _FORMATS[ext]:
        raise AudioError("content_mismatch", "O formato real do arquivo difere da extensão.", 415)
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise AudioError("no_audio_stream", "O arquivo não contém fluxo de áudio.")
    duration = float(info["format"].get("duration") or 0)
    if duration < settings.min_duration_s:
        raise AudioError("too_short", f"Áudio muito curto (mínimo {settings.min_duration_s:.0f}s).")
    if duration > settings.max_duration_s:
        raise AudioError("too_long", f"Áudio muito longo (máximo {settings.max_duration_s / 60:.0f} min).", 413)
    return {
        "duration": round(duration, 2),
        "format": fmt[0],
        "sample_rate": int(streams[0].get("sample_rate") or 0),
        "channels": int(streams[0].get("channels") or 0),
    }


def load_audio(path: Path):
    """Mono, 22.05 kHz. Falha clara se a decodificação ou o conteúdo (silêncio) forem inválidos."""
    try:
        y, _ = librosa.load(str(path), sr=SR, mono=True)
    except Exception as e:  # noqa: BLE001 - qualquer falha de decodificação vira erro de domínio
        raise AudioError("decode_error", f"Falha ao decodificar o áudio: {e}")
    if len(y) == 0 or float(np.max(np.abs(y))) < 1e-4:
        raise AudioError("silent_audio", "O áudio está vazio ou silencioso.")
    return y
