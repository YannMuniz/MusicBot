"""Pipeline completo: áudio -> tom, acordes, seções. Sem dados predefinidos: tudo vem do sinal."""
import os
import time
from pathlib import Path
from typing import Callable, Optional

import librosa
import numpy as np

from ..audio import SR, load_audio
from . import bass as bass_mod
from . import harmony
from . import smoothing as smoothing_mod
from .smoothing import smooth_chords
from .btc_engine import AMBIG_MIN_MARGIN, AMBIG_MIN_P, FRAME_S, VOCABULARY, decode, get_engine
from .chords import detect_chords, segments_from_runs
from . import sections as sections_mod
from .sections import detect_sections
from .tonality import estimate_key

HOP = 512
BASELINE = {"name": "librosa-baseline", "version": "0.2.0", "vocabulary": ["maj", "min"]}
WEIGHTS = os.environ.get("ANALYZER_BTC_WEIGHTS", "/opt/models/btc_large_voca.pt")
NEURAL_WARNING = ("Vocabulário do modelo: maj, min, 7, maj7, m7, dim, aug, sus2, sus4, 6, m6, dim7, m7(b5), mM7. "
                  "Acordes com 9ª, 11ª, 13ª, add ou notas alteradas não são reconhecidos como tal: aparecem como o acorde mais próximo do vocabulário.")


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def run_analysis(path: Path, progress: Optional[Callable[[str], None]] = None) -> dict:
    step = progress or (lambda _s: None)
    t0 = time.time()
    step("decoding")
    y = load_audio(path)
    duration = len(y) / SR

    step("separating")
    y_harm, y_perc = librosa.effects.hpss(y)  # uma única passada (a mais cara)

    step("features")
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=SR, hop_length=HOP)
    mfcc = librosa.feature.mfcc(y=y, sr=SR, hop_length=HOP, n_mfcc=13)

    step("tonality")
    key = estimate_key(chroma)

    step("beats")
    onset = librosa.onset.onset_strength(y=y_perc, sr=SR, hop_length=HOP)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=SR, hop_length=HOP)
    tempo = float(np.atleast_1d(tempo)[0])
    warnings = list(key["warnings"])
    n_frames = chroma.shape[1]
    if len(beats) < 8:
        warnings.append("Poucas batidas detectadas; usada grade fixa de 0,5 s (menor precisão nos limites de acordes).")
        beats = np.arange(0, n_frames, int(0.5 * SR / HOP))
    bounds = librosa.util.fix_frames(beats, x_min=0, x_max=n_frames)
    edges_s = librosa.frames_to_time(bounds, sr=SR, hop_length=HOP)

    step("chords")
    raw_segs = None
    engine = get_engine(WEIGHTS) if os.environ.get("ANALYZER_CHORD_ENGINE", "btc") == "btc" else None
    if engine is not None:
        post = engine.posteriors(y)
        stay, min_dur = 0.9, 0.25
        segs = segments_from_runs(decode(post, stay=stay, min_dur_s=min_dur), FRAME_S, duration, key["prefers_flats"], post=post)
        raw_segs = [dict(x) for x in segs]
        beat_len = float(np.median(np.diff(edges_s))) if len(edges_s) > 2 else 0.5
        segs, smooth_log = smooth_chords(segs, beat_len)
        algorithm = {"name": "btc-large-voca", "version": "ISMIR2019-2682317", "vocabulary": VOCABULARY,
                     "weights_sha256": engine.weights_sha256,
                     "parameters": {"viterbi_stay": stay, "min_segment_s": min_dur, "ambiguity_min_p": AMBIG_MIN_P,
                                    "ambiguity_min_margin": AMBIG_MIN_MARGIN, "frame_s": round(FRAME_S, 4),
                                    "smoothing": {"min_p": smoothing_mod.MIN_P, "min_blip_s": smoothing_mod.MIN_BLIP_S,
                                                  "rest_min_s": smoothing_mod.REST_MIN_S, "beat_len_s": round(beat_len, 3), **smooth_log,
                                                  "segments_before": len(raw_segs), "segments_after": len(segs)}}}
        n_amb = sum(1 for x in segs if x.get("ambiguous"))
        warnings.append(f"{n_amb} de {len(segs)} segmentos marcados como ambíguos (probabilidade do modelo baixa ou "
                        "empatada com outro acorde). As probabilidades do modelo não são calibradas.")
        if os.environ.get("ANALYZER_BASS", "1") == "1":
            pcs, tt = bass_mod.bass_chroma(y, SR)
            bass_mod.annotate_bass(segs, pcs, tt, key["prefers_flats"])
            algorithm["parameters"].update(bass_method="harmonic-summation+vote-v2", bass_min_vote_share=bass_mod.MIN_VOTE_SHARE,
                                           bass_min_voiced=bass_mod.MIN_VOICED, bass_min_segment_s=bass_mod.MIN_SEG_S,
                                           color_tone_min_rel=harmony.MIN_COLOR_REL)
            harmony.tone_evidence(segs, chroma, HOP / SR)
            harmony.finalize(segs, key["prefers_flats"])
            n_inv = sum(1 for x in segs if x.get("inversion"))
            warnings.append(f"{n_inv} inversões registradas a partir do baixo (rótulo final 'X/Y'; o acorde harmônico fica em harmonic_label). "
                            "Regra e limiares não foram validados com referência anotada em número suficiente de músicas.")
            if any(x.get("possible_additions") for x in segs):
                warnings.append("'possible_additions': notas de cor (2ª/4ª/6ª/7ª) com alguma evidência no áudio; evidência fraca, não "
                                "validada, e NÃO altera o acorde exibido. O BTC não reconhece 6ª/sus2 de forma confiável nesta gravação.")
        warnings.append(NEURAL_WARNING)
        warnings.append("Modelo neural pré-treinado (BTC, ISMIR 2019) em corpora públicos de música pop/rock; "
                        "a precisão em outros gêneros/gravações não foi medida neste projeto.")
    else:
        chroma_sync = librosa.util.sync(chroma, bounds, aggregate=np.median, pad=False)
        segs = detect_chords(chroma_sync, edges_s, key["prefers_flats"])
        algorithm = BASELINE
        for x in segs:
            x["kind"] = "chord"
        warnings.append("Motor neural indisponível: usado o método clássico (somente acordes maiores e menores).")

    step("sections")
    feats = np.vstack([librosa.util.normalize(chroma, axis=0), librosa.util.normalize(mfcc[1:], axis=0)])
    fs = librosa.util.sync(feats, bounds, aggregate=np.mean, pad=False)
    fs = (fs - fs.mean(axis=1, keepdims=True)) / (fs.std(axis=1, keepdims=True) + 1e-9)
    sections = detect_sections(fs, edges_s, duration, segs)
    algorithm = {**algorithm, "sections": {"method": "foote+SF novelty, DTW grouping, repeat compression", "kernel_beats": sections_mod.KERNEL_BEATS, "phrases_min_s": sections_mod.MIN_SECTION_S,
                                           "sf_delay_beats": sections_mod.SF_DELAY, "sf_filter_beats": sections_mod.SF_FILTER_BEATS,
                                           "peak_lambda": sections_mod.PEAK_LAMBDA, "group_distance": sections_mod.GROUP_DISTANCE,
                                           "max_ngram_phrases": sections_mod.MAX_NGRAM, "labels": "neutral (Parte A, B...); no semantic labels"}}

    if np.median([s["score"] for s in segs]) < 0.2:
        warnings.append("Scores de acorde baixos em geral: a gravação pode ser polifônica/densa demais para este método.")

    return {
        "algorithm": algorithm,
        "librosa": librosa.__version__,
        "duration": round(duration, 2),
        "tempo_bpm": round(tempo, 1),
        "key": key,
        "chords": segs,
        "raw_chords": raw_segs if raw_segs is not None else segs,
        "sections": sections,
        "warnings": warnings,
        "processing_seconds": round(time.time() - t0, 1),
    }


def build_report(song_name: str, r: dict) -> str:
    k = r["key"]
    L = [f"Relatório de análise — {song_name}",
         f"Algoritmo: {r['algorithm']['name']} {r['algorithm']['version']} (librosa {r['librosa']})",
         f"Duração: {_fmt(r['duration'])} | Andamento estimado: {r['tempo_bpm']:.0f} BPM | Processado em {r['processing_seconds']} s",
         f"Tom estimado: {k['name']} (relativo: {k['relative']['tonic']} {k['relative']['mode']}) | "
         f"correlação {k['correlation']} | margem p/ 2ª candidata {k['margin_to_second']}",
         "  Alternativas: " + ", ".join(f"{a['name']} ({a['correlation']})" for a in k["alternatives"]),
         "", "Seções (rótulos neutros; 'grupo' igual = trechos acusticamente semelhantes, sem significado semântico):"]
    for s in r["sections"]:
        occ = f" ({s['occurrence']}/{s['occurrences_total']})" if s.get("occurrences_total", 1) > 1 else ""
        L.append(f"  {s['label']}{occ:<6} {_fmt(s['start'])} – {_fmt(s['end'])}  grupo {s['repeat_group']}")
        L.append("      " + " | ".join(s["progression"]))
    L += ["", "Avisos:"] + [f"  - {w}" for w in r["warnings"]]
    return "\n".join(L) + "\n"
