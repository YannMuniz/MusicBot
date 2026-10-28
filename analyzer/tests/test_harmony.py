"""Baixo (inversões), representação estruturada e evidência de notas de cor. Áudio SINTÉTICO: verifica o funcionamento
técnico dos detectores, não a precisão em música real."""
import numpy as np

from app.analysis import bass as B
from app.analysis import harmony
from tests.synth import SR

A3, CS4, E4 = 220.0, 277.18, 329.63
CS2, A2, B2 = 69.30, 110.0, 123.47


def tone(f, n, harmonics=(1, 0.6, 0.4, 0.3), drop_fundamental=False):
    t = np.arange(n) / SR
    y = np.zeros(n)
    for h, a in enumerate(harmonics, start=1):
        if drop_fundamental and h == 1:
            continue
        y += a * np.sin(2 * np.pi * f * h * t)
    return y


def chord_with_bass(bass_notes, seconds=2.0, drop_fundamental=False, noise=0.0, seed=0, harmonics=(1, 0.6, 0.4, 0.3)):
    """Tríade de A maior em oitava média + sequência de notas de baixo (cada uma dura seconds/len)."""
    n = int(seconds * SR)
    y = 0.35 * sum(tone(f, n) for f in (A3, CS4, E4))
    per = n // len(bass_notes)
    for i, f in enumerate(bass_notes):
        y[i * per:(i + 1) * per] += 1.0 * tone(f, per, harmonics=harmonics, drop_fundamental=drop_fundamental)
    if noise:
        y += np.random.default_rng(seed).normal(0, noise, n)
    return (y / np.max(np.abs(y)) * 0.8).astype(np.float32)


def run(y, seconds=2.0):
    pcs, tt = B.bass_chroma(y, SR)
    seg = [{"start": 0.0, "end": seconds, "chord": "A", "root": 9, "quality": "maj"}]
    B.annotate_bass(seg, pcs, tt, flats=False)
    return seg[0]


def test_inversion_detected_when_bass_is_third():
    s = run(chord_with_bass([CS2]))
    assert s["inversion"] == "A/C#" and s["bass"]["reason"] == "inversion"


def test_no_inversion_when_bass_is_root():
    s = run(chord_with_bass([A2]))
    assert "inversion" not in s and s["bass"]["reason"] == "root" and s["bass"]["note"] == "A"


def test_weak_or_missing_fundamental_is_found_by_pitch_class():
    weak = chord_with_bass([CS2], harmonics=(0.4, 1.0, 0.8, 0.6))            # fundamental fraca, harmônicos fortes (MP3/alto-falante pequeno)
    assert run(weak)["bass"]["note"] == "C#"
    gone = run(chord_with_bass([CS2], drop_fundamental=True))              # sem a fundamental, o 2º harmônico (C#3) está na faixa: mesma classe de altura
    assert gone["bass"]["note"] == "C#"


def test_chord_without_any_bass_instrument_never_gets_an_inversion():
    n = 2 * SR
    y = (0.35 * sum(tone(f, n) for f in (A3, CS4, E4))).astype(np.float32)   # só a tríade: sem baixo
    s = run(y)
    assert "inversion" not in s and s["bass"]["reason"] in ("no_bass_energy", "root", "weak_evidence", "bass_not_in_chord")


def test_passing_note_outside_chord_is_not_an_inversion():
    s = run(chord_with_bass([B2]))                           # B não é nota de A maior
    assert "inversion" not in s and s["bass"]["reason"] == "bass_not_in_chord"


def test_walking_bass_without_majority_is_not_an_inversion():
    s = run(chord_with_bass([A2, CS2, A2, CS2, A2]))         # alterna: nenhuma nota tem 60 % dos votos... exceto A
    assert "inversion" not in s


def test_noise_and_silence_do_not_invent_inversions():
    s = run(chord_with_bass([CS2], noise=0.3))
    assert s["bass"]["note"] in ("C#", None) and (s.get("inversion") in (None, "A/C#"))
    silence = run(np.zeros(2 * SR, dtype=np.float32))
    assert "inversion" not in silence and silence["bass"]["reason"] == "no_bass_energy"


def test_finalize_builds_structure_and_keeps_harmonic_label():
    segs = [{"start": 0, "end": 2, "chord": "A", "root": 9, "quality": "maj", "inversion": "A/C#", "bass": {"note": "C#", "reason": "inversion"}},
            {"start": 2, "end": 4, "chord": "D", "root": 2, "quality": "maj", "bass": {"note": "D", "reason": "root"}},
            {"start": 4, "end": 5, "chord": "N", "root": None, "quality": None}]
    harmony.finalize(segs, flats=False)
    a, d, n = segs
    assert a["chord"] == "A/C#" and a["harmonic_label"] == "A" and a["model_label"] == "A"
    assert a["structure"]["inversion"] == {"bass": "C#", "interval": 4, "degree": "1"} and a["structure"]["intervals"] == [0, 4, 7]
    assert d["chord"] == "D" and d["structure"]["inversion"] is None and d["structure"]["bass"] == "D"
    assert n["structure"]["root"] is None


def _chroma(notes):
    c = np.full((12, 200), 0.02)
    for pc, v in notes.items():
        c[pc] = v
    return c


def test_color_tone_evidence_flags_add9_vs_sus2_without_changing_chord():
    frame_s = 0.0232
    base = {"start": 0.0, "end": 4.0, "chord": "D", "harmonic_label": "D", "root": 2, "quality": "maj"}
    base_raw = {k: v for k, v in base.items() if k != "harmonic_label"}          # como no pipeline: tone_evidence roda antes de finalize
    add9, sus2, plain = dict(base_raw), dict(base), dict(base)
    harmony.tone_evidence([add9], _chroma({2: 1.0, 6: 1.0, 9: 1.0, 4: 0.9}), frame_s)      # D F# A + E
    harmony.tone_evidence([sus2], _chroma({2: 1.0, 9: 1.0, 4: 0.9, 6: 0.05}), frame_s)      # D A + E, sem terça
    harmony.tone_evidence([plain], _chroma({2: 1.0, 6: 1.0, 9: 1.0}), frame_s)
    assert add9["possible_additions"][0]["label"] == "D(add9?)"
    assert sus2["possible_additions"][0]["label"] == "D(sus2?)"
    assert "possible_additions" not in plain
    assert add9["chord"] == "D"                       # nunca altera o rótulo exibido


def test_color_tones_ignored_for_short_segments_and_non_triads():
    frame_s = 0.0232
    short = {"start": 0.0, "end": 0.5, "chord": "D", "harmonic_label": "D", "root": 2, "quality": "maj"}
    seventh = {"start": 0.0, "end": 4.0, "chord": "Dm7", "harmonic_label": "Dm7", "root": 2, "quality": "min7"}
    harmony.tone_evidence([short, seventh], _chroma({2: 1.0, 6: 1.0, 9: 1.0, 4: 0.9, 5: 1.0, 0: 1.0}), frame_s)
    assert "possible_additions" not in short and "possible_additions" not in seventh
