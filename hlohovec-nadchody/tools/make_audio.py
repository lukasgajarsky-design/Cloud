"""Synthesize a soundtrack for a rendered video from the per-frame metadata.

usage: make_audio.py FRAMES_DIR FPS DURATION OUT.wav [--fpv]
Layers: city ambience, traffic swells (from real vehicle distances / stereo pan per frame),
footsteps on pavement or the wooden deck (first-person videos), birds and a soft music bed.
"""
import glob, json, sys
import numpy as np
from scipy import signal
from scipy.io import wavfile

frames_dir, fps, dur, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
fpv = "--fpv" in sys.argv
SR = 48000
N = int(dur * SR)
rng = np.random.default_rng(11)

meta = {}
for f in glob.glob(f"{frames_dir}/meta_*.json"):
    meta.update({int(k): v for k, v in json.load(open(f)).items()})
nf = int(round(dur * fps))
t_frames = np.arange(nf) / fps


def bp(x, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def lp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="high", fs=SR, output="sos"), x)


def pink(n):
    w = rng.standard_normal(n)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    return signal.lfilter(b, a, w)


def env_to_audio(env, smooth_ms=60):
    e = np.interp(np.arange(N) / SR, t_frames[: len(env)], env)
    k = int(SR * smooth_ms / 1000)
    return np.convolve(e, np.ones(k) / k, mode="same")


L = np.zeros(N)
R = np.zeros(N)

# ---- city ambience
amb = lp(pink(N), 500) * 0.05
amb2 = lp(pink(N), 500) * 0.05
mod = 0.8 + 0.2 * np.sin(2 * np.pi * np.arange(N) / SR / 7.3)
L += amb * mod
R += amb2 * mod

# ---- traffic (envelopes from vehicle distances)
gl = np.zeros(nf)
gr = np.zeros(nf)
for i in range(nf):
    for c in meta.get(i, {}).get("cars", []):
        d, bus, pan = c[0], c[1], (c[2] if len(c) > 2 else 0.0)
        g = (1.7 if bus else 1.0) / (1 + (d / 6.5) ** 2)
        gl[i] += g * (0.5 - 0.32 * pan)
        gr[i] += g * (0.5 + 0.32 * pan)
tyre_l, tyre_r = bp(rng.standard_normal(N), 180, 1600), bp(rng.standard_normal(N), 180, 1600)
rumble_l, rumble_r = lp(rng.standard_normal(N), 110) * 2.2, lp(rng.standard_normal(N), 110) * 2.2
el, er = env_to_audio(gl), env_to_audio(gr)
L += np.tanh((tyre_l + rumble_l) * el * 0.9) * 0.55
R += np.tanh((tyre_r + rumble_r) * er * 0.9) * 0.55

# ---- footsteps
if fpv:
    ph = np.array([meta.get(i, {}).get("phase", 0) for i in range(nf)])
    deck = np.array([meta.get(i, {}).get("onDeck", False) for i in range(nf)])
    for i in range(1, nf):
        a, b = ph[i - 1], ph[i]
        k = np.floor(a)
        while k + 1 <= b:
            k += 1
            f = (k - a) / max(b - a, 1e-6)
            t = (i - 1 + f) / fps
            s0 = int(t * SR)
            n = int(0.16 * SR)
            if s0 + n >= N:
                break
            tt = np.arange(n) / SR
            if deck[i]:
                body = (np.sin(2 * np.pi * 170 * tt) * 0.8 + np.sin(2 * np.pi * 410 * tt) * 0.35) * np.exp(-tt / 0.045)
                click = bp(rng.standard_normal(n), 500, 2500) * np.exp(-tt / 0.012)
                snd = (body * 0.22 + click * 0.5) * (0.8 + 0.25 * rng.random())
            else:
                scuff = bp(rng.standard_normal(n), 900, 4200) * np.exp(-tt / 0.022)
                thud = np.sin(2 * np.pi * 85 * tt) * np.exp(-tt / 0.025)
                snd = (scuff * 0.42 + thud * 0.18) * (0.75 + 0.3 * rng.random())
            side = 1 if int(k) % 2 else -1
            L[s0:s0 + n] += snd * (1 - 0.15 * side)
            R[s0:s0 + n] += snd * (1 + 0.15 * side)

# ---- birds
t = 1.0
while t < dur - 1:
    n = int(0.09 * SR)
    s0 = int(t * SR)
    for rep in range(rng.integers(2, 5)):
        tt = np.arange(n) / SR
        f0 = rng.uniform(2800, 4800)
        sweep = f0 * (1 + 0.35 * np.sin(np.pi * tt / tt[-1]))
        chirp = np.sin(2 * np.pi * np.cumsum(sweep) / SR) * np.sin(np.pi * tt / tt[-1]) ** 2 * 0.035
        pan = rng.uniform(-0.8, 0.8)
        a = s0 + rep * int(0.13 * SR)
        if a + n < N:
            L[a:a + n] += chirp * (1 - pan) / 2
            R[a:a + n] += chirp * (1 + pan) / 2
    t += rng.uniform(2.5, 7.0) if fpv else rng.uniform(5, 11)

# ---- soft music bed (D - Bm - G - A, slow pad + sparse plucks)
chords = [[62, 66, 69, 74], [59, 62, 66, 71], [55, 59, 62, 67], [57, 61, 64, 69]]
bar = 4.0
tt = np.arange(N) / SR
pad = np.zeros(N)
for ci in range(int(dur / bar) + 1):
    notes = chords[ci % 4]
    s0, s1 = int(ci * bar * SR), int(min(N, (ci + 1.15) * bar * SR))
    if s0 >= N:
        break
    seg = tt[s0:s1] - ci * bar
    envp = np.minimum(1, seg / 1.2) * np.minimum(1, np.maximum(0, (bar * 1.15 - seg) / 1.0))
    for m in notes:
        f = 440 * 2 ** ((m - 69) / 12)
        pad[s0:s1] += (np.sin(2 * np.pi * f * seg) + 0.5 * np.sin(2 * np.pi * f * 1.003 * seg + 1.3) + 0.25 * np.sin(2 * np.pi * 2 * f * seg)) * envp
    # plucks on beats 1 and 3
    for beat in (0, 2):
        m = notes[(ci + beat) % 4] + 12
        f = 440 * 2 ** ((m - 69) / 12)
        p0 = int((ci * bar + beat) * SR)
        n = int(1.5 * SR)
        if p0 + n < N:
            q = np.arange(n) / SR
            pad[p0:p0 + n] += np.sin(2 * np.pi * f * q) * np.exp(-q / 0.45) * 1.6
pad = lp(pad, 2200) * 0.018
fade = np.minimum(1, tt / 2.5) * np.minimum(1, np.maximum(0, (dur - tt) / 3.0))
L += pad * fade
R += pad * fade

# ---- master
mix = np.stack([L, R], 1)
mix = hp(mix.T, 30).T
mix *= np.minimum(1, np.arange(N)[:, None] / (0.4 * SR))
mix *= np.minimum(1, (N - np.arange(N))[:, None] / (1.5 * SR))
peak = np.max(np.abs(mix))
mix = mix / peak * 0.89
wavfile.write(out, SR, (mix * 32767).astype(np.int16))
print("wrote", out, f"{dur:.1f}s", "frames with meta:", len(meta))
