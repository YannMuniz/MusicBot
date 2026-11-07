"""Etiquetagem de áudio por janelas (PANNs Cnn14, AudioSet): voz cantada, guitarra, baixo, teclas, bateria.

Não é um detector de solo: dá EVIDÊNCIA por janela (probabilidades do AudioSet, não calibradas) para decidir onde há voz e
qual família de instrumento domina. A decisão fica em instrumental.py, com limiares explícitos e avaliados em eval/.
Código MIT, pesos CC BY 4.0 (atribuição: Kong et al., PANNs, TASLP 2020): ver panns/LICENSE_PANNS.
"""
import logging
import threading
from pathlib import Path

import librosa
import numpy as np
import torch

from .panns.cnn14 import SR as PANN_SR
from .panns.cnn14 import Cnn14

log = logging.getLogger("analyzer.tagger")
CLASSES = {"music": 137, "speech": 0, "singing": 27, "male_singing": 32, "female_singing": 33, "guitar": 140, "electric_guitar": 141,
           "bass_guitar": 142, "acoustic_guitar": 143, "keyboard": 152, "piano": 153, "organ": 155, "synth": 158, "drum_kit": 162}
WINDOW_S, HOP_S = 6.0, 2.0


class Tagger:
    def __init__(self, weights: Path):
        ckpt = torch.load(weights, map_location="cpu", weights_only=True)
        sd = ckpt["model"] if "model" in ckpt else ckpt
        self.model = Cnn14()
        mapped = {("mel_w" if k == "logmel_extractor.melW" else k): v for k, v in sd.items()}
        res = self.model.load_state_dict(mapped, strict=False)
        bad = [k for k in res.missing_keys if k not in ("window",)]
        if bad:
            raise RuntimeError(f"pesos PANNs incompatíveis: faltam {bad[:3]}")
        self.model.eval()
        self._lock = threading.Lock()

    def tag(self, y: np.ndarray, sr: int, window_s: float = WINDOW_S, hop_s: float = HOP_S):
        """Retorna (tempos centrais em s, {classe: probabilidades por janela}). y mono em qualquer sr."""
        y32 = librosa.resample(y.astype(np.float32), orig_sr=sr, target_sr=PANN_SR)
        win, hop = int(window_s * PANN_SR), int(hop_s * PANN_SR)
        starts = list(range(0, max(len(y32) - win, 0) + 1, hop)) or [0]
        if starts[-1] + win < len(y32):                       # cauda
            starts.append(max(len(y32) - win, 0))
        batch = np.stack([np.pad(y32[s:s + win], (0, max(0, win - len(y32[s:s + win])))) for s in starts])
        out = []
        with self._lock, torch.no_grad():
            for i in range(0, len(batch), 8):
                out.append(self.model(torch.from_numpy(batch[i:i + 8])).numpy())
        p = np.concatenate(out)
        times = np.array([(s + win / 2) / PANN_SR for s in starts])
        return times, {name: p[:, idx] for name, idx in CLASSES.items()}


_tagger = None
_lock = threading.Lock()


def get_tagger(weights_path: str):
    global _tagger
    p = Path(weights_path)
    if not p.is_file():
        return None
    with _lock:
        if _tagger is None:
            log.info("carregando pesos PANNs de %s", p)
            _tagger = Tagger(p)
        return _tagger
