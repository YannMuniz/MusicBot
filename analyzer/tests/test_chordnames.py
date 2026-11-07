from app.analysis import harmony
from app.chordnames import canonical

import numpy as np


def test_canonical_brazilian_seventh_names():
    assert canonical("C#7M") == "C#maj7"
    assert canonical("CM7") == "Cmaj7"
    assert canonical("Db7M/Ab") == "Dbmaj7/Ab"
    assert canonical("Cm7M") == "CmM7"
    assert canonical("Cm(maj7)") == "CmM7"
    assert canonical("C9M") == "Cmaj9"


def test_canonical_leaves_other_chords_alone():
    for c in ["C", "F#m7", "Bb7", "Gm7(b5)", "Dsus4", "A/C#", "N", "C7", "Cmaj7", "CmM7", "C79"]:
        assert canonical(c) == c


def _seg(quality="maj"):
    return {"start": 0.0, "end": 4.0, "root": 1, "quality": quality, "chord": "Db"}


def _chroma(pcs, frames=100):
    m = np.zeros((12, frames))
    for pc, v in pcs.items():
        m[pc] = v
    return m


def test_maj7_suggestion_when_major_seventh_dominates_minor_seventh():
    # Db maj: Db(1) F(5) Ab(8); 7M = C(0), b7 = B(11)
    with_m7 = _seg()
    harmony.tone_evidence([with_m7], _chroma({1: 1.0, 5: 1.0, 8: 1.0, 0: 0.55}), 0.1)
    assert [a["degree"] for a in with_m7.get("possible_additions", [])] == ["maj7"]
    assert with_m7["chord"] == "Db"                       # nunca altera o acorde


def test_no_maj7_suggestion_for_dominant_or_plain_triad():
    dom, plain = _seg(), _seg()
    harmony.tone_evidence([dom], _chroma({1: 1.0, 5: 1.0, 8: 1.0, 11: 0.8, 0: 0.5}), 0.1)   # b7 mais forte
    harmony.tone_evidence([plain], _chroma({1: 1.0, 5: 1.0, 8: 1.0, 0: 0.2}), 0.1)
    assert all(a["degree"] != "maj7" for a in dom.get("possible_additions", []))
    assert "possible_additions" not in plain
