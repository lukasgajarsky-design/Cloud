"""Pomocné funkcie pre text: hashtagy, skladanie popisu, bezpečné skracovanie.

Limity Instagramu, ktoré tu vynucujeme (aby Meta API požiadavku neodmietla):

* popis príspevku: max. 2 200 znakov, max. 30 hashtagov,
* text DM správy: max. 1 000 bajtov v UTF-8.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final

INSTAGRAM_CAPTION_MAX_CHARS: Final[int] = 2200
INSTAGRAM_MAX_HASHTAGS: Final[int] = 30
INSTAGRAM_DM_MAX_BYTES: Final[int] = 1000

_HASHTAG_BODY = re.compile(r"[^\w]", re.UNICODE)
_HASHTAG_IN_TEXT = re.compile(r"#\w+", re.UNICODE)
_MULTI_NEWLINES = re.compile(r"\n{3,}")


def normalize_hashtags(raw_tags: Iterable[str], max_count: int = INSTAGRAM_MAX_HASHTAGS) -> list[str]:
    """Vyčistí hashtagy: pridá ``#``, odstráni medzery/interpunkciu, duplicity a orezá počet.

    >>> normalize_hashtags(["Káva", "#kava", "ranná rutina", "#", "#Káva"])
    ['#Káva', '#kava', '#rannárutina']
    """
    result: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        body = _HASHTAG_BODY.sub("", str(tag).strip().lstrip("#"))
        if not body or body.isdigit():
            continue
        key = body.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(f"#{body}")
        if len(result) >= max_count:
            break
    return result


def count_hashtags(text: str) -> int:
    return len(_HASHTAG_IN_TEXT.findall(text))


def truncate_text(text: str, max_chars: int, ellipsis: str = "…") -> str:
    """Skráti text na ``max_chars`` znakov, ideálne na hranici slova."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    limit = max(0, max_chars - len(ellipsis))
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-–") + ellipsis


def truncate_utf8_bytes(text: str, max_bytes: int, ellipsis: str = "…") -> str:
    """Skráti text tak, aby v UTF-8 nepresiahol ``max_bytes`` (diakritika má 2 bajty)."""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    budget = max_bytes - len(ellipsis.encode("utf-8"))
    encoded = text.encode("utf-8")[:budget]
    # errors="ignore" zahodí prípadný rozseknutý viacbajtový znak na konci.
    shortened = encoded.decode("utf-8", errors="ignore")
    space = shortened.rfind(" ")
    if space > len(shortened) * 0.6:
        shortened = shortened[:space]
    return shortened.rstrip() + ellipsis


def clean_reply(text: str) -> str:
    """Upraví odpoveď od modelu: oreže medzery, zlúči nadbytočné prázdne riadky."""
    text = text.replace("\r\n", "\n").strip().strip('"').strip()
    return _MULTI_NEWLINES.sub("\n\n", text)


def compose_caption(
    hook: str,
    body: str,
    cta: str,
    hashtags: Iterable[str],
    *,
    max_chars: int = INSTAGRAM_CAPTION_MAX_CHARS,
    max_hashtags: int = INSTAGRAM_MAX_HASHTAGS,
) -> str:
    """Poskladá popis príspevku v štruktúre Hook → Body → CTA → hashtagy.

    Ak by výsledok presiahol limit Instagramu, najprv uberá hashtagy z konca
    a až potom skracuje telo – hook a CTA sú pre výkon príspevku najdôležitejšie.
    """
    hook, body, cta = clean_reply(hook), clean_reply(body), clean_reply(cta)
    # Hashtagy priamo v texte sa rátajú do limitu 30.
    inline_tags = count_hashtags(" ".join((hook, body, cta)))
    tags = normalize_hashtags(hashtags, max_count=max(0, max_hashtags - inline_tags))

    def assemble(current_body: str, current_tags: list[str]) -> str:
        parts = [part for part in (hook, current_body, cta) if part]
        if current_tags:
            parts.append(" ".join(current_tags))
        return "\n\n".join(parts)

    caption = assemble(body, tags)
    while len(caption) > max_chars and tags:
        tags.pop()
        caption = assemble(body, tags)
    if len(caption) > max_chars:
        fixed = len(assemble("", tags))
        body_budget = max(0, max_chars - fixed - 2)
        caption = assemble(truncate_text(body, body_budget) if body_budget > 0 else "", tags)
    return caption[:max_chars]


def format_timestamp(seconds: float) -> str:
    """Formát času pre prepisy a snímky: ``mm:ss.s`` (alebo ``h:mm:ss.s``)."""
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours >= 1:
        return f"{int(hours)}:{int(minutes):02d}:{secs:04.1f}"
    return f"{int(minutes):02d}:{secs:04.1f}"


def slugify(text: str, max_length: int = 60) -> str:
    """Bezpečný názov súboru z ľubovoľného textu (bez diakritiky a špeciálnych znakov)."""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:max_length].rstrip("-") or "bez-nazvu"
