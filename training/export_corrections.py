"""Exporta correções REVISADAS (validation_status == "accepted", não 'superseded') como rótulos parciais.

Uso: python export_corrections.py <storage/songs> <saida.json>
Correções são rótulos de TRECHOS, não da música inteira: no treino os quadros fora delas ficam como IGNORE.
Excluídas e listadas: correções 'unreviewed'/'rejected', 'superseded', e trechos sobrepostos com acordes diferentes
na mesma música (inconsistência). Nada é lido de outras músicas para alterar resultados.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from score_chords import to_harte  # noqa: E402


def export(root: Path) -> dict:
    out, excluded = [], []
    for d in sorted(root.iterdir()):
        f = d / "corrections.json"
        if not f.is_file():
            continue
        cs = json.loads(f.read_text(encoding="utf-8"))["corrections"]
        ok = [c for c in cs if c["validation_status"] == "accepted" and not c["superseded"]]
        for c in cs:
            if c not in ok:
                excluded.append({"id": c["id"], "song_id": c["song_id"], "reason": c["validation_status"] if not c["superseded"] else "superseded"})
        for i, c in enumerate(ok):
            clash = [o for o in ok[:i] if min(c["end"], o["end"]) - max(c["start"], o["start"]) > 0 and o["corrected"] != c["corrected"]]
            if clash:
                excluded.append({"id": c["id"], "song_id": c["song_id"], "reason": "overlap_conflict"})
                continue
            row = {k: c.get(k) for k in ("id", "song_id", "run_id", "start", "end", "corrected", "predicted", "model",
                                         "corrected_harmonic", "corrected_bass", "predicted_harmonic", "predicted_bass", "predicted_confidence")}
            try:
                row["corrected_harte"] = to_harte(c["corrected"])      # formato dos treinos/avaliação (mir_eval)
            except ValueError:
                row["corrected_harte"] = None                          # rótulo fora do vocabulário: revisar antes de treinar
            out.append(row)
    return {"accepted": out, "excluded": excluded}


if __name__ == "__main__":
    res = export(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(res['accepted'])} aceitas, {len(res['excluded'])} excluídas")
