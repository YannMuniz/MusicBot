"""Áudio sintético com acordes conhecidos (verdade de referência por construção). NÃO substitui música real."""
import numpy as np
import soundfile as sf

SR = 22050
PCS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "Bb": 10}


def chord_pcs(name: str):
    minor = name.endswith("m")
    root = PCS[name[:-1] if minor else name]
    return [root, (root + (3 if minor else 4)) % 12, (root + 7) % 12]


def render(prog, seconds_each=2.0, harmonics=4, decay=0.6, bpm=120, clicks=True, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for name in prog:
        n = int(seconds_each * SR)
        t = np.arange(n) / SR
        y = np.zeros(n)
        for pc in chord_pcs(name):
            f0 = 261.63 * 2 ** (pc / 12)
            for h in range(1, harmonics + 1):
                y += (decay ** (h - 1)) * np.sin(2 * np.pi * f0 * h * t)
        y *= np.minimum(1, np.minimum(t, seconds_each - t) / 0.02) / 3
        out.append(y)
    y = np.concatenate(out)
    if clicks:
        step = int(60 / bpm * SR)
        for i in range(0, len(y) - 400, step):
            y[i:i + 400] += rng.normal(0, 0.5, 400) * np.hanning(400)
    return (y / np.max(np.abs(y)) * 0.8).astype(np.float32)


def write_wav(path, y):
    sf.write(str(path), y, SR)
