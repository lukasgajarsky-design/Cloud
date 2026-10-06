#!/usr/bin/env python3
"""Build the Rituál kontroly animatic from shots.py.

Every shot is a generated still (frames/*.png, made by gen_images.py) with a slow camera move,
the screenplay text on screen and a synthesized sound track: room tones per scene plus foley
(CVAK, steps, keys, heartbeat...) placed at the cues in shots.py. Scene 7 cuts in the Veo clip.

    pip install torch diffusers transformers accelerate numpy scipy pillow   # plus ffmpeg on PATH
    python3 gen_images.py   # once, ~20 min on CPU
    python3 build.py        # ~10 min, writes ../ritual_kontroly_animatik.mp4 (about 19 minutes long)
"""

import subprocess
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from scipy.io import wavfile
from scipy.signal import butter, oaconvolve, sosfilt

from shots import SHOTS, VEO_CLIP, Shot

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "frames"
WORK = HERE / "build"
OUTPUT = HERE.parent / "ritual_kontroly_animatik.mp4"
W, H, FPS, SR = 1280, 720, 25, 48000
BASE_W, BASE_H = 1536, 864  # stills are upscaled to this so the camera can move inside them
CARDS = ("heading", "title")

LIB = Path("/usr/share/fonts/truetype/liberation")
DEJAVU = Path("/usr/share/fonts/truetype/dejavu")
FONT_FILES = {
    "sans": LIB / "LiberationSans-Regular.ttf",
    "sans_i": LIB / "LiberationSans-Italic.ttf",
    "sans_b": LIB / "LiberationSans-Bold.ttf",
    "serif_b": LIB / "LiberationSerif-Bold.ttf",
    "mono": DEJAVU / "DejaVuSansMono.ttf",
    "mono_b": DEJAVU / "DejaVuSansMono-Bold.ttf",
}


# --- Timeline -------------------------------------------------------------------------------------

def shot_frames(shot: Shot) -> int:
    if shot.dur:
        seconds = shot.dur
    elif shot.img == VEO_CLIP:
        seconds = 8.0  # 4 s clip at half speed
    elif not shot.text:
        seconds = 3.5
    else:
        seconds = max(3.0, 1.6 + (len(shot.text) + len(shot.who)) / 13)
    return round(seconds * FPS)


def timeline() -> list[dict]:
    """Resolve durations, start frames, inherited beds and camera moves."""
    plan, start, bed = [], 0, "black"
    for i, shot in enumerate(SHOTS):
        bed = shot.bed or bed
        move = shot.move or ("in", "out", "left", "right")[zlib.crc32(f"{i}{shot.img}".encode()) % 4]
        n = shot_frames(shot)
        plan.append({"shot": shot, "start": start, "frames": n, "bed": bed, "move": move})
        start += n
    for i, item in enumerate(plan):
        prev = plan[i - 1]["shot"] if i else None
        nxt = plan[i + 1]["shot"] if i + 1 < len(plan) else None
        item["fade_in"] = prev is None or prev.kind in CARDS or prev.img is None
        item["fade_out"] = nxt is None or nxt.kind == "heading"
    return plan


# --- Pictures -------------------------------------------------------------------------------------

def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_FILES[name]), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=fnt) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def spaced(draw, xy_center, text, fnt, fill, spacing, stroke=0):
    """Draw letter-spaced text centred on xy_center."""
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    x = xy_center[0] - (sum(widths) + spacing * (len(text) - 1)) / 2
    for ch, w in zip(text, widths):
        draw.text((x, xy_center[1]), ch, font=fnt, fill=fill, anchor="lm", stroke_width=stroke, stroke_fill=(0, 0, 0))
        x += w + spacing


def text_layer(shot: Shot) -> Image.Image | None:
    if not shot.text and not shot.clock:
        return None
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    if shot.clock:
        clock_font = font("mono", 26)
        box = draw.textbbox((44, 36), shot.clock, font=clock_font)
        draw.rounded_rectangle((box[0] - 12, box[1] - 8, box[2] + 12, box[3] + 8), 6, fill=(0, 0, 0, 140))
        draw.text((44, 36), shot.clock, font=clock_font, fill=(255, 190, 90, 255))

    if shot.kind == "title":
        first, *rest = shot.text.split("\n")
        spaced(draw, (W / 2, H / 2 - 30), first, font("serif_b", 76), (240, 236, 225, 255), 10)
        for n, extra in enumerate(rest):
            draw.text((W / 2, H / 2 + 50 + n * 40), extra, font=font("sans", 28), fill=(190, 185, 170, 255), anchor="mm")
    elif shot.kind == "heading":
        fnt = font("mono_b", 36)
        lines = wrap(draw, shot.text, fnt, 1080)
        for n, text in enumerate(lines):
            y = H / 2 + (n - (len(lines) - 1) / 2) * 48
            draw.text((W / 2, y), text, font=fnt, fill=(235, 235, 235, 255), anchor="mm")
    elif shot.kind == "sound":
        spaced(draw, (W / 2, H * 0.46), shot.text, font("serif_b", 104), (250, 248, 240, 235), 12, stroke=3)
    elif shot.text and shot.img is None:
        fnt = font("sans", 26)
        for n, text in enumerate(wrap(draw, shot.text, fnt, 1000)):
            draw.text((W / 2, H / 2 + n * 38), text, font=fnt, fill=(170, 170, 170, 255), anchor="mm")
    elif shot.text:
        if shot.kind == "vo":
            label, label_color, fnt, color = "VNÚTORNÝ HLAS", (160, 185, 210, 255), font("sans_i", 36), (250, 228, 165, 255)
        elif shot.kind == "line":
            label, label_color, fnt, color = shot.who, (235, 180, 95, 255), font("sans", 36), (255, 255, 255, 255)
        else:
            label, label_color, fnt, color = "", None, font("sans", 33), (228, 228, 228, 255)
        lines = wrap(draw, shot.text, fnt, 1080)
        line_h = 46
        top = H - 56 - line_h * len(lines)
        band_top = top - (70 if label else 40)
        for y in range(band_top, H):  # dark gradient under the text
            alpha = int(200 * ((y - band_top) / (H - band_top)) ** 0.8)
            draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
        if label:
            draw.text((W / 2, top - 22), label, font=font("sans_b", 25), fill=label_color, anchor="mm")
        for n, text in enumerate(lines):
            draw.text((W / 2, top + line_h * n + line_h / 2), text, font=fnt, fill=color, anchor="mm",
                      stroke_width=2, stroke_fill=(0, 0, 0, 255))
    return layer


VIGNETTE = None


def load_still(key: str, fx: str) -> Image.Image:
    global VIGNETTE
    im = Image.open(FRAMES / f"{key}.png").convert("RGB").resize((BASE_W, BASE_H), Image.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    if fx == "vivid":
        im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.4)).enhance(1.1)
    elif fx == "blur":
        im = ImageEnhance.Brightness(ImageEnhance.Color(im.filter(ImageFilter.GaussianBlur(10))).enhance(0.2)).enhance(0.75)
    elif fx == "bright":
        im = Image.blend(ImageEnhance.Brightness(im).enhance(1.25), Image.new("RGB", im.size, (255, 250, 235)), 0.12)
    if VIGNETTE is None:
        y, x = np.mgrid[-1:1:BASE_H * 1j, -1:1:BASE_W * 1j]
        VIGNETTE = np.clip(1.08 - 0.42 * (x**2 + y**2) ** 1.2, 0.45, 1.0)[..., None]
    arr = np.asarray(im, dtype=np.float32) * VIGNETTE
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def camera_box(move: str, p: float) -> tuple[float, float, float, float]:
    if move == "in":
        zoom, cx = 1.0 + 0.09 * p, 0.5
    elif move == "out":
        zoom, cx = 1.09 - 0.09 * p, 0.5
    elif move == "left":
        zoom, cx = 1.1, 0.5 + 0.035 * (1 - 2 * p)
    elif move == "right":
        zoom, cx = 1.1, 0.5 - 0.035 * (1 - 2 * p)
    else:
        zoom, cx = 1.03 + 0.012 * p, 0.5
    w, h = BASE_W / zoom, BASE_H / zoom
    x0 = min(max(cx * BASE_W - w / 2, 0), BASE_W - w)
    y0 = (BASE_H - h) / 2
    return (x0, y0, x0 + w, y0 + h)


def clip_frames(n: int) -> list[Image.Image]:
    """The Veo clip at half speed, motion-interpolated to FPS."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(HERE.parent / VEO_CLIP), "-vf",
           f"setpts=2.0*PTS,minterpolate=fps={FPS}:mi_mode=mci,scale={W}:{H}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    frames = [Image.frombytes("RGB", (W, H), raw[i:i + W * H * 3]) for i in range(0, len(raw), W * H * 3)]
    return (frames + frames[-1:] * n)[:n]


def ramp(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def render_segment(args) -> str:
    index, items = args
    path = WORK / f"seg_{index:03d}.mp4"
    encoder = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-vf", "noise=alls=4:allf=t", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
         "-pix_fmt", "yuv420p", "-g", "50", str(path)],
        stdin=subprocess.PIPE,
    )
    black = Image.new("RGB", (W, H))
    stills = {}
    for item in items:
        shot, n = item["shot"], item["frames"]
        seconds = n / FPS
        layer = text_layer(shot)
        if shot.img == VEO_CLIP:
            clip = clip_frames(n)
        elif shot.img:
            key = (shot.img, shot.fx)
            if key not in stills:
                stills[key] = load_still(*key)
            still = stills[key]
        text_from = shot.sfx[0][0] if shot.kind == "sound" and shot.sfx else 0.0
        for f in range(n):
            t = f / FPS
            if shot.img == VEO_CLIP:
                frame = clip[f]
            elif shot.img:
                frame = still.resize((W, H), Image.BICUBIC, box=camera_box(item["move"], f / max(n - 1, 1)))
            else:
                frame = black
            fade = 1.0
            if shot.img and item["fade_in"]:
                fade *= ramp(t / 0.5)
            if shot.img and item["fade_out"]:
                fade *= ramp((seconds - t) / 0.4)
            if fade < 1:
                frame = Image.blend(black, frame, fade)
            if layer is not None:
                if shot.kind in CARDS:
                    alpha = ramp(t / (1.0 if shot.kind == "title" else 0.5)) * ramp((seconds - t) / 0.5)
                elif shot.kind == "sound":
                    alpha = (1.0 if t >= text_from else 0.0) * ramp((seconds - t) / 0.4)
                else:
                    alpha = ramp(t / 0.25) * ramp((seconds - t) / 0.25)
                if shot.img is None and shot.kind == "action":
                    alpha = ramp(t / 0.6) * ramp((seconds - t) / 0.6)
                if alpha > 0:
                    composed = Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")
                    frame = composed if alpha >= 1 else Image.blend(frame, composed, alpha)
            encoder.stdin.write(frame.tobytes())
    encoder.stdin.close()
    if encoder.wait():
        raise RuntimeError(f"ffmpeg failed on segment {index}")
    return str(path)


# --- Sound ----------------------------------------------------------------------------------------

rng = np.random.default_rng(7)


def sec(t: float) -> int:
    return int(round(t * SR))


def tvec(d: float) -> np.ndarray:
    return np.arange(sec(d)) / SR


def noise(d: float) -> np.ndarray:
    return rng.standard_normal(sec(d))


def filt(x: np.ndarray, kind: str, f, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, f, btype=kind, fs=SR, output="sos"), x)


def decay(d: float, tau: float) -> np.ndarray:
    return np.exp(-tvec(d) / tau)


def ring(freqs, taus, amps, d: float) -> np.ndarray:
    t = tvec(d)
    out = np.zeros_like(t)
    for f, tau, a in zip(freqs, taus, amps):
        out += a * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) * np.exp(-t / tau)
    return out


def burst(d: float, lo: float, hi: float, tau: float) -> np.ndarray:
    return filt(noise(d), "band", [lo, hi]) * decay(d, tau)


def norm(x: np.ndarray, peak: float) -> np.ndarray:
    m = np.max(np.abs(x))
    return x / m * peak if m else x


def mix(length: float, *parts) -> np.ndarray:
    """parts: (signal, offset_seconds)."""
    out = np.zeros(sec(length))
    for sig, at in parts:
        i = sec(at)
        n = min(len(sig), len(out) - i)
        out[i:i + n] += sig[:n]
    return out


def stick_slip(d: float, f0: float, f1: float, lo: float, hi: float) -> np.ndarray:
    """Creak: a train of tiny clicks whose rate glides from f0 to f1 Hz."""
    t = tvec(d)
    phase = np.cumsum(f0 + (f1 - f0) * t / d) / SR
    pulses = (np.diff(np.floor(phase), prepend=0) > 0) * (0.5 + 0.5 * rng.random(len(t)))
    return filt(pulses, "band", [lo, hi]) * np.sin(np.pi * t / d) ** 0.7


def echo(x: np.ndarray, taps=((0.037, 0.3), (0.071, 0.2), (0.113, 0.12))) -> np.ndarray:
    return mix(len(x) / SR + 0.15, (x, 0), *[(x * g, d) for d, g in taps])


def fx_cvak():
    clack = burst(0.15, 1200, 6500, 0.010) + 0.8 * ring([2350, 3720, 5180], [0.05, 0.035, 0.02], [0.5, 0.3, 0.2], 0.15)
    clack += 0.6 * ring([170, 260], [0.035, 0.025], [1.0, 0.5], 0.15)
    return norm(mix(0.35, (0.35 * burst(0.03, 2500, 9000, 0.003), 0), (clack, 0.06)), 0.9)


def fx_cvak_far():
    return norm(echo(filt(fx_cvak(), "low", 1800)), 0.32)


def fx_handle():
    t = tvec(0.25)
    squeak = 0.15 * np.sin(2 * np.pi * np.cumsum(900 + 500 * t / 0.25) / SR) * np.sin(np.pi * t / 0.25)
    squeak += 0.05 * filt(noise(0.25), "band", [2000, 5000]) * np.sin(np.pi * t / 0.25)
    return norm(mix(0.6, (squeak, 0), (fx_cvak() * 0.9, 0.2)), 0.9)


def fx_handle_slow():
    t = tvec(1.0)
    squeak = np.sin(2 * np.pi * np.cumsum(700 + 300 * t) / SR) * np.sin(np.pi * t) * 0.2
    return norm(squeak + 0.6 * stick_slip(1.0, 40, 70, 800, 3500), 0.4)


def fx_lock_bump():
    return norm(mix(0.25, (ring([140, 320], [0.04, 0.03], [1, 0.5], 0.25), 0), (0.5 * burst(0.05, 300, 3000, 0.005), 0)), 0.75)


def fx_handle_shake():
    rattle = [(burst(0.08, 1500, 7000, 0.006) + ring([1900, 2900], [0.03, 0.02], [0.4, 0.3], 0.08), 0.09 * i)
              for i in range(5)]
    return norm(mix(0.8, *rattle, (fx_lock_bump(), 0.48)), 0.7)


def fx_rattle():
    hits = []
    for i in range(7):
        detune = rng.uniform(0.95, 1.05)
        hit = ring([300 * detune, 520 * detune, 870 * detune, 1290 * detune], [0.25, 0.2, 0.15, 0.1],
                   [1, 0.7, 0.5, 0.3], 0.5) + burst(0.5, 400, 5000, 0.01)
        hits.append((hit * rng.uniform(0.5, 1.0), 0.13 * i + rng.uniform(0, 0.04)))
    return norm(mix(1.6, *hits), 0.95)


def fx_switch():
    return norm(mix(0.1, (burst(0.02, 2000, 9000, 0.002), 0),
                    (burst(0.05, 800, 5000, 0.004) + 0.3 * ring([1400], [0.01], [1], 0.05), 0.012)), 0.6)


def step(strength: float, soft: bool = False):
    sig = mix(0.3, (filt(ring([95, 160], [0.05, 0.03], [1, 0.4], 0.25), "low", 400), 0),
              (0.6 * burst(0.04, 1200, 4000, 0.004), 0.004))
    if soft:
        sig = filt(sig, "low", 900)
    return norm(sig, 0.5 * strength)


def fx_shuffle():
    t = tvec(0.35)
    return norm(filt(noise(0.35), "band", [700, 3500]) * np.sin(np.pi * t / 0.35) ** 2, 0.16)


def fx_keys():
    pings = [(ring([rng.uniform(3000, 8000)], [rng.uniform(0.03, 0.08)], [1], 0.12) + 0.3 * burst(0.12, 3000, 9000, 0.003),
              rng.uniform(0, 0.55)) for _ in range(28)]
    return norm(mix(0.8, *pings), 0.4)


def fx_door_open():
    return norm(mix(1.1, (fx_switch() * 0.6, 0), (stick_slip(0.9, 70, 140, 500, 2500), 0.1)), 0.5)


def fx_door_close():
    thud = filt(noise(0.4), "low", 200) * decay(0.4, 0.05) * 3 + ring([70, 110], [0.12, 0.08], [1, 0.6], 0.4)
    return norm(mix(0.5, (thud, 0), (fx_cvak() * 0.5, 0.02)), 0.85)


def fx_chair():
    return norm(stick_slip(0.4, 180, 320, 700, 3000), 0.3)


def fx_sigh():
    t = tvec(1.6)
    env = np.minimum(t / 0.25, 1) * np.exp(-np.maximum(t - 0.25, 0) / 0.45)
    return norm(filt(noise(1.6), "band", [300, 2000]) * env, 0.18)


def fx_breath():
    t_in, t_out = tvec(1.8), tvec(2.4)
    inhale = filt(noise(1.8), "band", [600, 4000]) * (t_in / 1.8) ** 1.5
    exhale = filt(noise(2.4), "band", [300, 2200]) * np.exp(-t_out / 0.8)
    return norm(np.concatenate([inhale, exhale]), 0.28)


def fx_page():
    gate = filt((rng.random(sec(0.35)) > 0.6).astype(float), "low", 60)
    return norm(filt(noise(0.35), "high", 1500) * gate * np.sin(np.pi * tvec(0.35) / 0.35), 0.22)


def fx_drawer():
    return norm(mix(0.7, (stick_slip(0.5, 90, 140, 150, 1200) + 0.3 * filt(noise(0.5), "band", [200, 1500]), 0),
                    (ring([120, 240], [0.05, 0.04], [1, 0.5], 0.2), 0.5)), 0.45)


def fx_car_pass():
    d = 5.0
    t = tvec(d)
    freq = 70 - 10 * np.tanh((t - 2.2) * 2)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    tone = sum(np.sin(k * phase) / k for k in range(1, 7))
    body = 0.6 * filt(noise(d), "low", 900) + 0.4 * filt(tone, "low", 800)
    sig = norm(body * np.exp(-(((t - 2.2) / 1.0) ** 2)), 0.45)
    pan = np.clip((t - 2.2) / 2.0, -1, 1)
    return np.stack([sig * np.sqrt((1 - pan) / 2), sig * np.sqrt((1 + pan) / 2)], axis=1)


def engine(d: float, f0: float, f1: float, clatter: float) -> np.ndarray:
    t = tvec(d)
    freq = f0 + (f1 - f0) * t / d
    phase = 2 * np.pi * np.cumsum(freq) / SR
    rumble = sum(np.sin(k * phase) / k for k in range(1, 8))
    pulses = (np.diff(np.floor(np.cumsum(freq / 3) / SR), prepend=0) > 0).astype(float)
    return filt(rumble + clatter * filt(pulses, "band", [150, 1500]) * 6, "low", 900)


def fx_diesel():
    t = tvec(7.0)
    sig = engine(7.0, 44, 34, 0.8)
    env = np.minimum(t / 3.5, 1) ** 1.5 * np.clip((6.2 - t) / 0.2, 0, 1)
    return norm(mix(7.5, (sig * env, 0), (fx_door_close() * 0.35, 6.7)), 0.55)


def fx_car_leave():
    t = tvec(4.5)
    return norm(engine(4.5, 38, 70, 0.6) * np.clip((4.5 - t) / 3.5, 0, 1), 0.5)


def fx_pour():
    glugs = []
    at = 0.0
    while at < 1.1:
        f0 = rng.uniform(500, 1000)
        tt = tvec(0.05)
        glugs.append((np.sin(2 * np.pi * np.cumsum(f0 * (1 - 0.3 * tt / 0.05)) / SR) * np.exp(-tt / 0.02), at))
        at += rng.uniform(0.06, 0.11)
    splash = filt(noise(1.3), "band", [1500, 6000]) * 0.15 * np.sin(np.pi * tvec(1.3) / 1.3)
    return norm(mix(1.4, *glugs, (splash, 0)), 0.38)


def fx_glass_table():
    return norm(ring([2600, 4100, 5900], [0.25, 0.15, 0.08], [1, 0.6, 0.3], 0.6)
                + 0.6 * np.pad(ring([180], [0.02], [1], 0.1), (0, sec(0.5))), 0.6)


def fx_cabinet():
    return norm(mix(0.6, (0.5 * stick_slip(0.3, 120, 200, 400, 2000), 0),
                    (ring([120, 240], [0.05, 0.04], [1, 0.5], 0.25) + 0.4 * burst(0.25, 1000, 6000, 0.004), 0.32)), 0.5)


def fx_tap():
    flutter = 0.6 + 0.4 * filt(rng.standard_normal(sec(2.2)), "low", 8) * 4
    return norm(filt(noise(2.2), "band", [800, 6000]) * flutter * np.sin(np.pi * tvec(2.2) / 2.2) ** 0.3, 0.28)


def fx_tick():
    return norm(burst(0.04, 2500, 9000, 0.0015) + 0.5 * ring([1800], [0.008], [1], 0.04), 0.45)


def fx_spoon():
    return norm(ring([3200, 5400, 7600], [0.3, 0.18, 0.1], [1, 0.6, 0.3], 0.7), 0.42)


def fx_floor_creak():
    return norm(stick_slip(0.9, 35, 70, 200, 1200), 0.4)


def fx_stair_creak():
    return norm(stick_slip(0.6, 60, 110, 300, 1800), 0.45)


def fx_bin():
    return norm(ring([180, 420], [0.06, 0.04], [1, 0.5], 0.3) + ring([2900, 4700], [0.12, 0.08], [0.4, 0.3], 0.3), 0.5)


def fx_heartbeat():
    beat = mix(0.6, (ring([48, 70], [0.07, 0.05], [1, 0.5], 0.25), 0), (ring([58, 84], [0.05, 0.04], [0.8, 0.4], 0.2), 0.28))
    return norm(filt(beat, "low", 160), 0.8)


def fx_flicker():
    t = tvec(0.12)
    buzz = sum(np.sin(2 * np.pi * 100 * k * t) / k for k in range(1, 12)) * np.exp(-t / 0.05)
    return norm(mix(0.2, (burst(0.03, 3000, 9000, 0.002), 0), (0.4 * buzz, 0.02)), 0.3)


def fx_key_turn():
    clicks = [(burst(0.03, 2000, 8000, 0.002), at) for at in (0, 0.05, 0.11)]
    return norm(mix(0.5, *clicks, (fx_cvak() * 0.5, 0.18)), 0.6)


def fx_window_open():
    return norm(mix(0.9, (0.6 * stick_slip(0.4, 300, 500, 1000, 4000), 0), (ring([150, 300], [0.04, 0.03], [1, 0.4], 0.2), 0.4),
                    (filt(noise(0.25), "low", 600) * decay(0.25, 0.08), 0.5)), 0.5)


def fx_hum_hit():
    t = tvec(1.8)
    drone = np.sin(2 * np.pi * 55 * t) + 0.5 * np.sin(2 * np.pi * 110 * t) + 0.3 * np.sin(2 * np.pi * 165 * t)
    return norm((drone + 0.5 * filt(noise(1.8), "low", 300)) * np.minimum(t / 0.02, 1) * np.exp(-t / 0.7), 0.55)


EFFECTS = {
    "cvak": fx_cvak, "cvak_far": fx_cvak_far, "handle": fx_handle, "handle_slow": fx_handle_slow,
    "lock_bump": fx_lock_bump, "handle_shake": fx_handle_shake, "rattle": fx_rattle, "switch": fx_switch,
    "step_r": lambda: step(1.0), "step_l": lambda: step(0.7), "step_soft": lambda: step(0.4, soft=True),
    "shuffle": fx_shuffle, "keys": fx_keys, "door_open": fx_door_open, "door_close": fx_door_close, "chair": fx_chair,
    "sigh": fx_sigh, "breath": fx_breath, "page": fx_page, "drawer": fx_drawer, "car_pass": fx_car_pass,
    "diesel": fx_diesel, "car_leave": fx_car_leave, "pour": fx_pour, "glass_table": fx_glass_table,
    "cabinet": fx_cabinet, "tap": fx_tap, "tick": fx_tick, "spoon": fx_spoon, "floor_creak": fx_floor_creak,
    "stair_creak": fx_stair_creak, "bin": fx_bin, "heartbeat": fx_heartbeat, "flicker": fx_flicker,
    "key_turn": fx_key_turn, "window_open": fx_window_open, "hum_hit": fx_hum_hit,
}


def lfo_noise(n: int, rate: float) -> np.ndarray:
    """Slow random wobble in [-1, 1]."""
    x = filt(rng.standard_normal(n), "low", rate)
    return x / (np.max(np.abs(x)) or 1)


def bed_buzz(n):
    t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * 100 * k * t) / k for k in range(1, 14)) + 0.3 * np.sin(2 * np.pi * 50 * t)
    return filt(x, "band", [90, 4000]) * (1 + 0.08 * lfo_noise(n, 3)) * 0.022


def bed_hum(n):
    t = np.arange(n) / SR
    x = 0.6 * np.sin(2 * np.pi * 55 * t) + 0.6 * np.sin(2 * np.pi * 55.7 * t) + 0.3 * np.sin(2 * np.pi * 110.3 * t)
    x += 0.15 * np.sin(2 * np.pi * 165.5 * t) + 0.1 * np.sin(2 * np.pi * 220.4 * t)
    x += 0.8 * filt(rng.standard_normal(n), "low", 180)
    return x * (0.8 + 0.2 * np.sin(2 * np.pi * 0.07 * t)) * 0.03


def bed_room(n):
    return filt(rng.standard_normal(n), "low", 500) * 0.007


def bed_ticks(n):
    out = np.zeros(n)
    for i, at in enumerate(np.arange(0.5, n / SR - 0.1, 1.0)):
        tick = ring([2400 if i % 2 else 2000], [0.008], [1], 0.05) + 0.3 * burst(0.05, 3000, 8000, 0.001)
        j = sec(at)
        out[j:j + len(tick)] += norm(tick, 0.035)[: n - j]
    return out


def bed_fridge(n):
    t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * 50 * k * t) / k for k in range(1, 5)) + 0.5 * filt(rng.standard_normal(n), "low", 300)
    return x * 0.008


def bed_wind(n):
    return filt(rng.standard_normal(n), "band", [150, 900]) * (0.6 + 0.4 * lfo_noise(n, 0.3)) * 0.08


def bed_birds(n):
    out = np.zeros(n)
    for at in np.sort(rng.uniform(0, n / SR, int(n / SR * 0.7))):
        for k in range(rng.integers(2, 5)):
            d = rng.uniform(0.06, 0.15)
            tt = tvec(d)
            f0, f1 = rng.uniform(3000, 4500), rng.uniform(-800, 800)
            chirp = np.sin(2 * np.pi * np.cumsum(f0 + f1 * tt / d) / SR) * np.sin(np.pi * tt / d)
            j = sec(at + k * 0.18)
            if j < n:
                out[j:j + len(chirp)] += chirp[: n - j] * 0.03
    return out


def bed_traffic(n):
    return filt(rng.standard_normal(n), "low", 250) * (0.6 + 0.4 * lfo_noise(n, 0.2)) * 0.06


def bed_engine(n):
    return engine(n / SR, 38, 38, 0.5) * 0.02


def bed_computer(n):
    t = np.arange(n) / SR
    return filt(rng.standard_normal(n), "band", [200, 2000]) * 0.004 + 0.003 * np.sin(2 * np.pi * 120 * t)


def bed_heart(n, bpm0, bpm1, gain):
    out = np.zeros(n)
    at = 0.2
    while at < n / SR - 0.6:
        beat = fx_heartbeat() * gain
        j = sec(at)
        out[j:j + len(beat)] += beat[: n - j]
        at += 60 / (bpm0 + (bpm1 - bpm0) * at / (n / SR))
    return out


def ramp_env(n, a, b):
    return np.linspace(a, b, n)


BEDS = {
    "hum": lambda n: bed_hum(n),
    "office": lambda n: bed_buzz(n) + bed_hum(n) * 0.8 + bed_room(n),
    "office_evening": lambda n: bed_buzz(n) * 0.5 + bed_hum(n) + bed_room(n),
    "office_night": lambda n: bed_computer(n) + bed_hum(n) * 0.8 + bed_room(n),
    "gate": lambda n: bed_wind(n) + bed_traffic(n),
    "muffled": lambda n: filt(bed_room(n) * 3 + bed_buzz(n), "low", 300) * 0.6,
    "pulse": lambda n: bed_hum(n) * 1.4 + bed_heart(n, 80, 132, 0.3) + bed_buzz(n) * ramp_env(n, 1.0, 0.2),
    "silence_day": lambda n: bed_wind(n) * 0.8 + bed_birds(n) + bed_room(n) * 0.5,
    "car": lambda n: bed_engine(n) + bed_hum(n) * 0.6,
    "kitchen": lambda n: bed_fridge(n) + bed_ticks(n) + bed_hum(n) * 0.7 + bed_room(n),
    "kitchen_soft": lambda n: bed_fridge(n) + bed_ticks(n) + bed_hum(n) * 0.35 + bed_room(n),
    "house": lambda n: bed_room(n) + bed_ticks(n) * 0.6 + bed_hum(n) * 0.8,
    "room": lambda n: bed_room(n) + bed_hum(n) * 0.8,
    "heart": lambda n: bed_room(n) + bed_hum(n) + bed_heart(n, 88, 104, 0.3),
    "relief": lambda n: bed_room(n) * 0.7 + bed_hum(n) * np.clip(ramp_env(n, 1.0, -2.0), 0, 1),
    "night": lambda n: bed_room(n) * 0.8,
    "morning": lambda n: bed_fridge(n) + bed_birds(n) * 0.5 + bed_room(n) + bed_hum(n) * 0.45,
    "hallucination": lambda n: bed_buzz(n) * ramp_env(n, 0.0, 2.6) + bed_hum(n) * ramp_env(n, 0.6, 2.3),
    "black_soft": lambda n: bed_room(n) * 0.3 + bed_hum(n) * 0.4,
    "black": lambda n: np.zeros(n),
}


def reverb_ir(seed: int) -> np.ndarray:
    local = np.random.default_rng(seed)
    t = np.arange(sec(0.9)) / SR
    ir = filt(local.standard_normal(len(t)), "low", 4000) * np.exp(-t / 0.22)
    ir[0] = 0
    return ir / np.sqrt(np.sum(ir**2))


def soundtrack(plan: list[dict]) -> np.ndarray:
    total = sec(sum(item["frames"] for item in plan) / FPS)
    beds = np.zeros(total)
    events = np.zeros((total, 2))

    # Beds: one continuous stretch per run of shots sharing a bed, with short fades at the joins.
    runs = []
    for item in plan:
        if runs and runs[-1][0] == item["bed"]:
            runs[-1][2] += item["frames"]
        else:
            runs.append([item["bed"], item["start"], item["frames"]])
    for name, start, frames in runs:
        i, n = sec(start / FPS), sec(frames / FPS)
        sig = BEDS[name](n)
        fade = min(sec(0.25), n // 2)
        sig[:fade] *= np.linspace(0, 1, fade)
        sig[-fade:] *= np.linspace(1, 0, fade)
        beds[i:i + n] += sig[: total - i]

    for item in plan:
        for cue in item["shot"].sfx:
            offset, name, gain = (*cue, 1.0)[:3]
            sig = EFFECTS[name]() * gain
            if sig.ndim == 1:
                sig = np.stack([sig, sig], axis=1) * np.sqrt(0.5) * 1.4
            j = sec(item["start"] / FPS + offset)
            n = min(len(sig), total - j)
            if n > 0:
                events[j:j + n] += sig[:n]

    wet = np.stack([oaconvolve(events[:, c], reverb_ir(c + 1))[:total] for c in (0, 1)], axis=1)
    out = beds[:, None] + events + 0.22 * wet
    peak = np.max(np.abs(out))
    return out / peak * 0.89 if peak else out


# --- Main -----------------------------------------------------------------------------------------

def main() -> int:
    missing = sorted({s.img for s in SHOTS if s.img and s.img != VEO_CLIP and not (FRAMES / f"{s.img}.png").exists()})
    if missing:
        print(f"Missing {len(missing)} stills, run gen_images.py first: {', '.join(missing[:5])}...", file=sys.stderr)
        return 1
    WORK.mkdir(exist_ok=True)
    plan = timeline()
    total_frames = sum(item["frames"] for item in plan)
    print(f"{len(plan)} shots, {total_frames / FPS / 60:.1f} min")

    segments, current = [], []
    for item in plan:
        if item["shot"].kind == "heading" and current:
            segments.append(current)
            current = []
        current.append(item)
    segments.append(current)

    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = pool.map(render_segment, enumerate(segments))
        print("rendering sound...", flush=True)
        audio = soundtrack(plan)
        wavfile.write(WORK / "sound.wav", SR, (audio * 32767).astype(np.int16))
        paths = list(futures)
    print(f"rendered {len(paths)} segments", flush=True)

    concat = WORK / "segments.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in paths))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-i",
                    str(WORK / "sound.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", "-shortest", str(OUTPUT)], check=True)
    print(f"Done: {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
