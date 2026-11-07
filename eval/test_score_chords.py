import json

import numpy as np
from score_chords import load_est, load_lab, score, to_harte


def test_label_conversion():
    assert to_harte("C") == "C:maj" and to_harte("F#m") == "F#:min" and to_harte("Bbmaj7") == "Bb:maj7"
    assert to_harte("Am7") == "A:min7" and to_harte("Bm7(b5)") == "B:hdim7" and to_harte("C/E") == "C:maj/E"
    assert to_harte("C:min7") == "C:min7" and to_harte("N") == "N"


def test_perfect_and_wrong_scores(tmp_path):
    ref = tmp_path / "r.lab"
    ref.write_text("0 2 C\n2 4 G7\n4 6 Am7\n6 8 Fmaj7\n")
    est = tmp_path / "c.json"
    est.write_text(json.dumps({"segments": [{"start": 0, "end": 2, "chord": "C"}, {"start": 2, "end": 4, "chord": "G7"},
                                            {"start": 4, "end": 6, "chord": "Am7"}, {"start": 6, "end": 8, "chord": "Fmaj7"}]}))
    r = score(load_est(est), load_lab(ref))
    assert r["root"] == r["majmin"] == r["sevenths"] == 1.0
    # sétimas simplificadas: raiz e tríade certas, "sevenths" cai
    est.write_text(json.dumps({"segments": [{"start": 0, "end": 2, "chord": "C"}, {"start": 2, "end": 4, "chord": "G"},
                                            {"start": 4, "end": 6, "chord": "Am"}, {"start": 6, "end": 8, "chord": "F"}]}))
    r = score(load_est(est), load_lab(ref))
    assert r["root"] == 1.0 and r["majmin"] == 1.0 and r["sevenths"] == 0.25


def test_extension_labels_convert_and_validate():
    import mir_eval
    for lab in ["C9", "Cm9", "Cmaj9", "Cadd9", "C7sus4", "C13", "C7(#5)", "C7(b9)", "Fm(add9)", "C11", "Cm11"]:
        mir_eval.chord.validate_chord_label(to_harte(lab))


def test_detailed_metrics_by_type_and_extensions():
    from metrics import detailed
    ref = (np.array([[0, 2], [2, 4], [4, 6], [6, 8]]), ["C:maj", "G:7", "A:min7", "F:maj(9)"])
    est = (np.array([[0, 2], [2, 4], [4, 6], [6, 8]]), ["C:maj", "G:7", "A:min", "F:maj"])
    r = detailed(*est, *ref)
    bt = r["by_type"]
    assert bt["maj"]["exact_notes"] == 1.0 and bt["7"]["exact_notes"] == 1.0
    assert bt["min7"]["root"] == 1.0 and bt["min7"]["exact_notes"] == 0.0   # sétima perdida
    assert bt["extensions"]["root"] == 1.0 and bt["extensions"]["exact_notes"] == 0.0   # nona não reconhecida
    assert r["fragmentation"]["ratio_est_to_ref_segments"] == 1.0


def test_detailed_fragmentation_inversions_and_ambiguity():
    from metrics import detailed
    ref = (np.array([[0, 4], [4, 8]]), ["F:maj/3", "C:maj"])
    est_iv = np.array([[0, 1], [1, 2], [2, 4], [4, 8]])
    est_lb = ["F:maj", "F:maj", "F:maj", "C:maj/5"]
    r = detailed(est_iv, est_lb, *ref, est_ambiguous=[True, False, False, False])
    assert r["fragmentation"]["ratio_est_to_ref_segments"] == 2.0
    assert r["inversions"]["bass_correct_on_ref_inversions"] == 0.0     # baixo perdido
    assert r["inversions"]["false_inversion_rate"] == 1.0               # inversão inventada
    assert r["unknown"]["ambiguous_fraction"] == 0.125


def test_ambiguous_numeric_suffixes_are_rejected():
    import pytest
    for lab in ("D2", "A4", "C2"):
        with pytest.raises(ValueError, match="ambíguo"):
            to_harte(lab)
    assert to_harte("Dsus2") == "D:sus2" and to_harte("Dadd9") == "D:maj(9)" and to_harte("Asus4") == "A:sus4"


def test_confusions_simplification_and_bass_accuracy():
    from metrics import detailed
    ref = (np.array([[0, 2], [2, 4], [4, 6]]), ["D:sus2", "E:maj6", "A:maj/3"])
    est = (np.array([[0, 2], [2, 4], [4, 6]]), ["D:maj", "E:maj", "A:maj/3"])
    r = detailed(*est, *ref)
    assert r["confusions_same_root_seconds"] == {"sus2 -> maj": 2.0, "maj6 -> maj": 2.0}
    assert r["simplification"]["simplified_to_triad_fraction"] == 1.0
    assert r["bass"]["bass_correct_fraction_all_chords"] == 1.0     # D/E sem inversão e A/C# acertado
    est2 = (np.array([[0, 2], [2, 4], [4, 6]]), ["D:maj", "E:maj", "A:maj"])   # perdeu a inversão A/C#
    assert detailed(*est2, *ref)["bass"]["bass_correct_fraction_all_chords"] == 0.667


def test_forced_alignment_recovers_root_changes_and_cannot_split_same_root():
    from align_chart import align
    fr = 0.0926
    T = 300
    post = np.full((170, T), 1e-4)
    truth = [(0, 100, 0), (100, 200, 7), (200, 300, 9)]                    # C, G, A (raízes 0, 7, 9) em quadros
    for a, b, r in truth:
        post[r * 14 + 1, a:b] = 0.9
    chords = [{"root": 0, "label": "C"}, {"root": 7, "label": "G"}, {"root": 9, "label": "Asus4"}, {"root": 9, "label": "A"}]
    runs = align(post, chords, fr)
    spans = {k: (a, b) for k, a, b in runs if k is not None}
    assert abs(spans[0][1] - 100) <= 2 and abs(spans[1][1] - 200) <= 2      # fronteiras entre raízes diferentes: recuperadas
    assert spans[2][0] >= 198 and spans[3][1] == 300                         # A4/A (mesma raiz) dividem o trecho: fronteira entre eles é arbitrária


def test_chart_events_counts_exact_hits_and_plain_triad_substitution(tmp_path):
    from chart_events import main
    import json as _json
    segs = [{"start": 0, "end": 4, "chord": "D", "root": 2, "alternatives": []},
            {"start": 4, "end": 8, "chord": "A/C#", "harmonic_label": "A", "root": 9, "alternatives": [{"chord": "Asus4", "p": 0.1}]}]
    meta = {"spans": [{"cifra": "D2", "label": "Dsus2", "start": 0, "end": 4}, {"cifra": "A/C#", "label": "A/C#", "start": 4, "end": 8}]}
    (tmp_path / "c.json").write_text(_json.dumps({"segments": segs})); (tmp_path / "m.json").write_text(_json.dumps(meta))
    out = tmp_path / "o.json"
    main(str(tmp_path / "c.json"), str(tmp_path / "m.json"), str(out))
    r = _json.load(open(out))["eventos_por_rotulo_da_cifra"]
    assert r["D2"]["rotulo_exato"] == 0 and r["D2"]["so_triade"] == 1 and r["D2"]["raiz_certa"] == 1
    assert r["A/C#"]["rotulo_exato"] == 1


def test_tab_parser_and_transcription_alignment():
    from score_transcription import score
    from tab_reference import parse_tab
    tab = """Parte 1 de 4
E|--5-6-6/8--|
B|-----------|
G|-----------|
D|-----------|
A|-----------|
E|-----------|
"""
    notes = parse_tab(tab)
    assert [n["pitch"] for n in notes] == [69, 70, 70, 72] and notes[3]["technique"] == "slide_up_in"      # A4 A#4 A#4 C5
    ref = [n["pitch"] for n in notes]
    s = score([60, 69, 70, 70, 72, 40], ref)                                                              # ruído nas pontas
    assert s["exact"]["reference_notes_found_in_order"] == 4 and s["exact"]["recall"] == 1.0
    wrong = score([69 + 12, 70 + 12, 70 + 12, 72 + 12], ref)                                              # tudo uma oitava acima
    assert wrong["exact"]["recall"] == 0.0 and wrong["pitch_class"]["recall"] == 1.0
