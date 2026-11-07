"""Memória de correções revisadas. Dados SINTÉTICOS de características: verificam as regras de decisão; a utilidade real
(melhora em músicas independentes) só pode ser medida com muitas gravações revisadas (ver docs/avaliacao.md)."""
import json

import numpy as np
import pytest

from app.analysis import segfeatures
from app.memory import ReviewedMemory, apply_memory, label_tuple, parse_label, tuple_to_label
from app.store import SongStore

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def feat(root, kind, chord, p=0.9, noise=0.0, seed=0):
    """Característica já girada para a raiz prevista: 'maj' = 0,4,7; 'sus2' = 0,2,7."""
    rng = np.random.default_rng(seed)
    tones = {"maj": (0, 4, 7), "sus2": (0, 2, 7)}[kind]
    ch = np.full(12, 0.02)
    ch[list(tones)] = 1.0
    ch = np.clip(ch + rng.normal(0, noise, 12), 0, None)
    bass = np.zeros(12); bass[0] = 1.0
    q = np.zeros(15); q[1] = 0.9; q[14] = 0.1
    ctx = np.zeros(24); ctx[5] = 1; ctx[12 + 7] = 1
    n = lambda v: (np.asarray(v) / np.linalg.norm(v)).round(4).tolist()  # noqa: E731
    return {"start": 0.0, "end": 4.0, "chord": chord, "root": root, "p": p, "chroma": n(ch), "bass": n(bass), "qpost": n(q), "ctx": ctx.tolist()}


def make_song(store_root, sid, sha, items, reviewed=True, edited=None):
    """items: lista de (root, kind, predicted_label). Cada item ocupa 4 s consecutivos."""
    d = store_root / sid
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({"sha256": sha, "extension": "mp3"}))
    feats = []
    for i, (root, kind, label) in enumerate(items):
        f = feat(root, kind, label, noise=0.01, seed=i)
        f["start"], f["end"] = i * 4.0, i * 4.0 + 4.0
        feats.append(f)
    (d / "segment_features.json").write_text(json.dumps({"run_id": "r", "features": feats}))
    if reviewed:
        (d / "review.json").write_text(json.dumps({"reviewed": True}))
    if edited:
        (d / "chords.edited.json").write_text(json.dumps({"segments": edited}))
    return d


def sid(n):
    return f"{n:032x}"


@pytest.fixture()
def store(tmp_path):
    return SongStore(tmp_path / "songs")


def build_memory(store, n_songs=3):
    """n_songs músicas revisadas: 3 trechos 'D previsto' que o usuário corrigiu p/ Dsus2 (sonoridade sus2) e 4 D realmente D."""
    for k in range(n_songs):
        items = [(2, "sus2", "D")] * 3 + [(2, "maj", "D")] * 4
        edited = [{"start": i * 4.0, "end": i * 4.0 + 4.0, "chord": "Dsus2"} for i in range(3)]
        make_song(store.root, sid(k + 1), f"sha{k}", items, edited=edited)
    return ReviewedMemory(store, exclude_song_id=sid(99), exclude_sha="shaX")


def test_label_tuple_roundtrip_and_key_invariance():
    assert parse_label("A/C#") == (9, "", 1) and parse_label("Dsus2") == (2, "sus2", None) and parse_label("N") is None
    assert label_tuple("Dsus2", 2) == (0, "sus2", None) and label_tuple("Esus2", 4) == (0, "sus2", None)
    assert tuple_to_label((0, "sus2", None), 4, flats=False) == "Esus2"
    assert label_tuple("A/C#", 9) == (0, "", 4)


def test_similar_sound_gets_the_learned_correction_but_plain_chords_do_not(store):
    mem = build_memory(store)
    assert mem.summary()["songs"] == 3 and mem.summary()["corrected_examples"] == 9
    segs = [{"chord": "D", "root": 2, "p": 0.9, "harmonic_label": "D", "start": 0, "end": 4},    # soa como sus2
            {"chord": "D", "root": 2, "p": 0.9, "harmonic_label": "D", "start": 4, "end": 8}]    # soa como D maior
    feats = [feat(2, "sus2", "D", seed=11), feat(2, "maj", "D", seed=12)]
    res = apply_memory(segs, feats, mem, flats=False)
    assert segs[0]["chord"] == "Dsus2" and segs[0]["memory"]["applied"] and segs[0]["memory"]["songs"] == 3
    assert segs[1]["chord"] == "D" and not segs[1]["memory"]["applied"]            # NÃO vira Dsus2: vizinhos de D plano votam D
    assert res["applied"] == 1


def test_correction_generalizes_across_keys_not_by_chord_name(store):
    mem = build_memory(store)
    seg = [{"chord": "E", "root": 4, "p": 0.9, "harmonic_label": "E", "start": 0, "end": 4}]
    apply_memory(seg, [feat(4, "sus2", "E", seed=5)], mem, flats=False)
    assert seg[0]["chord"] == "Esus2"                                                # aprendido com D, aplicado a E de mesma sonoridade


def test_audit_trail_and_model_label_preserved(store):
    mem = build_memory(store)
    seg = [{"chord": "D", "root": 2, "p": 0.9, "harmonic_label": "D", "model_label": "D", "start": 0, "end": 4}]
    apply_memory(seg, [feat(2, "sus2", "D", seed=3)], mem, flats=False)
    m = seg[0]["memory"]
    assert m["from_label"] == "D" and m["to_label"] == "Dsus2" and m["example_ids"] and m["agreement"] >= 0.8 and seg[0]["model_label"] == "D"


def test_safeguards_min_songs_min_neighbors_confidence_and_other_predicted_type(store):
    make_song(store.root, sid(1), "a", [(2, "sus2", "D")] * 4, edited=[{"start": i * 4.0, "end": i * 4.0 + 4.0, "chord": "Dsus2"} for i in range(4)])
    one_song = ReviewedMemory(store, exclude_song_id=sid(99))
    seg = [{"chord": "D", "root": 2, "p": 0.9, "harmonic_label": "D", "start": 0, "end": 4}]
    apply_memory(seg, [feat(2, "sus2", "D", seed=1)], one_song, flats=False)
    assert seg[0]["chord"] == "D" and seg[0]["memory"]["reason"] == "insufficient_examples"       # 1 música só não basta
    mem = build_memory(SongStore(store.root.parent / "songs2"))
    # p quase certo: não sobrescreve
    seg = [{"chord": "D", "root": 2, "p": 0.99, "harmonic_label": "D", "start": 0, "end": 4}]
    apply_memory(seg, [feat(2, "sus2", "D", p=0.99, seed=1)], mem, flats=False)
    assert seg[0]["chord"] == "D"
    # tipo previsto diferente (Dm): exemplos de 'D maior' não se aplicam
    seg = [{"chord": "Dm", "root": 2, "p": 0.9, "harmonic_label": "Dm", "start": 0, "end": 4}]
    assert apply_memory(seg, [feat(2, "sus2", "Dm", seed=1)], mem, flats=False)["considered"] == 0


def test_same_song_same_recording_and_unreviewed_are_excluded(store):
    for k in range(3):
        make_song(store.root, sid(k + 1), f"sha{k}", [(2, "sus2", "D")] * 3,
                  edited=[{"start": i * 4.0, "end": i * 4.0 + 4.0, "chord": "Dsus2"} for i in range(3)], reviewed=(k != 2))
    mem = ReviewedMemory(store, exclude_song_id=sid(1), exclude_sha="sha1")
    s = mem.summary()
    assert s["skipped"]["same_song"] == 1 and s["skipped"]["same_recording"] == 1 and s["skipped"]["not_reviewed"] == 1 and s["examples"] == 0


def test_segfeatures_are_key_invariant_and_do_not_use_the_chord_name():
    post = np.full((170, 40), 1e-4)
    chroma_d = np.zeros((12, 100)); chroma_d[[2, 6, 9]] = 1.0          # D maior
    chroma_e = np.zeros((12, 100)); chroma_e[[4, 8, 11]] = 1.0         # E maior (mesma sonoridade, outro tom)
    sd = [{"start": 0.0, "end": 2.0, "chord": "D", "root": 2, "p": 0.9}]
    se = [{"start": 0.0, "end": 2.0, "chord": "E", "root": 4, "p": 0.9}]
    fd = segfeatures.compute(sd, chroma_d, 0.02, None, None, post, 0.0926)[0]
    fe = segfeatures.compute(se, chroma_e, 0.02, None, None, post, 0.0926)[0]
    assert float(segfeatures.vector(fd) @ segfeatures.vector(fe)) > 0.999
