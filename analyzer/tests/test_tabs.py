"""Transcrição monofônica e conversão para tablatura. Áudio SINTÉTICO: verifica a lógica e a sincronia, NÃO a precisão em
guitarra real (medida em eval/ contra a tablatura da cifra de "O Tempo")."""
import numpy as np
import pytest

from app.analysis import tabs
from app.analysis import transcription as T

SR = T.SR


def tone(midi, dur, vibrato=False, harmonics=(1, 0.5, 0.3)):
    f0 = 440.0 * 2 ** ((midi - 69) / 12)
    t = np.arange(int(dur * SR)) / SR
    inst = f0 * (1 + (0.03 * np.sin(2 * np.pi * 6 * t) if vibrato else 0.0) * np.ones_like(t))
    ph = 2 * np.pi * np.cumsum(inst) / SR
    y = sum(a * np.sin(h * ph) for h, a in enumerate(harmonics, start=1))
    return (y * np.minimum(1, np.minimum(t, dur - t) / 0.01)).astype(np.float32)


def melody(notes):
    """notes: [(midi, dur)] separadas por 30 ms de silêncio."""
    parts, t0, truth = [], 0.0, []
    for m, d in notes:
        parts += [tone(m, d), np.zeros(int(0.03 * SR), np.float32)]
        truth.append((m, t0, t0 + d))
        t0 += d + 0.03
    return np.concatenate(parts), truth


# --- tablatura ---------------------------------------------------------------------------------------------
def test_positions_and_tuning_change_recalculate_fingering():
    assert (1, 5) in tabs.positions(69, tabs.STANDARD, 22) and (2, 10) in tabs.positions(69, tabs.STANDARD, 22)   # A4: 5ª casa da corda 1 ou 10ª da 2
    a = tabs.to_tab([{"pitch": 40}], tabs.STANDARD)["notes"][0]
    assert (a["string"], a["fret"]) == (6, 0)                                  # E2 = corda solta
    d = tabs.to_tab([{"pitch": 38}], tabs.TUNINGS["drop_d"])["notes"][0]
    assert (d["string"], d["fret"]) == (6, 0)                                  # D2 solta em Drop D; em afinação padrão não existe
    assert tabs.to_tab([{"pitch": 38}], tabs.STANDARD)["notes"][0]["unreachable"] is True


def test_unreachable_notes_are_not_invented_and_range_is_respected():
    r = tabs.to_tab([{"pitch": 100}, {"pitch": 20}, {"pitch": 64}], tabs.STANDARD, max_fret=12)
    assert r["notes"][0]["string"] is None and r["notes"][1]["string"] is None and r["notes"][2]["string"] is not None
    assert all(n["fret"] <= 12 for n in r["notes"] if n["fret"] is not None)


def test_fingering_prefers_close_positions_and_keeps_alternatives():
    seq = [{"pitch": p} for p in (60, 62, 64, 65, 67)]                         # C4 D4 E4 F4 G4 subindo
    out = tabs.to_tab(seq, tabs.STANDARD)["notes"]
    frets = [n["fret"] for n in out if n["fret"] != 0]
    assert max(frets) - min(frets) <= 5 and all(n["string"] for n in out)       # posição compacta, não saltos pela escala
    assert all(len(n["alternatives"]) >= 1 for n in out[:3])
    assert all(tabs.STANDARD[n["string"] - 1] + n["fret"] == n["pitch"] for n in out)   # a posição escolhida sempre produz a altura certa


def test_time_and_techniques_survive_retab():
    notes = [{"pitch": 64, "start": 1.0, "end": 1.4, "techniques": [{"type": "vibrato", "inferred": True}]}, {"pitch": 67, "start": 1.4, "end": 2.0}]
    a = tabs.to_tab(notes)["notes"]
    b = tabs.retab(notes, tabs.TUNINGS["half_step_down"])["notes"]
    assert [(n["start"], n["end"]) for n in a] == [(n["start"], n["end"]) for n in b] and b[0]["techniques"][0]["type"] == "vibrato"
    assert a[0]["fret"] != b[0]["fret"] or a[0]["string"] != b[0]["string"]    # afinação diferente => outra digitação


# --- transcrição --------------------------------------------------------------------------------------------
def test_monophonic_melody_is_transcribed_with_pitch_and_time():
    y, truth = melody([(64, 0.4), (67, 0.4), (69, 0.4), (72, 0.5), (69, 0.4)])
    r = T.transcribe(y, start_s=10.0, mode="raw")
    got = [(n["pitch"], n["start"], n["end"]) for n in r["notes"]]
    assert [g[0] for g in got] == [t[0] for t in truth]                           # alturas e ordem corretas
    for (_, a, b), (_, ta, tb) in zip(got, truth):                               # tempos sincronizados (deslocados por start_s)
        assert abs(a - (10.0 + ta)) < 0.08 and abs(b - (10.0 + tb)) < 0.1
    assert r["state"] == "completed" and r["monophonic_only"] is True


def test_vibrato_is_inferred_only_when_present_and_flagged_inferred():
    vib = np.concatenate([tone(69, 1.0, vibrato=True), np.zeros(int(0.1 * SR), np.float32)])
    plain = np.concatenate([tone(69, 1.0), np.zeros(int(0.1 * SR), np.float32)])
    nv = T.transcribe(vib, mode="raw")["notes"]
    npl = T.transcribe(plain, mode="raw")["notes"]
    assert any(t["type"] == "vibrato" and t["inferred"] for n in nv for t in n["techniques"])
    assert not any(t["type"] == "vibrato" for n in npl for t in n["techniques"])
    assert all(t["type"] in ("vibrato", "glissando") for n in nv + npl for t in n["techniques"])    # bend/hammer/pull NÃO são inventados


def test_noise_and_silence_give_low_confidence_not_made_up_notes():
    rng = np.random.default_rng(0)
    noise = (rng.normal(0, 0.1, 3 * SR)).astype(np.float32)
    r = T.transcribe(noise, mode="raw")
    assert r["state"] == "low_confidence"
    s = T.transcribe(np.zeros(2 * SR, np.float32), mode="raw")
    assert s["notes"] == [] and s["state"] == "low_confidence"
