"""Načítanie a validácia konfigurácie z ``.env`` súboru.

Bezpečnostné zásady:

* Tajomstvá (tokeny, API kľúče) sa čítajú VÝHRADNE z prostredia / ``.env`` súboru
  cez ``python-dotenv`` – nikdy nie sú natvrdo v kóde.
* Premenné nastavené priamo v prostredí (napr. cez systemd alebo Docker secrets)
  majú prednosť pred hodnotami v ``.env`` (``override=False``).
* Polia s tajomstvami majú ``repr=False``, takže sa omylom nevypíšu do logu
  pri ``print(settings)`` ani v traceback-u.
* Validácia je „fail fast“: všetky chyby sa zozbierajú naraz a bot sa so
  zrozumiteľnou hláškou ukončí ešte pred prvým volaním API.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .exceptions import ConfigError

# Koreňový priečinok projektu (tam, kde je main.py). Relatívne cesty v .env sa
# rátajú od neho – vďaka tomu bot funguje rovnako aj z cronu, kde je pracovný
# adresár zvyčajne domovský priečinok používateľa.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# Povolené úrovne úsilia (effort) pre adaptívne premýšľanie Claude Opus 5.5.
VALID_EFFORTS: Final[frozenset[str]] = frozenset({"low", "medium", "high", "xhigh", "max"})

# Povolení poskytovatelia prepisu reči (ASR) v režime učenia z videa.
VALID_ASR_PROVIDERS: Final[frozenset[str]] = frozenset({"openai", "faster-whisper", "none"})

# Hostitelia Graph API: Instagram Login (graph.instagram.com) alebo Facebook Login
# (graph.facebook.com). Endpointy pre médiá, komentáre a publikovanie sú rovnaké.
VALID_GRAPH_HOSTS: Final[frozenset[str]] = frozenset({"graph.instagram.com", "graph.facebook.com"})

# Claude Opus 5.5 má 1M kontext a prijme až 600 obrázkov v jednej požiadavke.
MAX_IMAGES_PER_REQUEST: Final[int] = 600


class RunMode(str, Enum):
    """Režimy spustenia – každý potrebuje iné povinné nastavenia."""

    RUN = "run"
    LEARN = "learn"
    SCRIPT = "script"
    CHECK = "check"
    REFRESH_TOKEN = "refresh-token"  # noqa: S105 – názov režimu, nie heslo


@dataclass(frozen=True)
class Settings:
    """Nemenná (frozen) konfigurácia celej aplikácie.

    Inštanciu vytvárajte cez :meth:`Settings.load`, ktorá načíta ``.env``,
    skonvertuje typy a skontroluje rozsahy hodnôt.
    """

    # --- Meta Graph API -------------------------------------------------------
    meta_access_token: str = field(repr=False)
    instagram_account_id: str
    meta_graph_host: str
    meta_api_version: str
    meta_page_id: str | None
    meta_app_secret: str | None = field(repr=False)

    # --- Anthropic / Claude ---------------------------------------------------
    anthropic_api_key: str = field(repr=False)
    anthropic_model: str
    effort_replies: str
    effort_content: str
    effort_learn: str
    anthropic_max_retries: int
    anthropic_timeout_seconds: float
    anthropic_server_fallback: bool

    # --- Prepis reči (ASR) pre režim učenia -----------------------------------
    asr_provider: str
    openai_api_key: str = field(repr=False)
    openai_transcribe_model: str
    asr_language: str | None
    faster_whisper_model: str

    # --- Správanie bota -------------------------------------------------------
    enable_comments: bool
    enable_dms: bool
    enable_posts: bool
    dry_run: bool
    poll_interval_seconds: int
    max_media_to_scan: int
    max_comments_per_media: int
    comment_max_age_hours: int
    max_comment_replies_per_cycle: int
    max_dm_replies_per_cycle: int
    max_conversations_to_scan: int
    dm_history_messages: int
    min_seconds_between_actions: float
    comment_mention_user: bool
    comment_reply_max_chars: int
    dm_reply_max_chars: int

    # --- HTTP, retries a rate limiting ---------------------------------------
    request_timeout_seconds: float
    http_max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    usage_throttle_threshold: float
    max_throttle_sleep_seconds: float

    # --- Plánovanie príspevkov ------------------------------------------------
    queue_dir: Path
    media_public_base_url: str | None
    verify_media_url: bool
    max_posts_per_cycle: int
    queue_min_file_age_seconds: int
    timezone: ZoneInfo

    # --- Súbory a cesty -------------------------------------------------------
    database_path: Path
    log_file: Path
    log_level: str
    brand_voice_path: Path
    style_guide_path: Path
    scripts_output_dir: Path
    lock_file: Path
    env_file: Path | None

    # --- Režim učenia z videa -------------------------------------------------
    learn_scene_threshold: float
    learn_sample_fps: float
    learn_max_frames: int
    learn_frame_max_side: int
    learn_jpeg_quality: int
    learn_dedup_distance: int
    learn_max_video_seconds: int
    learn_max_request_mb: float
    learn_timeout_seconds: float
    learn_audio_chunk_seconds: int
    ffmpeg_binary: str
    ffprobe_binary: str

    @classmethod
    def load(cls, env_file: Path | None = None) -> Settings:
        """Načíta ``.env`` (ak existuje) a vytvorí validovanú inštanciu nastavení.

        :param env_file: voliteľná cesta k ``.env``; predvolene ``<projekt>/.env``.
        :raises ConfigError: ak je niektorá hodnota neplatná (typ, rozsah).
        """
        resolved_env = (env_file or PROJECT_ROOT / ".env").expanduser()
        if not resolved_env.is_absolute():
            resolved_env = (Path.cwd() / resolved_env).resolve()
        env_exists = resolved_env.is_file()
        if env_exists:
            # override=False: premenné z reálneho prostredia majú prednosť.
            load_dotenv(resolved_env, override=False, encoding="utf-8")
        elif env_file is not None:
            raise ConfigError(f"Zadaný .env súbor neexistuje: {resolved_env}")

        reader = _EnvReader()
        timezone_name = reader.text("BOT_TIMEZONE", "Europe/Bratislava")
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            reader.errors.append(f"BOT_TIMEZONE: neznáme časové pásmo '{timezone_name}'.")
            timezone = ZoneInfo("UTC")

        settings = cls(
            meta_access_token=reader.secret("META_ACCESS_TOKEN"),
            instagram_account_id=reader.text("INSTAGRAM_BUSINESS_ACCOUNT_ID", ""),
            meta_graph_host=reader.choice("META_GRAPH_HOST", "graph.instagram.com", VALID_GRAPH_HOSTS),
            meta_api_version=reader.text("META_API_VERSION", "v23.0"),
            meta_page_id=reader.optional("META_PAGE_ID"),
            meta_app_secret=reader.optional("META_APP_SECRET"),
            anthropic_api_key=reader.secret("ANTHROPIC_API_KEY"),
            anthropic_model=reader.text("ANTHROPIC_MODEL", "claude-opus-5-5"),
            effort_replies=reader.choice("ANTHROPIC_EFFORT_REPLIES", "medium", VALID_EFFORTS),
            effort_content=reader.choice("ANTHROPIC_EFFORT_CONTENT", "high", VALID_EFFORTS),
            effort_learn=reader.choice("ANTHROPIC_EFFORT_LEARN", "high", VALID_EFFORTS),
            anthropic_max_retries=reader.integer("ANTHROPIC_MAX_RETRIES", 5, 0, 10),
            anthropic_timeout_seconds=reader.number("ANTHROPIC_TIMEOUT_SECONDS", 600.0, 10.0, 3600.0),
            anthropic_server_fallback=reader.boolean("ANTHROPIC_SERVER_FALLBACK", True),
            asr_provider=reader.choice("ASR_PROVIDER", "openai", VALID_ASR_PROVIDERS),
            openai_api_key=reader.secret("OPENAI_API_KEY"),
            openai_transcribe_model=reader.text("OPENAI_TRANSCRIBE_MODEL", "whisper-1"),
            asr_language=reader.optional("ASR_LANGUAGE"),
            faster_whisper_model=reader.text("FASTER_WHISPER_MODEL", "small"),
            enable_comments=reader.boolean("ENABLE_COMMENTS", True),
            enable_dms=reader.boolean("ENABLE_DMS", True),
            enable_posts=reader.boolean("ENABLE_POSTS", True),
            dry_run=reader.boolean("DRY_RUN", False),
            poll_interval_seconds=reader.integer("POLL_INTERVAL_SECONDS", 300, 30, 86_400),
            max_media_to_scan=reader.integer("MAX_MEDIA_TO_SCAN", 5, 1, 50),
            max_comments_per_media=reader.integer("MAX_COMMENTS_PER_MEDIA", 50, 1, 500),
            comment_max_age_hours=reader.integer("COMMENT_MAX_AGE_HOURS", 48, 1, 24 * 30),
            max_comment_replies_per_cycle=reader.integer("MAX_COMMENT_REPLIES_PER_CYCLE", 20, 0, 500),
            max_dm_replies_per_cycle=reader.integer("MAX_DM_REPLIES_PER_CYCLE", 20, 0, 500),
            max_conversations_to_scan=reader.integer("MAX_CONVERSATIONS_TO_SCAN", 25, 1, 200),
            dm_history_messages=reader.integer("DM_HISTORY_MESSAGES", 10, 1, 20),
            min_seconds_between_actions=reader.number("MIN_SECONDS_BETWEEN_ACTIONS", 8.0, 0.0, 600.0),
            comment_mention_user=reader.boolean("COMMENT_MENTION_USER", True),
            comment_reply_max_chars=reader.integer("COMMENT_REPLY_MAX_CHARS", 500, 50, 2200),
            dm_reply_max_chars=reader.integer("DM_REPLY_MAX_CHARS", 900, 50, 1000),
            request_timeout_seconds=reader.number("REQUEST_TIMEOUT_SECONDS", 30.0, 5.0, 300.0),
            http_max_retries=reader.integer("HTTP_MAX_RETRIES", 5, 0, 10),
            backoff_base_seconds=reader.number("BACKOFF_BASE_SECONDS", 2.0, 0.1, 60.0),
            backoff_max_seconds=reader.number("BACKOFF_MAX_SECONDS", 120.0, 1.0, 3600.0),
            usage_throttle_threshold=reader.number("USAGE_THROTTLE_THRESHOLD", 75.0, 10.0, 99.0),
            max_throttle_sleep_seconds=reader.number("MAX_THROTTLE_SLEEP_SECONDS", 60.0, 0.0, 900.0),
            queue_dir=reader.path("QUEUE_DIR", "queue"),
            media_public_base_url=reader.optional("MEDIA_PUBLIC_BASE_URL"),
            verify_media_url=reader.boolean("VERIFY_MEDIA_URL", True),
            max_posts_per_cycle=reader.integer("MAX_POSTS_PER_CYCLE", 1, 0, 25),
            queue_min_file_age_seconds=reader.integer("QUEUE_MIN_FILE_AGE_SECONDS", 60, 0, 86_400),
            timezone=timezone,
            database_path=reader.path("DATABASE_PATH", "data/instagram_bot.db"),
            log_file=reader.path("LOG_FILE", "instagram_bot.log"),
            log_level=reader.choice("LOG_LEVEL", "INFO", frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})),
            brand_voice_path=reader.path("BRAND_VOICE_PATH", "config/brand_voice.md"),
            style_guide_path=reader.path("STYLE_GUIDE_PATH", "config/style_guide.txt"),
            scripts_output_dir=reader.path("SCRIPTS_OUTPUT_DIR", "output/scripts"),
            lock_file=reader.path("LOCK_FILE", "data/instagram_bot.lock"),
            env_file=resolved_env if env_exists else None,
            learn_scene_threshold=reader.number("LEARN_SCENE_THRESHOLD", 0.3, 0.05, 0.95),
            learn_sample_fps=reader.number("LEARN_SAMPLE_FPS", 1.0, 0.05, 10.0),
            learn_max_frames=reader.integer("LEARN_MAX_FRAMES", 240, 4, MAX_IMAGES_PER_REQUEST),
            learn_frame_max_side=reader.integer("LEARN_FRAME_MAX_SIDE", 768, 256, 2000),
            learn_jpeg_quality=reader.integer("LEARN_JPEG_QUALITY", 5, 2, 31),
            learn_dedup_distance=reader.integer("LEARN_DEDUP_DISTANCE", 6, 0, 64),
            learn_max_video_seconds=reader.integer("LEARN_MAX_VIDEO_SECONDS", 3600, 5, 4 * 3600),
            learn_max_request_mb=reader.number("LEARN_MAX_REQUEST_MB", 28.0, 1.0, 31.0),
            learn_timeout_seconds=reader.number("LEARN_TIMEOUT_SECONDS", 1800.0, 60.0, 7200.0),
            learn_audio_chunk_seconds=reader.integer("LEARN_AUDIO_CHUNK_SECONDS", 600, 60, 1800),
            ffmpeg_binary=reader.text("FFMPEG_BINARY", "ffmpeg"),
            ffprobe_binary=reader.text("FFPROBE_BINARY", "ffprobe"),
        )

        if settings.backoff_base_seconds > settings.backoff_max_seconds:
            reader.errors.append("BACKOFF_BASE_SECONDS nesmie byť väčšie ako BACKOFF_MAX_SECONDS.")
        if not settings.meta_api_version.startswith("v"):
            reader.errors.append("META_API_VERSION musí mať tvar 'vXX.X', napr. v23.0.")

        if reader.errors:
            raise ConfigError("Neplatná konfigurácia:\n  - " + "\n  - ".join(reader.errors))
        return settings

    def validate_for(self, mode: RunMode) -> None:
        """Skontroluje, že sú vyplnené všetky povinné hodnoty pre daný režim.

        Napr. režim ``--learn`` nepotrebuje Meta token, ale potrebuje Anthropic
        kľúč a (pri ASR cez OpenAI) aj OpenAI kľúč.

        :raises ConfigError: so zoznamom všetkých chýbajúcich hodnôt.
        """
        missing: list[str] = []
        problems: list[str] = []

        needs_meta = mode in {RunMode.RUN, RunMode.CHECK, RunMode.REFRESH_TOKEN}
        needs_claude = mode in {RunMode.RUN, RunMode.LEARN, RunMode.SCRIPT}

        if needs_meta and not self.meta_access_token:
            missing.append("META_ACCESS_TOKEN")
        if mode in {RunMode.RUN, RunMode.CHECK} and not self.instagram_account_id:
            missing.append("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        if (
            mode in {RunMode.RUN, RunMode.CHECK}
            and self.instagram_account_id
            and not self.instagram_account_id.isdigit()
        ):
            problems.append("INSTAGRAM_BUSINESS_ACCOUNT_ID musí byť číselné ID (napr. 17841400000000000).")
        if needs_claude and not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")

        if mode is RunMode.RUN and self.enable_posts:
            if not self.media_public_base_url:
                missing.append("MEDIA_PUBLIC_BASE_URL (alebo nastav ENABLE_POSTS=false)")
            elif not self.media_public_base_url.startswith("https://"):
                problems.append(
                    "MEDIA_PUBLIC_BASE_URL musí začínať https:// (Meta sťahuje médiá z verejnej HTTPS URL)."
                )

        if mode is RunMode.LEARN and self.asr_provider == "openai" and not self.openai_api_key:
            missing.append("OPENAI_API_KEY (alebo nastav ASR_PROVIDER=faster-whisper / none)")

        if mode is RunMode.REFRESH_TOKEN and self.meta_graph_host != "graph.instagram.com":
            problems.append(
                "Obnova tokenu cez --refresh-token funguje len pre Instagram Login "
                "(META_GRAPH_HOST=graph.instagram.com). Page token z Facebook Login neexpiruje."
            )

        if missing:
            problems.insert(0, "Chýbajú povinné hodnoty v .env: " + ", ".join(missing))
        if problems:
            raise ConfigError("\n  - ".join(["Konfigurácia nie je kompletná:", *problems]))

    def secret_values(self) -> list[str]:
        """Zoznam tajomstiev – logovací filter ich nahradí hviezdičkami."""
        candidates = [self.meta_access_token, self.anthropic_api_key, self.openai_api_key, self.meta_app_secret]
        return [value for value in candidates if value]

    def security_warnings(self) -> list[str]:
        """Bezpečnostné upozornenia, ktoré sa zalogujú po štarte (nie sú fatálne)."""
        warnings: list[str] = []
        if self.env_file is not None and os.name == "posix":
            mode = self.env_file.stat().st_mode
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                warnings.append(
                    f"Súbor {self.env_file} je čitateľný aj pre iných používateľov. "
                    f"Odporúčanie: chmod 600 {self.env_file}"
                )
        if self.meta_graph_host == "graph.facebook.com" and not self.meta_app_secret:
            warnings.append(
                "META_APP_SECRET nie je nastavený – odporúčame zapnúť 'Require App Secret' "
                "v nastaveniach Meta aplikácie a doplniť ho (bot potom posiela appsecret_proof)."
            )
        return warnings


class _EnvReader:
    """Pomocná trieda na čítanie premenných prostredia s konverziou typov.

    Chyby sa nevyhadzujú hneď, ale zbierajú v ``errors`` – používateľ tak
    uvidí všetky problémy naraz a nemusí bota spúšťať opakovane.
    """

    # Hodnoty, ktoré vyzerajú ako nevyplnená šablóna z .env.example.
    _PLACEHOLDER_PREFIXES: Final[tuple[str, ...]] = ("your_", "tvoj_", "<", "xxx", "changeme")

    def __init__(self) -> None:
        self.errors: list[str] = []

    def _raw(self, name: str) -> str | None:
        value = os.environ.get(name)
        if value is None:
            return None
        value = value.strip()
        return value or None

    def text(self, name: str, default: str) -> str:
        return self._raw(name) or default

    def optional(self, name: str) -> str | None:
        value = self._raw(name)
        if value and value.lower().startswith(self._PLACEHOLDER_PREFIXES):
            return None
        return value

    def secret(self, name: str) -> str:
        """Tajomstvo – placeholder zo šablóny sa považuje za nevyplnenú hodnotu."""
        return self.optional(name) or ""

    def choice(self, name: str, default: str, allowed: frozenset[str]) -> str:
        value = self._raw(name) or default
        # Úrovne effort a ASR sú malými písmenami, LOG_LEVEL veľkými – porovnávame tolerantne.
        normalized = value.upper() if default.isupper() else value.lower()
        if normalized not in allowed:
            self.errors.append(f"{name}: hodnota '{value}' nie je povolená ({', '.join(sorted(allowed))}).")
            return default
        return normalized

    def boolean(self, name: str, default: bool) -> bool:
        value = self._raw(name)
        if value is None:
            return default
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "ano", "áno", "on"}:
            return True
        if lowered in {"0", "false", "no", "nie", "off"}:
            return False
        self.errors.append(f"{name}: '{value}' nie je logická hodnota (true/false).")
        return default

    def integer(self, name: str, default: int, minimum: int, maximum: int) -> int:
        value = self._raw(name)
        if value is None:
            return default
        try:
            parsed = int(value)
        except ValueError:
            self.errors.append(f"{name}: '{value}' nie je celé číslo.")
            return default
        if not minimum <= parsed <= maximum:
            self.errors.append(f"{name}: {parsed} musí byť v rozsahu {minimum}–{maximum}.")
            return default
        return parsed

    def number(self, name: str, default: float, minimum: float, maximum: float) -> float:
        value = self._raw(name)
        if value is None:
            return default
        try:
            parsed = float(value.replace(",", "."))
        except ValueError:
            self.errors.append(f"{name}: '{value}' nie je číslo.")
            return default
        if not minimum <= parsed <= maximum:
            self.errors.append(f"{name}: {parsed} musí byť v rozsahu {minimum}–{maximum}.")
            return default
        return parsed

    def path(self, name: str, default: str) -> Path:
        raw = Path(self._raw(name) or default).expanduser()
        return raw if raw.is_absolute() else (PROJECT_ROOT / raw)
