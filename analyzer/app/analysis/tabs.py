"""Conversão de notas (MIDI) para tablatura jogável por programação dinâmica, com afinação/cordas/casas configuráveis.

Cada nota tem várias posições possíveis (corda, casa). Escolhemos o caminho de menor custo: mudança de casa, troca de corda,
deslocamento de posição e casas altas. É uma digitação PLAUSÍVEL, não a usada na gravação: o áudio não diz em que corda
a nota foi tocada. Alternativas ficam em cada nota (as 3 posições de menor custo local) para escolha/correção manual.
Cordas numeradas da mais aguda (1) à mais grave (N), como em tablaturas.
"""
from typing import List, Optional

STANDARD = [64, 59, 55, 50, 45, 40]                     # E4 B3 G3 D3 A2 E2 (cordas 1..6), altura real
TUNINGS = {"standard": STANDARD, "drop_d": [64, 59, 55, 50, 45, 38], "half_step_down": [63, 58, 54, 49, 44, 39],
           "dadgad": [62, 57, 55, 50, 45, 38], "bass_4": [43, 38, 33, 28]}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

W_FRET_STEP = 1.0      # por casa de deslocamento
W_STRING_JUMP = 0.7    # por corda de salto
W_HIGH_FRET = 0.12     # por casa acima da 12
W_OPEN = -0.3          # corda solta é cômoda (mas quebra posição: leve bônus)
W_POSITION = 0.35      # por casa de distância da posição média do trecho recente


def midi_name(m: int) -> str:
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def positions(pitch: int, tuning: List[int], max_fret: int) -> list:
    """Todas as (corda 1-based, casa) que produzem 'pitch'."""
    return [(s + 1, pitch - t) for s, t in enumerate(tuning) if 0 <= pitch - t <= max_fret]


def _cost(prev: Optional[tuple], cur: tuple, mean_fret: float) -> float:
    s, f = cur
    c = W_HIGH_FRET * max(0, f - 12) + (W_OPEN if f == 0 else 0.0) + W_POSITION * abs((f if f else mean_fret) - mean_fret) * 0
    if prev is not None:
        ps, pf = prev
        fe = 0 if f == 0 or pf == 0 else abs(f - pf)
        c += W_FRET_STEP * fe + W_STRING_JUMP * abs(s - ps)
    return c


def to_tab(notes: list, tuning: Optional[List[int]] = None, max_fret: int = 22) -> dict:
    """notes: [{'pitch': midi, ...}] em ordem temporal. Retorna as notas com string/fret/alternatives; notas fora de alcance
    ficam com string=None (não se inventa posição)."""
    tuning = list(tuning or STANDARD)
    opts = [positions(n["pitch"], tuning, max_fret) for n in notes]
    idx = [i for i, o in enumerate(opts) if o]
    best = {}                                          # i -> lista de (custo acumulado, ponteiro) por opção
    prev_i = None
    for i in idx:
        cur = []
        for o in opts[i]:
            if prev_i is None:
                cur.append((_cost(None, o, 5.0), None))
            else:
                cur.append(min((best[prev_i][k][0] + _cost(opts[prev_i][k], o, 5.0), k) for k in range(len(opts[prev_i]))))
        best[i] = cur
        prev_i = i
    choice = {}
    if idx:
        k = min(range(len(best[idx[-1]])), key=lambda k: best[idx[-1]][k][0])
        for i in reversed(idx):
            choice[i] = k
            k = best[i][k][1]
    out = []
    for i, n in enumerate(notes):
        m = dict(n)
        if i in choice:
            s, f = opts[i][choice[i]]
            m.update(string=s, fret=f)
            m["alternatives"] = [{"string": a, "fret": b} for a, b in sorted(opts[i], key=lambda p: (abs(p[1] - f), p[0])) if (a, b) != (s, f)][:3]
        else:
            m.update(string=None, fret=None, alternatives=[], unreachable=True)
        out.append(m)
    return {"tuning": tuning, "max_fret": max_fret, "strings": len(tuning), "notes": out,
            "disclaimer": "digitação plausível; o áudio não revela a corda/casa realmente usadas"}


def retab(notes: list, tuning: List[int], max_fret: int = 22) -> dict:
    """Recalcula a digitação (ex.: ao mudar a afinação) preservando tempos e técnicas; posições manuais ('locked') são mantidas."""
    return to_tab(notes, tuning, max_fret)
