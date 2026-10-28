"""Avalia um checkpoint BTC (original ou fine-tuned) em um conjunto do manifesto, com as métricas de eval/.

Uso: python evaluate_split.py manifest.json --weights W.pt --split test --out resultado.json
Rode duas vezes (pesos originais e fine-tuned) e compare os JSON. Só o conjunto 'test' deve ser usado para reportar.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "eval"))
from finetune import read_lab  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest"); ap.add_argument("--weights", required=True)
    ap.add_argument("--split", default="test"); ap.add_argument("--out")
    a = ap.parse_args(argv)
    from app.audio import load_audio
    from app.analysis.btc_engine import FRAME_S, BtcEngine, decode
    from app.analysis.chords import segments_from_runs
    from metrics import detailed
    from score_chords import to_harte
    eng = BtcEngine(Path(a.weights))
    man = json.load(open(a.manifest, encoding="utf-8"))
    per, keys = [], ("root", "majmin", "sevenths", "mirex", "thirds", "triads", "tetrads", "seg", "overseg", "underseg")
    for it in [i for i in man["items"] if i["split"] == a.split]:
        y = load_audio(Path(it["audio"]))
        post = eng.posteriors(y)
        segs = segments_from_runs(decode(post), FRAME_S, len(y) / 22050, True, post=post)
        ri, rl = read_lab(it["lab"])
        res = detailed(np.array([[s["start"], s["end"]] for s in segs]), [to_harte(s["chord"]) for s in segs],
                       np.array(ri), [to_harte(x) for x in rl], [s["ambiguous"] for s in segs])
        per.append({"work_id": it["work_id"], "audio": it["audio"], "minutes": it["minutes"], **res})
    tot = sum(p["minutes"] for p in per) or 1.0
    agg = {k: round(sum(p[k] * p["minutes"] for p in per) / tot, 4) for k in keys} if per else {}
    out = {"weights": a.weights, "weights_sha256": eng.weights_sha256, "split": a.split, "songs": len(per),
           "minutes": round(tot, 1), "weighted_mean": agg, "per_song": per}
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"songs": out["songs"], "minutes": out["minutes"], "weighted_mean": agg}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
