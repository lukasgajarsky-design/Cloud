"""Testy pomocných funkcií: text, retry, logovanie, konfigurácia, databáza."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from instagram_bot.config import RunMode, Settings
from instagram_bot.exceptions import ConfigError
from instagram_bot.logging_setup import SecretRedactingFormatter
from instagram_bot.retry import compute_backoff
from instagram_bot.storage import StateStore, Status
from instagram_bot.text_utils import (
    compose_caption,
    count_hashtags,
    normalize_hashtags,
    slugify,
    truncate_text,
    truncate_utf8_bytes,
)


# ----------------------------------------------------------------------- text
def test_normalize_hashtags_cleans_dedupes_and_limits() -> None:
    tags = normalize_hashtags(["Káva", "#kava", "ranná rutina", "#", "#Káva", "123", "#kava!"], max_count=30)
    assert tags == ["#Káva", "#kava", "#rannárutina"]
    assert len(normalize_hashtags([f"tag{i}" for i in range(50)])) == 30


def test_compose_caption_structure_and_limits() -> None:
    caption = compose_caption("Hook!", "Telo.", "Napíš nám.", ["kava", "rano"])
    assert caption == "Hook!\n\nTelo.\n\nNapíš nám.\n\n#kava #rano"

    long_body = "slovo " * 600
    caption = compose_caption("Hook", long_body, "CTA", [f"t{i}" for i in range(40)])
    assert len(caption) <= 2200
    assert caption.startswith("Hook") and "CTA" in caption
    assert count_hashtags(caption) <= 30


def test_truncation_helpers() -> None:
    assert truncate_text("krátky text", 50) == "krátky text"
    shortened = truncate_text("toto je dlhá veta, ktorú treba skrátiť na hranici slova", 25)
    assert len(shortened) <= 25 and shortened.endswith("…")
    diacritics = "ž" * 600  # 2 bajty na znak
    limited = truncate_utf8_bytes(diacritics, 1000)
    assert len(limited.encode("utf-8")) <= 1000
    assert slugify("3 chyby pri výbere kávy!") == "3-chyby-pri-vybere-kavy"


# ---------------------------------------------------------------------- retry
def test_backoff_grows_exponentially_and_is_capped() -> None:
    def no_jitter() -> float:
        return 1.0  # horná hranica intervalu

    assert compute_backoff(0, 2, 120, rng=no_jitter) == 2
    assert compute_backoff(3, 2, 120, rng=no_jitter) == 16
    assert compute_backoff(10, 2, 120, rng=no_jitter) == 120
    assert compute_backoff(3, 2, 120, rng=lambda: 0.0) == 8  # dolná polovica intervalu


# ------------------------------------------------------------------ logovanie
def test_formatter_redacts_tokens_everywhere() -> None:
    formatter = SecretRedactingFormatter(["IGQsupertajnytoken123456"])
    record = logging.LogRecord(
        "x",
        logging.ERROR,
        __file__,
        1,
        "chyba pri https://graph.instagram.com/me?access_token=EAAabc123&x=1 token IGQsupertajnytoken123456 "
        "kľúč sk-ant-api03-abcdefghijklmnop",
        None,
        None,
    )
    output = formatter.format(record)
    assert "IGQsupertajnytoken123456" not in output
    assert "EAAabc123" not in output
    assert "sk-ant-api03" not in output
    assert "access_token=***" in output


# ---------------------------------------------------------------- konfigurácia
def test_settings_defaults_use_opus_with_adaptive_effort(settings_factory: Callable[..., Settings]) -> None:
    settings = settings_factory()
    assert settings.anthropic_model == "claude-opus-5-5"
    assert (settings.effort_replies, settings.effort_content, settings.effort_learn) == ("medium", "high", "high")
    assert settings.style_guide_path.name == "style_guide.txt"
    settings.validate_for(RunMode.RUN)
    assert "IGQtesttoken" not in repr(settings)  # tajomstvá sa nevypisujú


def test_settings_reports_all_problems(settings_factory: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigError) as excinfo:
        settings_factory(ANTHROPIC_EFFORT_LEARN="extreme", POLL_INTERVAL_SECONDS="5", DRY_RUN="mozno")
    message = str(excinfo.value)
    assert "ANTHROPIC_EFFORT_LEARN" in message and "POLL_INTERVAL_SECONDS" in message and "DRY_RUN" in message


def test_validate_for_mode_specific_requirements(settings_factory: Callable[..., Settings]) -> None:
    settings = settings_factory(META_ACCESS_TOKEN="your_meta_access_token", OPENAI_API_KEY="")
    settings.validate_for(RunMode.SCRIPT)  # scenár nepotrebuje Meta token
    with pytest.raises(ConfigError, match="META_ACCESS_TOKEN"):
        settings.validate_for(RunMode.RUN)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        settings.validate_for(RunMode.LEARN)


# ------------------------------------------------------------------- databáza
def test_state_store_claim_release_finish(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    assert store.claim_comment("c1", "m1") is True
    assert store.claim_comment("c1", "m1") is False  # druhýkrát sa nezaberie → žiadna duplicita
    store.release_comment("c1")
    assert store.is_comment_known("c1") is False
    assert store.claim_comment("c1", "m1") is True
    store.finish_comment("c1", Status.REPLIED, reply_id="r1")
    store.release_comment("c1")  # dokončený záznam sa uvoľniť nedá
    assert store.is_comment_known("c1") is True

    store.mark_messages(["d1", "d2"], "conv", Status.REPLIED, "ok")
    assert store.is_message_known("d1") and store.is_message_known("d2")
    assert store.claim_message("d2", "conv") is False

    store.upsert_post("hash", "post", Status.PUBLISHING, container_id="c")
    store.upsert_post("hash", "post", Status.PUBLISHED, media_id="m")
    record = store.get_post("hash")
    assert record is not None and record.status == Status.PUBLISHED
    assert record.container_id == "c" and record.media_id == "m"
    assert store.count_by_status("published_posts") == {Status.PUBLISHED: 1}
    store.close()
