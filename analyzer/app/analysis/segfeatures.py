"""Características por segmento de acorde, independentes da tonalidade, para comparar sonoridades entre músicas.

Tudo é girado para que a raiz PREVISTA fique no índice 0 (um D de uma música e um E de outra com a mesma qualidade ficam
comparáveis). Blocos: chroma harmônico médio (12), perfil do baixo (12), massa posterior do BTC nas 14 qualidades da raiz
prevista + resto (15) e contexto (intervalo da raiz anterior e da seguinte, 12+12). Cada bloco é normalizado e ponderado;
a semelhança é o cosseno do vetor concatenado. Não usa o NOME do acorde como critério.
"""
import numpy as np

W_CHROMA, W_BASS, W_QPOST, W_CTX = 1.0, 0.6, 0.6, 0.4


def _norm(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _rot(v, root):
    return np.roll(np.asarray(v, float), -root)


def compute(segs: list, chroma: np.ndarray, chroma_frame_s: float, bass_pcs, bass_times, post, post_frame_s: float) -> list:
    """Retorna uma lista alinhada a segs (None para pausas) com start/end/chord/root/p e os blocos de características."""
    out = []
    for i, s in enumerate(segs):
        if s.get("root") is None:
            out.append(None)
            continue
        r, d = s["root"], s["end"] - s["start"]
        i0 = int((s["start"] + 0.15 * d) / chroma_frame_s)
        i1 = max(int((s["end"] - 0.15 * d) / chroma_frame_s), i0 + 1)
        ch = chroma[:, i0:min(i1, chroma.shape[1])].mean(axis=1) if i0 < chroma.shape[1] else np.zeros(12)
        if bass_pcs is not None:
            m = (bass_times >= s["start"]) & (bass_times < s["end"])
            bs = bass_pcs[:, m].mean(axis=1) if m.any() else np.zeros(12)
        else:
            bs = np.zeros(12)
        a, b = int(s["start"] / post_frame_s), max(int(s["end"] / post_frame_s), int(s["start"] / post_frame_s) + 1)
        pm = post[:, a:b].mean(axis=1)
        q = pm[r * 14:(r + 1) * 14]
        qpost = np.concatenate([q, [max(0.0, 1.0 - q.sum())]])
        prev_r = next((x["root"] for x in reversed(segs[:i]) if x.get("root") is not None), None)
        next_r = next((x["root"] for x in segs[i + 1:] if x.get("root") is not None), None)
        ctx = np.zeros(24)
        if prev_r is not None:
            ctx[(prev_r - r) % 12] = 1.0
        if next_r is not None:
            ctx[12 + (next_r - r) % 12] = 1.0
        out.append({"start": s["start"], "end": s["end"], "chord": s["chord"], "root": r, "p": s.get("p"),
                    "chroma": np.round(_norm(_rot(ch, r)), 4).tolist(), "bass": np.round(_norm(_rot(bs, r)), 4).tolist(),
                    "qpost": np.round(_norm(qpost), 4).tolist(), "ctx": ctx.tolist()})
    return out


def vector(f: dict) -> np.ndarray:
    """Vetor único (norma 1) a partir dos blocos de uma característica."""
    v = np.concatenate([W_CHROMA * _norm(f["chroma"]), W_BASS * _norm(f["bass"]), W_QPOST * _norm(f["qpost"]), W_CTX * _norm(f["ctx"])])
    return _norm(v)
