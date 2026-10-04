"""Audio analysis and mastering QC: BPM, key, LUFS, true peak and clipping.

Usage:
    python analyze_audio.py FILE [--json OUT.json] [--target-lufs -14] [--max-true-peak -1.0]

Exit codes: 0 = OK, 1 = file missing, unreadable or silent, 2 = clipping or true peak over the limit.
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm
import soundfile as sf
from scipy.signal import resample_poly

ANALYSIS_SR = 22050
CLIP_LEVEL = 0.999  # about -0.01 dBFS
CLIP_MIN_RUN = 3  # consecutive samples at full scale that count as one clipping event
TRUE_PEAK_OVERSAMPLE = 4  # ITU-R BS.1770-4 true peak meter oversampling factor

# Krumhansl-Kessler key profiles, index 0 = tonic
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
# Conventional spellings, so Strudel gets e.g. "Eb:major" rather than "D#:major"
MAJOR_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MINOR_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]


def load_audio(path):
    """Return (samples, sample_rate) with samples shaped (frames, channels), float32."""
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        return data, sr
    except (sf.LibsndfileError, RuntimeError):
        pass

    # Formats libsndfile can't read (m4a, aac, ...) go through ffmpeg
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("súbor nevie prečítať soundfile a ffmpeg/ffprobe nie je nainštalovaný")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    sr, channels = int(stream["sample_rate"]), int(stream["channels"])
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    data = np.frombuffer(pcm, dtype=np.float32).reshape(-1, channels)
    return data, sr


def to_db(value):
    return float(20 * np.log10(value)) if value > 0 else float("-inf")


def true_peak(data, chunk=1 << 20, pad=64):
    """Max inter-sample peak via 4x polyphase oversampling, processed in chunks to bound memory."""
    peak = 0.0
    n = len(data)
    for ch in range(data.shape[1]):
        x = data[:, ch]
        for start in range(0, n, chunk):
            lo, hi = max(0, start - pad), min(n, start + chunk + pad)
            up = resample_poly(x[lo:hi], TRUE_PEAK_OVERSAMPLE, 1)
            # Drop the padded edges: zero-padding there causes ringing that isn't in the signal
            core = up[(start - lo) * TRUE_PEAK_OVERSAMPLE:(min(n, start + chunk) - lo) * TRUE_PEAK_OVERSAMPLE]
            peak = max(peak, float(np.max(np.abs(core))))
    return peak


def clipping_events(data, sr):
    """Find runs of CLIP_MIN_RUN+ consecutive samples at or above CLIP_LEVEL on any channel."""
    hot = np.any(np.abs(data) >= CLIP_LEVEL, axis=1).astype(np.int8)
    edges = np.diff(np.concatenate(([0], hot, [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    lengths = ends - starts
    keep = lengths >= CLIP_MIN_RUN
    return {
        "samples_at_full_scale": int(hot.sum()),
        "events": int(keep.sum()),
        "first_events_sec": [round(float(s) / sr, 3) for s in starts[keep][:10]],
    }


def refine_bpm(env, fps, coarse_bpm, span=0.05, step=0.02):
    """librosa's tempo estimate is quantized to tempogram bins (e.g. 117.45 instead of 120).
    Search a fine BPM grid around it for the pulse train that best lines up with the onsets.
    Returns (bpm, offset of the first beat-grid line in seconds)."""
    frames = np.arange(len(env))
    best_score, best_bpm, best_phase = -1.0, coarse_bpm, 0.0
    for bpm in np.arange(coarse_bpm * (1 - span), coarse_bpm * (1 + span), step):
        period = 60 / bpm * fps
        beats = np.arange(int((len(env) - period) // period)) * period
        if len(beats) < 4:
            continue
        phases = np.arange(0, period)
        scores = np.interp(phases[:, None] + beats[None, :], frames, env).mean(axis=1)
        i = int(scores.argmax())
        if scores[i] > best_score:
            best_score, best_bpm, best_phase = scores[i], bpm, phases[i]
    return float(best_bpm), float(best_phase / fps)


def detect_tempo(y, sr):
    hop = 128  # ~6 ms onset frames for a finer grid than librosa's default 23 ms
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    coarse = float(librosa.feature.tempo(onset_envelope=env, sr=sr, hop_length=hop)[0])
    bpm, offset = refine_bpm(env, sr / hop, coarse)
    # Produced music is almost always at a whole BPM
    if abs(bpm - round(bpm)) < 0.3:
        bpm = float(round(bpm))
    return {
        "bpm": round(bpm, 2),
        "half_time_bpm": round(bpm / 2, 2),
        "double_time_bpm": round(bpm * 2, 2),
        "first_beat_sec": round(offset, 3),
    }


def detect_key(y, sr):
    harmonic = librosa.effects.harmonic(y)
    chroma = librosa.feature.chroma_cqt(y=harmonic, sr=sr).mean(axis=1)
    candidates = []
    for tonic in range(12):
        for mode, profile, names in (("major", MAJOR_PROFILE, MAJOR_NAMES),
                                     ("minor", MINOR_PROFILE, MINOR_NAMES)):
            score = float(np.corrcoef(chroma, np.roll(profile, tonic))[0, 1])
            candidates.append((score, names[tonic], mode))
    candidates.sort(reverse=True)
    best_score, tonic, mode = candidates[0]
    # Relative major/minor share all seven notes, so the profiles often confuse them
    index = (MAJOR_NAMES if mode == "major" else MINOR_NAMES).index(tonic)
    if mode == "major":
        relative = f"{MINOR_NAMES[(index + 9) % 12]} minor"
    else:
        relative = f"{MAJOR_NAMES[(index + 3) % 12]} major"
    return {
        "key": f"{tonic} {mode}",
        "strudel_scale": f"{tonic}:{mode}",
        "relative_key": relative,
        "confidence": round(best_score, 3),
        "alternatives": [
            {"key": f"{t} {m}", "confidence": round(s, 3)} for s, t, m in candidates[1:4]
        ],
    }


def analyze(path, target_lufs, max_true_peak):
    data, sr = load_audio(path)
    duration = len(data) / sr
    if duration < 1 or not np.any(data):
        raise RuntimeError("súbor je prázdny, tichý alebo kratší ako 1 s")

    meter = pyloudnorm.Meter(sr)
    lufs = float(meter.integrated_loudness(data))
    sample_peak = float(np.max(np.abs(data)))
    tp = true_peak(data)
    tp_db = to_db(tp)

    mono = librosa.resample(data.mean(axis=1), orig_sr=sr, target_sr=ANALYSIS_SR)
    tempo = detect_tempo(mono, ANALYSIS_SR)
    key = detect_key(mono, ANALYSIS_SR)
    bars = duration * tempo["bpm"] / 60 / 4

    clipping = clipping_events(data, sr)
    problems, warnings = [], []
    if clipping["events"]:
        problems.append(f"clipping: {clipping['events']} udalostí (prvé v {clipping['first_events_sec']} s)")
    if tp_db > max_true_peak:
        problems.append(f"true peak {tp_db:.2f} dBTP je nad limitom {max_true_peak} dBTP")
    gain_to_target = None
    if target_lufs is not None and np.isfinite(lufs):
        gain_to_target = round(target_lufs - lufs, 2)
        if abs(gain_to_target) > 1.0:
            warnings.append(f"hlasitosť {lufs:.1f} LUFS je mimo cieľa {target_lufs} LUFS (zmeň gain o {gain_to_target:+.1f} dB)")
        if tp_db + gain_to_target > max_true_peak:
            warnings.append("po dorovnaní na cieľovú hlasitosť by true peak prekročil limit: treba limiter")

    return {
        "file": str(path),
        "analyzed_on": date.today().isoformat(),
        "duration_sec": round(duration, 2),
        "sample_rate": sr,
        "channels": int(data.shape[1]),
        "tempo": tempo,
        "key": key,
        "loudness": {
            "integrated_lufs": round(lufs, 2) if np.isfinite(lufs) else None,
            "sample_peak_dbfs": round(to_db(sample_peak), 2),
            "true_peak_dbtp": round(tp_db, 2),
            "peak_to_loudness_ratio_db": round(tp_db - lufs, 2) if np.isfinite(lufs) else None,
            "target_lufs": target_lufs,
            "gain_to_target_db": gain_to_target,
        },
        "clipping": clipping,
        "strudel": {
            "setcpm": f"setcpm({tempo['bpm']:g}/4)",
            "scale": key["strudel_scale"],
            "bars": round(bars, 1),
        },
        "problems": problems,
        "warnings": warnings,
    }


def print_report(r):
    t, k, l = r["tempo"], r["key"], r["loudness"]
    alts = ", ".join(f"{a['key']} ({a['confidence']})" for a in k["alternatives"])
    print(f"🎧 {r['file']}")
    print(f"   Dĺžka:      {r['duration_sec']} s, {r['sample_rate']} Hz, {r['channels']} kanál(y)")
    print(f"   Tempo:      {t['bpm']} BPM (polovičné {t['half_time_bpm']}, dvojnásobné {t['double_time_bpm']}), prvý beat {t['first_beat_sec']} s")
    print(f"   Tónina:     {k['key']} (istota {k['confidence']}; ďalšie: {alts})")
    print(f"               relatívna {k['relative_key']} má rovnaké tóny; ktorá je domov, rozhodne basa a ucho")
    print(f"   Hlasitosť:  {l['integrated_lufs']} LUFS integrated")
    print(f"   Špičky:     sample peak {l['sample_peak_dbfs']} dBFS, true peak {l['true_peak_dbtp']} dBTP, PLR {l['peak_to_loudness_ratio_db']} dB")
    print(f"   Clipping:   {r['clipping']['events']} udalostí, {r['clipping']['samples_at_full_scale']} vzoriek na plnej úrovni")
    print(f"   Strudel:    {r['strudel']['setcpm']}  .scale(\"{r['strudel']['scale']}\")  ~{r['strudel']['bars']} taktov")
    for w in r["warnings"]:
        print(f"⚠️  {w}")
    for p in r["problems"]:
        print(f"❌ {p}")
    if not r["problems"]:
        print("✅ Bez clippingu, true peak v limite.")


def main():
    parser = argparse.ArgumentParser(description="BPM, tónina, LUFS, true peak a clipping pre audio súbor.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--json", type=Path, help="uložiť report ako JSON (napr. analysis/<skladba>.json)")
    parser.add_argument("--target-lufs", type=float, help="cieľová integrovaná hlasitosť, napr. -14")
    parser.add_argument("--max-true-peak", type=float, default=-1.0, help="limit true peak v dBTP (predvolene -1.0)")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"❌ Súbor neexistuje: {args.file}", file=sys.stderr)
        return 1
    try:
        report = analyze(args.file, args.target_lufs, args.max_true_peak)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as e:
        print(f"❌ Nepodarilo sa analyzovať {args.file}: {e}", file=sys.stderr)
        return 1

    print_report(report)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"💾 Report uložený: {args.json}")
    return 2 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
