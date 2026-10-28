"""Fine-tuning do BTC (só cabeça de saída + últimas camadas) sobre um manifesto com rótulos reais.

Uso (de dentro de training/, com PYTHONPATH=../analyzer):
  python finetune.py manifest.json --base /opt/models/btc_large_voca.pt --out runs/ft01 [--unfreeze-layers 2] [--epochs 20]

TRAVAS: não treina com menos de MIN_TRAIN_MINUTES de áudio anotado em 'train', nem sem 'val' e 'test' não vazios.
--allow-small só serve para testar o encanamento: o checkpoint sai com valid_for_use=false e NÃO deve ser usado.
O checkpoint usa o mesmo formato do original (model/mean/std) e vem acompanhado de run.json com tudo que é preciso
para reproduzir (SHA dos pesos-base, SHA do manifesto, seed, hiperparâmetros, versões, perdas).
Rótulos parciais (correções) ficam como IGNORE e não entram na perda. Nenhum dado é tratado como verdade sem licença.
"""
import argparse
import hashlib
import json
import platform
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vocab import IGNORE, frames_from_intervals  # noqa: E402

MIN_TRAIN_MINUTES = 120.0


def read_lab(path):
    iv, lb = [], []
    for line in open(path, encoding="utf-8"):
        p = line.split(None, 2)
        if len(p) == 3:
            iv.append((float(p[0]), float(p[1])))
            lb.append(p[2].strip())
    return iv, lb


def prepare(engine, items, cache: Path):
    """Features normalizadas (T,144) e classes por quadro (T,) por música, em cache .npz."""
    from app.audio import load_audio
    from app.analysis.btc_engine import FRAME_S
    data = []
    cache.mkdir(parents=True, exist_ok=True)
    for it in items:
        f = cache / f"{it['audio_sha256'][:16]}.npz"
        if f.is_file():
            z = np.load(f)
            x = z["x"]
        else:
            y = load_audio(Path(it["audio"]))
            x = ((engine.features(y).T - engine.mean) / engine.std).astype(np.float32)
            np.savez_compressed(f, x=x)
        iv, lb = read_lab(it["lab"])
        data.append((x, frames_from_intervals(iv, lb, x.shape[0], FRAME_S)))
    return data


def batches(data, timestep, batch_size, rng):
    blocks = []
    for x, y in data:
        for a in range(0, max(x.shape[0] - timestep, 0) + 1, timestep):
            xb, yb = x[a:a + timestep], y[a:a + timestep]
            if len(xb) == timestep and (yb != IGNORE).any():
                blocks.append((xb, yb))
    rng.shuffle(blocks)
    for i in range(0, len(blocks), batch_size):
        chunk = blocks[i:i + batch_size]
        yield torch.tensor(np.stack([c[0] for c in chunk])), torch.tensor(np.stack([c[1] for c in chunk]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--unfreeze-layers", type=int, default=2)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cache", default=".cache")
    ap.add_argument("--allow-small", action="store_true")
    a = ap.parse_args(argv)

    man = json.load(open(a.manifest, encoding="utf-8"))
    summ = man["summary"]
    problems = []
    if summ["train"]["minutes"] < MIN_TRAIN_MINUTES:
        problems.append(f"treino com {summ['train']['minutes']} min (< {MIN_TRAIN_MINUTES})")
    if summ["val"]["items"] == 0 or summ["test"]["items"] == 0:
        problems.append("val/test vazios")
    if problems and not a.allow_small:
        print("RECUSADO: dados insuficientes para um treino válido: " + "; ".join(problems), file=sys.stderr)
        return 2

    random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
    from app.analysis.btc_engine import BtcEngine, TIMESTEP, sha256_file
    engine = BtcEngine(Path(a.base))
    model = engine.model
    for p in model.parameters():
        p.requires_grad = False
    layers = model.self_attn_layers.self_attn_layers
    train_mods = [model.output_layer, model.self_attn_layers.layer_norm] + list(layers[len(layers) - a.unfreeze_layers:])
    for m in train_mods:
        for p in m.parameters():
            p.requires_grad = True
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr)
    lossf = torch.nn.CrossEntropyLoss(ignore_index=IGNORE)

    cache = Path(a.cache)
    split = lambda s: [i for i in man["items"] if i["split"] == s]  # noqa: E731
    train, val = prepare(engine, split("train"), cache), prepare(engine, split("val"), cache)
    rng = random.Random(a.seed)

    def run_epoch(data, training):
        model.train(training)
        tot, n = 0.0, 0
        for xb, yb in batches(data, TIMESTEP, a.batch_size, rng):
            with torch.set_grad_enabled(training):
                h, _ = model.self_attn_layers(xb)
                logits = model.output_layer(h)
                loss = lossf(logits.reshape(-1, logits.shape[-1]), yb.reshape(-1))
                if training:
                    opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item() * len(xb); n += len(xb)
        return tot / max(n, 1)

    history, best, t0 = [], (float("inf"), None), time.time()
    for ep in range(a.epochs):
        tl, vl = run_epoch(train, True), run_epoch(val, False)
        history.append({"epoch": ep + 1, "train_loss": round(tl, 4), "val_loss": round(vl, 4)})
        if vl < best[0]:
            best = (vl, {k: v.clone() for k, v in model.state_dict().items()})
    model.load_state_dict(best[1])  # escolhe pela perda de VALIDAÇÃO; o teste não é tocado aqui

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    torch.save({"model": model.state_dict(), "mean": engine.mean, "std": engine.std}, out / "btc_finetuned.pt")
    meta = {"valid_for_use": not problems, "problems": problems, "base_weights_sha256": sha256_file(Path(a.base)),
            "manifest_sha256": man["manifest_sha256"], "manifest_summary": summ, "seed": a.seed,
            "hyperparameters": {"unfreeze_layers": a.unfreeze_layers, "epochs": a.epochs, "lr": a.lr, "batch_size": a.batch_size},
            "trainable_parameters": int(sum(p.numel() for p in params)), "history": history,
            "best_val_loss": round(best[0], 4), "train_seconds": round(time.time() - t0, 1),
            "versions": {"torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version()},
            "checkpoint_sha256": hashlib.sha256((out / "btc_finetuned.pt").read_bytes()).hexdigest()}
    (out / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("valid_for_use", "best_val_loss", "train_seconds", "checkpoint_sha256")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
