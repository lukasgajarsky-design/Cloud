"""Spoločné fixtures: izolované nastavenia, falošné API a falošný Claude.

Testy nikdy nevolajú skutočné Meta, Anthropic ani OpenAI API.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from instagram_bot.config import Settings
from instagram_bot.models import (
    AccountProfile,
    CaptionDraft,
    ClaudeTextResult,
    Comment,
    ConversationSummary,
    DirectMessage,
    Media,
    PublishingQuota,
    ReplyAction,
    ReplyDecision,
)

BASE_ENV: dict[str, str] = {
    "META_ACCESS_TOKEN": "IGQtesttoken1234567890abcdefghijklmnopqrstuvwxyz",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID": "17841400000000000",
    "ANTHROPIC_API_KEY": "sk-ant-test-key-1234567890",
    "OPENAI_API_KEY": "sk-test-openai-key-1234567890abcdef",
    "MEDIA_PUBLIC_BASE_URL": "https://cdn.example.com/queue",
    "MIN_SECONDS_BETWEEN_ACTIONS": "0",
    "QUEUE_MIN_FILE_AGE_SECONDS": "0",
    "MAX_THROTTLE_SLEEP_SECONDS": "0",
    "BOT_TIMEZONE": "Europe/Bratislava",
}


@pytest.fixture
def settings_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., Settings]:
    """Vytvorí ``Settings`` s cestami v dočasnom priečinku a vlastnými hodnotami."""

    def factory(**overrides: str) -> Settings:
        env_file = tmp_path / "test.env"
        env_file.write_text("", encoding="utf-8")
        values = {
            **BASE_ENV,
            "DATABASE_PATH": str(tmp_path / "data" / "state.db"),
            "LOG_FILE": str(tmp_path / "bot.log"),
            "QUEUE_DIR": str(tmp_path / "queue"),
            "BRAND_VOICE_PATH": str(tmp_path / "config" / "brand_voice.md"),
            "STYLE_GUIDE_PATH": str(tmp_path / "config" / "style_guide.txt"),
            "SCRIPTS_OUTPUT_DIR": str(tmp_path / "output"),
            "LOCK_FILE": str(tmp_path / "data" / "bot.lock"),
            **overrides,
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        return Settings.load(env_file)

    return factory


# ----------------------------------------------------------------------- Meta API
class FakeInstagramAPI:
    """Pamäťová náhrada ``InstagramAPI`` – zaznamenáva odoslané odpovede."""

    def __init__(self) -> None:
        self.profile = AccountProfile(id="17841400000000000", username="moja_znacka")
        self.media: list[Media] = []
        self.comments: dict[str, list[Comment]] = {}
        self.conversations: list[ConversationSummary] = []
        self.messages: dict[str, list[DirectMessage]] = {}
        self.comment_replies: list[tuple[str, str]] = []
        self.sent_messages: list[tuple[str, str]] = []
        self.published: list[str] = []
        self.containers: list[tuple[str, str, str]] = []
        self.reply_error: Exception | None = None
        self.quota: PublishingQuota | None = None

    def get_profile(self) -> AccountProfile:
        return self.profile

    def get_recent_media(self, limit: int) -> list[Media]:
        return self.media[:limit]

    def get_comments(self, media_id: str, max_items: int) -> list[Comment]:
        return self.comments.get(media_id, [])[:max_items]

    def reply_to_comment(self, comment_id: str, message: str) -> str:
        if self.reply_error:
            raise self.reply_error
        self.comment_replies.append((comment_id, message))
        return f"reply_{comment_id}"

    def get_conversations(self, limit: int) -> list[ConversationSummary]:
        return self.conversations[:limit]

    def get_conversation_messages(self, conversation_id: str, limit: int) -> list[DirectMessage]:
        return self.messages.get(conversation_id, [])[-limit:]

    def send_direct_message(self, recipient_id: str, text: str) -> str:
        self.sent_messages.append((recipient_id, text))
        return f"mid_{len(self.sent_messages)}"

    def get_publishing_quota(self) -> PublishingQuota | None:
        return self.quota

    def create_image_container(self, image_url: str, caption: str) -> str:
        self.containers.append(("IMAGE", image_url, caption))
        return f"container_{len(self.containers)}"

    def create_reel_container(self, video_url: str, caption: str, *, share_to_feed: bool = True) -> str:
        self.containers.append(("REELS", video_url, caption))
        return f"container_{len(self.containers)}"

    def wait_for_container(self, container_id: str, *, timeout_seconds: float, poll_interval_seconds: float) -> None:
        return None

    def publish_container(self, container_id: str) -> str:
        self.published.append(container_id)
        return f"media_{len(self.published)}"

    def get_permalink(self, media_id: str) -> str | None:
        return f"https://www.instagram.com/p/{media_id}/"


@pytest.fixture
def fake_api() -> FakeInstagramAPI:
    return FakeInstagramAPI()


# ------------------------------------------------------------------------ Claude
class FakeAssistant:
    """Náhrada ``ClaudeAssistant`` s nastaviteľnými rozhodnutiami."""

    model = "claude-opus-5-5"

    def __init__(self) -> None:
        self.comment_decision = ReplyDecision(ReplyAction.REPLY, "Ďakujeme, tešíme sa! ☕", "pochvala")
        self.dm_decision = ReplyDecision(ReplyAction.REPLY, "Ahoj! Áno, máme to skladom.", "otázka na dostupnosť")
        self.caption = CaptionDraft(True, (), "Hook riadok", "Telo príspevku.", "Napíš nám do DM!", ("kava", "#rano"))
        self.comment_calls: list[Comment] = []
        self.dm_calls: list[list[DirectMessage]] = []
        self.caption_calls: list[str] = []
        self.error: Exception | None = None

    def decide_comment_reply(self, comment: Comment, media: Media) -> ReplyDecision:
        if self.error:
            raise self.error
        self.comment_calls.append(comment)
        return self.comment_decision

    def decide_dm_reply(self, history: Any, *, own_label: str, is_own: Any) -> ReplyDecision:
        if self.error:
            raise self.error
        self.dm_calls.append(list(history))
        return self.dm_decision

    def draft_caption(self, prompt_text: str, media_kind: str, source_name: str) -> CaptionDraft:
        self.caption_calls.append(prompt_text)
        return self.caption

    def write_video_script(self, topic: str, notes: str | None = None) -> ClaudeTextResult:
        return ClaudeTextResult(text=f"# Scenár: {topic}", model=self.model, input_tokens=10, output_tokens=20)


@pytest.fixture
def fake_assistant() -> FakeAssistant:
    return FakeAssistant()


class FakeMediaHost:
    def public_url_for(self, file_path: Path) -> str:
        return f"https://cdn.example.com/queue/{file_path.name}"

    def verify(self, url: str, expected_size: int) -> None:
        return None


# ------------------------------------------------------- falošný Anthropic klient
class FakeAnthropicClient:
    """Napodobňuje ``anthropic.Anthropic`` – zaznamenáva parametre volaní."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create, stream=self._stream)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create, stream=self._stream))

    def with_options(self, **_: Any) -> FakeAnthropicClient:
        return self

    def _next(self, kwargs: dict[str, Any]) -> Any:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def _create(self, **kwargs: Any) -> Any:
        return self._next(kwargs)

    def _stream(self, **kwargs: Any) -> Any:
        client = self

        class _Stream:
            def __enter__(self) -> Any:
                message = client._next(kwargs)
                return SimpleNamespace(get_final_message=lambda: message)

            def __exit__(self, *_: Any) -> None:
                return None

        return _Stream()


def make_message(text: str, *, stop_reason: str = "end_turn", content: list[Any] | None = None) -> SimpleNamespace:
    """Odpoveď v tvare objektu ``Message`` z Anthropic SDK."""
    blocks = (
        content
        if content is not None
        else [
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ]
    )
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        stop_details=None,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
        _request_id="req_test",
    )


def make_json_message(payload: dict[str, Any]) -> SimpleNamespace:
    return make_message(json.dumps(payload, ensure_ascii=False))


# ------------------------------------------------------------------ ffmpeg video
@pytest.fixture(scope="session")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Syntetické 6 s video: 3 výrazne odlišné scény po 2 s + tón 440 Hz."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg nie je nainštalovaný")
    path = tmp_path_factory.mktemp("video") / "ukazka.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25:duration=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=640x360:rate=25:duration=2",
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=640x360:rate=25:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "3:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        timeout=120,
    )
    return path
