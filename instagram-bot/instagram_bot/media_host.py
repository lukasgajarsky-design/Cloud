"""Sprístupnenie lokálnych médií pre Meta API.

Instagram Graph API neprijíma súbory priamo – pri publikovaní mu odovzdáme
verejnú HTTPS adresu (``image_url`` / ``video_url``) a Meta si súbor stiahne.
Preto musí byť priečinok ``queue/`` dostupný z internetu, napr.:

* cez nginx/Caddy na vašom serveri (iba prípony .jpg/.jpeg/.mp4/.mov!),
* cez synchronizovaný bucket (S3, Cloudflare R2, Google Cloud Storage).

Rozhranie ``MediaHost`` umožňuje neskôr doplniť napr. priamy upload do S3
bez zmeny zvyšku kódu.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import requests

from .exceptions import MediaHostError

logger = logging.getLogger(__name__)


class MediaHost(Protocol):
    """Rozhranie: z lokálnej cesty urobí verejnú URL, ktorú si Meta vie stiahnuť."""

    def public_url_for(self, file_path: Path) -> str: ...

    def verify(self, url: str, expected_size: int) -> None: ...


class PublicUrlMediaHost:
    """Súbory z ``queue/`` sú dostupné na ``MEDIA_PUBLIC_BASE_URL/<názov súboru>``."""

    def __init__(
        self,
        base_url: str,
        queue_dir: Path,
        *,
        verify_enabled: bool = True,
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise MediaHostError("MEDIA_PUBLIC_BASE_URL musí začínať https://")
        self._base_url = base_url.rstrip("/")
        self._queue_dir = queue_dir.resolve()
        self._verify_enabled = verify_enabled
        self._timeout = timeout_seconds
        self._session = session or requests.Session()

    def public_url_for(self, file_path: Path) -> str:
        """Prevedie cestu v ``queue/`` na URL (s korektným URL-kódovaním názvu)."""
        try:
            relative = file_path.resolve().relative_to(self._queue_dir)
        except ValueError as exc:
            raise MediaHostError(f"Súbor {file_path} nie je v priečinku fronty {self._queue_dir}.") from exc
        return f"{self._base_url}/{quote(relative.as_posix())}"

    def verify(self, url: str, expected_size: int) -> None:
        """Overí (HEAD požiadavkou), že médium je verejne dostupné a má správnu veľkosť.

        Chybu odhalíme skôr, než ju Meta vráti ako nejasné „Media download failed“.
        """
        if not self._verify_enabled:
            return
        try:
            response = self._session.head(url, timeout=self._timeout, allow_redirects=True)
        except requests.RequestException as exc:
            raise MediaHostError(f"Médium nie je dostupné na {url}: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise MediaHostError(f"Médium na {url} vrátilo HTTP {response.status_code} (očakávané 200).")
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) != expected_size:
            raise MediaHostError(
                f"Veľkosť média na {url} ({length} B) nesedí s lokálnym súborom ({expected_size} B) – "
                "server pravdepodobne ešte nemá aktuálnu verziu."
            )
        logger.debug("Médium je verejne dostupné: %s", url)
