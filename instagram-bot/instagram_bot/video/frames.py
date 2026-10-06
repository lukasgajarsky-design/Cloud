"""Deduplikácia a výber snímok pred odoslaním do Claude.

Deduplikácia prebieha v dvoch krokoch:

1. **Presné duplikáty** – rovnaký SHA-256 obsahu súboru (napr. statický obraz).
2. **Takmer identické zábery** – percepčný hash *dHash* (16×16 = 256 bitov):
   obrázok sa zmenší na sivú mriežku 17×16 a pre každý pixel sa zapíše, či je
   jasnejší ako jeho pravý sused. Podobné obrázky majú podobný hash; počet
   rozdielnych bitov (Hammingova vzdialenosť) ≤ ``LEARN_DEDUP_DISTANCE`` znamená
   „rovnaký záber“. Porovnávame s naposledy ponechanou snímkou, takže striedanie
   záberov A/B/A/B (dôležité pre rytmus strihu) ostane zachované.

Ak je unikátnych snímok viac, než dovoľuje limit, prednostne sa ponechajú snímky
zo strihov a pravidelné vzorky sa rovnomerne preriedia.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from PIL import Image

from .ffmpeg import ExtractedFrame

logger = logging.getLogger(__name__)

T = TypeVar("T")


def dhash(path: Path, hash_size: int = 16) -> int:
    """Vypočíta rozdielový percepčný hash (dHash) obrázka ako celé číslo s ``hash_size²`` bitmi."""
    with Image.open(path) as image:
        gray = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        pixels = gray.tobytes()
    width = hash_size + 1
    bits = 0
    for row in range(hash_size):
        offset = row * width
        for col in range(hash_size):
            bits = (bits << 1) | (1 if pixels[offset + col] > pixels[offset + col + 1] else 0)
    return bits


def hamming_distance(first: int, second: int) -> int:
    """Počet rozdielnych bitov medzi dvoma hashmi."""
    return (first ^ second).bit_count()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deduplicate_frames(
    frames: Sequence[ExtractedFrame], max_distance: int, hash_size: int = 16
) -> list[ExtractedFrame]:
    """Odstráni identické a takmer identické po sebe idúce snímky.

    Snímky sa zoradia podľa času; pri zhode času má prednosť snímka zo strihu,
    lebo nesie informáciu „tu začína nová scéna“.
    """
    ordered = sorted(frames, key=lambda frame: (frame.timestamp, 0 if frame.source == "scene" else 1))
    kept: list[tuple[ExtractedFrame, int]] = []
    seen_digests: set[str] = set()
    for frame in ordered:
        digest = _file_digest(frame.path)
        if digest in seen_digests:
            continue
        frame_hash = dhash(frame.path, hash_size)
        if kept:
            last_frame, last_hash = kept[-1]
            if hamming_distance(frame_hash, last_hash) <= max_distance:
                # Rovnaký záber: ak je nová snímka zo strihu a tá predošlá len vzorka
                # z takmer rovnakého času, nahradíme ju (zachová sa značka strihu).
                if (
                    frame.source == "scene"
                    and last_frame.source == "sample"
                    and abs(frame.timestamp - last_frame.timestamp) < 1.0
                ):
                    kept[-1] = (frame, frame_hash)
                    seen_digests.add(digest)
                continue
        seen_digests.add(digest)
        kept.append((frame, frame_hash))
    result = [frame for frame, _ in kept]
    logger.info("Deduplikácia snímok: %d → %d (prah vzdialenosti %d).", len(frames), len(result), max_distance)
    return result


def uniform_subsample(items: Sequence[T], count: int) -> list[T]:
    """Vyberie ``count`` prvkov rovnomerne rozložených (vrátane prvého a posledného)."""
    total = len(items)
    if count <= 0:
        return []
    if count >= total:
        return list(items)
    if count == 1:
        return [items[0]]
    indices = sorted({round(i * (total - 1) / (count - 1)) for i in range(count)})
    return [items[i] for i in indices]


def select_frames(frames: Sequence[ExtractedFrame], max_frames: int) -> list[ExtractedFrame]:
    """Obmedzí počet snímok na ``max_frames`` s prioritou snímok zo strihov."""
    if len(frames) <= max_frames:
        return list(frames)
    scenes = [frame for frame in frames if frame.source == "scene"]
    samples = [frame for frame in frames if frame.source != "scene"]
    if len(scenes) >= max_frames:
        chosen = uniform_subsample(scenes, max_frames)
    else:
        chosen = scenes + uniform_subsample(samples, max_frames - len(scenes))
    return sorted(chosen, key=lambda frame: frame.timestamp)


def base64_size(byte_count: int) -> int:
    """Veľkosť dát po zakódovaní do base64 (4 znaky na každé 3 bajty)."""
    return ((byte_count + 2) // 3) * 4
