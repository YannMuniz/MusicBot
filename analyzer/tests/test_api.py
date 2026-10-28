import time

from tests.conftest import H
from tests.synth import render, write_wav

PROG = ["C", "G", "Am", "F"] * 3


def _wav(tmp_path, name="t.wav"):
    p = tmp_path / name
    write_wav(p, render(PROG, 2.0))
    return p


def _wait(client, sid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = client.get(f"/v1/songs/{sid}", headers=H).json()
        if s["status"] in ("completed", "failed"):
            return s
        time.sleep(0.5)
    raise AssertionError("timeout")


def test_requires_token(client):
    assert client.get("/v1/songs").status_code == 401
    assert client.get("/v1/songs", headers={"X-Internal-Token": "x"}).status_code == 401
    assert client.get("/health").status_code == 200


def test_full_flow_and_isolation(client, tmp_path, settings):
    p = _wav(tmp_path)
    ids = []
    for _ in range(2):  # mesmo nome de arquivo duas vezes: não pode sobrescrever
        r = client.post("/v1/songs", headers=H, files={"file": ("mesmo.wav", p.read_bytes(), "audio/wav")})
        assert r.status_code == 202
        ids.append(r.json()["id"])
    assert ids[0] != ids[1]
    for sid in ids:
        assert _wait(client, sid)["status"] == "completed"
        d = settings.storage_root / sid
        for f in ("original.wav", "metadata.json", "status.json", "analysis.json", "chords.json", "sections.json", "report.txt"):
            assert (d / f).is_file(), f
        assert client.get(f"/v1/songs/{sid}/analysis", headers=H).json()["key"]["name"] == "C major"
        assert len(client.get(f"/v1/songs/{sid}/chords", headers=H).json()["segments"]) > 2
        assert "Parte A" in client.get(f"/v1/songs/{sid}/report", headers=H).text
        assert client.get(f"/v1/songs/{sid}/audio", headers=H).content == p.read_bytes()
    assert len(client.get("/v1/songs", headers=H).json()["songs"]) == 2


def test_reanalyze_archives_previous_run(client, tmp_path):
    p = _wav(tmp_path)
    sid = client.post("/v1/songs", headers=H, files={"file": ("a.wav", p.read_bytes())}).json()["id"]
    _wait(client, sid)
    first = client.get(f"/v1/songs/{sid}/analysis", headers=H).json()["run_id"]
    assert client.post(f"/v1/songs/{sid}/reanalyze", headers=H).status_code == 202
    time.sleep(0.3)
    _wait(client, sid)
    second = client.get(f"/v1/songs/{sid}/analysis", headers=H).json()["run_id"]
    assert first != second
    assert [r["run_id"] for r in client.get(f"/v1/songs/{sid}/history", headers=H).json()["runs"]] == [first]


def test_edits_do_not_overwrite_detection(client, tmp_path):
    sid = client.post("/v1/songs", headers=H, files={"file": ("a.wav", _wav(tmp_path).read_bytes())}).json()["id"]
    _wait(client, sid)
    before = client.get(f"/v1/songs/{sid}/chords", headers=H).json()["segments"]
    r = client.put(f"/v1/songs/{sid}/chords/edited", headers=H, json={"segments": [{"start": 0, "end": 2, "chord": "Cmaj7"}]})
    assert r.status_code == 200
    after = client.get(f"/v1/songs/{sid}/chords", headers=H).json()
    assert after["segments"] == before and after["edited"]["segments"][0]["chord"] == "Cmaj7"
    bad = client.put(f"/v1/songs/{sid}/chords/edited", headers=H, json={"segments": [{"start": 0, "end": 2, "chord": "<script>"}]})
    assert bad.status_code == 422


def test_rejects_bad_uploads(client, tmp_path):
    cases = {
        "txt": ("x.txt", b"hello world" * 100),
        "fake_wav": ("x.wav", b"not really audio at all" * 100),
        "exe_as_mp3": ("x.mp3", b"MZ\x90\x00" + b"\x00" * 2000),
        "mp3_content_in_wav_ext": ("x.wav", b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 2000),
    }
    for name, (fn, data) in cases.items():
        r = client.post("/v1/songs", headers=H, files={"file": (fn, data)})
        assert r.status_code in (415, 422), (name, r.status_code)
    short = tmp_path / "short.wav"
    write_wav(short, render(["C"], 2.0))
    assert client.post("/v1/songs", headers=H, files={"file": ("s.wav", short.read_bytes())}).status_code == 422


def test_path_traversal_and_unknown_ids(client):
    for bad in ("../../etc/passwd", "0" * 32, "nao-e-id"):
        assert client.get(f"/v1/songs/{bad}", headers=H).status_code == 404


def test_filename_never_used_as_path(client, tmp_path, settings):
    p = _wav(tmp_path)
    r = client.post("/v1/songs", headers=H, files={"file": ("../../evil.wav", p.read_bytes())})
    sid = r.json()["id"]
    assert (settings.storage_root / sid / "original.wav").is_file()
    assert client.get(f"/v1/songs/{sid}", headers=H).json()["original_filename"] == "evil.wav"
    _wait(client, sid)


def test_corrections_are_logged_with_provenance_and_deduplicated(client, tmp_path, settings):
    sid = client.post("/v1/songs", headers=H, files={"file": ("c.wav", _wav(tmp_path).read_bytes())}).json()["id"]
    _wait(client, sid)
    run = client.get(f"/v1/songs/{sid}/analysis", headers=H).json()
    first = client.get(f"/v1/songs/{sid}/chords", headers=H).json()["segments"][0]
    edit = {"base_run_id": run["run_id"], "segments": [
        {"start": first["start"], "end": first["end"], "chord": "Dm7"}]}        # muda o acorde
    for _ in range(2):                                                         # salvar duas vezes não duplica
        assert client.put(f"/v1/songs/{sid}/chords/edited", headers=H, json=edit).status_code == 200
    log = client.get(f"/v1/songs/{sid}/corrections", headers=H).json()["corrections"]
    assert len(log) == 1
    c = log[0]
    assert c["corrected"] == "Dm7" and c["predicted"] == first["chord"] and c["validation_status"] == "unreviewed"
    assert c["source"] == "ui" and c["run_id"] == run["run_id"] and c["model"]["name"] == run["algorithm"]["name"]
    assert c["superseded"] is False
    # edição que confirma o acorde previsto não gera correção; a anterior passa a 'superseded'
    same = {"base_run_id": run["run_id"], "segments": [{"start": first["start"], "end": first["end"], "chord": first["chord"]}]}
    client.put(f"/v1/songs/{sid}/chords/edited", headers=H, json=same)
    log = client.get(f"/v1/songs/{sid}/corrections", headers=H).json()["corrections"]
    assert len(log) == 1 and log[0]["superseded"] is True
    # a correção não altera o resultado automático
    assert client.get(f"/v1/songs/{sid}/chords", headers=H).json()["segments"][0]["chord"] == first["chord"]


def test_bass_correction_records_harmonic_and_bass_separately(client, tmp_path):
    sid = client.post("/v1/songs", headers=H, files={"file": ("b.wav", _wav(tmp_path).read_bytes())}).json()["id"]
    _wait(client, sid)
    run = client.get(f"/v1/songs/{sid}/analysis", headers=H).json()
    first = client.get(f"/v1/songs/{sid}/chords", headers=H).json()["segments"][0]
    assert {"model_label", "harmonic_label", "structure"} <= set(first)          # representação estruturada preservada
    edit = {"base_run_id": run["run_id"], "segments": [{"start": first["start"], "end": first["end"], "chord": "A/C#"}]}
    assert client.put(f"/v1/songs/{sid}/chords/edited", headers=H, json=edit).status_code == 200
    c = client.get(f"/v1/songs/{sid}/corrections", headers=H).json()["corrections"][0]
    assert c["corrected_harmonic"] == "A" and c["corrected_bass"] == "C#" and "predicted_confidence" in c
