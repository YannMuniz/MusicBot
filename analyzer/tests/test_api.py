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
    br = client.put(f"/v1/songs/{sid}/chords/edited", headers=H, json={"segments": [{"start": 0, "end": 2, "chord": "C#7M/G#"}]})
    assert br.json()["segments"][0]["chord"] == "C#maj7/G#"       # cifra brasileira vira a forma canônica
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


def test_corrections_keep_features_survive_reanalysis_and_review_flow(client, tmp_path):
    sid = client.post("/v1/songs", headers=H, files={"file": ("r.wav", _wav(tmp_path).read_bytes())}).json()["id"]
    _wait(client, sid)
    run1 = client.get(f"/v1/songs/{sid}/analysis", headers=H).json()["run_id"]
    first = client.get(f"/v1/songs/{sid}/chords", headers=H).json()["segments"][0]
    edit = {"base_run_id": run1, "segments": [{"start": first["start"], "end": first["end"], "chord": "Dsus2"}]}
    client.put(f"/v1/songs/{sid}/chords/edited", headers=H, json=edit)
    c = client.get(f"/v1/songs/{sid}/corrections", headers=H).json()["corrections"][0]
    assert c["type"] == "chord" and c["origin"] == "user" and c["analyzer_version"] and c["audio_ref"]["file"] == "original"
    assert c["features"] and len(c["features"]["chroma"]) == 12 and c["predicted_confidence"]["p"] is not None
    # reprocessar não apaga correção nem a previsão original registrada
    assert client.post(f"/v1/songs/{sid}/reanalyze", headers=H).status_code == 202
    time.sleep(0.3)
    _wait(client, sid)
    again = client.get(f"/v1/songs/{sid}/corrections", headers=H).json()["corrections"]
    assert len(again) == 1 and again[0]["id"] == c["id"] and again[0]["predicted"] == first["chord"]
    assert client.get(f"/v1/songs/{sid}/chords", headers=H).json()["edited"]["segments"][0]["chord"] == "Dsus2"
    # tipo 'bass' quando só o baixo muda
    from app.corrections import correction_type
    assert correction_type("A", "A/C#") == "bass" and correction_type("D", "Dsus2") == "chord"
    # revisão e status
    assert client.get(f"/v1/songs/{sid}/learning", headers=H).json()["reviewed"] is False
    assert client.post(f"/v1/songs/{sid}/review", headers=H, json={"reviewed": True}).json()["reviewed"] is True
    assert client.get(f"/v1/songs/{sid}/learning", headers=H).json()["reviewed"] is True
    r = client.put(f"/v1/songs/{sid}/corrections/{c['id']}/status", headers=H, json={"validation_status": "accepted"})
    assert r.status_code == 200 and r.json()["validation_status"] == "accepted"
    assert client.put(f"/v1/songs/{sid}/corrections/{c['id']}/status", headers=H, json={"validation_status": "xyz"}).status_code == 422
    assert client.put(f"/v1/songs/{sid}/corrections/naoexiste/status", headers=H, json={"validation_status": "accepted"}).status_code == 404


def _melody_wav(tmp_path):
    from tests.test_tabs import melody
    from tests.synth import write_wav
    notes = [(64, 0.6), (67, 0.6), (69, 0.6), (72, 0.7), (69, 0.6), (67, 0.6), (64, 0.9)]
    lead, _ = melody(notes)
    import numpy as np
    y = np.concatenate([np.zeros(int(1.0 * 22050), np.float32), lead, np.zeros(int(1.5 * 22050), np.float32)])
    p = tmp_path / "mel.wav"
    write_wav(p, y)
    return p


def _wait_tab(client, sid, solo, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/v1/songs/{sid}/solos/{solo}/tab", headers=H)
        if r.status_code == 200 and r.json()["state"] != "processing":
            return r.json()
        time.sleep(0.5)
    raise AssertionError("transcrição não terminou")


def test_solo_marking_transcription_tab_edit_and_typed_annotations(client, tmp_path):
    sid = client.post("/v1/songs", headers=H, files={"file": ("mel.wav", _melody_wav(tmp_path).read_bytes())}).json()["id"]
    _wait(client, sid)
    # validação do trecho
    assert client.post(f"/v1/songs/{sid}/solos", headers=H, json={"start": 5, "end": 4}).status_code == 422
    assert client.post(f"/v1/songs/{sid}/solos", headers=H, json={"start": 0, "end": 1}).status_code == 422          # curto demais
    assert client.post(f"/v1/songs/{sid}/solos", headers=H, json={"start": 0, "end": 9999}).status_code == 422
    assert client.post(f"/v1/songs/{sid}/solos", headers=H, json={"start": 0, "end": 5, "category": "banana"}).status_code == 422
    solo = client.post(f"/v1/songs/{sid}/solos", headers=H, json={"start": 0.9, "end": 6.0, "instrument": "guitar"}).json()
    assert solo["id"] == "s1" and solo["source"] == "user" and solo["audio_ref"]["file"] == "original"
    assert client.get(f"/v1/songs/{sid}/solos", headers=H).json()["solos"][0]["transcription_state"] == "not_started"
    assert client.get(f"/v1/songs/{sid}/solos/s1/tab", headers=H).status_code == 404
    # transcrição assíncrona
    assert client.post(f"/v1/songs/{sid}/solos/s1/transcribe", headers=H, json={"preprocess": "raw"}).status_code == 202
    tab = _wait_tab(client, sid, "s1")
    assert tab["state"] in ("completed", "low_confidence") and tab["monophonic_only"] is True and "disclaimer" in tab
    notes = tab["notes"]
    assert [n["pitch"] for n in notes] == [64, 67, 69, 72, 69, 67, 64]
    assert all(0.9 <= n["start"] < n["end"] <= 6.05 for n in notes)                  # tempos absolutos, dentro do solo marcado
    assert all(tab["tuning"][n["string"] - 1] + n["fret"] == n["pitch"] for n in notes)
    # correção de nota e de afinação preserva o original e gera anotações TIPADAS
    edited = [dict(n) for n in notes]
    edited[1] = {**edited[1], "string": 2, "fret": 8}                                # G4: 8ª casa da corda 2 (mesma altura)
    edited[2]["deleted"] = True
    drop_d = [64, 59, 55, 50, 45, 38]
    r = client.put(f"/v1/songs/{sid}/solos/s1/tab", headers=H, json={"tuning": drop_d, "max_fret": 22, "notes": edited})
    assert r.status_code == 200 and len(r.json()["notes"]) == len(notes) - 1
    again = client.get(f"/v1/songs/{sid}/solos/s1/tab", headers=H).json()
    assert again["notes"] == notes and again["edited"]["tuning"] == drop_d              # automático intacto; correção separada
    anns = client.get(f"/v1/songs/{sid}/annotations", headers=H).json()["annotations"]
    types = {a["type"] for a in anns}
    assert {"solo_bounds", "note"} <= types and "chord" not in types                   # notas não viram correção de acorde
    deleted = [a for a in anns if a["type"] == "note" and a["corrected"].get("deleted")]
    assert deleted and deleted[0]["original"]["pitch"] == 69 and deleted[0]["validation_status"] == "unreviewed"
    # posição impossível é rejeitada
    bad = [dict(n) for n in notes]; bad[0]["string"], bad[0]["fret"] = 1, 29
    assert client.put(f"/v1/songs/{sid}/solos/s1/tab", headers=H, json={"tuning": [64, 59, 55, 50, 45, 40], "max_fret": 22, "notes": bad}).status_code == 422
    # retab: outra afinação recalcula a digitação sem gravar
    rt = client.post(f"/v1/songs/{sid}/solos/s1/retab", headers=H, json={"tuning": drop_d, "max_fret": 22, "notes": notes}).json()
    assert rt["tuning"] == drop_d and [n["start"] for n in rt["notes"]] == [n["start"] for n in notes]
    # ajuste de limites e instrumento é registrado com o original
    p = client.patch(f"/v1/songs/{sid}/solos/s1", headers=H, json={"start": 1.0, "instrument": "keyboard"}).json()
    assert p["start"] == 1.0 and p["instrument"] == "keyboard"
    anns = client.get(f"/v1/songs/{sid}/annotations", headers=H).json()["annotations"]
    assert any(a["type"] == "solo_instrument" and a["original"]["instrument"] == "guitar" for a in anns)
    # reprocessar a análise de acordes não apaga solos, transcrições nem anotações
    client.post(f"/v1/songs/{sid}/reanalyze", headers=H); time.sleep(0.3); _wait(client, sid)
    assert client.get(f"/v1/songs/{sid}/solos", headers=H).json()["solos"][0]["id"] == "s1"
    assert client.get(f"/v1/songs/{sid}/solos/s1/tab", headers=H).json()["edited"]["tuning"] == drop_d
    assert len(client.get(f"/v1/songs/{sid}/annotations", headers=H).json()["annotations"]) == len(anns)
    assert client.delete(f"/v1/songs/{sid}/solos/s1", headers=H).status_code == 204
