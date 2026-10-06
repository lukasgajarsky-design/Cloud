"""Nastavenie logovania do súboru ``instagram_bot.log`` a na konzolu.

* Súbor sa rotuje (max. 5 MB × 5 záloh), aby nezaplnil disk pri dlhom behu.
* Každý riadok prechádza maskovaním tajomstiev: access tokeny, API kľúče
  a ``appsecret_proof`` sa nikdy nedostanú do logu – ani v traceback-u výnimky.
* Úrovne: INFO pre bežné udalosti (odoslaná odpoveď, publikovaný post),
  WARNING pre veci na kontrolu človekom, ERROR pre zlyhania.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

# Vzory tajomstiev, ktoré maskujeme aj vtedy, keď nie sú v zozname známych hodnôt
# (napr. token v URL, ktorú vypíše knižnica requests vo výnimke).
_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(access_token=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(appsecret_proof=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(Authorization:?\s*(?:Bearer|OAuth)\s+)[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{16,}"),
    re.compile(r"()sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"()sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"()\b(?:EAA|IGQ|IGA)[A-Za-z0-9_\-]{30,}"),
)
_MASK: Final[str] = "***"


class SecretRedactingFormatter(logging.Formatter):
    """Formatter, ktorý po naformátovaní záznamu zamaskuje všetky tajomstvá."""

    def __init__(self, secrets: Iterable[str], fmt: str = LOG_FORMAT, datefmt: str = DATE_FORMAT) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        # Krátke reťazce nemaskujeme – hrozilo by poškodenie bežného textu.
        self._secrets = sorted({s for s in secrets if s and len(s) >= 8}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        """Nahradí známe tajomstvá aj typické vzory tokenov reťazcom ``***``."""
        for secret in self._secrets:
            text = text.replace(secret, _MASK)
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(lambda match: f"{match.group(1)}{_MASK}", text)
        return text

    def format(self, record: logging.LogRecord) -> str:
        return self.redact(super().format(record))


def setup_logging(log_file: Path, level: str = "INFO", secrets: Iterable[str] = ()) -> logging.Logger:
    """Nakonfiguruje koreňový logger a vráti logger aplikácie ``instagram_bot``.

    :param log_file: cesta k logu (predvolene ``instagram_bot.log`` v koreni projektu).
    :param level: minimálna úroveň (DEBUG/INFO/WARNING/ERROR).
    :param secrets: hodnoty, ktoré sa nesmú objaviť v logu.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = SecretRedactingFormatter(secrets)

    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    # Pri opakovanom volaní (napr. v testoch) odstránime staré handlery,
    # aby sa riadky v logu neduplikovali.
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(level.upper())

    # Knižnice tretích strán sú pri INFO príliš „ukecané“ – necháme len varovania.
    for noisy in ("urllib3", "httpx", "httpx2", "httpcore", "anthropic", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger("instagram_bot")
