"""Manifesto de dados de treino com divisão treino/validação/teste SEM vazamento entre músicas relacionadas.

Entrada: um CSV com colunas  audio,lab,work_id,source,license
  - work_id identifica a OBRA (todas as gravações/versões/covers da mesma canção compartilham o work_id).
    A divisão é feita por work_id, então versões da mesma obra nunca ficam em conjuntos diferentes.
  - audio/lab: caminhos; lab = "inicio fim acorde" por linha (Harte ou notação do sistema).
Também recusa: mesmo SHA-256 de áudio em work_ids diferentes (duplicata disfarçada) e licença vazia.
A divisão é determinística (hash do work_id + seed), reprodutível e registrada no manifesto.
"""
import csv
import hashlib
import json
from pathlib import Path

SPLITS = ("train", "val", "test")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_of(work_id: str, seed: int, fractions=(0.8, 0.1, 0.1)) -> str:
    u = int(hashlib.sha256(f"{seed}:{work_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "train" if u < fractions[0] else ("val" if u < fractions[0] + fractions[1] else "test")


def lab_duration(path: Path) -> float:
    end = 0.0
    for line in open(path, encoding="utf-8"):
        p = line.split(None, 2)
        if len(p) == 3:
            end = max(end, float(p[1]))
    return end


def build_manifest(csv_path: Path, seed: int = 0, fractions=(0.8, 0.1, 0.1)) -> dict:
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    base, items, seen_sha = Path(csv_path).parent, [], {}
    for r in rows:
        if not r.get("license", "").strip():
            raise ValueError(f"Licença ausente para {r.get('audio')}: não incluo dado sem licença registrada.")
        a, l = base / r["audio"], base / r["lab"]
        sha = _sha256(a)
        if sha in seen_sha and seen_sha[sha] != r["work_id"]:
            raise ValueError(f"Áudio duplicado em obras diferentes ({r['audio']}); vazamento potencial.")
        seen_sha[sha] = r["work_id"]
        items.append({"audio": str(a), "lab": str(l), "work_id": r["work_id"], "source": r.get("source", ""),
                      "license": r["license"], "audio_sha256": sha, "minutes": round(lab_duration(l) / 60, 2),
                      "split": split_of(r["work_id"], seed, fractions)})
    works = {}
    for it in items:
        works.setdefault(it["work_id"], set()).add(it["split"])
    assert all(len(v) == 1 for v in works.values()), "obra dividida entre conjuntos"
    summary = {s: {"items": sum(i["split"] == s for i in items), "works": len({i["work_id"] for i in items if i["split"] == s}),
                   "minutes": round(sum(i["minutes"] for i in items if i["split"] == s), 1)} for s in SPLITS}
    manifest = {"seed": seed, "fractions": list(fractions), "summary": summary, "items": items}
    manifest["manifest_sha256"] = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    return manifest
