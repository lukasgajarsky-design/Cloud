"""Testy triedy InstagramBot: komentáre, DM, fronta postov, ochrana proti duplicitám."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import FakeAssistant, FakeInstagramAPI, FakeMediaHost

from instagram_bot.bot import InstagramBot
from instagram_bot.config import Settings
from instagram_bot.exceptions import ClaudeError, MetaRateLimitError
from instagram_bot.models import (
    Comment,
    ConversationSummary,
    DirectMessage,
    Media,
    ReplyAction,
    ReplyDecision,
)
from instagram_bot.post_queue import parse_prompt_file
from instagram_bot.storage import Status

NOW = datetime.now(timezone.utc)


def build_bot(
    settings: Settings, api: FakeInstagramAPI, assistant: FakeAssistant, *, dry_run: bool | None = None
) -> InstagramBot:
    bot = InstagramBot(settings, dry_run=dry_run)
    # cached_property → komponenty nahradíme falošnými (žiadne reálne API volania).
    bot.__dict__["api"] = api
    bot.__dict__["assistant"] = assistant
    bot.__dict__["profile"] = api.profile
    bot.__dict__["media_host"] = FakeMediaHost()
    return bot


def comment(cid: str, text: str = "Super káva!", username: str = "jana", age_hours: float = 1, **kw: object) -> Comment:
    return Comment(
        id=cid,
        media_id="m1",
        text=text,
        username=username,
        author_id=kw.get("author_id"),  # type: ignore[arg-type]
        timestamp=NOW - timedelta(hours=age_hours),
        reply_usernames=kw.get("replies", ()),  # type: ignore[arg-type]
    )


@pytest.fixture
def api_with_comments(fake_api: FakeInstagramAPI) -> FakeInstagramAPI:
    fake_api.media = [Media("m1", "Jesenná káva", "IMAGE", "https://instagram.com/p/m1", NOW, 5)]
    fake_api.comments["m1"] = [
        comment("c_new"),
        comment("c_old", age_hours=24 * 10),
        comment("c_own", username="moja_znacka"),
        comment("c_answered", replies=("moja_znacka",)),
        comment("c_empty", text="   "),
    ]
    return fake_api


# ------------------------------------------------------------------ komentáre
def test_comments_reply_once_and_skip_the_rest(
    settings_factory: Callable[..., Settings], api_with_comments: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    bot = build_bot(settings_factory(), api_with_comments, fake_assistant)
    assert bot.process_comments() == 1
    assert api_with_comments.comment_replies == [("c_new", "@jana Ďakujeme, tešíme sa! ☕")]
    assert [c.id for c in fake_assistant.comment_calls] == ["c_new"]  # Claude sa volal len raz

    # Druhý cyklus: nič nové → žiadna duplicitná odpoveď ani volanie Claude.
    assert bot.process_comments() == 0
    assert len(api_with_comments.comment_replies) == 1 and len(fake_assistant.comment_calls) == 1
    counts = bot.store.count_by_status("processed_comments")
    assert counts == {
        Status.REPLIED: 1,
        Status.SKIPPED_OLD: 1,
        Status.SKIPPED_OWN: 1,
        Status.SKIPPED_ANSWERED: 1,
        Status.SKIPPED_EMPTY: 1,
    }
    bot.close()


def test_escalated_comment_is_not_answered(
    settings_factory: Callable[..., Settings], api_with_comments: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    fake_assistant.comment_decision = ReplyDecision(ReplyAction.ESCALATE, "", "reklamácia")
    bot = build_bot(settings_factory(), api_with_comments, fake_assistant)
    assert bot.process_comments() == 0
    assert api_with_comments.comment_replies == []
    assert bot.store.count_by_status("processed_comments")[Status.ESCALATED] == 1
    bot.close()


def test_transient_claude_error_releases_comment_for_next_cycle(
    settings_factory: Callable[..., Settings], api_with_comments: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    fake_assistant.error = ClaudeError("preťažené", retryable=True)
    bot = build_bot(settings_factory(), api_with_comments, fake_assistant)
    with pytest.raises(ClaudeError):
        bot.process_comments()
    assert not bot.store.is_comment_known("c_new")  # spracuje sa v ďalšom cykle
    fake_assistant.error = None
    assert bot.process_comments() == 1
    bot.close()


def test_rate_limit_on_reply_releases_comment_and_sets_cooldown(
    settings_factory: Callable[..., Settings], api_with_comments: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    api_with_comments.reply_error = MetaRateLimitError("limit", retry_after_seconds=600)
    bot = build_bot(settings_factory(ENABLE_DMS="false", ENABLE_POSTS="false"), api_with_comments, fake_assistant)
    report = bot.run_once(["comments"])
    assert report.errors and bot._cooldown_until > 0
    assert not bot.store.is_comment_known("c_new")
    bot.close()


def test_dry_run_sends_nothing_and_stores_nothing(
    settings_factory: Callable[..., Settings], api_with_comments: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    bot = build_bot(settings_factory(), api_with_comments, fake_assistant, dry_run=True)
    bot.process_comments()
    bot.process_comments()
    assert api_with_comments.comment_replies == []
    assert len(fake_assistant.comment_calls) == 1  # v rámci procesu sa Claude nevolá opakovane
    assert bot.store.count_by_status("processed_comments") == {}
    bot.close()


# ------------------------------------------------------------------------ DM
def dm(mid: str, sender: str, text: str, minutes_ago: float) -> DirectMessage:
    sender_id = "17841400000000000" if sender == "moja_znacka" else f"igsid_{sender}"
    return DirectMessage(mid, "conv1", text, sender_id, sender, NOW - timedelta(minutes=minutes_ago))


def test_dm_replies_to_pending_customer_messages_once(
    settings_factory: Callable[..., Settings], fake_api: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    fake_api.conversations = [ConversationSummary("conv1", NOW)]
    fake_api.messages["conv1"] = [
        dm("d1", "peter", "Dobrý deň", 30),
        dm("d2", "moja_znacka", "Ahoj Peter!", 25),
        dm("d3", "peter", "Máte XL?", 5),
        dm("d4", "peter", "A v čiernej?", 4),
    ]
    bot = build_bot(settings_factory(), fake_api, fake_assistant)
    assert bot.process_direct_messages() == 1
    assert fake_api.sent_messages == [("igsid_peter", "Ahoj! Áno, máme to skladom.")]
    assert bot.store.is_message_known("d3") and bot.store.is_message_known("d4")
    assert bot.process_direct_messages() == 0  # žiadna duplicita
    bot.close()


def test_dm_already_answered_or_outside_window_is_skipped(
    settings_factory: Callable[..., Settings], fake_api: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    fake_api.conversations = [ConversationSummary("conv1", NOW), ConversationSummary("conv2", NOW)]
    fake_api.messages["conv1"] = [dm("a1", "peter", "Ďakujem", 10), dm("a2", "moja_znacka", "Rado sa stalo", 5)]
    old = DirectMessage("b1", "conv2", "Haló?", "igsid_eva", "eva", NOW - timedelta(hours=30))
    fake_api.messages["conv2"] = [old]
    bot = build_bot(settings_factory(), fake_api, fake_assistant)
    assert bot.process_direct_messages() == 0
    assert fake_api.sent_messages == [] and fake_assistant.dm_calls == []
    bot.close()


# --------------------------------------------------------------- fronta postov
def write_post(queue: Path, name: str, prompt: str, media_bytes: bytes = b"\xff\xd8\xff\xe0fakejpeg") -> None:
    queue.mkdir(parents=True, exist_ok=True)
    (queue / f"{name}.jpg").write_bytes(media_bytes)
    (queue / f"{name}.txt").write_text(prompt, encoding="utf-8")


def test_post_queue_publishes_and_archives(
    settings_factory: Callable[..., Settings], fake_api: FakeInstagramAPI, fake_assistant: FakeAssistant, tmp_path: Path
) -> None:
    settings = settings_factory()
    write_post(settings.queue_dir, "jesen", "Jesenná akcia na kávu")
    bot = build_bot(settings, fake_api, fake_assistant)
    assert bot.process_post_queue() == 1

    kind, url, caption = fake_api.containers[0]
    assert kind == "IMAGE" and url.endswith("jesen.jpg")
    assert caption == "Hook riadok\n\nTelo príspevku.\n\nNapíš nám do DM!\n\n#kava #rano"
    archived = list((settings.queue_dir / "published").iterdir())
    assert len(archived) == 1
    result = json.loads((archived[0] / "result.json").read_text(encoding="utf-8"))
    assert result["media_id"] == "media_1"
    assert not (settings.queue_dir / "jesen.jpg").exists()

    # Rovnaký obsah znova vo fronte → nepublikuje sa druhýkrát.
    write_post(settings.queue_dir, "jesen-kopia", "Jesenná akcia na kávu")
    assert bot.process_post_queue() == 0
    assert len(fake_api.published) == 1
    bot.close()


def test_scheduled_and_invalid_posts(
    settings_factory: Callable[..., Settings], fake_api: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    settings = settings_factory()
    future = (datetime.now(ZoneInfo("Europe/Bratislava")) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    write_post(settings.queue_dir, "zajtra", f"publish_at: {future}\n---\nZajtrajší post")
    (settings.queue_dir / "obrazok.png").write_bytes(b"png")
    (settings.queue_dir / "obrazok.txt").write_text("text", encoding="utf-8")
    bot = build_bot(settings, fake_api, fake_assistant)
    assert bot.process_post_queue() == 0
    assert fake_api.containers == []
    assert (settings.queue_dir / "zajtra.jpg").exists()  # čaká na svoj čas
    failed = list((settings.queue_dir / "failed").iterdir())
    assert len(failed) == 1 and "JPEG" in (failed[0] / "error.txt").read_text(encoding="utf-8")
    bot.close()


def test_rejected_caption_moves_post_to_failed(
    settings_factory: Callable[..., Settings], fake_api: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    from instagram_bot.models import CaptionDraft

    fake_assistant.caption = CaptionDraft(False, ("klamlivé zdravotné tvrdenie",), "", "", "", ())
    settings = settings_factory()
    write_post(settings.queue_dir, "zly", "Káva lieči všetky choroby")
    bot = build_bot(settings, fake_api, fake_assistant)
    assert bot.process_post_queue() == 0
    assert fake_api.containers == []
    assert bot.store.count_by_status("published_posts") == {Status.REJECTED: 1}
    bot.close()


def test_parse_prompt_file_header() -> None:
    tz = ZoneInfo("Europe/Bratislava")
    parsed = parse_prompt_file("publish_at: 5.10.2026 18:00\n---\nText postu", tz)
    assert parsed.body == "Text postu"
    assert parsed.publish_at == datetime(2026, 10, 5, 18, 0, tzinfo=tz)
    plain = parse_prompt_file("Text bez hlavičky\n---\nďalší odsek", tz)
    assert plain.publish_at is None and "ďalší odsek" in plain.body


def test_generate_script_writes_markdown(
    settings_factory: Callable[..., Settings], fake_api: FakeInstagramAPI, fake_assistant: FakeAssistant
) -> None:
    settings = settings_factory()
    bot = build_bot(settings, fake_api, fake_assistant)
    path = bot.generate_video_script("3 chyby pri výbere kávy")
    assert path.parent == settings.scripts_output_dir and path.name.endswith("3-chyby-pri-vybere-kavy.md")
    assert path.read_text(encoding="utf-8").startswith("# Scenár")
    bot.close()
