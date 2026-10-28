"""Motor neural de acordes: BTC (Park et al., ISMIR 2019), vocabulário large_voca (14 qualidades x 12 raízes + N + X).

Pré-processamento idêntico ao do treino original: CQT de 144 bins (24/oitava), hop 2048 a 22,05 kHz,
calculado em blocos de 10 s, log-magnitude, normalizado por média/desvio salvos no checkpoint.
"""
import hashlib
import logging
import threading
from pathlib import Path

import librosa
import numpy as np
import torch

from .btc.btc_model import BTC_model

log = logging.getLogger("analyzer.btc")

SR = 22050
HOP = 2048
N_BINS = 144
BINS_PER_OCTAVE = 24
INST_LEN = 10.0
TIMESTEP = 108
FRAME_S = INST_LEN / TIMESTEP  # 0,0926 s por quadro de saída
N_CLASSES = 170
IDX_X, IDX_N = 168, 169

QUALITIES = ["min", "maj", "dim", "aug", "min6", "maj6", "min7", "minmaj7", "maj7", "7", "dim7", "hdim7", "sus2", "sus4"]
SUFFIX = {"min": "m", "maj": "", "dim": "dim", "aug": "aug", "min6": "m6", "maj6": "6", "min7": "m7",
          "minmaj7": "mM7", "maj7": "maj7", "7": "7", "dim7": "dim7", "hdim7": "m7(b5)", "sus2": "sus2", "sus4": "sus4"}
VOCABULARY = [SUFFIX[q] or "maj" for q in QUALITIES]

_CONFIG = dict(feature_size=N_BINS, timestep=TIMESTEP, num_chords=N_CLASSES, input_dropout=0.2, layer_dropout=0.2,
               attention_dropout=0.2, relu_dropout=0.2, num_layers=8, num_heads=4, hidden_size=128,
               total_key_depth=128, total_value_depth=128, filter_size=128, probs_out=True)


def class_to_chord(idx: int):
    """idx -> (root_pc | None, quality | None). N e X não têm raiz."""
    if idx >= IDX_X:
        return None, None
    return idx // 14, QUALITIES[idx % 14]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class BtcEngine:
    def __init__(self, weights: Path):
        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        # weights_only=True (sem executar código do pickle); libera só o escalar numpy de mean/std.
        from numpy._core.multiarray import scalar as _np_scalar
        with torch.serialization.safe_globals([(_np_scalar, "numpy.core.multiarray.scalar"), np.dtype, type(np.dtype("float64"))]):
            ckpt = torch.load(weights, map_location="cpu", weights_only=True)
        self.mean, self.std = float(ckpt["mean"]), float(ckpt["std"])
        self.model = BTC_model(config=_CONFIG)
        self.model.load_state_dict(ckpt["model"])
        self.model.eval()
        self.weights_sha256 = sha256_file(weights)
        self._lock = threading.Lock()

    @staticmethod
    def features(y: np.ndarray) -> np.ndarray:
        step = int(SR * INST_LEN)
        parts, cur = [], 0
        while len(y) > cur + step:
            parts.append(librosa.cqt(y[cur:cur + step], sr=SR, n_bins=N_BINS, bins_per_octave=BINS_PER_OCTAVE, hop_length=HOP))
            cur += step
        if len(y) - cur > 0:
            parts.append(librosa.cqt(y[cur:], sr=SR, n_bins=N_BINS, bins_per_octave=BINS_PER_OCTAVE, hop_length=HOP))
        return np.log(np.abs(np.concatenate(parts, axis=1)) + 1e-6)

    def posteriors(self, y: np.ndarray) -> np.ndarray:
        """Retorna probabilidades (170, T) por quadro de ~0,0926 s."""
        feat = (self.features(y).T - self.mean) / self.std  # (T, 144)
        n_frames = feat.shape[0]
        pad = (-n_frames) % TIMESTEP
        feat = np.pad(feat, ((0, pad), (0, 0)))
        x = torch.tensor(feat, dtype=torch.float32)
        out = []
        with self._lock, torch.no_grad():
            for t in range(feat.shape[0] // TIMESTEP):
                h, _ = self.model.self_attn_layers(x[None, t * TIMESTEP:(t + 1) * TIMESTEP])
                logits = self.model.output_layer(h)  # probs_out=True -> logits
                out.append(torch.softmax(logits[0], dim=-1).numpy())
        return np.concatenate(out, axis=0)[:n_frames].T


def decode(post: np.ndarray, stay: float = 0.9, min_dur_s: float = 0.25) -> list:
    """Viterbi sobre as posteriors (remove oscilações de 1-2 quadros) e fusão de trechos muito curtos."""
    post = post.copy()
    post[IDX_X] = 1e-6  # "X" (acorde fora do vocabulário) não é um rótulo útil
    post /= post.sum(axis=0, keepdims=True)
    n = post.shape[0]
    trans = np.full((n, n), (1 - stay) / (n - 1))
    np.fill_diagonal(trans, stay)
    path = librosa.sequence.viterbi(post, trans)

    runs = []  # [classe, quadro_inicial, quadro_final_exclusivo]
    for i, c in enumerate(path):
        if runs and runs[-1][0] == c:
            runs[-1][2] = i + 1
        else:
            runs.append([int(c), i, i + 1])
    # funde trechos mais curtos que min_dur_s no vizinho de maior probabilidade média
    min_frames = max(1, int(round(min_dur_s / FRAME_S)))
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for k, (c, a, b) in enumerate(runs):
            if b - a < min_frames:
                left = runs[k - 1] if k > 0 else None
                right = runs[k + 1] if k + 1 < len(runs) else None
                cands = [r for r in (left, right) if r is not None]
                tgt = max(cands, key=lambda r: post[r[0], a:b].mean())
                if tgt is left:
                    left[2] = b
                else:
                    right[1] = a
                runs.pop(k)
                changed = True
                break
        # reagrupa vizinhos iguais
        merged = []
        for r in runs:
            if merged and merged[-1][0] == r[0]:
                merged[-1][2] = r[2]
            else:
                merged.append(r)
        runs = merged
    return [(c, a, b, float(post[c, a:b].mean())) for c, a, b in runs]


_engine = None
_engine_lock = threading.Lock()


def get_engine(weights_path: str):
    """Carrega o modelo uma única vez. Devolve None se os pesos não existirem."""
    global _engine
    p = Path(weights_path)
    if not p.is_file():
        return None
    with _engine_lock:
        if _engine is None:
            log.info("carregando pesos BTC de %s", p)
            _engine = BtcEngine(p)
        return _engine


# Heurísticas de ambiguidade (NÃO calibradas): uma previsão é marcada ambígua quando o rótulo escolhido
# tem probabilidade média baixa ou quase empata com a melhor alternativa de outro rótulo.
AMBIG_MIN_P = 0.5
AMBIG_MIN_MARGIN = 0.25


def describe_runs(post: np.ndarray, runs: list, name_of) -> list:
    """Para cada corrida: probabilidade média, probabilidade da raiz (soma das qualidades da mesma raiz),
    até 3 alternativas e a marca 'ambiguous'. name_of(classe) -> nome do acorde."""
    out = []
    for c, a, b, _ in runs:
        mean = post[:, a:b].mean(axis=1)
        mean[IDX_X] = 0.0
        p = float(mean[c])
        root_p = None
        if c < IDX_X:
            r = c // 14
            root_p = float(mean[r * 14:(r + 1) * 14].sum())
        order = [int(i) for i in np.argsort(mean)[::-1] if i != c][:3]
        alts = [{"chord": name_of(i), "p": round(float(mean[i]), 3)} for i in order]
        margin = p - float(mean[order[0]])
        out.append({"p": round(p, 3), "root_p": None if root_p is None else round(root_p, 3),
                    "alternatives": alts, "ambiguous": bool(p < AMBIG_MIN_P or margin < AMBIG_MIN_MARGIN)})
    return out
