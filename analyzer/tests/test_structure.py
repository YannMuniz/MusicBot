"""Pós-processamento temporal dos acordes e segmentação em seções. Dados SINTÉTICOS: verificam a lógica (não a precisão
em música real, que é medida em eval/ com cifras alinhadas)."""
import numpy as np

from app.analysis import sections as S
from app.analysis.smoothing import smooth_chords


def seg(a, b, chord, p=0.9, root=None, amb=False, alts=()):
    if root is None:
        root = None if chord == "N" else {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "Am": 9, "Em": 4}[chord]
    return {"start": a, "end": b, "chord": chord, "root": root, "quality": None if root is None else "maj", "p": p,
            "ambiguous": amb, "alternatives": [{"chord": c, "p": 0.2} for c in alts]}


def contiguous(segs, duration):
    return segs[0]["start"] == 0 and segs[-1]["end"] == duration and all(a["end"] == b["start"] for a, b in zip(segs, segs[1:]))


# --- acordes -----------------------------------------------------------------------------------------------
def test_same_label_neighbours_are_merged():
    out, log = smooth_chords([seg(0, 2, "C"), seg(2, 4, "C", p=0.7), seg(4, 6, "G")], 0.58)
    assert [s["chord"] for s in out] == ["C", "G"] and out[0]["end"] == 4 and log["merged_same_label"] == 1
    assert contiguous(out, 6)


def test_legitimate_fast_changes_are_preserved():
    fast = [seg(0, 0.4, "C"), seg(0.4, 0.8, "G"), seg(0.8, 1.2, "Am"), seg(1.2, 1.6, "F", root=5)]   # curtos MAS confiantes
    out, log = smooth_chords(fast, 0.58)
    assert [s["chord"] for s in out] == ["C", "G", "Am", "F"] and log["absorbed_blips"] == 0


def test_short_low_confidence_blip_between_same_chord_is_absorbed():
    out, log = smooth_chords([seg(0, 4, "C"), seg(4, 4.3, "E", p=0.3, amb=True), seg(4.3, 8, "C")], 0.58)
    assert [s["chord"] for s in out] == ["C"] and out[0]["end"] == 8 and log["absorbed_blips"] == 1


def test_short_low_confidence_with_different_neighbours_is_kept_unless_compatible():
    a = smooth_chords([seg(0, 4, "C"), seg(4, 4.3, "E", p=0.3, amb=True), seg(4.3, 8, "G")], 0.58)[0]
    assert [s["chord"] for s in a] == ["C", "E", "G"]                       # nenhuma evidência de que seja artefato
    b = smooth_chords([seg(0, 4, "C"), seg(4, 4.3, "E", p=0.3, amb=True, alts=("G",)), seg(4.3, 8, "G")], 0.58)[0]
    assert [s["chord"] for s in b] == ["C", "G"]                            # o próprio modelo aponta o vizinho como alternativa
    c = smooth_chords([seg(0, 4, "E"), seg(4, 4.3, "Em", p=0.4, amb=True, root=4), seg(4.3, 8, "G")], 0.58)[0]
    assert [s["chord"] for s in c] == ["E", "G"]                            # mesma raiz do vizinho: mesma harmonia


def test_rests_do_not_become_fake_chords_and_edges_are_preserved():
    segs = [seg(0, 2.5, "N"), seg(2.5, 6, "C"), seg(6, 6.4, "N"), seg(6.4, 10, "C"), seg(10, 14, "G"), seg(14, 20, "N")]
    out, log = smooth_chords(segs, 0.58)
    assert out[0]["kind"] == "rest" and out[-1]["kind"] == "rest"           # início/fim reais
    assert [s["chord"] for s in out] == ["N", "C", "G", "N"] and log["absorbed_short_rests"] == 1
    long_rest = smooth_chords([seg(0, 4, "C"), seg(4, 9, "N"), seg(9, 13, "G")], 0.58)[0]
    assert [s["chord"] for s in long_rest] == ["C", "N", "G"]               # pausa longa no meio é real


def test_times_and_total_duration_preserved_after_smoothing():
    segs = [seg(0, 3, "N"), seg(3, 5, "C"), seg(5, 5.2, "E", p=0.2, amb=True), seg(5.2, 9, "C"), seg(9, 9.3, "N"), seg(9.3, 15, "G"),
            seg(15, 15.2, "A", p=0.3, amb=True, alts=("G",)), seg(15.2, 22.5, "G")]
    out, _ = smooth_chords(segs, 0.58)
    assert contiguous(out, 22.5) and len(out) < len(segs)
    boundaries = {s["start"] for s in out}
    assert boundaries <= {s["start"] for s in segs}                         # só SOMEM fronteiras; nenhuma é inventada ou deslocada


# --- seções ------------------------------------------------------------------------------------------------
CHORDS = np.vstack([np.eye(12), np.roll(np.eye(12), 5, axis=1)])[:20]


def build(parts, beats_per_chord=8, timbre=None):
    """parts: lista de listas de acordes (índices). Cada acorde dura beats_per_chord batidas; ruído pequeno e fixo."""
    rng = np.random.default_rng(1)
    cols = []
    for part in parts:
        for c in part:
            for _ in range(beats_per_chord):
                chroma = CHORDS[c] + rng.normal(0, 0.05, 12)
                cols.append(np.concatenate([chroma, rng.normal(0, 0.05, 6) + (timbre or 0)]))
    feat = np.array(cols).T
    feat = (feat - feat.mean(axis=1, keepdims=True)) / (feat.std(axis=1, keepdims=True) + 1e-9)
    n = feat.shape[1]
    return feat, np.arange(n + 1) * 0.58, n * 0.58


def test_sections_are_not_one_per_chord_change_and_repeats_share_identity():
    A, B, Cc = [0, 5, 7, 2], [9, 4, 0, 7], [3, 8, 10, 1]
    parts = [A, A, B, A, A, B, Cc, Cc, A, A, B]                # 44 trocas de acorde; estrutura A A B A A B C C A A B
    feat, edges, dur = build(parts, beats_per_chord=12)
    out = S.detect_sections(feat, edges, dur, [])
    n_changes = sum(len(p) for p in parts)
    assert len(out) <= 12 and len(out) < n_changes / 3          # nunca uma seção por mudança de acorde
    groups = [s["repeat_group"] for s in out]
    assert len(set(groups)) < len(groups)                       # há repetição reconhecida (mesma identidade em mais de uma ocorrência)
    rep = [s for s in out if s["occurrences_total"] > 1]
    assert rep and all(s["occurrence"] <= s["occurrences_total"] for s in rep)


def test_section_labels_are_neutral_and_never_semantic():
    A, B = [0, 5, 7, 2], [9, 4, 0, 7]
    feat, edges, dur = build([A, A, B, B, A, A, B, B], beats_per_chord=6)
    for s in S.detect_sections(feat, edges, dur, []):
        assert s["semantic_label"] is None and s["label"].startswith("Parte ")


def test_sections_cover_the_whole_song_without_gaps_or_empty_sections():
    A, B, Cc = [0, 5, 7, 2], [9, 4, 0, 7], [3, 8, 10, 1]
    feat, edges, dur = build([A, A, B, B, Cc, Cc, A, A], beats_per_chord=6)
    out = S.detect_sections(feat, edges, dur, [])
    assert out[0]["start"] == 0 and abs(out[-1]["end"] - dur) < 0.01
    assert all(a["end"] == b["start"] for a, b in zip(out, out[1:])) and all(s["end"] > s["start"] for s in out)


def test_compress_repeats_merges_repeated_ngram_and_runs():
    spans = [(i * 10.0, (i + 1) * 10.0) for i in range(10)]
    # tipos: verso(1) refrão-a(2) refrão-b(3) ponte(4) verso(1) refrão-a(2) refrão-b(3) final(5) final(5) final(5)
    items = S.compress_repeats([1, 2, 3, 4, 1, 2, 3, 5, 5, 5], spans)
    assert [(it["first"], it["last"]) for it in items] == [(0, 2), (3, 3), (4, 6), (7, 9)]   # (1,2,3) vira UMA parte que volta; finais em corrida = 1 ocorrência
    labels = [it["label"] for it in items]
    assert labels[0] == labels[2] and len({labels[0], labels[1], labels[3]}) == 3
    # parte composta repetida lado a lado: DUAS ocorrências da mesma parte (identidade != ocorrência)
    adj = S.compress_repeats([1, 2, 3, 1, 2, 3, 4], spans)
    assert [(it["first"], it["last"]) for it in adj] == [(0, 2), (3, 5), (6, 6)] and adj[0]["label"] == adj[1]["label"]
    # ciclos idênticos de uma única frase (ponte) viram UMA ocorrência
    cyc = S.compress_repeats([1, 2, 5, 5, 5, 5, 3], spans)
    assert [(it["first"], it["last"]) for it in cyc] == [(0, 0), (1, 1), (2, 5), (6, 6)]
