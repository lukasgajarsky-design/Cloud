"""Volania Claude Opus 5.5 cez oficiálne ``anthropic`` Python SDK.

Kľúčové rozhodnutia:

* **Model** ``claude-opus-5-5`` (1M kontext, až 600 obrázkov v jednej požiadavke)
  s **adaptívnym premýšľaním** (``thinking={"type": "adaptive"}``). Hĺbku
  premýšľania riadi ``output_config.effort`` – iná úroveň pre odpovede,
  pre tvorbu obsahu a pre analýzu videa (nastaviteľné v ``.env``).
* **Štruktúrovaný výstup** (``output_config.format`` s JSON schémou) – API
  garantuje validný JSON, takže odpoveď sa nedá „rozbiť“ ani prompt injection-om.
  (Vynútené ``tool_choice`` Opus 5.5 nepodporuje, preto používame tento spôsob.)
* **Retries s exponenciálnym vyčkávaním** rieši SDK automaticky pri 408/409/429/5xx
  a sieťových chybách (``max_retries`` z ``.env``); my už len preložíme konečnú
  chybu na ``ClaudeError`` s príznakom, či má zmysel skúsiť to neskôr.
* **Odmietnutie** (``stop_reason == "refusal"``) sa nikdy nepublikuje – bot
  vec eskaluje človeku. Voliteľný server-side fallback (``fallbacks: "default"``)
  nechá API v prípade odmietnutia požiadavku zopakovať na odporúčanom modeli.
* **Dlhé výstupy** (blueprint, scenár) sa sťahujú streamingom, aby veľká
  požiadavka nenarazila na HTTP timeout.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any, Final

import anthropic

from .exceptions import ClaudeAuthError, ClaudeError
from .knowledge import KnowledgeBase
from .models import (
    CaptionDraft,
    ClaudeTextResult,
    Comment,
    DirectMessage,
    Media,
    MediaKind,
    ReplyAction,
    ReplyDecision,
)
from .prompts import (
    CAPTION_SCHEMA,
    CAPTION_TASK_INSTRUCTIONS,
    REPLY_DECISION_SCHEMA,
    SCRIPT_TASK_INSTRUCTIONS,
    STYLE_ANALYSIS_SYSTEM,
    build_shared_context,
    comment_task_instructions,
    dm_task_instructions,
    neutralize_untrusted,
)

logger = logging.getLogger(__name__)

# Beta hlavička pre server-side fallback v tvare ``fallbacks: "default"``.
SERVER_FALLBACK_BETA: Final[str] = "server-side-fallback-2026-07-01"
# Limity výstupných tokenov: krátke JSON odpovede vs. dlhé dokumenty (streaming).
STRUCTURED_MAX_TOKENS: Final[int] = 16_000
SCRIPT_MAX_TOKENS: Final[int] = 32_000
BLUEPRINT_MAX_TOKENS: Final[int] = 64_000


class ClaudeAssistant:
    """Všetky úlohy, pri ktorých bot „premýšľa“ cez Claude."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        knowledge: KnowledgeBase,
        effort_replies: str = "medium",
        effort_content: str = "high",
        effort_learn: str = "high",
        max_retries: int = 5,
        timeout_seconds: float = 600.0,
        learn_timeout_seconds: float = 1800.0,
        server_fallback: bool = True,
        comment_max_chars: int = 500,
        dm_max_chars: int = 900,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        # SDK samo opakuje 429/5xx s exponenciálnym backoffom (rešpektuje aj retry-after).
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=max_retries, timeout=timeout_seconds)
        self._model = model
        self._knowledge = knowledge
        self._effort_replies = effort_replies
        self._effort_content = effort_content
        self._effort_learn = effort_learn
        self._learn_timeout = learn_timeout_seconds
        self._server_fallback = server_fallback
        self._comment_max_chars = comment_max_chars
        self._dm_max_chars = dm_max_chars

    @property
    def model(self) -> str:
        return self._model

    # ------------------------------------------------------------ verejné úlohy
    def decide_comment_reply(self, comment: Comment, media: Media) -> ReplyDecision:
        """Rozhodne o odpovedi na komentár (reply / ignore / escalate)."""
        post_caption = media.caption[:1500] if media.caption else "(bez popisu)"
        user_content = (
            "<post_context>\n"
            f"Typ príspevku: {media.media_type or 'neznámy'}\n"
            f"Popis príspevku: {post_caption}\n"
            "</post_context>\n\n"
            f'<untrusted_comment author="@{neutralize_untrusted(comment.username)}">\n'
            f"{neutralize_untrusted(comment.text)}\n"
            "</untrusted_comment>"
        )
        data = self._structured_call(
            task="komentár",
            task_instructions=comment_task_instructions(self._comment_max_chars),
            user_content=user_content,
            schema=REPLY_DECISION_SCHEMA,
            effort=self._effort_replies,
        )
        return self._to_reply_decision(data)

    def decide_dm_reply(
        self, history: Sequence[DirectMessage], *, own_label: str, is_own: Sequence[bool]
    ) -> ReplyDecision:
        """Rozhodne o odpovedi v DM na základe histórie konverzácie (chronologicky)."""
        lines = []
        for message, own in zip(history, is_own, strict=True):
            when = message.created_time.strftime("%Y-%m-%d %H:%M UTC") if message.created_time else "?"
            author = own_label if own else f"zákazník (@{neutralize_untrusted(message.sender_username or 'neznámy')})"
            text = neutralize_untrusted(message.text) if message.text else "[príloha / nálepka bez textu]"
            lines.append(f"[{when}] {author}: {text}")
        user_content = (
            "<untrusted_conversation>\n" + "\n".join(lines) + "\n</untrusted_conversation>\n\n"
            "Odpovedz na posledné nezodpovedané správy zákazníka."
        )
        data = self._structured_call(
            task="DM",
            task_instructions=dm_task_instructions(self._dm_max_chars),
            user_content=user_content,
            schema=REPLY_DECISION_SCHEMA,
            effort=self._effort_replies,
        )
        return self._to_reply_decision(data)

    def draft_caption(self, prompt_text: str, media_kind: MediaKind, source_name: str) -> CaptionDraft:
        """Skontroluje a vylepší popis príspevku z fronty (hook → body → CTA + hashtagy)."""
        kind_label = "obrázok (feed post)" if media_kind == "IMAGE" else "video (Instagram Reels)"
        user_content = (
            f"Typ média: {kind_label}\nNázov súboru: {source_name}\n\n<author_prompt>\n{prompt_text}\n</author_prompt>"
        )
        data = self._structured_call(
            task="popis príspevku",
            task_instructions=CAPTION_TASK_INSTRUCTIONS,
            user_content=user_content,
            schema=CAPTION_SCHEMA,
            effort=self._effort_content,
        )
        if data is None:
            return CaptionDraft(
                approved=False,
                issues=("Claude požiadavku odmietol (refusal) – skontroluj obsah promptu.",),
                hook="",
                body="",
                cta="",
                hashtags=(),
            )
        return CaptionDraft(
            approved=bool(data.get("approved")),
            issues=tuple(str(issue) for issue in data.get("issues") or []),
            hook=str(data.get("hook") or ""),
            body=str(data.get("body") or ""),
            cta=str(data.get("cta") or ""),
            hashtags=tuple(str(tag) for tag in data.get("hashtags") or []),
        )

    def write_video_script(self, topic: str, notes: str | None = None) -> ClaudeTextResult:
        """Vygeneruje scenár nového videa presne podľa Video Style Blueprintu."""
        user_content = f"<tema>\n{topic}\n</tema>"
        if notes:
            user_content += f"\n\n<poznamky_autora>\n{notes}\n</poznamky_autora>"
        message = self._stream_call(
            system=self._system_blocks(SCRIPT_TASK_INSTRUCTIONS),
            content=user_content,
            effort=self._effort_content,
            max_tokens=SCRIPT_MAX_TOKENS,
            timeout=self._learn_timeout,
            task="scenár videa",
        )
        return self._to_text_result(message, task="scenár videa")

    def analyze_video_style(self, content: list[dict[str, Any]]) -> ClaudeTextResult:
        """Jedna masívna multimodálna požiadavka: snímky + metriky + prepis → blueprint.

        ``content`` pripravuje ``VideoStyleLearner`` (text + obrázky v base64).
        Brand voice ani starý blueprint sa sem nevkladajú automaticky – analýza
        má opisovať video, nie existujúce predstavy o značke.
        """
        message = self._stream_call(
            system=[{"type": "text", "text": STYLE_ANALYSIS_SYSTEM}],
            content=content,
            effort=self._effort_learn,
            max_tokens=BLUEPRINT_MAX_TOKENS,
            timeout=self._learn_timeout,
            task="analýza videa",
        )
        return self._to_text_result(message, task="analýza videa")

    # ---------------------------------------------------------- interné metódy
    def _system_blocks(self, task_instructions: str) -> list[dict[str, Any]]:
        """System prompt: [spoločný kontext s blueprintom (cache), pokyny úlohy]."""
        shared = build_shared_context(self._knowledge.snapshot())
        return [
            {"type": "text", "text": shared, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": task_instructions},
        ]

    def _structured_call(
        self,
        *,
        task: str,
        task_instructions: str,
        user_content: str,
        schema: dict[str, Any],
        effort: str,
    ) -> dict[str, Any] | None:
        """Volanie so štruktúrovaným JSON výstupom. ``None`` = model odmietol odpovedať."""
        message = self._invoke(
            stream=False,
            timeout=None,
            model=self._model,
            max_tokens=STRUCTURED_MAX_TOKENS,
            system=self._system_blocks(task_instructions),
            messages=[{"role": "user", "content": user_content}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        self._log_usage(message, task)
        if message.stop_reason == "refusal":
            self._log_refusal(message, task)
            return None
        if message.stop_reason == "max_tokens":
            raise ClaudeError(f"Odpoveď Claude ({task}) bola orezaná limitom max_tokens.", retryable=False)
        text = _final_text(message.content)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClaudeError(f"Claude ({task}) nevrátil platný JSON.", retryable=True) from exc
        if not isinstance(data, dict):
            raise ClaudeError(f"Claude ({task}) vrátil neočakávaný JSON.", retryable=True)
        return data

    def _stream_call(
        self,
        *,
        system: list[dict[str, Any]],
        content: str | list[dict[str, Any]],
        effort: str,
        max_tokens: int,
        timeout: float,
        task: str,
    ) -> Any:
        """Dlhý výstup cez streaming (vracia kompletnú správu po dokončení)."""
        logger.info("Odosielam požiadavku na Claude (%s, model %s, effort %s)…", task, self._model, effort)
        message = self._invoke(
            stream=True,
            timeout=timeout,
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
        )
        self._log_usage(message, task)
        return message

    def _invoke(self, *, stream: bool, timeout: float | None, **params: Any) -> Any:
        """Zavolá Messages API (voliteľne cez beta endpoint so server-side fallbackom).

        Chyby SDK prekladá na ``ClaudeError``; poradie ``except`` je od najšpecifickejšej.
        """
        client = self._client.with_options(timeout=timeout) if timeout else self._client
        try:
            if self._server_fallback:
                params = {**params, "betas": [SERVER_FALLBACK_BETA], "fallbacks": "default"}
                if stream:
                    with client.beta.messages.stream(**params) as response_stream:
                        return response_stream.get_final_message()
                return client.beta.messages.create(**params)
            if stream:
                with client.messages.stream(**params) as response_stream:
                    return response_stream.get_final_message()
            return client.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise ClaudeAuthError("Neplatný ANTHROPIC_API_KEY (401).") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ClaudeAuthError("API kľúč nemá prístup k modelu alebo funkcii (403).") from exc
        except anthropic.NotFoundError as exc:
            raise ClaudeAuthError(f"Model '{self._model}' neexistuje alebo k nemu nemáš prístup (404).") from exc
        except anthropic.BadRequestError as exc:
            raise ClaudeError(f"Neplatná požiadavka na Claude (400): {exc.message}", retryable=False) from exc
        except anthropic.RateLimitError as exc:
            raise ClaudeError(
                f"Rate limit Anthropic API pretrváva aj po opakovaniach (request_id={_request_id(exc)}).",
                retryable=True,
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ClaudeError(
                f"Chyba Anthropic API {exc.status_code} (request_id={_request_id(exc)}).",
                retryable=exc.status_code >= 500,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ClaudeError(
                f"Sieťová chyba alebo timeout pri volaní Claude: {type(exc).__name__}", retryable=True
            ) from exc

    def _to_text_result(self, message: Any, *, task: str) -> ClaudeTextResult:
        if message.stop_reason == "refusal":
            self._log_refusal(message, task)
            raise ClaudeError(f"Claude odmietol úlohu „{task}“ (refusal).", retryable=False)
        text = _final_text(message.content).strip()
        if not text:
            raise ClaudeError(f"Claude vrátil prázdny výstup ({task}).", retryable=True)
        if message.stop_reason == "max_tokens":
            logger.warning("Výstup (%s) narazil na limit max_tokens – môže byť neúplný.", task)
        usage = message.usage
        return ClaudeTextResult(
            text=text,
            model=str(getattr(message, "model", self._model)),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            stop_reason=message.stop_reason,
        )

    @staticmethod
    def _to_reply_decision(data: dict[str, Any] | None) -> ReplyDecision:
        if data is None:
            return ReplyDecision(ReplyAction.ESCALATE, "", "Claude odmietol odpovedať (refusal) – rieši človek.")
        try:
            action = ReplyAction(str(data.get("action", "")).lower())
        except ValueError:
            action = ReplyAction.ESCALATE
        reply = str(data.get("reply") or "").strip()
        if action is ReplyAction.REPLY and not reply:
            return ReplyDecision(ReplyAction.ESCALATE, "", "Model zvolil 'reply', ale text odpovede je prázdny.")
        return ReplyDecision(action, reply, str(data.get("reason") or "").strip())

    def _log_usage(self, message: Any, task: str) -> None:
        usage = getattr(message, "usage", None)
        if usage is None:
            return
        served_by = getattr(message, "model", self._model)
        logger.info(
            "Claude (%s) – model %s, vstup %s tok. (z cache %s), výstup %s tok., stop=%s, request_id=%s",
            task,
            served_by,
            getattr(usage, "input_tokens", "?"),
            getattr(usage, "cache_read_input_tokens", 0) or 0,
            getattr(usage, "output_tokens", "?"),
            message.stop_reason,
            getattr(message, "_request_id", None),
        )

    @staticmethod
    def _log_refusal(message: Any, task: str) -> None:
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        logger.warning("Claude odmietol úlohu „%s“ (refusal, kategória: %s) – nič sa nepublikuje.", task, category)


def _final_text(content: Sequence[Any]) -> str:
    """Spojí textové bloky odpovede (preskočí thinking bloky).

    Ak server-side fallback prepol na iný model, berieme len text za posledným
    blokom ``fallback`` – text pred ním patrí modelu, ktorý úlohu odmietol.
    """
    last_fallback = -1
    for index, block in enumerate(content):
        if getattr(block, "type", None) == "fallback":
            last_fallback = index
    texts = [
        block.text
        for block in list(content)[last_fallback + 1 :]
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    return "".join(texts)


def _request_id(exc: Exception) -> str | None:
    return getattr(exc, "request_id", None)
