"""Segmentação estrutural em duas camadas.

1. FRASES: picos de novidade (Foote, 2000) na matriz de autossimilaridade, sincronizada às batidas (chroma + timbre).
   Com mínimo de 8 s isto produz trechos do tamanho de uma frase musical (≈4 compassos), NÃO partes estruturais:
   era a causa das ~31 "seções" em uma música de 6,5 min.
2. SEÇÕES: as frases são comparadas entre si por trajetória (a ORDEM dentro da frase importa, não só a média), agrupadas
   em tipos, e sequências de tipos que se repetem (ex.: duas frases de refrão que voltam juntas) são compactadas em uma
   única parte recorrente; frases consecutivas do mesmo tipo (ex.: 4 ciclos iguais de uma ponte) viram uma só ocorrência.
O número de seções emerge dos dados. Rótulos são neutros ("Parte A", "Parte B"…): a identidade é o `repeat_group`, a
ocorrência é `occurrence`/`occurrences_total`. Nomes semânticos (verso/refrão/ponte) NÃO são inferidos: não há evidência
confiável (p.ex. detecção de voz) para isso. Os limiares abaixo são heurísticas fixadas e avaliadas em eval/ (ver docs).
"""
import librosa
import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.ndimage import uniform_filter1d
from scipy.spatial.distance import squareform

MIN_SECTION_S = 16.0  # distância mínima entre fronteiras (≈ 8 compassos a ~100 bpm)
KERNEL_BEATS = 8      # meia-largura do tabuleiro de Foote (mudança local), combinado com SF (mudança de repetição)
SF_DELAY = 4          # batidas empilhadas (contexto harmônico) na matriz de recorrência
SF_FILTER_BEATS = 10  # suavização temporal do perfil de repetição
PEAK_LAMBDA = 1.0     # limiar = média + PEAK_LAMBDA * desvio da curva de novidade
GROUP_DISTANCE = 0.65 # distância (custo DTW) máxima para considerar duas frases do mesmo tipo (heurístico)
LEN_PENALTY = 0.1     # penalidade por log da razão de durações (frases de tamanhos muito diferentes não são o mesmo trecho)
MAX_NGRAM = 8         # maior sequência de frases compactada como uma parte
MAX_SECTION_S = 120.0 # uma parte composta não passa disso


def _checkerboard(half: int) -> np.ndarray:
    idx = np.arange(2 * half) - (half - 0.5)
    g = np.exp(-0.5 * (idx / (half / 2)) ** 2)
    s = np.sign(idx)
    return np.outer(s, s) * np.outer(g, g)


def novelty_curve(feat: np.ndarray) -> np.ndarray:
    x = uniform_filter1d(feat, size=4, axis=1)
    x = x / (np.linalg.norm(x, axis=0, keepdims=True) + 1e-9)
    ssm = x.T @ x
    n = ssm.shape[0]
    half = int(min(KERNEL_BEATS, max(2, n // 4)))
    k = _checkerboard(half)
    pad = np.pad(ssm, half, mode="edge")
    nov = np.array([np.sum(pad[t: t + 2 * half, t: t + 2 * half] * k) for t in range(n)])
    return np.maximum(nov, 0)


def sf_novelty(feat: np.ndarray) -> np.ndarray:
    """Novidade por 'Structural Features' (Serrà et al., 2014): mudança do contexto de REPETIÇÃO, não da borda local.

    Matriz de recorrência (k-vizinhos, cosseno) sobre características com atraso, convertida para tempo-lag e suavizada
    no tempo; a novidade é a variação do perfil de repetição entre batidas vizinhas. Em duas músicas com cifra alinhada
    foi mais próxima das fronteiras reais do que o tabuleiro de Foote (ver docs/avaliacao.md)."""
    n = feat.shape[1]
    stacked = np.vstack([np.roll(feat, k, axis=1) for k in range(SF_DELAY)])
    rec = librosa.segment.recurrence_matrix(stacked, k=int(np.ceil(2 * np.sqrt(n))), width=SF_DELAY, metric="cosine",
                                            mode="affinity", sym=True)
    lag = uniform_filter1d(librosa.segment.recurrence_to_lag(rec, pad=True), size=SF_FILTER_BEATS, axis=1)
    return np.linalg.norm(np.diff(lag, axis=1), axis=0)


def combined_novelty(feat: np.ndarray) -> np.ndarray:
    """Soma (em z-score) da novidade local (tabuleiro de Foote) e da novidade de repetição (SF).

    Cada uma falha onde a outra acerta: o tabuleiro vê mudanças bruscas de conteúdo; o SF vê mudanças no padrão de
    repetição, mas perde fronteiras óbvias em estruturas muito regulares. Em 4 fontes (2 sintéticas com verdade exata +
    2 cifras alinhadas) a soma teve a maior F média de fronteira (0,52 vs 0,49 SF e 0,26 tabuleiro)."""
    z = lambda x: (x - x.mean()) / (x.std() + 1e-9)  # noqa: E731
    chk, sf = novelty_curve(feat), sf_novelty(feat)
    m = min(len(chk), len(sf))
    return z(chk[:m]) + z(sf[:m])


def phrase_boundaries(feat: np.ndarray, edges_s: np.ndarray, duration: float) -> list:
    """Fronteiras de frase (camada 1): picos da novidade combinada, supressão por força, distância mínima MIN_SECTION_S."""
    n = feat.shape[1]
    starts = edges_s[:-1]
    bounds = [0.0]
    if n >= 16:
        nov = combined_novelty(feat)
        thr = nov.mean() + PEAK_LAMBDA * nov.std()
        cand = [t for t in range(1, len(nov) - 1) if nov[t] >= thr and nov[t] == nov[max(0, t - 2): t + 3].max()]
        accepted = []
        for t in sorted(cand, key=lambda t: -nov[t]):
            tt = float(starts[min(t + 1, n - 1)])
            if tt < MIN_SECTION_S or duration - tt < MIN_SECTION_S:
                continue
            if all(abs(tt - a) >= MIN_SECTION_S for a in accepted):
                accepted.append(tt)
        bounds += sorted(accepted)
    bounds.append(duration)
    return bounds


def _block(feat: np.ndarray, starts: np.ndarray, a: float, b: float) -> np.ndarray:
    """Características (d, beats) do trecho [a, b)."""
    m = (starts >= a) & (starts < b)
    return feat[:, m]


def phrase_distance(xi: np.ndarray, xj: np.ndarray, len_i: float, len_j: float) -> float:
    """Custo DTW normalizado (cosseno) entre duas frases + penalidade por razão de durações.

    O DTW compara as trajetórias com tolerância a pequenas diferenças de andamento/duração (a mesma parte tocada outra
    vez raramente tem exatamente os mesmos compassos) mantendo a ORDEM dos eventos. Em "Estamos de pé" separou todos os
    pares de partes diferentes dos pares da mesma parte (blocos da referência), ao contrário da comparação de médias."""
    if xi.shape[1] < 2 or xj.shape[1] < 2:
        return 2.0
    cost, wp = librosa.sequence.dtw(xi, xj, metric="cosine")
    return float(cost[-1, -1] / len(wp)) + LEN_PENALTY * abs(float(np.log(max(len_i, 1e-3) / max(len_j, 1e-3))))


def group_phrases(traj: list, lens: list, threshold: float = None) -> tuple:
    """Agrupa frases em tipos (ligação média). Retorna (rótulos 1..k, matriz de distâncias)."""
    n = len(traj)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            D[i, j] = D[j, i] = phrase_distance(traj[i], traj[j], lens[i], lens[j])
    if n < 2:
        return np.ones(n, dtype=int), D
    labels = fcluster(linkage(squareform(D, checks=False), method="average"), t=GROUP_DISTANCE if threshold is None else threshold,
                      criterion="distance")
    return labels.astype(int), D


def compress_repeats(labels: list, spans: list) -> list:
    """Compacta a sequência de tipos de frase em ocorrências de partes.

    1) frases consecutivas do mesmo tipo viram uma ocorrência (partes compostas repetidas em sequência NÃO se fundem: são ocorrências distintas); 2) a sequência de tipos mais longa que se repete
    (≥ 2 ocorrências sem sobreposição, até MAX_NGRAM frases, cobrindo mais frases) vira um novo tipo composto; repete até
    não haver repetição. Retorna itens {label, first, last} em ordem (índices de frase)."""
    items = [{"label": ("p", int(l)), "first": i, "last": i} for i, l in enumerate(labels)]

    def run_merge(its):
        """Funde só FRASES idênticas consecutivas (ciclos de uma mesma ponte). Partes compostas repetidas em sequência
        (ex.: refrão duas vezes seguidas) continuam sendo duas ocorrências da mesma parte."""
        out = []
        for it in its:
            if out and out[-1]["label"] == it["label"] and it["label"][0] == "p":
                out[-1]["last"] = it["last"]
            else:
                out.append(dict(it))
        return out

    items = run_merge(items)
    serial = 0
    while True:
        best = None
        for n in range(min(MAX_NGRAM, len(items) // 2), 1, -1):
            seen = {}
            for i in range(len(items) - n + 1):
                seen.setdefault(tuple(x["label"] for x in items[i:i + n]), []).append(i)
            for gram, pos in seen.items():
                occ, last_end = [], -1
                for i in pos:                                   # ocorrências sem sobreposição
                    if i >= last_end:
                        occ.append(i)
                        last_end = i + n
                if len(occ) < 2:
                    continue
                if any(spans[items[i + n - 1]["last"]][1] - spans[items[i]["first"]][0] > MAX_SECTION_S for i in occ):
                    continue
                score = n * len(occ)
                if best is None or score > best[0] or (score == best[0] and n > best[1]):
                    best = (score, n, gram, occ)
        if best is None:
            break
        _, n, gram, occ = best
        serial += 1
        new, i = [], 0
        starts_at = set(occ)
        while i < len(items):
            if i in starts_at:
                new.append({"label": ("c", serial), "first": items[i]["first"], "last": items[i + n - 1]["last"]})
                i += n
            else:
                new.append(items[i])
                i += 1
        items = run_merge(new)
    return items


def _letters(k: int) -> str:
    s = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        s = chr(65 + r) + s
    return s


def detect_sections(feat: np.ndarray, edges_s: np.ndarray, duration: float, segs: list, group_threshold: float = None) -> list:
    """feat: (d, n) z-score por linha, sincronizado às batidas; edges_s: n+1 fronteiras em segundos."""
    starts = edges_s[:-1]
    bounds = phrase_boundaries(feat, edges_s, duration)
    spans = list(zip(bounds[:-1], bounds[1:]))
    traj = [_block(feat, starts, a, b) for a, b in spans]
    lens = [b - a for a, b in spans]
    if len(spans) > 1 and all(t.shape[1] >= 2 and np.linalg.norm(t) > 0 for t in traj):
        labels, D = group_phrases(traj, lens, group_threshold)
    else:
        labels, D = np.arange(1, len(spans) + 1), np.zeros((len(spans), len(spans)))
    items = compress_repeats([int(x) for x in labels], spans)

    ident, order = {}, []
    for it in items:
        ident.setdefault(it["label"], len(ident))
    total = {}
    for it in items:
        total[it["label"]] = total.get(it["label"], 0) + 1
    seen, out = {}, []
    for k, it in enumerate(items):
        a, b = spans[it["first"]][0], spans[it["last"]][1]
        seen[it["label"]] = seen.get(it["label"], 0) + 1
        gid = ident[it["label"]] + 1
        prog = []
        for s in segs:
            if s["end"] > a and s["start"] < b and s["chord"] != "N" and (not prog or prog[-1] != s["chord"]):
                prog.append(s["chord"])
        out.append({"index": k + 1, "label": f"Parte {_letters(ident[it['label']])}", "semantic_label": None,
                    "start": round(float(a), 2), "end": round(float(b), 2), "repeat_group": gid,
                    "occurrence": seen[it["label"]], "occurrences_total": total[it["label"]],
                    "phrases": [[round(float(spans[j][0]), 2), round(float(spans[j][1]), 2)] for j in range(it["first"], it["last"] + 1)],
                    "progression": prog})
    return out
