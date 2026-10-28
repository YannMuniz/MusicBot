import numpy as np

from app.analysis.pipeline import run_analysis
from tests.synth import render, write_wav

C_MAJOR = ["C", "G", "Am", "F"] * 4


def test_key_and_chords_on_synthetic_progression(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, render(C_MAJOR, 2.0))
    r = run_analysis(p)
    assert r["key"]["name"] == "C major"
    assert r["key"]["relative"] == {"tonic": "A", "mode": "minor"}
    # compara com a verdade: acorde ativo a cada instante (amostra a cada 0,25 s, ignorando 0,5 s ao redor das trocas)
    hits = total = 0
    for t in np.arange(0.5, 31.5, 0.25):
        idx = int(t // 2)
        if min(t - idx * 2, (idx + 1) * 2 - t) < 0.5:
            continue
        got = next(s["chord"] for s in r["chords"] if s["start"] <= t < s["end"])
        hits += got == C_MAJOR[idx]
        total += 1
    assert hits / total >= 0.9, f"acerto {hits}/{total}"
    assert all(s["end"] > s["start"] for s in r["chords"])


def test_no_artificial_flicker(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, render(C_MAJOR, 2.0))
    r = run_analysis(p)
    assert len(r["chords"]) <= len(C_MAJOR) * 1.5  # sem trocas espúrias a cada batida


def test_sections_vary_in_length_and_repeats_group(tmp_path):
    a = render(["C", "G", "Am", "F"] * 5, 1.0, harmonics=3, decay=0.4, seed=1)           # 20 s
    b = render(["Dm", "Bb", "F", "C"] * 5, 1.0, harmonics=8, decay=0.9, bpm=150, seed=2)  # 20 s, timbre diferente
    a2 = render(["C", "G", "Am", "F"] * 5, 1.0, harmonics=3, decay=0.4, seed=3)
    p = tmp_path / "s.wav"
    write_wav(p, np.concatenate([a, b, a2]))
    r = run_analysis(p)
    starts = [s["start"] for s in r["sections"]]
    assert any(abs(x - 20) < 3 for x in starts), starts
    assert any(abs(x - 40) < 3 for x in starts), starts
    first, last = r["sections"][0], r["sections"][-1]
    assert first["repeat_group"] == last["repeat_group"]
    assert all(s["semantic_label"] is None and s["label"].startswith("Parte") for s in r["sections"])
