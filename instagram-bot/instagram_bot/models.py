"""Dátové triedy (dataclasses), s ktorými pracuje zvyšok aplikácie.

Surové JSON odpovede z Graph API sa hneď pri príjme prevedú na tieto typy,
takže zvyšok kódu je plne typovaný a nemusí sa starať o chýbajúce kľúče.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal


def parse_graph_time(value: str | None) -> datetime | None:
    """Prevedie čas z Graph API (napr. ``2026-10-04T12:34:56+0000``) na ``datetime`` v UTC."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value, fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class AccountProfile:
    """Profil vlastného Instagram účtu (podľa neho spoznáme vlastné komentáre a správy)."""

    id: str
    username: str
    user_id: str | None = None  # IG professional account ID (len pri Instagram Login)

    @property
    def identifiers(self) -> frozenset[str]:
        """Všetky ID, pod ktorými sa náš účet môže objaviť v odpovediach API."""
        return frozenset(value for value in (self.id, self.user_id) if value)

    def is_own(self, *, user_id: str | None, username: str | None) -> bool:
        """Je autor (komentára/správy) náš vlastný účet?"""
        if user_id and user_id in self.identifiers:
            return True
        if not username:
            return False
        return username.lower() == self.username.lower()


@dataclass(frozen=True)
class Media:
    """Príspevok na Instagrame."""

    id: str
    caption: str
    media_type: str
    permalink: str | None
    timestamp: datetime | None
    comments_count: int


@dataclass(frozen=True)
class Comment:
    """Komentár najvyššej úrovne pod príspevkom (odpovede na odpovede neriešime)."""

    id: str
    media_id: str
    text: str
    username: str
    author_id: str | None
    timestamp: datetime | None
    reply_usernames: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationSummary:
    """Konverzácia v Instagram Direct (bez obsahu správ)."""

    id: str
    updated_time: datetime | None


@dataclass(frozen=True)
class DirectMessage:
    """Jedna správa v DM konverzácii."""

    id: str
    conversation_id: str
    text: str
    sender_id: str | None
    sender_username: str | None
    created_time: datetime | None


@dataclass(frozen=True)
class PublishingQuota:
    """Koľko príspevkov cez API sme za posledných 24 h publikovali a aký je limit."""

    used: int
    total: int

    @property
    def exhausted(self) -> bool:
        return self.used >= self.total


class ReplyAction(str, Enum):
    """Rozhodnutie Claude, čo urobiť s komentárom alebo správou."""

    REPLY = "reply"  # odpovedať automaticky
    IGNORE = "ignore"  # spam, emoji bez obsahu, nevyžaduje odpoveď
    ESCALATE = "escalate"  # citlivá vec (sťažnosť, reklamácia, právne) – musí riešiť človek


@dataclass(frozen=True)
class ReplyDecision:
    """Štruktúrovaný výstup Claude pre komentár alebo DM."""

    action: ReplyAction
    reply_text: str
    reason: str


@dataclass(frozen=True)
class CaptionDraft:
    """Štruktúrovaný výstup Claude pre popis príspevku (hook → body → CTA → hashtagy)."""

    approved: bool
    issues: tuple[str, ...]
    hook: str
    body: str
    cta: str
    hashtags: tuple[str, ...]


@dataclass(frozen=True)
class ClaudeTextResult:
    """Dlhý textový výstup Claude (blueprint, scenár) spolu so spotrebou tokenov."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    stop_reason: str | None = None


MediaKind = Literal["IMAGE", "REELS"]


@dataclass
class CycleReport:
    """Súhrn jedného cyklu bota (logujeme ho na konci cyklu)."""

    comment_replies: int = 0
    dm_replies: int = 0
    posts_published: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"odpovede na komentáre: {self.comment_replies}, DM odpovede: {self.dm_replies}, "
            f"publikované posty: {self.posts_published}, chyby: {len(self.errors)}"
        )
