"""Testes do ENCANAMENTO do treino (formato, divisão sem vazamento, travas). Não medem qualidade musical."""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analyzer"))
import dataset  # noqa: E402
import export_corrections  # noqa: E402
import finetune  # noqa: E402
from vocab import IDX_N, IDX_X, IGNORE, frames_from_intervals, label_to_class  # noqa: E402


def test_vocab_mapping():
    assert label_to_class("C:maj") == 1 and label_to_class("C:min") == 0 and label_to_class("N") == IDX_N
    assert label_to_class("G:9") == 7 * 14 + 9 and label_to_class("A:min9") == 9 * 14 + 6   # 9ª reduzida à sétima base
    assert label_to_class("C:minmaj7") == 7 and label_to_class("X") == IDX_X


def test_partial_labels_become_ignore():
    f = frames_from_intervals([(1.0, 2.0)], ["C:maj"], 40, 0.0926)
    assert (f == IGNORE).sum() > 20 and f[15] == 1


def _make(tmp_path, works):
    rows = []
    for i, (w, lic) in enumerate(works):
        a = tmp_path / f"a{i}.wav"; a.write_bytes(bytes([i]) * 100)
        l = tmp_path / f"l{i}.lab"; l.write_text("0 60 C:maj\n")
        rows.append({"audio": a.name, "lab": l.name, "work_id": w, "source": "t", "license": lic})
    p = tmp_path / "d.csv"
    with open(p, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    return p


def test_versions_of_same_work_never_split(tmp_path):
    p = _make(tmp_path, [(f"obra{i % 10}", "CC-BY") for i in range(60)])    # 10 obras, 6 versões cada
    m = dataset.build_manifest(p, seed=3)
    by_work = {}
    for it in m["items"]:
        by_work.setdefault(it["work_id"], set()).add(it["split"])
    assert all(len(s) == 1 for s in by_work.values())
    assert m == dataset.build_manifest(p, seed=3)                            # determinístico


def test_rejects_missing_license_and_duplicate_audio(tmp_path):
    with pytest.raises(ValueError, match="Licença"):
        dataset.build_manifest(_make(tmp_path, [("x", "")]))
    p = _make(tmp_path, [("obraA", "CC-BY"), ("obraB", "CC-BY")])
    (tmp_path / "a1.wav").write_bytes((tmp_path / "a0.wav").read_bytes())    # mesmo áudio em obras diferentes
    with pytest.raises(ValueError, match="duplicado"):
        dataset.build_manifest(p)


def test_finetune_refuses_small_data(tmp_path, capsys):
    m = {"summary": {"train": {"minutes": 3, "items": 1, "works": 1}, "val": {"items": 0, "minutes": 0, "works": 0},
                     "test": {"items": 0, "minutes": 0, "works": 0}}, "items": [], "manifest_sha256": "x"}
    (tmp_path / "m.json").write_text(json.dumps(m))
    assert finetune.main([str(tmp_path / "m.json"), "--base", "x", "--out", str(tmp_path / "o")]) == 2
    assert "RECUSADO" in capsys.readouterr().err


def test_export_corrections_only_accepted_and_consistent(tmp_path):
    base = {"song_id": "s1", "run_id": "r", "model": {}, "predicted": "C", "created_at": "t", "source": "ui"}
    cs = [dict(base, id="a", start=0, end=2, corrected="Dm", validation_status="accepted", superseded=False),
          dict(base, id="b", start=1, end=3, corrected="Em", validation_status="accepted", superseded=False),   # conflita com a
          dict(base, id="c", start=5, end=6, corrected="G", validation_status="unreviewed", superseded=False),
          dict(base, id="d", start=7, end=8, corrected="F", validation_status="accepted", superseded=True)]
    (tmp_path / "s1").mkdir(); (tmp_path / "s1" / "corrections.json").write_text(json.dumps({"corrections": cs}))
    r = export_corrections.export(tmp_path)
    assert [c["id"] for c in r["accepted"]] == ["a"]
    assert {e["id"]: e["reason"] for e in r["excluded"]} == {"b": "overlap_conflict", "c": "unreviewed", "d": "superseded"}
