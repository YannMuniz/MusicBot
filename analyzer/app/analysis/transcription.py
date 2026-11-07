"""Transcrição melódica de um trecho (solo) para notas, com técnicas INFERIDAS marcadas como tal.

Método (monofônico, adequado a linhas solistas; não transcreve acordes/polifonia):
  1. recorte do trecho; pré-processamento opcional ('harmonic' = componente harmônica do HPSS; 'foreground' = tira o que se repete);
  2. pYIN (librosa) em E2–E6 → f0 e probabilidade de vozeamento por quadro de ~11,6 ms;
  3. segmentação em notas: mediana do pitch em semitons, nova nota quando o pitch muda > 0,7 semitom e dura ≥ MIN_NOTE_S;
     lacunas sem voz < MAX_GAP_S entre a mesma nota são fundidas; confiança = vozeamento médio da nota.
  4. técnicas: vibrato (oscilação periódica 4–9 Hz, profundidade ≥ 30 cents numa nota ≥ 0,35 s) e 'glissando' (transição contínua,
     sem lacuna, entre notas com ≥ 1 semitom: pode ser slide OU bend, não distinguível aqui). Sempre inferred=True e com
     confiança baixa/média; bend, hammer-on, pull-off, palm mute NÃO são reconhecidos.
Limitações: pYIN é monofônico; em mistura com banda, voz e distorção pode seguir a voz/baixo; por isso cada nota leva confiança
e o trecho recebe um estado 'low_confidence' quando a confiança média é baixa. Avaliado contra a tablatura da cifra (ver docs).
"""
import numpy as np
import librosa

SR = 22050
HOP = 256
FMIN, FMAX = librosa.note_to_hz("E2"), librosa.note_to_hz("E6")
MIN_NOTE_S = 0.07
MAX_GAP_S = 0.08
PITCH_JUMP = 0.7
LOW_CONF = 0.5


def preprocess(y: np.ndarray, mode: str = "harmonic") -> np.ndarray:
    if mode == "raw":
        return y
    if mode == "harmonic":
        return librosa.effects.harmonic(y, margin=2.0)
    if mode == "foreground":
        S, ph = librosa.magphase(librosa.stft(y))
        bg = librosa.decompose.nn_filter(S, aggregate=np.median, metric="cosine", width=int(librosa.time_to_frames(2, sr=SR)))
        bg = np.minimum(S, bg)
        mask = librosa.util.softmask(S - bg, 2.0 * bg, power=2)
        return librosa.istft(mask * S * ph, length=len(y))
    raise ValueError(mode)


def track_pitch(y: np.ndarray):
    f0, voiced, prob = librosa.pyin(y, fmin=FMIN, fmax=FMAX, sr=SR, frame_length=2048, hop_length=HOP, fill_na=np.nan)
    return f0, voiced, prob, HOP / SR


def segment_notes(f0, voiced, prob, frame_s: float, offset_s: float = 0.0) -> list:
    midi = librosa.hz_to_midi(np.where(np.isnan(f0), 1.0, f0))
    midi[np.isnan(f0)] = np.nan
    n = len(midi)
    notes, i = [], 0
    while i < n:
        if not voiced[i] or np.isnan(midi[i]):
            i += 1
            continue
        j, ref = i, midi[i]
        buf = [midi[i]]
        while j + 1 < n and voiced[j + 1] and not np.isnan(midi[j + 1]) and abs(midi[j + 1] - np.median(buf)) <= PITCH_JUMP:
            j += 1
            buf.append(midi[j])
        if (j - i + 1) * frame_s >= MIN_NOTE_S:
            notes.append({"start": offset_s + i * frame_s, "end": offset_s + (j + 1) * frame_s, "midi_f": float(np.median(buf)),
                          "pitch": int(round(np.median(buf))), "confidence": round(float(np.nanmean(prob[i:j + 1])), 3),
                          "_i": i, "_j": j})
        i = j + 1
    # funde lacunas curtas entre notas de mesma altura
    merged = []
    for nt in notes:
        if merged and nt["pitch"] == merged[-1]["pitch"] and nt["start"] - merged[-1]["end"] <= MAX_GAP_S:
            m = merged[-1]
            d0, d1 = m["end"] - m["start"], nt["end"] - nt["start"]
            m["confidence"] = round((m["confidence"] * d0 + nt["confidence"] * d1) / (d0 + d1), 3)
            m["end"], m["_j"] = nt["end"], nt["_j"]
        else:
            merged.append(nt)
    return merged


def infer_techniques(notes: list, midi_contour: np.ndarray, frame_s: float, offset_s: float = 0.0) -> None:
    """Vibrato e glissando INFERIDOS (nunca certeza)."""
    for k, nt in enumerate(notes):
        nt["techniques"] = []
        seg = midi_contour[nt["_i"]:nt["_j"] + 1]
        seg = seg[~np.isnan(seg)]
        if len(seg) * frame_s >= 0.35 and len(seg) > 16:
            d = seg - np.mean(seg)
            depth_cents = float((np.percentile(d, 95) - np.percentile(d, 5)) * 100 / 2)
            spec = np.abs(np.fft.rfft(d * np.hanning(len(d))))
            freqs = np.fft.rfftfreq(len(d), frame_s)
            band = (freqs >= 4) & (freqs <= 9)
            if band.any() and depth_cents >= 30 and spec[band].max() >= 0.35 * spec[1:].max():
                nt["techniques"].append({"type": "vibrato", "inferred": True, "confidence": "low", "depth_cents": round(depth_cents)})
        if k + 1 < len(notes):
            nx = notes[k + 1]
            if nx["start"] - nt["end"] <= frame_s * 1.5 and abs(nx["pitch"] - nt["pitch"]) >= 1:
                nt["techniques"].append({"type": "glissando", "inferred": True, "confidence": "low",
                                         "note": "pode ser slide ou bend; não distinguível", "to_pitch": nx["pitch"]})


def transcribe(y: np.ndarray, start_s: float = 0.0, mode: str = "harmonic") -> dict:
    """y: trecho mono a 22,05 kHz. Retorna notas com tempos absolutos (start_s + t) e o estado da transcrição."""
    z = preprocess(y, mode)
    f0, voiced, prob, frame_s = track_pitch(z)
    notes = segment_notes(f0, voiced, prob, frame_s, offset_s=start_s)
    midi = librosa.hz_to_midi(np.where(np.isnan(f0), 1.0, f0)); midi[np.isnan(f0)] = np.nan
    infer_techniques(notes, midi, frame_s, start_s)
    for nt in notes:
        nt.pop("_i"); nt.pop("_j")
        nt["start"], nt["end"] = round(nt["start"], 3), round(nt["end"], 3)
        nt["midi_f"] = round(nt["midi_f"], 2)
    conf = float(np.mean([n["confidence"] for n in notes])) if notes else 0.0
    voiced_ratio = float(np.mean(voiced)) if len(voiced) else 0.0
    state = "low_confidence" if (not notes or conf < LOW_CONF or voiced_ratio < 0.25) else "completed"
    return {"notes": notes, "state": state, "mean_confidence": round(conf, 3), "voiced_ratio": round(voiced_ratio, 3),
            "preprocess": mode, "method": "pyin(E2-E6)+note segmentation", "monophonic_only": True}
