"""Fronta príspevkov v priečinku ``queue/``.

Formát: dvojica súborov s rovnakým názvom (líši sa len prípona)::

    queue/
      2026-10-05_jesenna-akcia.jpg      ← médium (.jpg/.jpeg obrázok alebo .mp4/.mov video)
      2026-10-05_jesenna-akcia.txt      ← prompt / návrh textu pre Claude

Textový súbor môže začínať voliteľnou hlavičkou s časom publikovania
(plánovanie). Hlavička končí riadkom ``---``::

    publish_at: 2026-10-05 18:00
    ---
    Jesenná akcia: -20 % na všetky sviečky do nedele. Chcem hravý tón…

Čas bez časového pásma sa berie v ``BOT_TIMEZONE`` (predvolene Europe/Bratislava).
Bez hlavičky sa príspevok publikuje pri najbližšom cykle.

Po publikovaní sa súbory presunú do ``queue/published/<čas>_<názov>/`` spolu
s ``result.json``; pri chybe do ``queue/failed/…`` s ``error.txt``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from .models import MediaKind

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS: Final[frozenset[str]] = frozenset({".jpg", ".jpeg"})
VIDEO_EXTENSIONS: Final[frozenset[str]] = frozenset({".mp4", ".mov"})
# Formáty, ktoré Instagram API pre obrázky NEPODPORUJE (len JPEG) – presunú sa do failed/.
UNSUPPORTED_MEDIA_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".png", ".webp", ".heic", ".heif", ".gif", ".avi", ".mkv"}
)
PUBLISHED_DIR: Final[str] = "published"
FAILED_DIR: Final[str] = "failed"

_HEADER_LINE = re.compile(r"^([a-z_]+)\s*:\s*(.*)$")
_KNOWN_HEADER_KEYS: Final[frozenset[str]] = frozenset({"publish_at"})
_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d. %m. %Y %H:%M",
)


@dataclass(frozen=True)
class PromptFile:
    """Rozparsovaný textový súbor s promptom."""

    body: str
    publish_at: datetime | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueueItem:
    """Pripravený príspevok vo fronte."""

    name: str
    media_path: Path
    prompt_path: Path
    media_kind: MediaKind
    prompt_text: str
    publish_at: datetime | None
    content_hash: str
    size_bytes: int


@dataclass(frozen=True)
class InvalidQueueEntry:
    """Súbory vo fronte, ktoré sa nedajú publikovať (s dôvodom)."""

    name: str
    paths: tuple[Path, ...]
    reason: str


@dataclass
class QueueScanResult:
    """Výsledok prehľadania fronty."""

    ready: list[QueueItem] = field(default_factory=list)
    scheduled: list[QueueItem] = field(default_factory=list)
    invalid: list[InvalidQueueEntry] = field(default_factory=list)


def parse_publish_at(value: str, tz: ZoneInfo) -> datetime:
    """Prevedie text (napr. ``2026-10-05 18:00`` alebo ``5.10.2026 18:00``) na čas s časovým pásmom."""
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Neplatný formát publish_at: '{value}' (použi napr. 2026-10-05 18:00)") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def parse_prompt_file(text: str, tz: ZoneInfo) -> PromptFile:
    """Oddelí voliteľnú hlavičku (``kľúč: hodnota`` … ``---``) od samotného promptu."""
    lines = text.replace("\r\n", "\n").lstrip("﻿").split("\n")
    separator_index = next((i for i, line in enumerate(lines[:30]) if line.strip() == "---"), None)
    if separator_index is None:
        return PromptFile(body=text.strip(), publish_at=None)

    header_lines = [line for line in lines[:separator_index] if line.strip()]
    if not header_lines or not all(_HEADER_LINE.match(line.strip()) for line in header_lines):
        # „---“ je súčasťou bežného textu, nie hlavičky.
        return PromptFile(body=text.strip(), publish_at=None)

    publish_at: datetime | None = None
    warnings: list[str] = []
    for line in header_lines:
        match = _HEADER_LINE.match(line.strip())
        if match is None:  # nenastane – formát overený vyššie, kontrola kvôli typom
            continue
        key, value = match.group(1), match.group(2)
        if key not in _KNOWN_HEADER_KEYS:
            warnings.append(f"neznámy kľúč hlavičky '{key}' bol ignorovaný")
            continue
        if key == "publish_at" and value.strip():
            publish_at = parse_publish_at(value, tz)
    body = "\n".join(lines[separator_index + 1 :]).strip()
    return PromptFile(body=body, publish_at=publish_at, warnings=tuple(warnings))


def _sha256_file(path: Path, hasher: Any) -> None:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)


class PostQueue:
    """Čítanie fronty a archivácia spracovaných príspevkov."""

    def __init__(self, queue_dir: Path, timezone: ZoneInfo, min_file_age_seconds: int = 60) -> None:
        self._queue_dir = queue_dir
        self._timezone = timezone
        self._min_file_age = min_file_age_seconds
        self._reported_missing_prompt: set[str] = set()

    @property
    def queue_dir(self) -> Path:
        return self._queue_dir

    def ensure_dirs(self) -> None:
        for directory in (self._queue_dir, self._queue_dir / PUBLISHED_DIR, self._queue_dir / FAILED_DIR):
            directory.mkdir(parents=True, exist_ok=True)

    def scan(self, now: datetime) -> QueueScanResult:
        """Nájde pripravené, naplánované aj neplatné položky fronty."""
        self.ensure_dirs()
        result = QueueScanResult()
        media_by_stem: dict[str, list[Path]] = {}
        for path in sorted(self._queue_dir.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            suffix = path.suffix.lower()
            if suffix in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | UNSUPPORTED_MEDIA_EXTENSIONS:
                media_by_stem.setdefault(path.stem, []).append(path)

        for stem, media_paths in media_by_stem.items():
            prompt_path = self._queue_dir / f"{stem}.txt"
            all_paths = (*media_paths, prompt_path) if prompt_path.exists() else tuple(media_paths)

            if not self._is_stable(all_paths):
                continue  # súbor sa ešte pravdepodobne kopíruje
            if len(media_paths) > 1:
                result.invalid.append(
                    InvalidQueueEntry(stem, all_paths, "Viac médií s rovnakým názvom – nechaj len jedno.")
                )
                continue
            media_path = media_paths[0]
            suffix = media_path.suffix.lower()
            if suffix in UNSUPPORTED_MEDIA_EXTENSIONS:
                result.invalid.append(
                    InvalidQueueEntry(
                        stem,
                        all_paths,
                        f"Formát {suffix} Instagram API nepodporuje. Obrázky musia byť JPEG (.jpg), videá MP4/MOV.",
                    )
                )
                continue
            if not prompt_path.exists():
                if stem not in self._reported_missing_prompt:
                    logger.info("Médium %s čaká na textový súbor %s.txt.", media_path.name, stem)
                    self._reported_missing_prompt.add(stem)
                continue

            try:
                prompt_file = parse_prompt_file(prompt_path.read_text(encoding="utf-8"), self._timezone)
            except UnicodeDecodeError:
                result.invalid.append(InvalidQueueEntry(stem, all_paths, "Textový súbor nie je v kódovaní UTF-8."))
                continue
            except ValueError as exc:
                result.invalid.append(InvalidQueueEntry(stem, all_paths, str(exc)))
                continue
            for warning in prompt_file.warnings:
                logger.warning("%s.txt: %s", stem, warning)
            if not prompt_file.body:
                result.invalid.append(InvalidQueueEntry(stem, all_paths, "Textový súbor neobsahuje žiadny prompt."))
                continue

            item = QueueItem(
                name=stem,
                media_path=media_path,
                prompt_path=prompt_path,
                media_kind="IMAGE" if suffix in IMAGE_EXTENSIONS else "REELS",
                prompt_text=prompt_file.body,
                publish_at=prompt_file.publish_at,
                content_hash=self._content_hash(media_path, prompt_file.body),
                size_bytes=media_path.stat().st_size,
            )
            if item.publish_at and item.publish_at > now:
                result.scheduled.append(item)
            else:
                result.ready.append(item)

        result.ready.sort(key=lambda i: (i.publish_at.timestamp() if i.publish_at else 0.0, i.name))
        result.scheduled.sort(key=lambda i: (i.publish_at.timestamp() if i.publish_at else 0.0, i.name))
        return result

    def mark_published(self, item: QueueItem, details: dict[str, Any]) -> Path:
        """Presunie publikovaný príspevok do ``published/`` a uloží ``result.json``."""
        note = json.dumps(details, ensure_ascii=False, indent=2, default=str)
        return self._archive((item.media_path, item.prompt_path), PUBLISHED_DIR, item.name, "result.json", note)

    def mark_failed(self, name: str, paths: tuple[Path, ...], reason: str) -> Path:
        """Presunie neúspešný príspevok do ``failed/`` a uloží ``error.txt`` s dôvodom."""
        note = (
            f"Čas: {datetime.now(self._timezone).isoformat(timespec='seconds')}\n"
            f"Dôvod: {reason}\n\n"
            "Po oprave presuň súbory späť do priečinka queue/ – bot ich spracuje znova.\n"
        )
        return self._archive(paths, FAILED_DIR, name, "error.txt", note)

    # ------------------------------------------------------------------ interné
    def _is_stable(self, paths: tuple[Path, ...]) -> bool:
        """Súbory musia byť aspoň ``QUEUE_MIN_FILE_AGE_SECONDS`` nezmenené (dokončené kopírovanie)."""
        now = time.time()
        return all(now - path.stat().st_mtime >= self._min_file_age for path in paths if path.exists())

    @staticmethod
    def _content_hash(media_path: Path, prompt_text: str) -> str:
        """Odtlačok obsahu – rovnaký post sa nepublikuje dvakrát ani po premenovaní súborov."""
        hasher = hashlib.sha256()
        _sha256_file(media_path, hasher)
        hasher.update(b"\x00")
        hasher.update(prompt_text.encode("utf-8"))
        return hasher.hexdigest()

    def _archive(self, paths: tuple[Path, ...], subdir: str, name: str, note_name: str, note: str) -> Path:
        stamp = datetime.now(self._timezone).strftime("%Y%m%d-%H%M%S")
        target = self._queue_dir / subdir / f"{stamp}_{name}"
        suffix = 1
        while target.exists():
            suffix += 1
            target = self._queue_dir / subdir / f"{stamp}_{name}_{suffix}"
        target.mkdir(parents=True)
        for path in paths:
            if path.exists():
                shutil.move(str(path), str(target / path.name))
        (target / note_name).write_text(note, encoding="utf-8")
        self._reported_missing_prompt.discard(name)
        return target
