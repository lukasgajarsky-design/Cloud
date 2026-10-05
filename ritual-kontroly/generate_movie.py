#!/usr/bin/env python3
"""Render the master shot of "Rituál kontroly" with a text-to-video API.

Uses the first provider whose API key is set in the environment, or the one
named with --provider:

    RUNWAYML_API_SECRET   Runway API, model gen4.5 (1280x720, 2-10 s)
    LUMA_AGENTS_API_KEY   Luma Agents API, model ray-3.2 (1080p, 5 or 10 s)
    REPLICATE_API_TOKEN   Replicate, model google/veo-3.1 (set REPLICATE_MODEL to change)

The script submits the master prompt, polls the task until it finishes and
saves the clip as ritual_kontroly.mp4 next to this file.

    python3 generate_movie.py                      # first provider with a key
    python3 generate_movie.py --provider luma --duration 5
    python3 generate_movie.py --dry-run            # print the request, send nothing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

MASTER_PROMPT = (
    "A raw, hyper-realistic cinematic scene from a psychological drama, 35mm film style. "
    "Moody, suffocating atmosphere with a sickening, buzzing yellowish fluorescent lighting. "
    "An exhausted 33-year-old man sits alone inside a house, frozen in silent anger, "
    "his body tensing up as he grips a glass. Simultaneously, outside the door, a paranoid "
    "older man in his 60s is methodically and aggressively shaking a metal door handle, "
    "testing the locks in a slow, calculated, sadistic ritual of control. Heavy shadows, "
    "intense suspense, slow-motion movement, photorealistic faces reflecting deep "
    "generational trauma and intense micro-gaslighting, 4k resolution."
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "ritual_kontroly.mp4"
HTTP_TIMEOUT = 60


class GenerationError(RuntimeError):
    pass


class Provider:
    name = ""
    env_var = ""
    base = ""
    durations: tuple[int, ...] = ()
    default_duration: int | None = None

    def __init__(self, api_key: str, duration: int | None):
        self.duration = duration or self.default_duration
        allowed = self.durations
        if allowed and self.duration not in allowed:
            spec = f"{allowed[0]}-{allowed[-1]}" if len(allowed) > 2 else " or ".join(map(str, allowed))
            raise GenerationError(f"{self.name} supports {spec} s clips, got {self.duration}")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def request(self) -> tuple[str, dict]:
        """Return the URL and JSON body of the create call."""
        raise NotImplementedError

    def poll(self, task_id: str) -> tuple[str, str | None]:
        """Return (status, video_url); video_url is set once the render succeeded."""
        raise NotImplementedError

    def submit(self) -> str:
        url, body = self.request()
        return self._call("POST", url, json=body)["id"]

    def _call(self, method: str, url: str, **kwargs) -> dict:
        resp = self.session.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
        if resp.status_code >= 400:
            raise GenerationError(f"{self.name}: HTTP {resp.status_code} from {url}: {resp.text[:500]}")
        return resp.json()


class Runway(Provider):
    name = "runway"
    env_var = "RUNWAYML_API_SECRET"
    base = "https://api.dev.runwayml.com/v1"
    durations = tuple(range(2, 11))
    default_duration = 10

    def __init__(self, api_key: str, duration: int | None):
        super().__init__(api_key, duration)
        self.session.headers["X-Runway-Version"] = "2024-11-06"

    def request(self):
        return f"{self.base}/text_to_video", {
            "model": "gen4.5",
            "promptText": MASTER_PROMPT,
            "ratio": "1280:720",
            "duration": self.duration,
        }

    def poll(self, task_id):
        task = self._call("GET", f"{self.base}/tasks/{task_id}")
        status = task["status"]
        if status == "SUCCEEDED":
            return status, task["output"][0]
        if status in ("FAILED", "CANCELLED"):
            raise GenerationError(f"runway task {status}: {task.get('failure') or task.get('failureCode')}")
        return status, None


class Luma(Provider):
    name = "luma"
    env_var = "LUMA_AGENTS_API_KEY"
    base = "https://agents.lumalabs.ai/v1"
    durations = (5, 10)
    default_duration = 10

    def request(self):
        return f"{self.base}/generations", {
            "model": "ray-3.2",
            "type": "video",
            "prompt": MASTER_PROMPT,
            "aspect_ratio": "16:9",
            "video": {"resolution": "1080p", "duration": f"{self.duration}s"},
        }

    def poll(self, task_id):
        generation = self._call("GET", f"{self.base}/generations/{task_id}")
        state = generation["state"]
        if state == "completed":
            return state, generation["output"][0]["url"]
        if state == "failed":
            reason = generation.get("failure_reason") or generation.get("failure_code")
            raise GenerationError(f"luma generation failed: {reason}")
        return state, None


class Replicate(Provider):
    name = "replicate"
    env_var = "REPLICATE_API_TOKEN"
    base = "https://api.replicate.com/v1"

    def __init__(self, api_key: str, duration: int | None):
        super().__init__(api_key, duration)
        self.model = os.environ.get("REPLICATE_MODEL", "google/veo-3.1")

    def request(self):
        model_input = {"prompt": MASTER_PROMPT}
        if self.duration:
            model_input["duration"] = self.duration
        return f"{self.base}/models/{self.model}/predictions", {"input": model_input}

    def poll(self, task_id):
        prediction = self._call("GET", f"{self.base}/predictions/{task_id}")
        status = prediction["status"]
        if status == "succeeded":
            output = prediction["output"]
            return status, output[0] if isinstance(output, list) else output
        if status in ("failed", "canceled"):
            raise GenerationError(f"replicate prediction {status}: {prediction.get('error')}")
        return status, None


PROVIDERS = {cls.name: cls for cls in (Runway, Luma, Replicate)}


def pick_provider(name: str | None) -> tuple[type[Provider], str | None]:
    """Return the requested provider, or the first one with a key, plus its key."""
    candidates = [PROVIDERS[name]] if name else list(PROVIDERS.values())
    for cls in candidates:
        if os.environ.get(cls.env_var):
            return cls, os.environ[cls.env_var]
    return candidates[0], None


def wait_for(provider: Provider, task_id: str, timeout: int, interval: int) -> str:
    start = time.monotonic()
    last_status = None
    while True:
        status, video_url = provider.poll(task_id)
        elapsed = int(time.monotonic() - start)
        if status != last_status:
            print(f"  [{elapsed:>4}s] {status}", flush=True)
            last_status = status
        if video_url:
            return video_url
        if elapsed >= timeout:
            raise GenerationError(f"gave up after {timeout} s; task {task_id} is still {status}")
        time.sleep(interval)


def download(url: str, dest: Path) -> None:
    # Output URLs are pre-signed, so no auth header: the API key must not leak to storage hosts.
    partial = dest.with_name(dest.name + ".part")
    with requests.get(url, stream=True, timeout=HTTP_TIMEOUT) as resp:
        resp.raise_for_status()
        with open(partial, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    partial.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=PROVIDERS, help="default: first provider with an API key set")
    parser.add_argument("--duration", type=int, help="clip length in seconds (default: provider maximum)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"default: {DEFAULT_OUTPUT.name}")
    parser.add_argument("--timeout", type=int, default=900, help="seconds to wait for the render (default 900)")
    parser.add_argument("--interval", type=int, default=10, help="seconds between status checks (default 10)")
    parser.add_argument("--dry-run", action="store_true", help="print the request instead of sending it")
    args = parser.parse_args()

    cls, api_key = pick_provider(args.provider)
    try:
        provider = cls(api_key or "dry-run", args.duration)
        if args.dry_run:
            url, body = provider.request()
            print(f"POST {url}\n{json.dumps(body, indent=2, ensure_ascii=False)}")
            return 0
        if not api_key:
            wanted = [cls] if args.provider else PROVIDERS.values()
            print("No API key found. Set one of: " + ", ".join(p.env_var for p in wanted), file=sys.stderr)
            return 2

        print(f"Provider: {cls.name}")
        task_id = provider.submit()
        print(f"Task {task_id} submitted, waiting for the render...", flush=True)
        video_url = wait_for(provider, task_id, args.timeout, args.interval)
        download(video_url, args.output)
    except (GenerationError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Done: {args.output} ({args.output.stat().st_size / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
