#!/usr/bin/env python3
"""Build a short free animatic of scene 1 ("Rituál kontroly", scena-1.md).

No API key needed. Keyframes come from Pollinations' free image endpoint
(cached in frames/; delete a file to fetch it again). ffmpeg then adds camera
moves, colour grades, fluorescent flicker, grain, a 2.39:1 frame with Slovak
subtitles, and a synthesized soundtrack: the 100 Hz fluorescent hum, the
father's footsteps, the door-handle clicks and the garage gate.

    python make_animatic.py            # -> ritual_kontroly_scena1_animatik.mp4 (about 58 s)

It leaves ritual_kontroly.mp4 alone: animatic/build.py reads that clip.

Needs ffmpeg with libx264 and drawtext, and the DejaVu fonts.
"""

import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "frames"
OUT = HERE / "ritual_kontroly_scena1_animatik.mp4"
FPS = 30
W, H, BAR = 1280, 536, 92  # 2.39:1 picture inside a 1280x720 frame
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

STYLE = "cinematic 35mm film still, {}, film grain, photorealistic"
GRADES = {
    "office": "colorbalance=rs=.06:gs=.07:bs=-.12:rm=.05:gm=.06:bm=-.10:rh=.03:gh=.04:bh=-.06,"
    "eq=saturation=.7:contrast=1.08:gamma=.9",
    "house": "colorbalance=rs=.03:gs=.05:bs=-.06:rm=.02:gm=.04:bm=-.05,"
    "eq=saturation=.6:contrast=1.1:gamma=.88:brightness=-.03",
    "night": "colorbalance=rs=-.05:gs=.06:bs=.02:rm=-.04:gm=.07,"
    "eq=saturation=.45:contrast=1.15:gamma=.8:brightness=-.08",
}
HUM_LEVEL = {"office": 1.0, "house": 0.3, "night": 0.18}

# zoom: (start, end); center: (x0, y0, x1, y1) as fractions of the image.
# Zoom stays >= 1.18 with the centre above 0.5 so the watermark corner never shows.
# Times in clicks/steps/subs are seconds from the start of the shot.
SHOTS = [
    {
        "frame": "p1", "seed": 4101, "seconds": 6, "grade": "office", "flicker": True,
        "zoom": (1.18, 1.32), "center": (0.52, 0.44, 0.56, 0.40), "stamp": "PONDELOK 17:42",
        "steps": [1.4, 2.5, 3.6, 4.7],
        "prompt": "dusk, a cramped warehouse office lit by one buzzing yellowish fluorescent tube, an exhausted "
        "33-year-old man with short dark hair, stubble and dark circles under his eyes, wearing a grey hoodie, "
        "sits at a desk with open binders, delivery notes and a chipped mug, pen frozen in his hand, shoulders "
        "raised, listening to footsteps behind the closed door, sickly yellow-green light, deep shadows",
    },
    {
        "frame": "p2", "seed": 4202, "seconds": 6, "grade": "office", "flicker": True,
        "zoom": (1.20, 1.38), "center": (0.66, 0.46, 0.72, 0.36),
        "subs": [(0.6, 3.0, "„Zase si nezavrel bránu na sklade.“"), (3.3, 5.7, "„Už som to urobil za teba. Ako vždy.“")],
        "prompt": "an older man in his late 60s with grey stubble, thinning grey hair, heavy-lidded eyes and reading "
        "glasses, wearing a worn brown work jacket, stands in an office doorway with one hand on the door frame, "
        "looking down with a disappointed, pitying expression, harsh yellowish fluorescent light from above, "
        "heavy shadows under his eyes",
    },
    {
        "frame": "p3", "seed": 4303, "seconds": 6, "grade": "office", "flicker": True,
        "zoom": (1.18, 1.40), "center": (0.50, 0.46, 0.52, 0.38), "stamp": "19:14",
        "subs": [(2.2, 5.6, "„Tak už idem. Len aby si vedel. Už zamykám.“")],
        "prompt": "night, an empty warehouse office under a yellowish fluorescent tube, an older man in his late 60s "
        "with grey stubble and thinning grey hair, worn brown work jacket, sits alone at a desk with his hands flat "
        "on the desk, calm, almost content expression, a chipped mug in front of him, monitor off, desaturated "
        "yellow tones",
    },
    {
        "frame": "hallway", "seed": 5101, "seconds": 5, "grade": "house", "flicker": False,
        "zoom": (1.18, 1.30), "center": (0.55, 0.44, 0.56, 0.40), "stamp": "19:51",
        "subs": [(1.8, 4.4, "„Tak. Som tu.“")], "clicks": [(0.6, 0.5)],
        "prompt": "night, inside a dim house, wide shot: on the left a tense young man in a grey hoodie sits at a "
        "kitchen table gripping a glass, on the right in the hallway an old grey-haired man in a brown jacket grips "
        "the handle of the front door, yellowish fluorescent light, heavy shadows, suspense",
    },
    {
        "frame": "table", "seed": 5103, "seconds": 6, "grade": "house", "flicker": True,
        "zoom": (1.18, 1.34), "center": (0.55, 0.48, 0.60, 0.44),
        "subs": [(2.4, 5.6, "„Nič. Ja nič nehovorím.“")], "clicks": [(0.5, 0.35), (1.1, 0.35)], "gate": [1.7],
        "prompt": "night, inside a dim house, wide shot: on the left a tense young man in a grey hoodie sits at a "
        "kitchen table gripping a glass, on the right in the hallway an old grey-haired man in a brown jacket grips "
        "the handle of the front door, yellowish fluorescent light, heavy shadows, suspense",
    },
    {
        "frame": "p4", "seed": 4404, "seconds": 6, "grade": "house", "flicker": False,
        "zoom": (1.20, 1.30), "center": (0.48, 0.46, 0.50, 0.44), "clicks": [(1.0, 1.0), (2.5, 1.0), (4.0, 1.0)],
        "prompt": "night, extreme close-up of an old man's hand pressing down a metal door handle on a locked front "
        "door of a house, wrinkled knuckles, cold light, deep shadows",
    },
    {
        "frame": "p5a", "seed": 4505, "seconds": 6, "grade": "night", "flicker": False,
        "zoom": (1.18, 1.36), "center": (0.48, 0.44, 0.52, 0.40), "stamp": "23:10",
        "prompt": "late night, a dark kitchen lit only by the green digits of a stove clock, an exhausted man in his "
        "early 30s with short dark hair and stubble, wearing a grey hoodie, pours clear spirit from a bottle into a "
        "ceramic mug, eyes glassy, desaturated, deep shadows",
    },
    {
        "frame": "p5b", "seed": 4606, "seconds": 6, "grade": "house", "hum": 0.18, "flicker": False,
        "zoom": (1.18, 1.30), "center": (0.52, 0.46, 0.54, 0.42), "stamp": "23:12",
        "clicks": [(1.3, 0.9), (2.8, 0.9), (4.3, 0.9)],
        "prompt": "late night, a dark house hallway, a man in a grey hoodie seen from behind his shoulder places his "
        "hand on the metal handle of the locked front door, faint light, desaturated, deep shadows",
    },
]
TITLE_SECONDS = 4
END_SECONDS = 7
END_TEXT = "Obchôdzka sa neskončila. Len si ju prevzal."

CLICK = (
    "0.55*exp(-80*t)*sin(2*PI*3100*t)+0.45*exp(-45*t)*sin(2*PI*1300*t)+0.35*exp(-25*t)*sin(2*PI*380*t)"
    "+0.3*gte(t,0.07)*exp(-90*(t-0.07))*sin(2*PI*2400*t)"
)
STEP = "0.8*exp(-28*t)*sin(2*PI*62*t)+0.15*exp(-70*t)*sin(2*PI*180*t)"
GATE = "0.4*exp(-6*t)*(sin(2*PI*523*t)+0.6*sin(2*PI*1187*t)+0.4*sin(2*PI*1873*t))"
HUM = "0.09*sin(2*PI*100*t)+0.05*sin(2*PI*200*t)+0.025*sin(2*PI*300*t)+0.012*sin(2*PI*500*t)"


def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def fetch_frame(shot):
    dest = FRAMES / f"{shot['frame']}.jpg"
    if dest.exists():
        return dest
    prompt = urllib.parse.quote(STYLE.format(shot["prompt"]))
    url = f"https://image.pollinations.ai/prompt/{prompt}?width=1536&height=640&seed={shot['seed']}&nologo=true"
    req = urllib.request.Request(url, headers={"User-Agent": "ritual-kontroly/1.0"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if data[:2] == b"\xff\xd8":
                FRAMES.mkdir(exist_ok=True)
                dest.write_bytes(data)
                print(f"fetched {dest.name}", flush=True)
                return dest
        except urllib.error.HTTPError as e:
            print(f"{dest.name}: HTTP {e.code}, retrying", flush=True)
        time.sleep(10 * (attempt + 1))  # the free tier rate-limits bursts
    sys.exit(f"could not fetch {dest.name} from Pollinations")


def fade(a, b, d=0.3):
    return f"if(lt(t,{a + d}),(t-{a})/{d},if(gt(t,{b - d}),({b}-t)/{d},1))"


def text(tmp, name, content, font, size, x, y, a, b, alpha=1.0):
    path = tmp / f"{name}.txt"
    path.write_text(content, encoding="utf-8")
    return (
        f"drawtext=fontfile={font}:textfile={path}:expansion=none:fontsize={size}:fontcolor=white"
        f":x={x}:y={y}:alpha='{alpha}*{fade(a, b)}':enable='between(t,{a},{b})'"
    )


def encode(inputs, vf, seconds, dest):
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-t", str(seconds), "-vf", vf, "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(dest)])


def render_shot(i, shot, tmp):
    n = shot["seconds"] * FPS - 1
    z0, z1 = shot["zoom"]
    x0, y0, x1, y1 = shot["center"]
    # A small downward jolt of the frame on each handle press.
    dip = "+".join(f"14*between(on/{FPS},{c},{c + 0.22})" for c, vol in shot.get("clicks", []) if vol >= 0.9) or "0"
    zoompan = (
        f"zoompan=z='{z0}+({z1}-{z0})*on/{n}'"
        f":x='clip(({x0}+({x1}-{x0})*on/{n})*iw-iw/zoom/2,0,iw-iw/zoom)'"
        f":y='clip(({y0}+({y1}-{y0})*on/{n})*ih-ih/zoom/2+{dip},0,ih-ih/zoom)'"
        f":d=1:s={W}x{H}:fps={FPS}"
    )
    filters = ["scale=3840:-2", zoompan, GRADES[shot["grade"]]]
    if shot["flicker"]:
        filters.append("eq=brightness='-0.07*lt(random(1),0.05)':eval=frame")
    filters += ["vignette=angle=PI/4.5", "noise=alls=8:allf=t+u", f"pad={W}:{H + 2 * BAR}:0:{BAR}:black"]
    if shot.get("stamp"):
        filters.append(text(tmp, f"stamp{i}", shot["stamp"], MONO, 20, 36, BAR + 22, 0.4, shot["seconds"] - 0.4, 0.75))
    for j, (a, b, line) in enumerate(shot.get("subs", [])):
        filters.append(text(tmp, f"sub{i}_{j}", line, SANS, 30, "(w-text_w)/2", H + BAR + 28, a, b))
    filters.append(f"fade=t=in:st=0:d=0.35,fade=t=out:st={shot['seconds'] - 0.35}:d=0.35")
    dest = tmp / f"seg{i + 1:02d}.mp4"
    encode(["-loop", "1", "-framerate", str(FPS), "-i", str(fetch_frame(shot))], ",".join(filters), shot["seconds"], dest)
    return dest


def render_card(name, seconds, texts, tmp):
    filters = [text(tmp, f"{name}{k}", *t) for k, t in enumerate(texts)]
    dest = tmp / f"{name}.mp4"
    encode(["-f", "lavfi", "-i", f"color=black:s={W}x{H + 2 * BAR}:r={FPS}"], ",".join(filters), seconds, dest)
    return dest


def soundtrack(tmp, total):
    # Hum level per section: rises with the title, follows the shot's location, and
    # outlasts the picture at the end like the light left on in the empty office.
    env, t = [f"min(t/3,1)*{HUM_LEVEL['office']}"], TITLE_SECONDS
    events = []
    for shot in SHOTS:
        env.append((t, shot.get("hum", HUM_LEVEL[shot["grade"]])))
        events += [(t + c, CLICK, 0.18, v) for c, v in shot.get("clicks", [])]
        events += [(t + s, STEP, 0.3, 0.5) for s in shot.get("steps", [])]
        events += [(t + g, GATE, 1.2, 0.25) for g in shot.get("gate", [])]
        t += shot["seconds"]
    level = env[0]
    for start, value in env[1:]:
        level = f"if(gte(t,{start}),{value},{level})"
    level = f"if(gte(t,{t}),0.7*min((t-{t})/1.5,1)*min(({total}-t)/2.5,1),{level})"

    inputs = ["-f", "lavfi", "-i", f"aevalsrc='{HUM}':s=48000:d={total}",
              "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.02:r=48000:d={total}"]
    graph = [f"[0]volume='{level}':eval=frame[hum]", "[1]lowpass=f=300,volume=0.6[room]"]
    labels = ["[hum]", "[room]"]
    for k, (at, expr, dur, vol) in enumerate(events):
        inputs += ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={dur}"]
        ms = int(at * 1000)
        graph.append(f"[{k + 2}]volume={vol},adelay={ms}|{ms}[e{k}]")
        labels.append(f"[e{k}]")
    graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first,alimiter=limit=0.9[out]")
    dest = tmp / "audio.wav"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph), "-map", "[out]",
         "-ac", "2", "-t", str(total), str(dest)])
    return dest


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found")
    total = TITLE_SECONDS + sum(s["seconds"] for s in SHOTS) + END_SECONDS
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        try:
            segments = [render_card("title", TITLE_SECONDS, [
                ("RITUÁL KONTROLY", SERIF_BOLD, 54, "(w-text_w)/2", "(h-text_h)/2-24", 0.5, 3.6),
                ("Scéna 1 · Zlomená pamäť a tiché stroje", SANS, 24, "(w-text_w)/2", "(h-text_h)/2+40", 0.9, 3.6, 0.7),
            ], tmp)]
            for i, shot in enumerate(SHOTS):
                print(f"shot {i + 1}/{len(SHOTS)}: {shot['frame']}", flush=True)
                segments.append(render_shot(i, shot, tmp))
            segments.append(render_card("end", END_SECONDS, [
                (END_TEXT, SERIF, 30, "(w-text_w)/2", "(h-text_h)/2", 0.6, 4.2, 0.85),
            ], tmp))
            print("soundtrack", flush=True)
            audio = soundtrack(tmp, total)
        except subprocess.CalledProcessError as e:
            sys.exit(f"ffmpeg failed:\n{e.stderr.decode(errors='replace')[-2000:]}")
        listing = tmp / "segments.txt"
        listing.write_text("".join(f"file '{s}'\n" for s in segments))
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(audio),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
             "-movflags", "+faststart", str(OUT)])
    print(f"ready: {OUT} ({total} s, {OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
