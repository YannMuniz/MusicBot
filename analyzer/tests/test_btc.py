import re

import numpy as np

from app.analysis.btc_engine import FRAME_S, IDX_N, IDX_X, N_CLASSES, QUALITIES, class_to_chord, decode
from app.analysis.chords import segments_from_runs
from app.analysis.pipeline import run_analysis
from tests.synth import render, write_wav

CHORD_RE = re.compile(r"^(N|[A-G][#b]?[A-Za-z0-9()]*(/[A-G][#b]?)?)$")


def _one_hot(seq, p=0.9):
    post = np.full((N_CLASSES, len(seq)), (1 - p) / (N_CLASSES - 1))
    for t, c in enumerate(seq):
        post[c, t] = p
    return post


def test_class_mapping_matches_original_vocabulary():
    assert class_to_chord(0 * 14 + 1) == (0, "maj")        # C
    assert class_to_chord(0) == (0, "min")                 # Cm
    assert class_to_chord(9 * 14 + 8) == (9, "maj7")       # Amaj7
    assert class_to_chord(7 * 14 + 9) == (7, "7")          # G7
    assert class_to_chord(IDX_X) == (None, None) and class_to_chord(IDX_N) == (None, None)
    assert len(QUALITIES) == 14


def test_decode_removes_one_frame_flicker():
    c, g = 1, 7 * 14 + 1
    seq = [c] * 20 + [g] + [c] * 20            # um quadro isolado de outro acorde
    runs = decode(_one_hot(seq))
    assert len(runs) == 1 and runs[0][0] == c and runs[0][1] == 0 and runs[0][2] == len(seq)


def test_decode_keeps_sustained_changes_and_covers_all_frames():
    seq = [1] * 15 + [7 * 14 + 9] * 15 + [IDX_N] * 15
    runs = decode(_one_hot(seq))
    assert [r[0] for r in runs] == [1, 7 * 14 + 9, IDX_N]
    assert runs[0][1] == 0 and runs[-1][2] == len(seq) and all(a[2] == b[1] for a, b in zip(runs, runs[1:]))


def test_segment_names_follow_key_spelling():
    runs = [(10 * 14 + 8, 0, 10, 0.9), (7 * 14 + 0, 10, 20, 0.8), (IDX_N, 20, 30, 0.7)]
    flats = segments_from_runs(runs, FRAME_S, 30 * FRAME_S, True)
    sharps = segments_from_runs(runs, FRAME_S, 30 * FRAME_S, False)
    assert [s["chord"] for s in flats] == ["Bbmaj7", "Gm", "N"]
    assert [s["chord"] for s in sharps] == ["A#maj7", "Gm", "N"]
    assert flats[0]["start"] == 0.0 and flats[-1]["end"] == round(30 * FRAME_S, 3)
    assert flats[2]["root"] is None


def test_pipeline_uses_neural_engine_and_records_provenance(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, render(["C", "G", "Am", "F"] * 3, 2.0))
    r = run_analysis(p)
    assert r["algorithm"]["name"] == "btc-large-voca" and len(r["algorithm"]["weights_sha256"]) == 64
    assert all(CHORD_RE.match(s["chord"]) for s in r["chords"])
    assert all(a["end"] == b["start"] for a, b in zip(r["chords"], r["chords"][1:]))
    assert any("9ª" in w for w in r["warnings"])  # limitação de vocabulário declarada


def test_fallback_to_baseline_when_engine_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYZER_CHORD_ENGINE", "baseline")
    p = tmp_path / "a.wav"
    write_wav(p, render(["C", "G", "Am", "F"] * 3, 2.0))
    r = run_analysis(p)
    assert r["algorithm"]["name"] == "librosa-baseline"
    assert any("indisponível" in w for w in r["warnings"])


def test_ambiguity_flag_and_alternatives():
    from app.analysis.btc_engine import describe_runs
    c_maj, c_maj7 = 1, 8              # C vs Cmaj7: classe vizinha com probabilidade parecida
    post = np.full((N_CLASSES, 20), 0.001)
    post[c_maj, :10], post[c_maj7, :10] = 0.45, 0.44        # empate -> ambíguo
    post[7 * 14 + 1, 10:] = 0.9                              # G claro
    post /= post.sum(axis=0, keepdims=True)
    runs = [(c_maj, 0, 10, 0.45), (7 * 14 + 1, 10, 20, 0.9)]
    info = describe_runs(post, runs, lambda i: f"cls{i}")
    assert info[0]["ambiguous"] is True and info[0]["alternatives"][0]["chord"] == f"cls{c_maj7}"
    assert info[1]["ambiguous"] is False
    assert 0 < info[0]["root_p"] <= 1.0


def test_bass_inversion_only_when_bass_is_chord_tone_and_dominant():
    from app.analysis.bass import annotate_bass
    pcs = np.full((12, 50), 0.01)
    pcs[4] = 1.0                      # baixo em E
    times = np.arange(50) * 0.1
    segs = [{"start": 0.0, "end": 2.0, "chord": "C", "root": 0, "quality": "maj"},      # E é 3ª de C -> C/E
            {"start": 2.0, "end": 4.0, "chord": "Am", "root": 9, "quality": "min"},    # E é 5ª de Am -> Am/E
            {"start": 4.0, "end": 5.0, "chord": "F", "root": 5, "quality": "maj"}]     # E é 7ª maior, fora do acorde -> sem inversão
    annotate_bass(segs, pcs, times, flats=False)
    assert segs[0]["inversion"] == "C/E" and segs[1]["inversion"] == "Am/E"
    assert "inversion" not in segs[2] and segs[2]["bass"]["note"] == "E"
    # baixo na fundamental: sem inversão
    pcs2 = np.full((12, 50), 0.01); pcs2[0] = 1.0
    s2 = [{"start": 0.0, "end": 2.0, "chord": "C", "root": 0, "quality": "maj"}]
    annotate_bass(s2, pcs2, times, flats=False)
    assert "inversion" not in s2[0]
    # energia dispersa (sem baixo dominante): sem inversão
    pcs3 = np.full((12, 50), 1.0)
    s3 = [{"start": 0.0, "end": 2.0, "chord": "C", "root": 0, "quality": "maj"}]
    annotate_bass(s3, pcs3, times, flats=False)
    assert "inversion" not in s3[0]


def test_pipeline_records_parameters_and_ambiguity():
    import os
    if not os.path.isfile("/opt/models/btc_large_voca.pt"):
        import pytest
        pytest.skip("pesos BTC ausentes")
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    write_wav(d / "a.wav", render(["C", "G", "Am", "F"] * 2, 2.0))
    r = run_analysis(d / "a.wav")
    p = r["algorithm"]["parameters"]
    assert p["viterbi_stay"] == 0.9 and "ambiguity_min_p" in p
    assert all("p" in s and "alternatives" in s and "ambiguous" in s for s in r["chords"])
    assert all(s["model_label"] and "structure" in s and "harmonic_label" in s for s in r["chords"])
    assert p["bass_method"] == "harmonic-summation+vote-v2"
