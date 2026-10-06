"""Vlastné výnimky projektu.

Každá vrstva aplikácie vyhadzuje vlastný typ výnimky. Vďaka tomu môže trieda
``InstagramBot`` presne rozhodnúť, čo s chybou urobiť – napríklad pri chybe
autentifikácie bot zastaví, pri rate limite si dá pauzu a pri bežnej chybe
jedného komentára pokračuje ďalším.
"""

from __future__ import annotations


class InstagramBotError(Exception):
    """Spoločný predok všetkých chýb tohto projektu."""


class ConfigError(InstagramBotError):
    """Chýbajúce alebo neplatné nastavenie v ``.env``."""


class AlreadyRunningError(InstagramBotError):
    """Iná inštancia bota už beží (drží zámok) – zabraňuje prekrývaniu cron úloh."""


class MetaApiError(InstagramBotError):
    """Chyba vrátená Meta Graph API (alebo chyba pri komunikácii s ním).

    Atribúty zodpovedajú objektu ``error`` z odpovede Graph API, aby sa dali
    chyby presne logovať a dohľadať (``fbtrace_id`` sa hodí pri komunikácii s Meta).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: int | None = None,
        subcode: int | None = None,
        fbtrace_id: str | None = None,
        is_transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.subcode = subcode
        self.fbtrace_id = fbtrace_id
        self.is_transient = is_transient

    def __str__(self) -> str:
        details = []
        if self.status_code is not None:
            details.append(f"HTTP {self.status_code}")
        if self.code is not None:
            details.append(f"code={self.code}")
        if self.subcode is not None:
            details.append(f"subcode={self.subcode}")
        if self.fbtrace_id:
            details.append(f"fbtrace_id={self.fbtrace_id}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"{self.message}{suffix}"


class MetaAuthError(MetaApiError):
    """Neplatný alebo expirovaný access token (Graph API kód 190) – bot nemôže pokračovať."""


class MetaRateLimitError(MetaApiError):
    """Prekročený limit volaní; ``retry_after_seconds`` hovorí, kedy to skúsiť znova."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float,
        status_code: int | None = None,
        code: int | None = None,
        subcode: int | None = None,
        fbtrace_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code=code,
            subcode=subcode,
            fbtrace_id=fbtrace_id,
            is_transient=True,
        )
        self.retry_after_seconds = retry_after_seconds


class MetaNetworkError(MetaApiError):
    """Sieťová chyba po vyčerpaní pokusov.

    ``ambiguous=True`` znamená, že požiadavka mohla na serveri prejsť (napr. timeout
    pri čítaní odpovede). Pri zápisových operáciách (odpoveď na komentár, publikovanie)
    ju preto nesmieme automaticky opakovať – hrozila by duplicita.
    """

    def __init__(self, message: str, *, ambiguous: bool) -> None:
        super().__init__(message)
        self.ambiguous = ambiguous


class ClaudeError(InstagramBotError):
    """Chyba pri volaní Claude (po vyčerpaní automatických pokusov SDK)."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ClaudeAuthError(ClaudeError):
    """Neplatný Anthropic API kľúč, chýbajúce oprávnenie alebo neexistujúci model – fatálne."""


class MediaHostError(InstagramBotError):
    """Médium nie je dostupné na verejnej URL, ktorú potrebuje Meta API."""


class FFmpegNotFoundError(InstagramBotError):
    """V systéme chýba ``ffmpeg`` alebo ``ffprobe``."""


class FFmpegError(InstagramBotError):
    """``ffmpeg``/``ffprobe`` skončil chybou."""


class TranscriptionError(InstagramBotError):
    """Prepis zvukovej stopy na text zlyhal."""


class StyleLearningError(InstagramBotError):
    """Chyba v režime učenia štýlu z videa (neplatný vstup, prázdny výsledok, …)."""
