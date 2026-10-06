"""Prepis reči na text s časovými značkami (ASR – automatic speech recognition).

Podporovaní poskytovatelia (``ASR_PROVIDER`` v ``.env``):

* ``openai`` (predvolené) – OpenAI Audio Transcriptions API s modelom
  ``whisper-1`` a formátom ``verbose_json``, ktorý vracia segmenty s časmi
  začiatku a konca. Volanie ide cez ``requests`` (bez ďalšej knižnice),
  s retries a exponenciálnym vyčkávaním pri 429/5xx. Limit súboru je 25 MB,
  preto dlhé audio delíme na časti (``LEARN_AUDIO_CHUNK_SECONDS``).
* ``faster-whisper`` – lokálny prepis na vlastnom počítači (zadarmo, súkromné,
  bez odosielania audia do cloudu). Vyžaduje ``pip install -r requirements-local-asr.txt``;
  model sa pri prvom spustení stiahne z Hugging Face.
* ``none`` – bez prepisu (analýza len z obrazu).
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import requests

from ..exceptions import TranscriptionError
from ..retry import compute_backoff
from ..text_utils import format_timestamp

logger = logging.getLogger(__name__)

OPENAI_TRANSCRIPTIONS_URL: Final[str] = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_MAX_FILE_BYTES: Final[int] = 25 * 1024 * 1024
_MIME_TYPES: Final[dict[str, str]] = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}


@dataclass(frozen=True)
class TranscriptSegment:
    """Úsek reči s časom začiatku a konca (v sekundách od začiatku videa)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    """Celý prepis videa."""

    segments: tuple[TranscriptSegment, ...]
    language: str | None
    provider: str

    @classmethod
    def empty(cls, provider: str) -> Transcript:
        return cls(segments=(), language=None, provider=provider)

    @property
    def is_empty(self) -> bool:
        return not any(segment.text.strip() for segment in self.segments)

    def shifted(self, offset: float) -> Transcript:
        """Posunie časy segmentov (pri prepise po častiach)."""
        return Transcript(
            segments=tuple(TranscriptSegment(s.start + offset, s.end + offset, s.text) for s in self.segments),
            language=self.language,
            provider=self.provider,
        )

    def to_prompt_text(self) -> str:
        """Formát pre Claude: ``[00:01.2 → 00:03.8] text``."""
        if self.is_empty:
            return "(bez reči / prepis nie je k dispozícii)"
        return "\n".join(
            f"[{format_timestamp(s.start)} → {format_timestamp(s.end)}] {s.text.strip()}"
            for s in self.segments
            if s.text.strip()
        )


def merge_transcripts(parts: list[Transcript], provider: str) -> Transcript:
    """Spojí prepisy jednotlivých častí audia do jedného."""
    segments = tuple(segment for part in parts for segment in part.segments)
    language = next((part.language for part in parts if part.language), None)
    return Transcript(segments=segments, language=language, provider=provider)


class Transcriber(Protocol):
    """Rozhranie poskytovateľa prepisu reči."""

    name: str
    # Ak poskytovateľ potrebuje kratšie súbory (limit API), dĺžka časti v sekundách.
    max_chunk_seconds: float | None

    def transcribe(self, audio_path: Path) -> Transcript: ...


class OpenAIWhisperTranscriber:
    """Prepis cez OpenAI Audio API (``whisper-1``, segmenty s časovými značkami)."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "whisper-1",
        language: str | None = None,
        chunk_seconds: float = 600,
        timeout_seconds: float = 300,
        max_retries: int = 5,
        backoff_base_seconds: float = 2.0,
        backoff_max_seconds: float = 60.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise TranscriptionError("Chýba OPENAI_API_KEY (alebo nastav ASR_PROVIDER=faster-whisper / none).")
        self._api_key = api_key
        self._model = model
        self._language = language
        self.max_chunk_seconds: float | None = chunk_seconds
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self._session = session or requests.Session()
        self._sleep = sleep

    def transcribe(self, audio_path: Path) -> Transcript:
        size = audio_path.stat().st_size
        if size > OPENAI_MAX_FILE_BYTES:
            raise TranscriptionError(
                f"Audio súbor má {size / 1_048_576:.1f} MB, OpenAI povoľuje max. 25 MB – "
                "zníž LEARN_AUDIO_CHUNK_SECONDS."
            )
        fields: list[tuple[str, str]] = [
            ("model", self._model),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "segment"),
        ]
        if self._language:
            fields.append(("language", self._language))
        mime = _MIME_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")

        for attempt in range(self._max_retries + 1):
            is_last = attempt >= self._max_retries
            try:
                with audio_path.open("rb") as handle:
                    response = self._session.post(
                        OPENAI_TRANSCRIPTIONS_URL,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        data=fields,
                        files={"file": (audio_path.name, handle, mime)},
                        timeout=self._timeout,
                    )
            except (requests.ConnectionError, requests.Timeout) as exc:
                # Prepis je len čítanie – opakovanie je bezpečné.
                if is_last:
                    raise TranscriptionError(f"Sieťová chyba pri prepise: {type(exc).__name__}") from exc
                self._wait(attempt, None, f"sieťová chyba ({type(exc).__name__})")
                continue

            if response.status_code == 200:
                return self._parse(response)
            if response.status_code == 401:
                raise TranscriptionError("OpenAI odmietol OPENAI_API_KEY (HTTP 401).")
            if response.status_code in {408, 409, 429} or response.status_code >= 500:
                if is_last:
                    raise TranscriptionError(f"OpenAI API vracia HTTP {response.status_code} aj po opakovaniach.")
                self._wait(attempt, response.headers.get("Retry-After"), f"HTTP {response.status_code}")
                continue
            raise TranscriptionError(f"OpenAI API vrátilo HTTP {response.status_code}: {_error_message(response)}")
        raise TranscriptionError("Prepis zlyhal po vyčerpaní pokusov.")

    def _wait(self, attempt: int, retry_after: str | None, reason: str) -> None:
        delay = compute_backoff(attempt, self._backoff_base, self._backoff_max)
        if retry_after:
            with contextlib.suppress(ValueError):
                delay = max(delay, float(retry_after))
        logger.warning(
            "Prepis reči: %s – opakujem o %.1f s (pokus %d/%d).", reason, delay, attempt + 1, self._max_retries
        )
        self._sleep(delay)

    def _parse(self, response: requests.Response) -> Transcript:
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise TranscriptionError("OpenAI vrátilo neplatný JSON.") from exc
        segments = [
            TranscriptSegment(
                float(s.get("start") or 0.0), float(s.get("end") or 0.0), str(s.get("text") or "").strip()
            )
            for s in payload.get("segments") or []
            if isinstance(s, dict)
        ]
        if not segments and payload.get("text"):
            duration = float(payload.get("duration") or 0.0)
            segments = [TranscriptSegment(0.0, duration, str(payload["text"]).strip())]
        return Transcript(segments=tuple(segments), language=payload.get("language"), provider=self.name)


class FasterWhisperTranscriber:
    """Lokálny prepis cez knižnicu ``faster-whisper`` (CTranslate2, beží aj na CPU)."""

    name = "faster-whisper"

    def __init__(self, *, model_size: str = "small", language: str | None = None) -> None:
        self._model_size = model_size
        self._language = language
        self.max_chunk_seconds: float | None = None  # lokálny model zvládne celý súbor naraz

    def transcribe(self, audio_path: Path) -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(
                "Lokálny prepis vyžaduje balík faster-whisper: pip install -r requirements-local-asr.txt"
            ) from exc
        logger.info("Načítavam lokálny model faster-whisper '%s' (prvé spustenie ho stiahne)…", self._model_size)
        model = WhisperModel(self._model_size, device="auto", compute_type="int8")
        segments, info = model.transcribe(str(audio_path), language=self._language, vad_filter=True, beam_size=5)
        result = tuple(TranscriptSegment(float(s.start), float(s.end), str(s.text).strip()) for s in segments)
        return Transcript(segments=result, language=getattr(info, "language", None), provider=self.name)


class NullTranscriber:
    """Bez prepisu – analýza štýlu len z obrazu a strihových metrík."""

    name = "none"
    max_chunk_seconds: float | None = None

    def transcribe(self, audio_path: Path) -> Transcript:
        return Transcript.empty(self.name)


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(payload)[:300]
