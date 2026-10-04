"""Trieda ``InstagramBot`` – orchestrátor všetkých funkcií.

Režimy (volané z ``main.py``):

* ``run_forever`` / ``run_once`` (``--run``) – monitoring komentárov, odpovede v DM
  a publikovanie príspevkov z ``queue/``. Pred každým volaním Claude sa načíta
  aktuálny ``config/style_guide.txt`` (Video Style Blueprint) a vloží do system promptu.
* ``learn_style_from_video`` (``--learn --video``) – vytvorí blueprint z videa.
* ``generate_video_script`` (``--script``) – nový scenár videa podľa blueprintu.
* ``check`` (``--check``) – overenie tokenu, prístupov a nastavení.
* ``refresh_token`` (``--refresh-token``) – predĺženie Instagram tokenu o 60 dní.

Komponenty (API klienti, databáza…) sa vytvárajú lenivo (``cached_property``),
takže napr. ``--learn`` nepotrebuje Meta token a ``--script`` nepotrebuje ffmpeg.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from types import FrameType
from typing import Final

from dotenv import set_key

from .claude_client import ClaudeAssistant
from .config import Settings
from .exceptions import (
    ClaudeAuthError,
    ClaudeError,
    ConfigError,
    InstagramBotError,
    MediaHostError,
    MetaApiError,
    MetaAuthError,
    MetaNetworkError,
    MetaRateLimitError,
)
from .graph_client import MetaGraphClient
from .instagram_api import InstagramAPI
from .knowledge import KnowledgeBase
from .media_host import MediaHost, PublicUrlMediaHost
from .models import (
    AccountProfile,
    Comment,
    CycleReport,
    DirectMessage,
    Media,
    ReplyAction,
    ReplyDecision,
)
from .post_queue import PostQueue, QueueItem
from .process_lock import ProcessLock
from .storage import StateStore, Status
from .text_utils import (
    INSTAGRAM_DM_MAX_BYTES,
    clean_reply,
    compose_caption,
    slugify,
    truncate_text,
    truncate_utf8_bytes,
)
from .video.ffmpeg import FFmpegToolkit
from .video.style_learner import StyleLearningResult, VideoStyleLearner
from .video.transcription import (
    FasterWhisperTranscriber,
    NullTranscriber,
    OpenAIWhisperTranscriber,
    Transcriber,
)

logger = logging.getLogger(__name__)

VALID_TASKS: Final[tuple[str, ...]] = ("comments", "dms", "posts")
# Instagram dovoľuje odpovedať na DM štandardne len do 24 h od poslednej správy zákazníka.
DM_REPLY_WINDOW: Final[timedelta] = timedelta(hours=24)
# Kód chyby Messaging API pre správu mimo povoleného okna.
_OUTSIDE_WINDOW_SUBCODE: Final[int] = 2534022
# Po koľkých neúspešných pokusoch (trvalá chyba Claude) označiť položku ako „failed“.
_MAX_ITEM_FAILURES: Final[int] = 3


class InstagramBot:
    """Produkčný Instagram bot riadený modelom Claude Opus 5.5."""

    def __init__(self, settings: Settings, *, dry_run: bool | None = None) -> None:
        self.settings = settings
        self.dry_run = settings.dry_run if dry_run is None else dry_run
        self._stop_event = threading.Event()
        self._last_action_at = 0.0
        self._cooldown_until = 0.0
        self._lock: ProcessLock | None = None
        # V dry-run režime si pamätáme spracované položky len v pamäti (nič sa neukladá).
        self._dry_run_seen: set[str] = set()
        # Počty trvalých chýb Claude pre konkrétne položky (ochrana pred „jedovatou“ položkou).
        self._failure_counts: dict[str, int] = {}

    # ================================================================ komponenty
    @cached_property
    def store(self) -> StateStore:
        return StateStore(self.settings.database_path)

    @cached_property
    def knowledge(self) -> KnowledgeBase:
        return KnowledgeBase(self.settings.brand_voice_path, self.settings.style_guide_path)

    @cached_property
    def assistant(self) -> ClaudeAssistant:
        s = self.settings
        return ClaudeAssistant(
            api_key=s.anthropic_api_key,
            model=s.anthropic_model,
            knowledge=self.knowledge,
            effort_replies=s.effort_replies,
            effort_content=s.effort_content,
            effort_learn=s.effort_learn,
            max_retries=s.anthropic_max_retries,
            timeout_seconds=s.anthropic_timeout_seconds,
            learn_timeout_seconds=s.learn_timeout_seconds,
            server_fallback=s.anthropic_server_fallback,
            comment_max_chars=s.comment_reply_max_chars,
            dm_max_chars=s.dm_reply_max_chars,
        )

    @cached_property
    def graph(self) -> MetaGraphClient:
        s = self.settings
        return MetaGraphClient(
            access_token=s.meta_access_token,
            host=s.meta_graph_host,
            api_version=s.meta_api_version,
            app_secret=s.meta_app_secret,
            timeout_seconds=s.request_timeout_seconds,
            max_retries=s.http_max_retries,
            backoff_base_seconds=s.backoff_base_seconds,
            backoff_max_seconds=s.backoff_max_seconds,
            usage_throttle_threshold=s.usage_throttle_threshold,
            max_throttle_sleep_seconds=s.max_throttle_sleep_seconds,
            sleep=self._interruptible_sleep,
        )

    @cached_property
    def api(self) -> InstagramAPI:
        return InstagramAPI(
            self.graph,
            account_id=self.settings.instagram_account_id,
            graph_host=self.settings.meta_graph_host,
            page_id=self.settings.meta_page_id,
            sleep=self._interruptible_sleep,
        )

    @cached_property
    def profile(self) -> AccountProfile:
        profile = self.api.get_profile()
        if not profile.username:
            raise MetaApiError("Graph API nevrátilo používateľské meno účtu – skontroluj oprávnenia tokenu.")
        logger.info("Prihlásený Instagram účet: @%s (ID %s)", profile.username, ", ".join(sorted(profile.identifiers)))
        return profile

    @cached_property
    def post_queue(self) -> PostQueue:
        return PostQueue(self.settings.queue_dir, self.settings.timezone, self.settings.queue_min_file_age_seconds)

    @cached_property
    def media_host(self) -> MediaHost:
        if not self.settings.media_public_base_url:
            raise ConfigError("Publikovanie vyžaduje MEDIA_PUBLIC_BASE_URL v .env.")
        return PublicUrlMediaHost(
            self.settings.media_public_base_url,
            self.settings.queue_dir,
            verify_enabled=self.settings.verify_media_url,
            timeout_seconds=self.settings.request_timeout_seconds,
        )

    # ============================================================ životný cyklus
    def __enter__(self) -> InstagramBot:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Uvoľní zámok a zatvorí spojenia (len tie, ktoré sa naozaj vytvorili)."""
        if "graph" in self.__dict__:
            self.graph.close()
        if "store" in self.__dict__:
            self.store.close()
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    def stop(self) -> None:
        """Požiada bežiacu slučku o bezpečné ukončenie (po dokončení aktuálnej operácie)."""
        self._stop_event.set()

    def _acquire_lock(self) -> None:
        if self._lock is None:
            lock = ProcessLock(self.settings.lock_file)
            lock.acquire()
            self._lock = lock

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return

        def handler(signum: int, _frame: FrameType | None) -> None:
            logger.info("Prijatý signál %s – dokončím aktuálnu operáciu a skončím.", signal.Signals(signum).name)
            self.stop()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def _interruptible_sleep(self, seconds: float) -> None:
        """Pauza, ktorú preruší Ctrl+C / SIGTERM (bot nečaká zbytočne celý interval)."""
        if seconds > 0:
            self._stop_event.wait(seconds)

    def _pace(self) -> None:
        """Minimálny odstup medzi zápisovými akciami – prirodzené tempo a ochrana pred spam filtrom."""
        elapsed = time.monotonic() - self._last_action_at
        remaining = self.settings.min_seconds_between_actions - elapsed
        if remaining > 0:
            self._interruptible_sleep(remaining)
        self._last_action_at = time.monotonic()

    # ============================================================= režim --run
    def run_forever(self, tasks: Sequence[str] = VALID_TASKS) -> None:
        """Nekonečná slučka: cyklus → pauza ``POLL_INTERVAL_SECONDS`` → cyklus…"""
        self._acquire_lock()
        self._install_signal_handlers()
        logger.info(
            "Bot štartuje v slučke (interval %d s, úlohy: %s, dry-run: %s).",
            self.settings.poll_interval_seconds,
            ", ".join(tasks),
            "áno" if self.dry_run else "nie",
        )
        while not self._stop_event.is_set():
            cooldown = self._cooldown_until - time.monotonic()
            if cooldown > 0:
                logger.warning("Rate limit Meta API – pauza %.0f s pred ďalším cyklom.", cooldown)
                self._interruptible_sleep(cooldown)
                continue
            self.run_once(tasks)
            if not self._stop_event.is_set():
                logger.info("Ďalší cyklus o %d s.", self.settings.poll_interval_seconds)
                self._interruptible_sleep(self.settings.poll_interval_seconds)
        logger.info("Bot bol bezpečne ukončený.")

    def run_once(self, tasks: Sequence[str] = VALID_TASKS) -> CycleReport:
        """Jeden cyklus všetkých zapnutých úloh (vhodné pre cron: ``--run --once``).

        :raises MetaAuthError: neplatný Meta token (bez neho nemá zmysel pokračovať).
        :raises ClaudeAuthError: neplatný Anthropic kľúč alebo model.
        """
        self._acquire_lock()
        report = CycleReport()
        enabled: dict[str, tuple[bool, Callable[[], int]]] = {
            "comments": (self.settings.enable_comments, self.process_comments),
            "dms": (self.settings.enable_dms, self.process_direct_messages),
            "posts": (self.settings.enable_posts, self.process_post_queue),
        }
        logger.info("=== Začiatok cyklu (%s) ===", ", ".join(tasks))
        for task in tasks:
            is_enabled, handler = enabled[task]
            if not is_enabled:
                logger.info("Úloha '%s' je vypnutá v .env – preskakujem.", task)
                continue
            if self._stop_event.is_set():
                break
            if time.monotonic() < self._cooldown_until:
                logger.warning("Meta API je dočasne zablokované (rate limit) – úlohu '%s' preskakujem.", task)
                continue
            try:
                count = handler()
            except (MetaAuthError, ClaudeAuthError):
                raise
            except MetaRateLimitError as exc:
                self._cooldown_until = time.monotonic() + exc.retry_after_seconds
                logger.error("Úloha '%s' prerušená – rate limit Meta API: %s", task, exc)
                report.errors.append(f"{task}: {exc}")
                continue
            except (InstagramBotError, OSError) as exc:
                logger.error("Úloha '%s' zlyhala: %s", task, exc)
                report.errors.append(f"{task}: {exc}")
                continue
            except Exception as exc:  # posledná poistka – slučka musí bežať ďalej
                logger.exception("Neočakávaná chyba v úlohe '%s'.", task)
                report.errors.append(f"{task}: {type(exc).__name__}: {exc}")
                continue
            if task == "comments":
                report.comment_replies = count
            elif task == "dms":
                report.dm_replies = count
            else:
                report.posts_published = count
        logger.info("=== Koniec cyklu – %s ===", report.summary())
        return report

    # -------------------------------------------------------------- komentáre
    def process_comments(self) -> int:
        """Skontroluje najnovšie príspevky a odpovie na nové komentáre. Vracia počet odpovedí."""
        s = self.settings
        profile = self.profile
        cutoff = datetime.now(timezone.utc) - timedelta(hours=s.comment_max_age_hours)
        replies_sent = 0
        media_list = self.api.get_recent_media(s.max_media_to_scan)
        logger.info("Kontrolujem komentáre pod najnovšími príspevkami (počet: %d).", len(media_list))

        for media in media_list:
            if media.comments_count == 0:
                continue
            comments = sorted(
                self.api.get_comments(media.id, s.max_comments_per_media),
                key=lambda c: c.timestamp.timestamp() if c.timestamp else 0.0,
            )
            for comment in comments:
                if self._stop_event.is_set():
                    return replies_sent
                if replies_sent >= s.max_comment_replies_per_cycle:
                    logger.info("Dosiahnutý limit %d odpovedí na komentáre za cyklus.", s.max_comment_replies_per_cycle)
                    return replies_sent
                if self._handle_comment(comment, media, profile, cutoff):
                    replies_sent += 1
        return replies_sent

    def _handle_comment(self, comment: Comment, media: Media, profile: AccountProfile, cutoff: datetime) -> bool:
        """Spracuje jeden komentár. Vracia ``True``, ak bola odoslaná odpoveď."""
        store = self.store
        if comment.id in self._dry_run_seen or store.is_comment_known(comment.id):
            return False

        skip_status = self._comment_skip_reason(comment, profile, cutoff)
        if skip_status is not None:
            if not self.dry_run:
                store.mark_comment(comment.id, media.id, skip_status)
            return False

        if not self.dry_run and not store.claim_comment(comment.id, media.id):
            return False  # iný proces si ho medzitým zabral

        try:
            decision = self.assistant.decide_comment_reply(comment, media)
        except ClaudeError as exc:
            self._handle_claude_failure(
                exc,
                comment.id,
                release=lambda: store.release_comment(comment.id),
                fail=lambda detail: store.finish_comment(comment.id, Status.FAILED, detail=detail),
            )
            return False

        if decision.action is not ReplyAction.REPLY:
            self._record_non_reply(
                decision, item=f"komentár {comment.id} od @{comment.username}", permalink=media.permalink
            )
            if self.dry_run:
                self._dry_run_seen.add(comment.id)
            else:
                status = Status.ESCALATED if decision.action is ReplyAction.ESCALATE else Status.IGNORED
                store.finish_comment(comment.id, status, detail=decision.reason)
            return False

        text = self._format_comment_reply(decision.reply_text, comment)
        if self.dry_run:
            logger.info("[DRY-RUN] Odpoveď na komentár @%s „%s“ → %s", comment.username, comment.text[:80], text)
            self._dry_run_seen.add(comment.id)
            return False

        self._pace()
        try:
            reply_id = self.api.reply_to_comment(comment.id, text)
        except (MetaRateLimitError, MetaAuthError):
            store.release_comment(comment.id)  # požiadavka bola odmietnutá → bezpečné zopakovať neskôr
            raise
        except MetaNetworkError as exc:
            status = Status.UNKNOWN if exc.ambiguous else Status.FAILED
            store.finish_comment(comment.id, status, detail=str(exc))
            logger.error("Odpoveď na komentár %s: %s", comment.id, exc)
            return False
        except MetaApiError as exc:
            store.finish_comment(comment.id, Status.FAILED, detail=str(exc))
            logger.error("Odpoveď na komentár %s zlyhala: %s", comment.id, exc)
            return False

        store.finish_comment(comment.id, Status.REPLIED, reply_id=reply_id, detail=decision.reason)
        logger.info("Odpovedané na komentár @%s („%s“): %s", comment.username, comment.text[:80], text)
        return True

    def _comment_skip_reason(self, comment: Comment, profile: AccountProfile, cutoff: datetime) -> str | None:
        if comment.timestamp and comment.timestamp < cutoff:
            return Status.SKIPPED_OLD
        if profile.is_own(user_id=comment.author_id, username=comment.username):
            return Status.SKIPPED_OWN
        if any(name.lower() == profile.username.lower() for name in comment.reply_usernames):
            return Status.SKIPPED_ANSWERED
        if not comment.text.strip():
            return Status.SKIPPED_EMPTY
        return None

    def _format_comment_reply(self, reply: str, comment: Comment) -> str:
        text = clean_reply(reply)
        if self.settings.comment_mention_user and comment.username:
            mention = f"@{comment.username}"
            if not text.lower().startswith(mention.lower()):
                text = f"{mention} {text}"
        return truncate_text(text, self.settings.comment_reply_max_chars)

    # ---------------------------------------------------------------- DM správy
    def process_direct_messages(self) -> int:
        """Odpovie na nevyriešené konverzácie (posledná správa je od zákazníka)."""
        s = self.settings
        profile = self.profile
        now = datetime.now(timezone.utc)
        replies_sent = 0
        conversations = self.api.get_conversations(s.max_conversations_to_scan)
        logger.info("Kontrolujem DM konverzácie (počet: %d).", len(conversations))

        for conversation in conversations:
            if self._stop_event.is_set() or replies_sent >= s.max_dm_replies_per_cycle:
                break
            if conversation.updated_time and now - conversation.updated_time > DM_REPLY_WINDOW:
                continue  # mimo 24 h okna – odpoveď by API aj tak odmietlo
            messages = self.api.get_conversation_messages(conversation.id, s.dm_history_messages)
            if self._handle_conversation(conversation.id, messages, profile, now):
                replies_sent += 1
        return replies_sent

    def _handle_conversation(
        self, conversation_id: str, messages: list[DirectMessage], profile: AccountProfile, now: datetime
    ) -> bool:
        """Spracuje jednu konverzáciu. Vracia ``True``, ak bola odoslaná odpoveď."""
        if not messages:
            return False
        own_flags = [profile.is_own(user_id=m.sender_id, username=m.sender_username) for m in messages]
        if own_flags[-1]:
            return False  # posledná správa je naša → vyriešené
        last_own_index = max((i for i, own in enumerate(own_flags) if own), default=-1)
        pending = messages[last_own_index + 1 :]
        latest = pending[-1]
        pending_ids = [m.id for m in pending]
        store = self.store

        if latest.id in self._dry_run_seen or store.is_message_known(latest.id):
            return False
        if latest.created_time and now - latest.created_time > DM_REPLY_WINDOW:
            if not self.dry_run:
                store.mark_messages(pending_ids, conversation_id, Status.SKIPPED_WINDOW)
            return False
        if not latest.sender_id:
            if not self.dry_run:
                store.mark_messages(pending_ids, conversation_id, Status.FAILED, "chýba ID odosielateľa")
            return False
        if not any(m.text.strip() for m in pending):
            logger.warning("DM od @%s obsahuje len prílohu bez textu – eskalujem človeku.", latest.sender_username)
            if not self.dry_run:
                store.mark_messages(pending_ids, conversation_id, Status.ESCALATED, "len príloha bez textu")
            return False

        if not self.dry_run and not store.claim_message(latest.id, conversation_id):
            return False

        try:
            decision = self.assistant.decide_dm_reply(
                messages, own_label=f"značka (@{profile.username})", is_own=own_flags
            )
        except ClaudeError as exc:
            self._handle_claude_failure(
                exc,
                latest.id,
                release=lambda: store.release_message(latest.id),
                fail=lambda detail: store.mark_messages(pending_ids, conversation_id, Status.FAILED, detail),
            )
            return False

        if decision.action is not ReplyAction.REPLY:
            self._record_non_reply(decision, item=f"DM od @{latest.sender_username}", permalink=None)
            if self.dry_run:
                self._dry_run_seen.add(latest.id)
            else:
                status = Status.ESCALATED if decision.action is ReplyAction.ESCALATE else Status.IGNORED
                store.mark_messages(pending_ids, conversation_id, status, decision.reason)
            return False

        text = truncate_text(clean_reply(decision.reply_text), self.settings.dm_reply_max_chars)
        text = truncate_utf8_bytes(text, INSTAGRAM_DM_MAX_BYTES)
        if self.dry_run:
            logger.info("[DRY-RUN] DM odpoveď pre @%s → %s", latest.sender_username, text)
            self._dry_run_seen.add(latest.id)
            return False

        self._pace()
        try:
            message_id = self.api.send_direct_message(latest.sender_id, text)
        except (MetaRateLimitError, MetaAuthError):
            store.release_message(latest.id)
            raise
        except MetaNetworkError as exc:
            status = Status.UNKNOWN if exc.ambiguous else Status.FAILED
            store.mark_messages(pending_ids, conversation_id, status, str(exc))
            logger.error("DM pre @%s: %s", latest.sender_username, exc)
            return False
        except MetaApiError as exc:
            status = Status.SKIPPED_WINDOW if exc.subcode == _OUTSIDE_WINDOW_SUBCODE else Status.FAILED
            store.mark_messages(pending_ids, conversation_id, status, str(exc))
            logger.error("DM pre @%s zlyhala: %s", latest.sender_username, exc)
            return False

        store.mark_messages(pending_ids, conversation_id, Status.REPLIED, decision.reason)
        store.finish_message(latest.id, Status.REPLIED, reply_id=message_id, detail=decision.reason)
        logger.info("Odoslaná DM odpoveď pre @%s: %s", latest.sender_username, text)
        return True

    # --------------------------------------------------------- spoločné pomocníky
    def _handle_claude_failure(
        self, exc: ClaudeError, item_id: str, *, release: Callable[[], None], fail: Callable[[str], None]
    ) -> None:
        """Chyba Claude pred odoslaním odpovede.

        * fatálna (kľúč/model) → uvoľniť a zastaviť bota,
        * prechodná (preťaženie, sieť) → uvoľniť a ukončiť úlohu, skúsi sa v ďalšom cykle,
        * trvalá pre túto položku → po ``_MAX_ITEM_FAILURES`` pokusoch označiť ako failed.
        """
        if isinstance(exc, ClaudeAuthError) or exc.retryable:
            if not self.dry_run:
                release()
            raise exc
        failures = self._failure_counts.get(item_id, 0) + 1
        self._failure_counts[item_id] = failures
        logger.error("Claude zlyhal pri položke %s (%d/%d): %s", item_id, failures, _MAX_ITEM_FAILURES, exc)
        if self.dry_run:
            return
        if failures >= _MAX_ITEM_FAILURES:
            fail(str(exc))
        else:
            release()

    @staticmethod
    def _record_non_reply(decision: ReplyDecision, *, item: str, permalink: str | None) -> None:
        if decision.action is ReplyAction.ESCALATE:
            where = f" ({permalink})" if permalink else ""
            logger.warning("ESKALÁCIA – %s%s vyžaduje človeka: %s", item, where, decision.reason)
        else:
            logger.info("Ignorované – %s: %s", item, decision.reason)

    # ------------------------------------------------------------- fronta postov
    def process_post_queue(self) -> int:
        """Publikuje pripravené príspevky z ``queue/``. Vracia počet publikovaných."""
        s = self.settings
        queue = self.post_queue
        scan = queue.scan(datetime.now(s.timezone))

        for invalid in scan.invalid:
            if self.dry_run:
                logger.error("[DRY-RUN] Príspevok '%s' je neplatný: %s", invalid.name, invalid.reason)
                continue
            target = queue.mark_failed(invalid.name, invalid.paths, invalid.reason)
            logger.error("Príspevok '%s' presunutý do %s: %s", invalid.name, target, invalid.reason)
        for item in scan.scheduled:
            if item.content_hash not in self._dry_run_seen:
                logger.info("Naplánovaný príspevok '%s' čaká na %s.", item.name, item.publish_at)
        if not scan.ready:
            return 0

        published = 0
        for item in scan.ready:
            if self._stop_event.is_set() or published >= s.max_posts_per_cycle:
                break
            if item.content_hash in self._dry_run_seen:
                continue
            if self._publish_item(item):
                published += 1
        return published

    def _publish_item(self, item: QueueItem) -> bool:
        """Celý proces jedného príspevku: kontrola → Claude → kontajner → publikovanie."""
        store, queue = self.store, self.post_queue
        record = store.get_post(item.content_hash)
        if record and record.status in {Status.PUBLISHED, Status.PUBLISHING, Status.UNKNOWN} and self.dry_run:
            logger.info("[DRY-RUN] Príspevok '%s' má v DB stav '%s' – preskakujem.", item.name, record.status)
            self._dry_run_seen.add(item.content_hash)
            return False
        if record and record.status == Status.PUBLISHED:
            queue.mark_published(item, {"duplicate_of": record.media_id, "permalink": record.permalink})
            logger.warning(
                "Príspevok '%s' už bol publikovaný (%s) – duplicitu presúvam bokom.", item.name, record.permalink
            )
            return False
        if record and record.status in {Status.PUBLISHING, Status.UNKNOWN}:
            reason = (
                "Predchádzajúce publikovanie skončilo v neistom stave. Skontroluj profil na Instagrame; "
                "ak príspevok chýba, presuň súbory späť do queue/."
            )
            store.upsert_post(item.content_hash, item.name, Status.FAILED, detail=reason)
            queue.mark_failed(item.name, (item.media_path, item.prompt_path), reason)
            logger.error("Príspevok '%s': %s", item.name, reason)
            return False

        quota = self.api.get_publishing_quota()
        if quota and quota.exhausted:
            logger.warning("Denný limit publikovania cez API je vyčerpaný (%d/%d).", quota.used, quota.total)
            return False

        try:
            url = self.media_host.public_url_for(item.media_path)
            self.media_host.verify(url, item.size_bytes)
        except MediaHostError as exc:
            # Často len chvíľkový stav (synchronizácia na server) – skúsi sa v ďalšom cykle.
            logger.error("Príspevok '%s' zatiaľ nemožno publikovať: %s", item.name, exc)
            return False

        draft = self.assistant.draft_caption(item.prompt_text, item.media_kind, item.name)
        if not draft.approved:
            reason = "Claude obsah neschválil: " + ("; ".join(draft.issues) or "bez uvedeného dôvodu")
            store.upsert_post(item.content_hash, item.name, Status.REJECTED, detail=reason)
            target = queue.mark_failed(item.name, (item.media_path, item.prompt_path), reason)
            logger.warning("Príspevok '%s' zamietnutý a presunutý do %s: %s", item.name, target, reason)
            return False
        caption = compose_caption(draft.hook, draft.body, draft.cta, draft.hashtags)
        if draft.issues:
            logger.info("Claude opravil v príspevku '%s': %s", item.name, "; ".join(draft.issues))

        if self.dry_run:
            logger.info("[DRY-RUN] Príspevok '%s' (%s) by bol publikovaný s popisom:\n%s", item.name, url, caption)
            self._dry_run_seen.add(item.content_hash)
            return False

        store.upsert_post(item.content_hash, item.name, Status.PUBLISHING)
        is_video = item.media_kind == "REELS"
        try:
            if is_video:
                container_id = self.api.create_reel_container(url, caption)
            else:
                container_id = self.api.create_image_container(url, caption)
            store.upsert_post(item.content_hash, item.name, Status.PUBLISHING, container_id=container_id)
            self.api.wait_for_container(
                container_id,
                timeout_seconds=900 if is_video else 120,
                poll_interval_seconds=15 if is_video else 5,
            )
        except (MetaRateLimitError, MetaAuthError):
            store.upsert_post(item.content_hash, item.name, Status.FAILED, detail="prerušené pred publikovaním")
            raise
        except MetaApiError as exc:
            # Pred volaním media_publish je chyba bezpečná – nič sa nezverejnilo.
            store.upsert_post(item.content_hash, item.name, Status.FAILED, detail=str(exc))
            queue.mark_failed(item.name, (item.media_path, item.prompt_path), str(exc))
            logger.error("Príprava príspevku '%s' zlyhala: %s", item.name, exc)
            return False

        self._pace()
        try:
            media_id = self.api.publish_container(container_id)
        except MetaNetworkError as exc:
            if exc.ambiguous:
                store.upsert_post(item.content_hash, item.name, Status.UNKNOWN, detail=str(exc))
                logger.error("Publikovanie '%s' má neistý výsledok – skontroluj profil ručne: %s", item.name, exc)
                return False
            store.upsert_post(item.content_hash, item.name, Status.FAILED, detail=str(exc))
            logger.error("Publikovanie '%s' zlyhalo (skúsi sa znova): %s", item.name, exc)
            return False
        except (MetaRateLimitError, MetaAuthError):
            store.upsert_post(item.content_hash, item.name, Status.FAILED, detail="prerušené pri publikovaní")
            raise
        except MetaApiError as exc:
            store.upsert_post(item.content_hash, item.name, Status.FAILED, detail=str(exc))
            queue.mark_failed(item.name, (item.media_path, item.prompt_path), str(exc))
            logger.error("Publikovanie '%s' zlyhalo: %s", item.name, exc)
            return False

        permalink = self.api.get_permalink(media_id)
        store.upsert_post(item.content_hash, item.name, Status.PUBLISHED, media_id=media_id, permalink=permalink)
        queue.mark_published(
            item,
            {
                "media_id": media_id,
                "permalink": permalink,
                "container_id": container_id,
                "media_kind": item.media_kind,
                "caption": caption,
                "published_at": datetime.now(self.settings.timezone).isoformat(timespec="seconds"),
            },
        )
        logger.info("Publikovaný príspevok '%s': %s", item.name, permalink or media_id)
        return True

    # =========================================================== režim --learn
    def learn_style_from_video(
        self, video: Path, *, force: bool = False, keep_temp: bool = False, merge: bool = False
    ) -> StyleLearningResult:
        """Vytvorí Video Style Blueprint (``config/style_guide.txt``) z lokálneho videa."""
        s = self.settings
        learner = VideoStyleLearner(
            ffmpeg=FFmpegToolkit(s.ffmpeg_binary, s.ffprobe_binary, timeout_seconds=s.learn_timeout_seconds),
            transcriber=self._build_transcriber(),
            assistant=self.assistant,
            store=self.store,
            style_guide_path=s.style_guide_path,
            timezone=s.timezone,
            scene_threshold=s.learn_scene_threshold,
            sample_fps=s.learn_sample_fps,
            max_frames=s.learn_max_frames,
            frame_max_side=s.learn_frame_max_side,
            jpeg_quality=s.learn_jpeg_quality,
            dedup_distance=s.learn_dedup_distance,
            max_video_seconds=s.learn_max_video_seconds,
            max_request_bytes=int(s.learn_max_request_mb * 1024 * 1024),
        )
        return learner.learn(video, force=force, keep_temp=keep_temp, merge=merge)

    def _build_transcriber(self) -> Transcriber:
        s = self.settings
        if s.asr_provider == "openai":
            return OpenAIWhisperTranscriber(
                api_key=s.openai_api_key,
                model=s.openai_transcribe_model,
                language=s.asr_language,
                chunk_seconds=s.learn_audio_chunk_seconds,
                max_retries=s.http_max_retries,
                backoff_base_seconds=s.backoff_base_seconds,
                backoff_max_seconds=s.backoff_max_seconds,
            )
        if s.asr_provider == "faster-whisper":
            return FasterWhisperTranscriber(model_size=s.faster_whisper_model, language=s.asr_language)
        return NullTranscriber()

    # ========================================================== režim --script
    def generate_video_script(self, topic: str, notes: str | None = None) -> Path:
        """Vygeneruje scenár videa podľa blueprintu a uloží ho do ``output/scripts/``."""
        result = self.assistant.write_video_script(topic, notes)
        out_dir = self.settings.scripts_output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(self.settings.timezone).strftime("%Y%m%d-%H%M")
        path = out_dir / f"{stamp}_{slugify(topic)}.md"
        path.write_text(result.text.strip() + "\n", encoding="utf-8")
        logger.info("Scenár uložený: %s (výstup %d tokenov).", path, result.output_tokens)
        return path

    # =========================================================== režim --check
    def check(self) -> list[str]:
        """Overí token, prístupy a súbory. Vracia riadky reportu pre konzolu."""
        s = self.settings
        lines: list[str] = []
        profile = self.profile
        lines.append(f"✔ Meta token je platný – účet @{profile.username}")
        lines.append(f"  ID z API: {', '.join(sorted(profile.identifiers))}")
        if s.instagram_account_id not in profile.identifiers:
            lines.append(
                f"⚠ INSTAGRAM_BUSINESS_ACCOUNT_ID ({s.instagram_account_id}) sa nezhoduje s ID z API – skontroluj .env."
            )
        media = self.api.get_recent_media(1)
        lines.append(f"✔ Prístup k príspevkom: OK ({'nájdený príspevok' if media else 'účet zatiaľ nemá príspevky'})")
        if s.enable_dms:
            try:
                conversations = self.api.get_conversations(1)
                lines.append(f"✔ Prístup k DM konverzáciám: OK ({len(conversations)} načítaná)")
            except MetaAuthError:
                raise
            except MetaApiError as exc:
                lines.append(f"✖ Prístup k DM konverzáciám zlyhal: {exc}")
        quota = self.api.get_publishing_quota()
        if quota:
            lines.append(f"✔ Limit publikovania: {quota.used}/{quota.total} za 24 h")
        snapshot = self.knowledge.snapshot()
        lines.append(
            f"{'✔' if snapshot.brand_voice else '⚠'} Brand voice: "
            f"{'načítaný' if snapshot.brand_voice else 'chýba'} ({s.brand_voice_path})"
        )
        lines.append(
            f"{'✔' if snapshot.style_guide else '⚠'} Video Style Blueprint: "
            f"{'načítaný' if snapshot.style_guide else 'chýba – spusti --learn'} ({s.style_guide_path})"
        )
        lines.append(
            f"✔ ANTHROPIC_API_KEY je nastavený (model {s.anthropic_model})"
            if s.anthropic_api_key
            else "✖ ANTHROPIC_API_KEY chýba"
        )
        try:
            version = FFmpegToolkit(s.ffmpeg_binary, s.ffprobe_binary).ensure_available()
            lines.append(f"✔ {version}")
        except InstagramBotError:
            lines.append("⚠ ffmpeg nie je nainštalovaný – režim --learn nebude fungovať")
        for table, label in (
            ("processed_comments", "Komentáre"),
            ("processed_messages", "DM správy"),
            ("published_posts", "Posty"),
        ):
            counts = self.store.count_by_status(table)
            lines.append(
                f"  {label} v DB: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "zatiaľ nič")
            )
        escalations = list(self.store.iter_escalations(10))
        if escalations:
            lines.append("⚠ Posledné eskalácie (rieši človek):")
            lines.extend(
                f"   - {row['kind']} {row['item_id']}: {row['detail']} ({row['updated_at']})" for row in escalations
            )
        return lines

    # =================================================== režim --refresh-token
    def refresh_token(self) -> int:
        """Predĺži Instagram token o 60 dní a zapíše ho do ``.env``. Vracia platnosť v dňoch."""
        env_file = self.settings.env_file
        if env_file is None:
            raise ConfigError("Obnova tokenu potrebuje .env súbor, do ktorého sa nový token zapíše.")
        new_token, expires_in = self.api.refresh_instagram_token(self.settings.meta_access_token)
        set_key(str(env_file), "META_ACCESS_TOKEN", new_token, quote_mode="never")
        if os.name == "posix":
            env_file.chmod(0o600)
        days = expires_in // 86_400
        logger.info("Meta access token bol obnovený a uložený do %s (platnosť %d dní).", env_file, days)
        return days
