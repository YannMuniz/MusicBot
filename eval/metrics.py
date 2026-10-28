"""Métricas detalhadas de acordes (por tipo, extensões, inversões, fragmentação, ambiguidade) sobre mir_eval.

Tudo é ponderado pelo tempo (fração da duração da referência). Só tem valor com referência anotada por humanos;
com poucas músicas os números descrevem essas músicas, não o sistema em geral. 'segundos' acompanha cada
categoria para mostrar quanta evidência há por trás do número.
"""
import numpy as np
import mir_eval

EXT_DEGREES = {"9", "11", "13", "b9", "#9", "#11", "b13", "b11"}


def _split(label):
    if label in ("N", "X"):
        return label, "", set(), "1"
    root, q, deg, bass = mir_eval.chord.split(label)
    return root, q, set(deg), (bass or "1")


def _category(label):
    root, q, deg, _ = _split(label)
    if root in ("N", "X"):
        return "N"
    return "extensions" if deg & EXT_DEGREES else (q or "maj")


def fragmentation(intervals, duration):
    d = np.diff(np.asarray(intervals), axis=1).ravel()
    return {"segments": int(len(d)), "per_minute": round(len(d) / (duration / 60), 2) if duration else None,
            "median_s": round(float(np.median(d)), 3), "short_fraction_lt_0_5s": round(float((d < 0.5).mean()), 3)}


def detailed(est_iv, est_lb, ref_iv, ref_lb, est_ambiguous=None):
    """est_ambiguous: lista de bool alinhada a est_* (opcional). Retorna dict com resumo por categoria."""
    est_iv, ref_iv = np.asarray(est_iv, float), np.asarray(ref_iv, float)
    t0, t1 = ref_iv.min(), ref_iv.max()
    est_frag = fragmentation(est_iv, est_iv.max() - est_iv.min())
    ei, el = mir_eval.util.adjust_intervals(est_iv, est_lb, t0, t1, "N", "N")
    ref_frag = fragmentation(ref_iv, t1 - t0)
    out = {k: round(float(v), 4) for k, v in mir_eval.chord.evaluate(ref_iv, ref_lb, ei, el).items()}

    iv, rl, el2 = mir_eval.util.merge_labeled_intervals(ref_iv, ref_lb, ei, el)
    w = np.diff(iv, axis=1).ravel()
    rs, es = [_split(x) for x in rl], [_split(x) for x in el2]
    cats = [_category(x) for x in rl]
    r_root, r_bm, r_bass = mir_eval.chord.encode_many(rl, True)
    e_root, e_bm, e_bass = mir_eval.chord.encode_many(el2, True)
    root_ok = (r_root == e_root) & (r_root >= 0)
    bitmap_ok = (r_bm == e_bm).all(axis=1)
    qual_ok = np.array([a[0] == b[0] and a[1] == b[1] for a, b in zip(rs, es)]) & root_ok
    exact = root_ok & bitmap_ok

    by = {}
    for c in sorted(set(cats) - {"N"}):
        m = np.array([x == c for x in cats])
        s = float(w[m].sum())
        by[c] = {"seconds": round(s, 2), "root": round(float(w[m & root_ok].sum() / s), 3),
                 "quality": round(float(w[m & qual_ok].sum() / s), 3), "exact_notes": round(float(w[m & exact].sum() / s), 3)}
    out["by_type"] = by

    # confusões entre classes semelhantes (só tempo com raiz certa: erro de qualidade, não de raiz) e simplificação indevida
    ecats = [_category(x) for x in el2]
    conf, simplified = {}, 0.0
    complex_ref = np.array([c not in ("maj", "min", "N") for c in cats])
    for i in np.where(root_ok & ~exact)[0]:
        if cats[i] != ecats[i]:
            k = f"{cats[i]} -> {ecats[i]}"
            conf[k] = conf.get(k, 0.0) + float(w[i])
        if complex_ref[i] and ecats[i] in ("maj", "min"):
            simplified += float(w[i])
    out["confusions_same_root_seconds"] = dict(sorted(((k, round(v, 2)) for k, v in conf.items()), key=lambda kv: -kv[1])[:20])
    comp_s = float(w[complex_ref & root_ok].sum())
    out["simplification"] = {"complex_ref_seconds_with_correct_root": round(comp_s, 2),
                             "simplified_to_triad_fraction": round(simplified / comp_s, 3) if comp_s else None}
    chord_ref = np.array([c != "N" for c in cats]) & (r_root >= 0)
    out["bass"] = {"bass_correct_fraction_all_chords": round(float(w[chord_ref & root_ok & (r_bass == e_bass)].sum() / w[chord_ref].sum()), 3)
                   if chord_ref.any() else None}

    has_inv = np.array([x[3] != "1" and x[0] not in ("N", "X") for x in rs])
    est_inv = (e_bass > 0) & (e_root >= 0)
    inv = {"ref_inversion_seconds": round(float(w[has_inv].sum()), 2)}
    if has_inv.any():
        inv["bass_correct_on_ref_inversions"] = round(float(w[has_inv & root_ok & (r_bass == e_bass)].sum() / w[has_inv].sum()), 3)
    plain = ~has_inv & (r_root >= 0)
    if plain.any():
        inv["false_inversion_rate"] = round(float(w[plain & est_inv].sum() / w[plain].sum()), 3)
    out["inversions"] = inv

    out["fragmentation"] = {"estimated": est_frag, "reference": ref_frag,
                            "ratio_est_to_ref_segments": round(est_frag["segments"] / max(ref_frag["segments"], 1), 2)}
    tot = float(w.sum())
    out["unknown"] = {"estimated_N_fraction": round(float(w[np.array([x[0] == "N" for x in es])].sum() / tot), 3)}
    if est_ambiguous is not None:
        ea = np.asarray(est_ambiguous, bool)
        d = np.diff(est_iv, axis=1).ravel()
        out["unknown"]["ambiguous_fraction"] = round(float(d[ea].sum() / d.sum()), 3)
        # ambíguo só vale como sinal se acertar menos que o não ambíguo
        amb_iv = est_iv[ea]
        if len(amb_iv):
            amb_mask = np.zeros(len(iv), bool)
            for a, b in amb_iv:
                amb_mask |= (iv[:, 0] >= a - 1e-9) & (iv[:, 1] <= b + 1e-9)
            for name, m in (("accuracy_when_ambiguous", amb_mask), ("accuracy_when_not_ambiguous", ~amb_mask)):
                if m.sum() and w[m].sum() > 0:
                    out["unknown"][name + "_exact"] = round(float(w[m & exact].sum() / w[m].sum()), 3)
    return out
