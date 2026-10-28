"""Estimativa de baixo por segmento para sugerir inversões (ex.: A/C#), independente da previsão do BTC.

Método (v2):
  1. CQT de 36 bins/oitava de C1 a C6 (preserva a informação de oitava, ao contrário do cromagrama).
  2. Saliência: candidatos são fundamentais entre E1 (41 Hz) e G3 (196 Hz) com energia real (≥ 25 % da maior do quadro);
     a energia dos harmônicos 2, 3 e 4 (pesos 0,7; 0,5; 0,35) reforça o candidato, e um harmônico forte de outra nota
     não vira "baixo". Não há fundamental "virtual": sem baixo audível o quadro não vota (ver bass_chroma).
  3. Quadros sem energia grave suficiente (< 20 % da mediana dos quadros com baixo) não votam.
  4. Em cada segmento do BTC, cada quadro vota na classe de altura mais saliente; vence a classe com maior fração dos votos.
Uma inversão só é registrada se: o baixo vencedor é nota do acorde previsto (3ª, 5ª ou 7ª), tem ≥ 60 % dos votos, os quadros
com voto cobrem ≥ 50 % do segmento e o segmento dura ≥ 0,4 s. Limiares fixados a priori, NÃO ajustados em dados anotados;
a validade da regra é medida em eval/ (ver docs/avaliacao.md). Se o baixo não é nota do acorde ou a evidência é fraca,
o acorde harmônico é mantido e o motivo fica em 'bass.reason'.
"""
import librosa
import numpy as np

from .tonality import note_name

HOP = 512
BPO = 36
N_OCT = 5
FMIN = librosa.note_to_hz("C1")
LOW, HIGH = librosa.note_to_hz("E1"), librosa.note_to_hz("G3")
HARMONICS = ((1, 1.0), (2, 0.7), (3, 0.5), (4, 0.35))
VOICED_REL = 0.2
FUND_MIN_REL = 0.25
BASS_VS_MID = 0.15
MIN_VOTE_SHARE = 0.6
MIN_VOICED = 0.5
MIN_SEG_S = 0.4
CHORD_TONES = {"maj": (0, 4, 7), "min": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8), "min6": (0, 3, 7, 9),
               "maj6": (0, 4, 7, 9), "min7": (0, 3, 7, 10), "minmaj7": (0, 3, 7, 11), "maj7": (0, 4, 7, 11),
               "7": (0, 4, 7, 10), "dim7": (0, 3, 6, 9), "hdim7": (0, 3, 6, 10), "sus2": (0, 2, 7), "sus4": (0, 5, 7)}


def bass_chroma(y: np.ndarray, sr: int):
    """(12, T) saliência de baixo por classe de altura e o tempo (s) de cada quadro.

    Candidato = fundamental entre E1 e G3 que EXISTE no áudio (energia ≥ 25 % da maior fundamental grave do quadro);
    harmônicos 2–4 só reforçam. Sem essa exigência a soma harmônica inventa fundamentais "virtuais" a partir das notas
    do próprio acorde (ex.: um E3 para C-E-G), gerando inversões falsas em trechos sem baixo. Quadros em que o grave
    é fraco frente aos médios (< 15 %) ficam sem voto."""
    c = np.abs(librosa.cqt(y, sr=sr, hop_length=HOP, fmin=FMIN, n_bins=BPO * N_OCT, bins_per_octave=BPO))
    freqs = librosa.cqt_frequencies(BPO * N_OCT, fmin=FMIN, bins_per_octave=BPO)
    cand = np.where((freqs >= LOW) & (freqs <= HIGH))[0]
    mid = np.where((freqs > HIGH) & (freqs <= librosa.note_to_hz("C6")))[0]
    fund = np.stack([c[max(k - 1, 0):k + 2].max(axis=0) for k in cand])
    sal = fund.copy()
    for h, w in HARMONICS[1:]:
        off = int(round(BPO * np.log2(h)))
        for i, k in enumerate(cand):
            if k + off + 1 < c.shape[0]:
                sal[i] += w * c[max(k + off - 1, 0):k + off + 2].max(axis=0)
    fmax = fund.max(axis=0)
    sal = np.where(fund >= FUND_MIN_REL * fmax, sal, 0.0)
    sal[:, fmax < BASS_VS_MID * c[mid].max(axis=0)] = 0.0
    pc = (np.round(cand / (BPO / 12)).astype(int)) % 12
    out = np.zeros((12, c.shape[1]))
    for p in range(12):
        sel = sal[pc == p]
        if len(sel):
            out[p] = sel.max(axis=0)
    return out, librosa.frames_to_time(np.arange(out.shape[1]), sr=sr, hop_length=HOP)


def estimate_bass(pcs: np.ndarray, times: np.ndarray, start: float, end: float):
    """Votação por quadro. Retorna (classe, fração_dos_votos, fração_com_voto) ou None sem baixo audível."""
    m = (times >= start) & (times < end)
    if not m.any():
        return None
    seg = pcs[:, m]
    peak = pcs.max(axis=0)
    if not (peak > 0).any():
        return None
    ref = np.median(peak[peak > 0])
    voiced = (seg.max(axis=0) >= VOICED_REL * ref) & (seg.max(axis=0) > 0)
    if not voiced.any():
        return None
    votes = np.bincount(seg[:, voiced].argmax(axis=0), minlength=12)
    b = int(votes.argmax())
    return b, float(votes[b] / votes.sum()), float(voiced.mean())


def annotate_bass(segs: list, pcs: np.ndarray, times: np.ndarray, flats: bool) -> None:
    """Acrescenta a cada segmento 'bass' {note, vote_share, voiced, reason?} e, se confiável, 'inversion' (ex.: 'A/C#')."""
    for s in segs:
        if s["root"] is None:
            continue
        est = estimate_bass(pcs, times, s["start"], s["end"])
        if est is None:
            s["bass"] = {"note": None, "reason": "no_bass_energy"}
            continue
        b, share, voiced = est
        info = {"note": note_name(b, flats), "vote_share": round(share, 3), "voiced": round(voiced, 3)}
        interval = (b - s["root"]) % 12
        if b == s["root"]:
            info["reason"] = "root"
        elif interval not in CHORD_TONES.get(s["quality"], ()):
            info["reason"] = "bass_not_in_chord"          # nota de passagem, extensão ou erro de harmonia: sem inversão
        elif share < MIN_VOTE_SHARE or voiced < MIN_VOICED:
            info["reason"] = "weak_evidence"
        elif s["end"] - s["start"] < MIN_SEG_S:
            info["reason"] = "segment_too_short"
        else:
            info["reason"] = "inversion"
            s["inversion"] = f"{s['chord']}/{note_name(b, flats)}"
        s["bass"] = info
