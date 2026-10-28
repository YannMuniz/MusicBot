"""Harmonização de rótulos de acorde (Harte/mir_eval) para o vocabulário de 170 classes do BTC.

Rótulos fora das 14 qualidades (9ª, 11ª, 13ª, add, alterados) são reduzidos à qualidade-base ou, se não houver
equivalente, viram X (ignorado no treino). Isso PERDE informação de extensão: para aprender extensões é preciso
um vocabulário maior (nova cabeça de saída) e dados anotados com extensões; ver training/README.md.
"""
import mir_eval

QUALITIES = ["min", "maj", "dim", "aug", "min6", "maj6", "min7", "minmaj7", "maj7", "7", "dim7", "hdim7", "sus2", "sus4"]
IDX_X, IDX_N = 168, 169
IGNORE = -100  # quadros sem rótulo (ex.: correções pontuais): fora da perda


def label_to_class(label: str) -> int:
    if label == "N":
        return IDX_N
    if label == "X":
        return IDX_X
    try:
        root, quality, deg, _bass = mir_eval.chord.split(label)
    except mir_eval.chord.InvalidChordException:
        return IDX_X
    q = quality or "maj"
    # extensões como grau extra (ex.: maj(9) = add9) são descartadas: a classe resultante é a qualidade-base
    if q not in QUALITIES and q in mir_eval.chord.EXTENDED_QUALITY_REDUX:
        q = mir_eval.chord.EXTENDED_QUALITY_REDUX[q][0]
    if q not in QUALITIES:
        return IDX_X
    pc = mir_eval.chord.pitch_class_to_semitone(root)
    return pc * 14 + QUALITIES.index(q)


def frames_from_intervals(intervals, labels, n_frames: int, frame_s: float, fill: int = IGNORE):
    """Vetor de classes por quadro (início do quadro + meio quadro); quadros fora dos intervalos = fill."""
    import numpy as np
    out = np.full(n_frames, fill, dtype=np.int64)
    for (a, b), lab in zip(intervals, labels):
        i0, i1 = int(round(a / frame_s)), int(round(b / frame_s))
        out[max(i0, 0):min(i1, n_frames)] = label_to_class(lab)
    return out
