"""Exponenciálne vyčkávanie (exponential backoff) s náhodným rozptylom (jitter).

Pri chybách 429/5xx nečakáme stále rovnako dlho, ale 2, 4, 8, 16 … sekúnd
(až po strop). Jitter pridáva náhodnú zložku, aby viac inštancií bota
nebombardovalo API v tú istú sekundu („thundering herd“).
"""

from __future__ import annotations

import random
from collections.abc import Callable


def compute_backoff(
    attempt: int,
    base_seconds: float,
    max_seconds: float,
    rng: Callable[[], float] = random.random,
) -> float:
    """Vráti počet sekúnd čakania pred ďalším pokusom.

    Používa stratégiu „equal jitter“: polovica intervalu je pevná, druhá polovica
    náhodná. Tým sa zachová rastúca pauza a zároveň sa pokusy rozptýlia v čase.

    :param attempt: poradie neúspešného pokusu, začína od 0.
    :param base_seconds: základ (pauza po prvom zlyhaní je cca ``base_seconds``).
    :param max_seconds: horný strop pauzy.
    :param rng: zdroj náhody (v testoch sa dá nahradiť deterministickou funkciou).
    """
    if attempt < 0:
        raise ValueError("attempt musí byť >= 0")
    exponential = min(max_seconds, base_seconds * (2.0**attempt))
    half = exponential / 2
    return half + rng() * half
