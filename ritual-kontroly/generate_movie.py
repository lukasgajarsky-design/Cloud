#!/usr/bin/env python3
"""Render shots of "Rituál kontroly" (scena-1.md) with a text-to-video API.

The provider is the first one whose API key is set in the environment
(override with --provider):

    runway       RUNWAYML_API_SECRET or RUNWAY_API_KEY  (model gen4.5, 2-10 s)
    luma-agents  LUMA_AGENTS_API_KEY                    (Luma Agents API, ray-3.2, 5 or 10 s, 1080p)
    luma         LUMAAI_API_KEY or LUMA_API_KEY         (Dream Machine API, ray-2, 5 or 9 s, 21:9)
    sora         OPENAI_API_KEY                         (model sora-2, 4/8/12 s)
    replicate    REPLICATE_API_TOKEN                    (model google/veo-3.1, or REPLICATE_MODEL)

Examples:
    python generate_movie.py                  # master shot -> ritual_kontroly.mp4
    python generate_movie.py --shot 3         # one shot from the shot list
    python generate_movie.py --shot all       # shots 1, 2, 3, 4, 5a, 5b
    python generate_movie.py --provider sora --shot 5
    python generate_movie.py --provider luma-agents --duration 5
    python generate_movie.py --list           # print every prompt
    python generate_movie.py --dry-run        # show what would be sent

Key values are never printed. Signed download URLs are fetched without the
API key; only Sora's download goes back to api.openai.com with it.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
POLL_SECONDS = 10
TIMEOUT_SECONDS = 30 * 60

FATHER = (
    "FATHER (man in his late 60s, grey stubble, thinning grey hair, heavy-lidded eyes, "
    "worn brown work jacket, reading glasses)"
)
SON = (
    "SON (man aged 33, short dark hair, unshaven, dark circles under the eyes, "
    "grey hoodie under a work jacket)"
)

MASTER_PROMPT = (
    "A raw, hyper-realistic cinematic scene from a psychological drama, 35mm film style. "
    "Moody, suffocating atmosphere with a sickening, buzzing yellowish fluorescent lighting. "
    "An exhausted 33-year-old man sits alone inside a house, frozen in silent anger, his body "
    "tensing up as he grips a glass. Simultaneously, outside the door, a paranoid older man in "
    "his 60s is methodically and aggressively shaking a metal door handle, testing the locks in "
    "a slow, calculated, sadistic ritual of control. Heavy shadows, intense suspense, "
    "slow-motion movement, photorealistic faces reflecting deep generational trauma and intense "
    "micro-gaslighting, 4k resolution."
)

SHOTS = {
    "master": {
        "title": "Master clip",
        "seconds": 10,
        "out": "ritual_kontroly.mp4",
        "prompt": MASTER_PROMPT,
    },
    "1": {
        "title": "The Hum",
        "seconds": 8,
        "out": "shot1_the_hum.mp4",
        "prompt": (
            "Photorealistic, 35mm film grain, dusk. A cramped warehouse office lit by one buzzing "
            "yellowish fluorescent tube that flickers faintly; one end of the tube is blackened. "
            f"{SON} sits at a desk with three open binders, delivery notes and a chipped mug with "
            "a broken handle. His pen freezes mid-number; his shoulders slowly rise, his breath "
            "stops as he listens to slow, shuffling footsteps approaching on linoleum behind the "
            "closed door. Static camera, very slow push-in on his face. Sickly yellow-green "
            "palette, deep shadows. Audio: constant low fluorescent hum, slow shuffling "
            "footsteps, one long sigh behind the door."
        ),
    },
    "2": {
        "title": "The Doorway",
        "seconds": 8,
        "out": "shot2_the_doorway.mp4",
        "prompt": (
            f"Photorealistic, 35mm film grain. {FATHER} stands exactly on the threshold of an "
            "office doorway, neither in nor out, one hand resting on the door frame. He lets out "
            "a long, tired sigh and looks down at the seated son with a disappointed, almost "
            "pitying expression; his calm is more frightening than shouting. Over-the-shoulder "
            "shot from behind the seated son, his tense shoulder soft in the foreground. "
            "Yellowish fluorescent light from above leaves heavy shadows under the father's eyes. "
            "Almost imperceptible push-in."
        ),
    },
    "3": {
        "title": "The Chair",
        "seconds": 10,
        "out": "shot3_the_chair.mp4",
        "prompt": (
            "Photorealistic, 35mm film grain, night. An empty warehouse office under a buzzing "
            f"yellowish fluorescent tube with a blackened end. {FATHER} sits alone in his son's "
            "chair, hands placed flat on the desk. He searches nothing: drawers closed, monitor "
            "off. His face is calm, almost content, like a man lowering himself into a warm bath. "
            "Slowly he reaches out and turns a chipped mug a quarter turn so its broken handle "
            "points toward the door. Locked-off wide shot, then a very slow push-in on his face. "
            "Desaturated yellow palette. Audio: constant low fluorescent hum."
        ),
    },
    "4": {
        "title": "The Handle",
        "seconds": 8,
        "out": "shot4_the_handle.mp4",
        "prompt": (
            f"Photorealistic, 35mm film grain, night, the entrance hall of a family house. {FATHER}, "
            "just home with his jacket still on, has locked the front door. He lays his hand on "
            "the metal door handle and presses it down slowly, once, twice, three times, pausing "
            "between each press, while staring off-camera toward his son. Extreme close-up on his "
            "hand and the handle, then a slow rack focus to his face: calm, watchful, quietly "
            "satisfied. Cold practical light, deep shadows. Audio: three dry metallic clicks of "
            "the handle, a ticking wall clock."
        ),
    },
    "5": {
        "title": "The Mug, Not the Glass (single 12 s take)",
        "seconds": 12,
        "out": "shot5_the_mug.mp4",
        "prompt": (
            "Photorealistic, late night, a dark kitchen lit only by the green digits of a stove "
            f"clock. {SON}, exhausted, silently pours clear spirit from a bottle into a ceramic "
            "mug instead of a glass, so it won't clink. He drinks; close-up on his jaw slowly "
            "unclenching, eyes going glassy. Continuous shot: he walks down the dark hallway to "
            "the locked front door, places his hand on the handle and presses it once, twice, "
            "three times, exactly like his father did. Camera follows behind his shoulder, then "
            "holds on his hand. Desaturated, deep shadows, natural grain, quiet and devastating. "
            "Audio: silence, then a faint fluorescent hum that seems to come from far away."
        ),
    },
    "5a": {
        "title": "The Mug (part 1: pouring)",
        "seconds": 6,
        "out": "shot5a_the_mug.mp4",
        "prompt": (
            "Photorealistic, late night, a dark kitchen lit only by the green digits of a stove "
            f"clock. {SON}, exhausted, silently pours clear spirit from a bottle into a ceramic "
            "mug instead of a glass, so it won't clink. He drinks; close-up on his jaw slowly "
            "unclenching, eyes going glassy. Desaturated, deep shadows, natural grain, quiet and "
            "devastating."
        ),
    },
    "5b": {
        "title": "The Mug (part 2: the handle)",
        "seconds": 6,
        "out": "shot5b_the_handle.mp4",
        "prompt": (
            f"Photorealistic, late night, a dark house hallway. {SON} walks slowly to the locked "
            "front door, places his hand on the metal handle and presses it once, twice, three "
            "times, exactly like his father did. Camera follows behind his shoulder, then holds "
            "on his hand. Desaturated, deep shadows, natural grain, quiet and devastating. Audio: "
            "silence, then a faint fluorescent hum that seems to come from far away."
        ),
    },
}
ALL_SHOTS = ["1", "2", "3", "4", "5a", "5b"]

PROVIDER_KEYS = {
    "runway": ["RUNWAYML_API_SECRET", "RUNWAY_API_KEY"],
    "luma-agents": ["LUMA_AGENTS_API_KEY"],
    "luma": ["LUMAAI_API_KEY", "LUMA_API_KEY"],
    "sora": ["OPENAI_API_KEY"],
    "replicate": ["REPLICATE_API_TOKEN"],
}


class ApiError(Exception):
    pass


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_key(provider):
    for name in PROVIDER_KEYS[provider]:
        if os.environ.get(name):
            return name, os.environ[name]
    return None, None


def pick_provider(requested):
    if requested:
        name, key = find_key(requested)
        if not key:
            raise ApiError(
                f"{requested}: none of {', '.join(PROVIDER_KEYS[requested])} is set in the environment"
            )
        return requested, name, key
    for provider in PROVIDER_KEYS:
        name, key = find_key(provider)
        if key:
            return provider, name, key
    wanted = ", ".join(n for names in PROVIDER_KEYS.values() for n in names)
    raise ApiError(f"no video API key found; set one of: {wanted}")


def check(resp):
    if resp.status_code >= 400:
        raise ApiError(f"HTTP {resp.status_code} from {resp.url.split('?')[0]}: {resp.text[:600]}")
    return resp.json()


def wait_for(label, fetch):
    """Poll fetch() until it returns (status, url) with a url; fetch raises on failure."""
    start = time.monotonic()
    last = None
    while True:
        status, url = fetch()
        if status != last:
            log(f"{label}: {status} ({int(time.monotonic() - start)} s)")
            last = status
        if url:
            return url
        if time.monotonic() - start > TIMEOUT_SECONDS:
            raise ApiError(f"{label}: gave up after {TIMEOUT_SECONDS // 60} minutes")
        time.sleep(POLL_SECONDS)


def render_runway(http, key, prompt, seconds, model):
    base = "https://api.dev.runwayml.com/v1"
    headers = {"Authorization": f"Bearer {key}", "X-Runway-Version": "2024-11-06"}
    if len(prompt) > 1000:
        raise ApiError(f"Runway accepts at most 1000 prompt characters, this one has {len(prompt)}")
    body = {
        "model": model or "gen4.5",
        "promptText": prompt,
        "ratio": "1280:720",
        "duration": max(2, min(10, seconds)),
    }
    task = check(http.post(f"{base}/text_to_video", json=body, headers=headers, timeout=60))
    task_id = task["id"]

    def fetch():
        t = check(http.get(f"{base}/tasks/{task_id}", headers=headers, timeout=60))
        if t["status"] == "SUCCEEDED":
            return t["status"], t["output"][0]
        if t["status"] in ("FAILED", "CANCELLED"):
            raise ApiError(f"Runway task {t['status']}: {t.get('failure') or t.get('failureCode')}")
        return t["status"], None

    return wait_for(f"runway {task_id}", fetch), {}


def render_luma(http, key, prompt, seconds, model):
    base = "https://api.lumalabs.ai/dream-machine/v1"
    headers = {"Authorization": f"Bearer {key}"}
    body = {
        "model": model or "ray-2",
        "prompt": prompt,
        "aspect_ratio": "21:9",
        "resolution": "720p",
        "duration": "9s" if seconds > 7 else "5s",
    }
    gen = check(http.post(f"{base}/generations", json=body, headers=headers, timeout=60))
    gen_id = gen["id"]

    def fetch():
        g = check(http.get(f"{base}/generations/{gen_id}", headers=headers, timeout=60))
        if g["state"] == "completed":
            return g["state"], g["assets"]["video"]
        if g["state"] == "failed":
            raise ApiError(f"Luma generation failed: {g.get('failure_reason')}")
        return g["state"], None

    return wait_for(f"luma {gen_id}", fetch), {}


def render_luma_agents(http, key, prompt, seconds, model):
    base = "https://agents.lumalabs.ai/v1"
    headers = {"Authorization": f"Bearer {key}"}
    body = {
        "model": model or "ray-3.2",
        "type": "video",
        "prompt": prompt,
        "aspect_ratio": "16:9",
        "video": {"resolution": "1080p", "duration": "10s" if seconds > 7 else "5s"},
    }
    gen = check(http.post(f"{base}/generations", json=body, headers=headers, timeout=60))
    gen_id = gen["id"]

    def fetch():
        g = check(http.get(f"{base}/generations/{gen_id}", headers=headers, timeout=60))
        if g["state"] == "completed":
            return g["state"], g["output"][0]["url"]
        if g["state"] == "failed":
            raise ApiError(f"Luma generation failed: {g.get('failure_reason') or g.get('failure_code')}")
        return g["state"], None

    return wait_for(f"luma-agents {gen_id}", fetch), {}


def render_sora(http, key, prompt, seconds, model):
    base = "https://api.openai.com/v1"
    headers = {"Authorization": f"Bearer {key}"}
    secs = min((4, 8, 12), key=lambda s: abs(s - seconds))
    form = {
        "model": (None, model or "sora-2"),
        "prompt": (None, prompt),
        "seconds": (None, str(secs)),
        "size": (None, "1280x720"),
    }
    job = check(http.post(f"{base}/videos", files=form, headers=headers, timeout=60))
    video_id = job["id"]

    def fetch():
        v = check(http.get(f"{base}/videos/{video_id}", headers=headers, timeout=60))
        if v["status"] == "completed":
            return v["status"], f"{base}/videos/{video_id}/content"
        if v["status"] == "failed":
            raise ApiError(f"Sora job failed: {v.get('error')}")
        return v["status"], None

    return wait_for(f"sora {video_id}", fetch), headers


def render_replicate(http, key, prompt, seconds, model):
    # Input fields differ per model, so seconds is None unless the user passed --duration;
    # pass any other fields as JSON in REPLICATE_EXTRA_INPUT.
    base = "https://api.replicate.com/v1"
    headers = {"Authorization": f"Bearer {key}"}
    model = model or os.environ.get("REPLICATE_MODEL", "google/veo-3.1")
    model_input = {"prompt": prompt, **json.loads(os.environ.get("REPLICATE_EXTRA_INPUT", "{}"))}
    if seconds:
        model_input["duration"] = seconds
    pred = check(
        http.post(f"{base}/models/{model}/predictions", json={"input": model_input}, headers=headers, timeout=60)
    )
    pred_id = pred["id"]

    def fetch():
        p = check(http.get(f"{base}/predictions/{pred_id}", headers=headers, timeout=60))
        if p["status"] == "succeeded":
            out = p["output"]
            return p["status"], out[0] if isinstance(out, list) else out
        if p["status"] in ("failed", "canceled"):
            raise ApiError(f"Replicate prediction {p['status']}: {p.get('error')}")
        return p["status"], None

    return wait_for(f"replicate {pred_id}", fetch), {}


RENDERERS = {
    "runway": render_runway,
    "luma-agents": render_luma_agents,
    "luma": render_luma,
    "sora": render_sora,
    "replicate": render_replicate,
}


def download(http, url, headers, dest):
    tmp = dest.with_name(dest.name + ".part")
    with http.get(url, headers=headers, stream=True, timeout=300) as r:
        if r.status_code >= 400:
            raise ApiError(f"download failed with HTTP {r.status_code}")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    with open(tmp, "rb") as f:
        if f.read(12)[4:8] != b"ftyp":
            raise ApiError(f"downloaded file is not an MP4; left it at {tmp}")
    tmp.replace(dest)
    return dest.stat().st_size


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shot", default="master", help="master (default), 1-5, 5a, 5b or all")
    ap.add_argument("--provider", choices=sorted(RENDERERS), help="default: first one with a key set")
    ap.add_argument("--model", help="override the provider's default model")
    ap.add_argument("--seconds", "--duration", type=int, help="override the shot's length")
    ap.add_argument("--out-dir", type=Path, default=HERE, help="where the .mp4 files go (default: next to this script)")
    ap.add_argument("--output", type=Path, help="exact output file; only with a single shot")
    ap.add_argument("--list", action="store_true", help="print the shot list and exit")
    ap.add_argument("--dry-run", action="store_true", help="show what would be rendered without calling an API")
    args = ap.parse_args()

    if args.shot != "all" and args.shot not in SHOTS:
        ap.error(f"unknown shot {args.shot!r}; choose from {', '.join(SHOTS)} or all")
    if args.output and args.shot == "all":
        ap.error("--output takes a single shot; use --out-dir with --shot all")
    shots = ALL_SHOTS if args.shot == "all" else [args.shot]

    if args.list:
        for sid, shot in SHOTS.items():
            print(f"[{sid}] {shot['title']} -> {shot['out']} ({shot['seconds']} s, {len(shot['prompt'])} chars)")
            print(f"    {shot['prompt']}\n")
        return 0

    try:
        provider, key_name, key = pick_provider(args.provider)
    except ApiError as e:
        if not args.dry_run:
            log(f"error: {e}")
            return 2
        provider, key_name, key = args.provider or "runway", None, None

    log(f"provider: {provider} (key from {key_name or 'nowhere: dry run'})")
    http = requests.Session()
    failures = 0

    for sid in shots:
        shot = SHOTS[sid]
        seconds = args.seconds or shot["seconds"]
        # Replicate models disagree on allowed lengths, so it only gets one the user asked for.
        length = args.seconds if provider == "replicate" else seconds
        dest = args.output or args.out_dir / shot["out"]
        log(f"shot {sid} '{shot['title']}': {f'{length} s' if length else 'model default length'} -> {dest}")
        if args.dry_run:
            print(f"    prompt ({len(shot['prompt'])} chars): {shot['prompt']}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            url, dl_headers = RENDERERS[provider](http, key, shot["prompt"], length, args.model)
            size = download(http, url, dl_headers, dest)
            log(f"ready: {dest} ({size / 1e6:.1f} MB)")
        except (ApiError, requests.RequestException) as e:
            log(f"shot {sid} failed: {e}")
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
