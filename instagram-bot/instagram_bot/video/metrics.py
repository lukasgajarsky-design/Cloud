"""Objektívne metriky videa, ktoré rátame lokálne (bez AI).

Claude dostane presné čísla namiesto odhadov z obrázkov:

* **Strihové metriky** – z časov detegovaných zmien scény: počet strihov,
  priemerná/mediánová dĺžka záberu, strihy za minútu a tempo v tretinách videa.
* **Metriky reči** – z prepisu: slová za minútu, priemerná dĺžka vety,
  kedy zaznie prvé slovo (dôležité pre verbálny hook).
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

from ..text_utils import format_timestamp
from .transcription import Transcript

_WORD = re.compile(r"\w+", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?…]+")


@dataclass(frozen=True)
class CutMetrics:
    """Rytmus strihu odvodený z časov zmien scény."""

    duration: float
    cut_times: tuple[float, ...]
    shot_lengths: tuple[float, ...]

    @property
    def cut_count(self) -> int:
        return len(self.cut_times)

    @property
    def shot_count(self) -> int:
        return len(self.shot_lengths)

    @property
    def average_shot(self) -> float:
        return statistics.fmean(self.shot_lengths) if self.shot_lengths else 0.0

    @property
    def median_shot(self) -> float:
        return statistics.median(self.shot_lengths) if self.shot_lengths else 0.0

    @property
    def cuts_per_minute(self) -> float:
        return self.cut_count / (self.duration / 60) if self.duration > 0 else 0.0

    def pace_by_thirds(self) -> list[tuple[str, float]]:
        """Strihy za minútu v začiatku, strede a na konci videa (zmena tempa v čase)."""
        if self.duration <= 0:
            return []
        third = self.duration / 3
        labels = ("začiatok", "stred", "koniec")
        result = []
        for index, label in enumerate(labels):
            start, end = index * third, (index + 1) * third
            cuts = sum(1 for t in self.cut_times if start <= t < end or (index == 2 and t == end))
            result.append((label, cuts / (third / 60)))
        return result

    def to_prompt_text(self, max_listed_cuts: int = 300) -> str:
        if not self.shot_lengths:
            return "Strihové metriky nie sú k dispozícii."
        lines = [
            f"- dĺžka videa: {self.duration:.1f} s",
            f"- detegované strihy (zmeny scény): {self.cut_count}",
            f"- počet záberov: {self.shot_count}",
            f"- priemerná dĺžka záberu: {self.average_shot:.2f} s, medián: {self.median_shot:.2f} s",
            f"- najkratší záber: {min(self.shot_lengths):.2f} s, najdlhší: {max(self.shot_lengths):.2f} s",
            f"- strihy za minútu: {self.cuts_per_minute:.1f}",
            "- tempo v tretinách videa (strihy/min): "
            + ", ".join(f"{label} {pace:.1f}" for label, pace in self.pace_by_thirds()),
        ]
        if self.cut_times:
            listed = ", ".join(format_timestamp(t) for t in self.cut_times[:max_listed_cuts])
            more = f" … (+{self.cut_count - max_listed_cuts})" if self.cut_count > max_listed_cuts else ""
            lines.append(f"- časy strihov: {listed}{more}")
        return "\n".join(lines)


def compute_cut_metrics(cut_times: Iterable[float], duration: float, min_gap: float = 0.25) -> CutMetrics:
    """Z časov zmien scény vypočíta dĺžky záberov.

    Strihy bližšie ako ``min_gap`` sekúnd sa zlúčia (blesk, rýchly prechod by
    inak vytvoril neexistujúce „mikrozábery“).
    """
    merged: list[float] = []
    for t in sorted(t for t in cut_times if 0.05 < t < duration - 0.05):
        if not merged or t - merged[-1] >= min_gap:
            merged.append(t)
    boundaries = [0.0, *merged, max(duration, merged[-1] if merged else 0.0)]
    shots = tuple(round(end - start, 3) for start, end in pairwise(boundaries) if end - start > 0)
    return CutMetrics(duration=duration, cut_times=tuple(merged), shot_lengths=shots)


@dataclass(frozen=True)
class SpeechMetrics:
    """Tempo a štruktúra reči z prepisu."""

    word_count: int
    speech_seconds: float
    words_per_minute: float
    sentence_count: int
    average_sentence_words: float
    first_speech_at: float | None
    last_speech_at: float | None

    def to_prompt_text(self) -> str:
        if self.word_count == 0:
            return "Video neobsahuje rozpoznanú reč (alebo bol prepis vypnutý)."
        first = format_timestamp(self.first_speech_at) if self.first_speech_at is not None else "?"
        last = format_timestamp(self.last_speech_at) if self.last_speech_at is not None else "?"
        return "\n".join(
            [
                f"- počet slov: {self.word_count}",
                f"- čas reči: {self.speech_seconds:.1f} s",
                f"- tempo reči: {self.words_per_minute:.0f} slov za minútu",
                f"- počet viet: {self.sentence_count}, priemerná dĺžka vety: {self.average_sentence_words:.1f} slova",
                f"- prvé slovo zaznie v čase {first}, posledné končí v {last}",
            ]
        )


def compute_speech_metrics(transcript: Transcript) -> SpeechMetrics:
    """Spočíta slová, tempo reči a dĺžku viet z prepisu."""
    segments = [segment for segment in transcript.segments if segment.text.strip()]
    if not segments:
        return SpeechMetrics(0, 0.0, 0.0, 0, 0.0, None, None)
    full_text = " ".join(segment.text.strip() for segment in segments)
    word_count = len(_WORD.findall(full_text))
    speech_seconds = sum(max(0.0, segment.end - segment.start) for segment in segments)
    sentences = [part for part in _SENTENCE_END.split(full_text) if _WORD.search(part)]
    sentence_count = max(1, len(sentences))
    return SpeechMetrics(
        word_count=word_count,
        speech_seconds=speech_seconds,
        words_per_minute=word_count / (speech_seconds / 60) if speech_seconds > 0 else 0.0,
        sentence_count=sentence_count,
        average_sentence_words=word_count / sentence_count,
        first_speech_at=segments[0].start,
        last_speech_at=segments[-1].end,
    )
