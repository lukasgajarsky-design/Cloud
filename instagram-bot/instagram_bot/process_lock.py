"""Zámok procesu – zabráni tomu, aby naraz bežali dve inštancie ``--run``.

Typický problém pri cron úlohách: predchádzajúci beh ešte nedobehol (napr.
čaká na spracovanie videa) a cron spustí ďalší. Dve inštancie by mohli
odpovedať na rovnaký komentár. Zámok je na úrovni operačného systému, takže
sa po páde procesu automaticky uvoľní.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import IO

from .exceptions import AlreadyRunningError


class ProcessLock:
    """Exkluzívny neblokujúci zámok súboru (``fcntl`` na Linuxe/macOS, ``msvcrt`` na Windows)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: IO[str] | None = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+", encoding="utf-8")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise AlreadyRunningError(
                f"Bot už beží (zámok {self._path} drží iný proces). Ukonči ho alebo počkaj na jeho dokončenie."
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> ProcessLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
