"""Znalostná báza bota: brand voice a Video Style Blueprint.

* ``config/brand_voice.md`` – ručne písaný popis značky: kto ste, ako hovoríte,
  fakty (otváracie hodiny, ceny, FAQ), čo bot nikdy nesmie sľúbiť.
* ``config/style_guide.txt`` – „Video Style Blueprint“ vygenerovaný režimom
  ``--learn`` z analýzy videa (rytmus strihu, titulky, hook/CTA, tón reči).

Súbory sa čítajú pri KAŽDOM volaní Claude (bot si blueprint „vždy najprv
načíta“), no vďaka kontrole času poslednej zmeny (mtime) sa z disku reálne
čítajú len vtedy, keď sa zmenili. Bežiaci bot (``--run``) tak nový blueprint
z ``--learn`` použije okamžite, bez reštartu.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

# Ochrana pred omylom obrovským súborom (napr. vložený log namiesto textu).
MAX_KNOWLEDGE_FILE_BYTES: Final[int] = 400_000


class CachedTextFile:
    """Textový súbor s cache podľa ``mtime`` a veľkosti."""

    def __init__(self, path: Path, label: str) -> None:
        self._path = path
        self._label = label
        self._signature: tuple[float, int] | None = None
        self._content: str | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> str | None:
        """Vráti obsah súboru, alebo ``None``, ak súbor neexistuje / je prázdny."""
        with self._lock:
            try:
                stat = self._path.stat()
            except FileNotFoundError:
                if self._signature is not None:
                    logger.warning("%s (%s) bol odstránený.", self._label, self._path)
                self._signature, self._content = None, None
                return None
            signature = (stat.st_mtime, stat.st_size)
            if signature == self._signature:
                return self._content
            if stat.st_size > MAX_KNOWLEDGE_FILE_BYTES:
                logger.error(
                    "%s je príliš veľký (%d B > %d B) – ignorujem ho.",
                    self._label,
                    stat.st_size,
                    MAX_KNOWLEDGE_FILE_BYTES,
                )
                self._signature, self._content = signature, None
                return None
            text = self._path.read_text(encoding="utf-8").strip()
            self._signature, self._content = signature, (text or None)
            logger.info("Načítaný %s (%s, %d znakov).", self._label, self._path.name, len(text))
            return self._content


@dataclass(frozen=True)
class KnowledgeSnapshot:
    """Aktuálny obsah oboch súborov v jednom okamihu."""

    brand_voice: str | None
    style_guide: str | None


class KnowledgeBase:
    """Poskytuje aktuálny brand voice a Video Style Blueprint."""

    def __init__(self, brand_voice_path: Path, style_guide_path: Path) -> None:
        self._brand_voice = CachedTextFile(brand_voice_path, "brand voice")
        self._style_guide = CachedTextFile(style_guide_path, "Video Style Blueprint")
        self._warned_missing_style = False

    @property
    def style_guide_path(self) -> Path:
        return self._style_guide.path

    def snapshot(self) -> KnowledgeSnapshot:
        """Načíta (alebo z cache vráti) oba súbory."""
        style_guide = self._style_guide.read()
        if style_guide is None and not self._warned_missing_style:
            logger.warning(
                "Video Style Blueprint (%s) zatiaľ neexistuje – bot použije len brand voice. "
                "Vytvoríš ho príkazom: python main.py --learn --video <video.mp4>",
                self._style_guide.path,
            )
            self._warned_missing_style = True
        elif style_guide is not None:
            self._warned_missing_style = False
        return KnowledgeSnapshot(brand_voice=self._brand_voice.read(), style_guide=style_guide)
