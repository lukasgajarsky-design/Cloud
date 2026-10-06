#!/usr/bin/env python3
"""Generate the animatic stills with SDXL-Turbo on the CPU (about 10 s per image).

Images go to frames/<key>.png; existing files are skipped, so the script can be rerun
after editing a prompt (delete that image first).
"""

import sys
import time
import zlib
from pathlib import Path

import torch
from diffusers import AutoPipelineForText2Image

from shots import IMAGES

OUT = Path(__file__).resolve().parent / "frames"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    todo = [key for key in IMAGES if not (OUT / f"{key}.png").exists()]
    if not todo:
        print("all images exist")
        return
    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sdxl-turbo", torch_dtype=torch.bfloat16, variant="fp16"
    )
    pipe.set_progress_bar_config(disable=True)
    for n, key in enumerate(todo, 1):
        start = time.time()
        image = pipe(
            IMAGES[key],
            num_inference_steps=4,
            guidance_scale=0.0,
            width=768,
            height=432,
            generator=torch.Generator().manual_seed(zlib.crc32(key.encode())),
        ).images[0]
        image.save(OUT / f"{key}.png")
        print(f"[{n}/{len(todo)}] {key} {time.time() - start:.1f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
