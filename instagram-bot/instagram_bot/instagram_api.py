"""Vysokoúrovňové operácie nad Instagram účtom (komentáre, DM, publikovanie).

Modul prekladá „biznis“ požiadavky (napr. *odpovedz na komentár*) na konkrétne
endpointy Graph API a surové JSON odpovede na typy z ``models.py``.

Podporované sú obe oficiálne prihlasovacie cesty Meta:

* **Instagram Login** – host ``graph.instagram.com``, token používateľa Instagramu.
* **Facebook Login** – host ``graph.facebook.com``, Page access token
  a ``META_PAGE_ID`` stránky prepojenej s Instagram účtom (potrebné pre DM).

Endpointy pre médiá, komentáre a publikovanie sú v oboch prípadoch rovnaké;
líši sa len uzol pre konverzácie (``me`` vs. ID stránky) a čítanie profilu.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .exceptions import MetaApiError, MetaAuthError
from .graph_client import JsonDict, MetaGraphClient
from .models import (
    AccountProfile,
    Comment,
    ConversationSummary,
    DirectMessage,
    Media,
    PublishingQuota,
    parse_graph_time,
)

logger = logging.getLogger(__name__)

# Graph API kód 100 = neplatný parameter/pole – použijeme ho na fallback pri
# poliach, ktoré niektorá verzia/host API nepodporuje.
_INVALID_PARAMETER_CODE = 100

_COMMENT_FIELDS_FULL = "id,text,timestamp,username,from,replies{username}"
_COMMENT_FIELDS_BASIC = "id,text,timestamp,username,replies{username}"
_MESSAGE_FIELDS = "id,created_time,from,message"


class InstagramAPI:
    """Fasáda nad ``MetaGraphClient`` s typovanými metódami pre Instagram."""

    def __init__(
        self,
        client: MetaGraphClient,
        *,
        account_id: str,
        graph_host: str,
        page_id: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._account_id = account_id
        self._is_instagram_login = graph_host == "graph.instagram.com"
        # Konverzácie: pri Instagram Login je uzol „me“ (účet), pri Facebook Login stránka.
        self._messaging_node = page_id or "me"
        self._comment_fields = _COMMENT_FIELDS_FULL
        self._sleep = sleep

    # ---------------------------------------------------------------- profil účtu
    def get_profile(self) -> AccountProfile:
        """Načíta ID a používateľské meno vlastného účtu."""
        if self._is_instagram_login:
            data = self._client.get("me", {"fields": "user_id,username"})
            return AccountProfile(
                id=str(data.get("id", "")),
                username=str(data.get("username", "")),
                user_id=str(data["user_id"]) if data.get("user_id") else None,
            )
        data = self._client.get(self._account_id, {"fields": "id,username"})
        return AccountProfile(id=str(data.get("id", "")), username=str(data.get("username", "")))

    # -------------------------------------------------------- príspevky a komentáre
    def get_recent_media(self, limit: int) -> list[Media]:
        """Vráti najnovšie príspevky (od najnovšieho)."""
        items = self._client.iterate(
            f"{self._account_id}/media",
            {"fields": "id,caption,media_type,permalink,timestamp,comments_count", "limit": min(limit, 50)},
            max_items=limit,
        )
        return [
            Media(
                id=str(item["id"]),
                caption=str(item.get("caption") or ""),
                media_type=str(item.get("media_type") or ""),
                permalink=item.get("permalink"),
                timestamp=parse_graph_time(item.get("timestamp")),
                comments_count=int(item.get("comments_count") or 0),
            )
            for item in items
            if item.get("id")
        ]

    def get_comments(self, media_id: str, max_items: int) -> list[Comment]:
        """Vráti komentáre najvyššej úrovne pod príspevkom.

        Pole ``replies{username}`` nám povie, či už vlastník účtu na komentár
        odpovedal (napr. ručne) – vtedy bot neodpovedá znova.
        """
        try:
            raw = list(self._iterate_comments(media_id, max_items))
        except MetaApiError as exc:
            if isinstance(exc, MetaAuthError) or exc.code != _INVALID_PARAMETER_CODE:
                raise
            if self._comment_fields == _COMMENT_FIELDS_BASIC:
                raise
            logger.info("Pole 'from' pri komentároch nie je dostupné – prepínam na základné polia.")
            self._comment_fields = _COMMENT_FIELDS_BASIC
            raw = list(self._iterate_comments(media_id, max_items))

        comments: list[Comment] = []
        for item in raw:
            if not item.get("id"):
                continue
            author = item.get("from") or {}
            replies = (item.get("replies") or {}).get("data") or []
            comments.append(
                Comment(
                    id=str(item["id"]),
                    media_id=media_id,
                    text=str(item.get("text") or ""),
                    username=str(item.get("username") or author.get("username") or ""),
                    author_id=str(author["id"]) if author.get("id") else None,
                    timestamp=parse_graph_time(item.get("timestamp")),
                    reply_usernames=tuple(str(r.get("username") or "") for r in replies if isinstance(r, dict)),
                )
            )
        return comments

    def _iterate_comments(self, media_id: str, max_items: int) -> Any:
        return self._client.iterate(
            f"{media_id}/comments",
            {"fields": self._comment_fields, "limit": min(max_items, 50)},
            max_items=max_items,
        )

    def reply_to_comment(self, comment_id: str, message: str) -> str:
        """Zverejní odpoveď na komentár a vráti ID novej odpovede.

        Operácia NIE JE idempotentná – pri nejasnom výsledku sa neopakuje.
        """
        data = self._client.post(f"{comment_id}/replies", data={"message": message})
        return str(data.get("id", ""))

    # ------------------------------------------------------------- Direct Messages
    def get_conversations(self, limit: int) -> list[ConversationSummary]:
        """Vráti posledné DM konverzácie (od naposledy aktualizovanej)."""
        items = self._client.iterate(
            f"{self._messaging_node}/conversations",
            {"platform": "instagram", "fields": "id,updated_time", "limit": min(limit, 25)},
            max_items=limit,
        )
        return [
            ConversationSummary(id=str(item["id"]), updated_time=parse_graph_time(item.get("updated_time")))
            for item in items
            if item.get("id")
        ]

    def get_conversation_messages(self, conversation_id: str, limit: int) -> list[DirectMessage]:
        """Vráti posledných ``limit`` správ konverzácie v chronologickom poradí.

        Najprv skúsime jedno volanie s rozbalením polí (field expansion). Ak ho
        API odmietne, prejdeme na oficiálny dvojkrokový postup: zoznam ID správ
        a potom detail každej správy (Meta sprístupňuje detail 20 posledných správ).
        """
        try:
            data = self._client.get(conversation_id, {"fields": f"messages.limit({limit}){{{_MESSAGE_FIELDS}}}"})
            raw_messages: list[JsonDict] = list((data.get("messages") or {}).get("data") or [])[:limit]
        except MetaApiError as exc:
            if isinstance(exc, MetaAuthError) or exc.code != _INVALID_PARAMETER_CODE:
                raise
            logger.info("Rozbalenie polí správ nie je podporené – používam dvojkrokové načítanie.")
            data = self._client.get(conversation_id, {"fields": "messages"})
            message_ids = [m["id"] for m in ((data.get("messages") or {}).get("data") or []) if m.get("id")]
            raw_messages = [self._client.get(mid, {"fields": _MESSAGE_FIELDS}) for mid in message_ids[:limit]]

        messages = []
        for item in raw_messages:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            sender = item.get("from") or {}
            messages.append(
                DirectMessage(
                    id=str(item["id"]),
                    conversation_id=conversation_id,
                    text=str(item.get("message") or ""),
                    sender_id=str(sender["id"]) if sender.get("id") else None,
                    sender_username=str(sender["username"]) if sender.get("username") else None,
                    created_time=parse_graph_time(item.get("created_time")),
                )
            )
        # API vracia od najnovšej; pre Claude potrebujeme chronologické poradie.
        messages.sort(key=lambda m: m.created_time.timestamp() if m.created_time else 0.0)
        return messages

    def send_direct_message(self, recipient_id: str, text: str) -> str:
        """Odošle textovú DM odpoveď (len v rámci 24-hodinového okna od správy zákazníka)."""
        data = self._client.post(
            f"{self._messaging_node}/messages",
            json_body={"recipient": {"id": recipient_id}, "message": {"text": text}},
        )
        return str(data.get("message_id") or data.get("id") or "")

    # ------------------------------------------------------------------ publikovanie
    def get_publishing_quota(self) -> PublishingQuota | None:
        """Zistí využitie denného limitu publikovania (ak ho API poskytne)."""
        try:
            data = self._client.get(f"{self._account_id}/content_publishing_limit", {"fields": "config,quota_usage"})
        except MetaAuthError:
            raise
        except MetaApiError as exc:
            logger.warning("Nepodarilo sa zistiť limit publikovania: %s", exc)
            return None
        entries = data.get("data") or []
        if not entries:
            return None
        entry = entries[0]
        total = int(((entry.get("config") or {}).get("quota_total")) or 0)
        if total <= 0:
            return None
        return PublishingQuota(used=int(entry.get("quota_usage") or 0), total=total)

    def create_image_container(self, image_url: str, caption: str) -> str:
        """Krok 1 publikovania obrázka: vytvorí kontajner (Meta si stiahne obrázok z URL)."""
        # Vytvorenie kontajnera je bezpečné opakovať – nepoužitý kontajner po 24 h expiruje.
        data = self._client.post(
            f"{self._account_id}/media", data={"image_url": image_url, "caption": caption}, idempotent=True
        )
        return self._require_id(data, "kontajner obrázka")

    def create_reel_container(self, video_url: str, caption: str, *, share_to_feed: bool = True) -> str:
        """Krok 1 publikovania videa: kontajner typu REELS."""
        data = self._client.post(
            f"{self._account_id}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true" if share_to_feed else "false",
            },
            idempotent=True,
        )
        return self._require_id(data, "kontajner videa")

    def wait_for_container(self, container_id: str, *, timeout_seconds: float, poll_interval_seconds: float) -> None:
        """Krok 2: čaká, kým Meta spracuje médium (stav ``FINISHED``)."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            data = self._client.get(container_id, {"fields": "status_code,status"})
            status_code = str(data.get("status_code") or "")
            if status_code in {"FINISHED", "PUBLISHED"}:
                return
            if status_code in {"ERROR", "EXPIRED"}:
                raise MetaApiError(
                    f"Meta nevedela spracovať médium: {status_code} – {data.get('status') or ''}".strip()
                )
            if time.monotonic() >= deadline:
                raise MetaApiError(
                    f"Spracovanie média trvá dlhšie ako {timeout_seconds:.0f} s (stav: {status_code or 'neznámy'})."
                )
            logger.info("Médium sa spracúva (stav: %s) – čakám %.0f s.", status_code or "?", poll_interval_seconds)
            self._sleep(poll_interval_seconds)

    def publish_container(self, container_id: str) -> str:
        """Krok 3: zverejní spracovaný kontajner. Nie je idempotentné!"""
        data = self._client.post(f"{self._account_id}/media_publish", data={"creation_id": container_id})
        return self._require_id(data, "publikovaný príspevok")

    def get_permalink(self, media_id: str) -> str | None:
        """Vráti verejný odkaz na príspevok (len pre log – chyba nie je fatálna)."""
        try:
            return self._client.get(media_id, {"fields": "permalink"}).get("permalink")
        except MetaAuthError:
            raise
        except MetaApiError as exc:
            logger.warning("Nepodarilo sa získať permalink pre %s: %s", media_id, exc)
            return None

    # -------------------------------------------------------------- správa tokenu
    def refresh_instagram_token(self, current_token: str) -> tuple[str, int]:
        """Predĺži long-lived token Instagram Login o ďalších 60 dní.

        Funguje len pre tokeny z ``graph.instagram.com``, ktoré sú staršie ako 24 h
        a ešte neexpirovali. Vracia dvojicu ``(nový_token, platnosť_v_sekundách)``.
        """
        data = self._client.get(
            "https://graph.instagram.com/refresh_access_token",
            {"grant_type": "ig_refresh_token", "access_token": current_token},
        )
        token = str(data.get("access_token") or "")
        if not token:
            raise MetaApiError("Odpoveď na obnovu tokenu neobsahuje access_token.")
        return token, int(data.get("expires_in") or 0)

    @staticmethod
    def _require_id(data: JsonDict, what: str) -> str:
        identifier = data.get("id")
        if not identifier:
            raise MetaApiError(f"Graph API nevrátilo ID pre {what}.")
        return str(identifier)
