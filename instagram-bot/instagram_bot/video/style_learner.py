"""Režim učenia: z videa vytvorí „Video Style Blueprint“ v ``config/style_guide.txt``.

Kroky (všetko v dočasnom priečinku, ktorý sa na konci automaticky vymaže):

1. kontrola vstupu (.mp4/.mov) a dostupnosti ffmpeg,
2. snímky pri zmene scény (``select=gt(scene,0.3)``) + pravidelné vzorky (napr. 1 fps),
3. deduplikácia snímok (SHA-256 + percepčný hash) a výber s prioritou strihov,
4. extrakcia audia cez ffmpeg a prepis reči s časovými značkami,
5. lokálne metriky (rytmus strihu, tempo reči),
6. JEDNA multimodálna požiadavka na Claude Opus 5.5 (snímky v base64 + prepis + metriky),
7. atómový zápis blueprintu (starý sa prepíše, posledná verzia sa zálohuje do ``.bak``),
8. záznam do SQLite – rovnaké video sa bez ``--force`` neanalyzuje znova.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from ..claude_client import ClaudeAssistant
from ..exceptions import StyleLearningError
from ..prompts import style_analysis_instructions
from ..storage import StateStore
from ..text_utils import format_timestamp
from .ffmpeg import ExtractedFrame, FFmpegToolkit, VideoInfo
from .frames import base64_size, deduplicate_frames, select_frames
from .metrics import (
    CutMetrics,
    SpeechMetrics,
    compute_cut_metrics,
    compute_speech_metrics,
)
from .transcription import Transcriber, Transcript, merge_transcripts

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_EXTENSIONS: Final[frozenset[str]] = frozenset({".mp4", ".mov"})
# Rezerva na JSON obal požiadavky, texty a prepis (bajty).
_REQUEST_OVERHEAD_BYTES: Final[int] = 512 * 1024
# Koľkokrát viac vzoriek, než nakoniec pošleme – aby deduplikácia mala z čoho vyberať.
_SAMPLING_OVERSAMPLE: Final[int] = 3
_MAX_IMAGE_BASE64_BYTES: Final[int] = 10 * 1024 * 1024


@dataclass(frozen=True)
class StyleLearningResult:
    """Výsledok učenia (alebo informácia, že video už bolo analyzované)."""

    output_path: Path
    video_hash: str
    skipped: bool
    model: str = ""
    frames_extracted: int = 0
    frames_sent: int = 0
    transcript_segments: int = 0
    cut_metrics: CutMetrics | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class VideoStyleLearner:
    """Orchestrácia celej pipeline učenia štýlu z jedného videa."""

    def __init__(
        self,
        *,
        ffmpeg: FFmpegToolkit,
        transcriber: Transcriber,
        assistant: ClaudeAssistant,
        store: StateStore,
        style_guide_path: Path,
        timezone: ZoneInfo,
        scene_threshold: float = 0.3,
        sample_fps: float = 1.0,
        max_frames: int = 240,
        frame_max_side: int = 768,
        jpeg_quality: int = 5,
        dedup_distance: int = 6,
        max_video_seconds: int = 3600,
        max_request_bytes: int = 28 * 1024 * 1024,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._transcriber = transcriber
        self._assistant = assistant
        self._store = store
        self._style_guide_path = style_guide_path
        self._timezone = timezone
        self._scene_threshold = scene_threshold
        self._sample_fps = sample_fps
        self._max_frames = max_frames
        self._frame_max_side = frame_max_side
        self._jpeg_quality = jpeg_quality
        self._dedup_distance = dedup_distance
        self._max_video_seconds = max_video_seconds
        self._max_request_bytes = max_request_bytes

    def learn(
        self, video_path: Path, *, force: bool = False, keep_temp: bool = False, merge: bool = False
    ) -> StyleLearningResult:
        """Spustí celú analýzu a zapíše blueprint. Vracia súhrn výsledku."""
        video = self._validate_input(video_path)
        logger.info("Režim učenia: %s", video)
        logger.info("Používam %s", self._ffmpeg.ensure_available())

        video_hash = _sha256_file(video)
        previous_run = self._store.get_learning_run(video_hash)
        if previous_run and not force and self._style_guide_path.exists():
            logger.info(
                "Toto video už bolo analyzované %s (počet snímok: %d). Pre novú analýzu použi --force.",
                previous_run.created_at,
                previous_run.frames_sent,
            )
            return StyleLearningResult(output_path=self._style_guide_path, video_hash=video_hash, skipped=True)

        info = self._ffmpeg.probe(video)
        self._validate_info(info, video)
        logger.info(
            "Video: %.1f s, %dx%d (%s), %s fps, zvuk: %s",
            info.duration,
            info.width,
            info.height,
            info.orientation,
            f"{info.fps:.2f}" if info.fps else "?",
            "áno" if info.has_audio else "nie",
        )

        previous_blueprint = self._read_previous_blueprint() if merge else None
        temp_dir = Path(tempfile.mkdtemp(prefix="igbot_learn_"))  # práva 0700 – len pre tento proces/používateľa
        logger.info("Dočasný priečinok pre snímky: %s", temp_dir)
        try:
            frames, extracted_count, cut_metrics = self._prepare_frames(video, info, temp_dir)
            transcript = self._transcribe(video, info, temp_dir)
            speech_metrics = compute_speech_metrics(transcript)
            frames = self._fit_payload(frames)
            content = self._build_request_content(
                video=video,
                info=info,
                frames=frames,
                cut_metrics=cut_metrics,
                speech_metrics=speech_metrics,
                transcript=transcript,
                previous_blueprint=previous_blueprint,
            )
            logger.info(
                "Posielam do Claude jednu multimodálnu požiadavku – snímky: %d, segmenty prepisu: %d.",
                len(frames),
                len(transcript.segments),
            )
            analysis = self._assistant.analyze_video_style(content)
            output_path = self._write_blueprint(
                analysis.text,
                video=video,
                video_hash=video_hash,
                model=analysis.model,
                frames_sent=len(frames),
                transcript=transcript,
                cut_metrics=cut_metrics,
            )
            self._store.record_learning_run(
                video_hash=video_hash,
                video_name=video.name,
                frames_sent=len(frames),
                transcript_segments=len(transcript.segments),
                output_path=str(output_path),
                model=analysis.model,
                input_tokens=analysis.input_tokens,
                output_tokens=analysis.output_tokens,
            )
            return StyleLearningResult(
                output_path=output_path,
                video_hash=video_hash,
                skipped=False,
                model=analysis.model,
                frames_extracted=extracted_count,
                frames_sent=len(frames),
                transcript_segments=len(transcript.segments),
                cut_metrics=cut_metrics,
                input_tokens=analysis.input_tokens,
                output_tokens=analysis.output_tokens,
            )
        finally:
            if keep_temp:
                logger.info("Dočasné súbory ponechané (--keep-temp): %s", temp_dir)
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info("Dočasný priečinok so snímkami bol vymazaný: %s", temp_dir)

    # ---------------------------------------------------------------- validácia
    @staticmethod
    def _validate_input(video_path: Path) -> Path:
        video = video_path.expanduser().resolve()
        if not video.is_file():
            raise StyleLearningError(f"Video neexistuje: {video}")
        if video.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise StyleLearningError(f"Nepodporovaný formát {video.suffix} – použi .mp4 alebo .mov.")
        if video.stat().st_size == 0:
            raise StyleLearningError(f"Video je prázdny súbor: {video}")
        return video

    def _validate_info(self, info: VideoInfo, video: Path) -> None:
        if info.duration <= 0:
            raise StyleLearningError(f"Nepodarilo sa zistiť dĺžku videa {video.name} (poškodený súbor?).")
        if info.duration > self._max_video_seconds:
            raise StyleLearningError(
                f"Video má {info.duration:.0f} s, limit je {self._max_video_seconds} s (LEARN_MAX_VIDEO_SECONDS)."
            )

    # -------------------------------------------------------------------- snímky
    def _prepare_frames(
        self, video: Path, info: VideoInfo, temp_dir: Path
    ) -> tuple[list[ExtractedFrame], int, CutMetrics]:
        """Extrakcia (strihy + vzorky), metriky strihu, deduplikácia a výber snímok."""
        scene_frames = self._ffmpeg.extract_scene_frames(
            video,
            temp_dir / "scenes",
            threshold=self._scene_threshold,
            max_side=self._frame_max_side,
            jpeg_quality=self._jpeg_quality,
        )
        cut_metrics = compute_cut_metrics((frame.timestamp for frame in scene_frames), info.duration)
        logger.info(
            "Detekcia scén – strihy: %d, priemerný záber: %.2f s, tempo: %.1f strihu/min.",
            cut_metrics.cut_count,
            cut_metrics.average_shot,
            cut_metrics.cuts_per_minute,
        )

        # Pri dlhých videách znížime frekvenciu vzorkovania – aj tak by sme
        # poslali najviac LEARN_MAX_FRAMES snímok, netreba plniť disk tisíckami.
        effective_fps = min(self._sample_fps, max(0.02, (self._max_frames * _SAMPLING_OVERSAMPLE) / info.duration))
        if effective_fps < self._sample_fps:
            logger.info("Dlhé video – vzorkovanie znížené na %.3f snímky/s.", effective_fps)
        sample_frames = self._ffmpeg.extract_sampled_frames(
            video,
            temp_dir / "samples",
            fps=effective_fps,
            max_side=self._frame_max_side,
            jpeg_quality=self._jpeg_quality,
        )
        all_frames = [*scene_frames, *sample_frames]
        if not all_frames:
            raise StyleLearningError("ffmpeg nevytvoril žiadne snímky – skontroluj, či video nie je poškodené.")

        unique = deduplicate_frames(all_frames, self._dedup_distance)
        selected = select_frames(unique, self._max_frames)
        if len(selected) < len(unique):
            logger.info("Výber snímok: %d → %d (limit LEARN_MAX_FRAMES).", len(unique), len(selected))
        return selected, len(all_frames), cut_metrics

    def _fit_payload(self, frames: list[ExtractedFrame]) -> list[ExtractedFrame]:
        """Zabezpečí, že base64 snímky sa zmestia do limitu veľkosti požiadavky (32 MB)."""
        frames = [f for f in frames if base64_size(f.path.stat().st_size) <= _MAX_IMAGE_BASE64_BYTES]
        budget = self._max_request_bytes - _REQUEST_OVERHEAD_BYTES

        def total(items: list[ExtractedFrame]) -> int:
            return sum(base64_size(f.path.stat().st_size) for f in items)

        current = total(frames)
        while current > budget and len(frames) > 4:
            target = max(4, math.floor(len(frames) * budget / current * 0.95))
            logger.info(
                "Snímky majú spolu %.1f MB (limit %.1f MB) – redukujem %d → %d.",
                current / 1_048_576,
                budget / 1_048_576,
                len(frames),
                target,
            )
            frames = select_frames(frames, target)
            current = total(frames)
        if current > budget:
            raise StyleLearningError(
                "Ani po redukcii sa snímky nezmestia do limitu požiadavky – zníž LEARN_FRAME_MAX_SIDE "
                "alebo zvýš LEARN_JPEG_QUALITY (vyššie číslo = menší súbor)."
            )
        return frames

    # --------------------------------------------------------------------- prepis
    def _transcribe(self, video: Path, info: VideoInfo, temp_dir: Path) -> Transcript:
        """Extrahuje audio (po častiach, ak to poskytovateľ vyžaduje) a prepíše ho."""
        if self._transcriber.name == "none":
            logger.info("Prepis reči je vypnutý (ASR_PROVIDER=none).")
            return Transcript.empty("none")
        if not info.has_audio:
            logger.info("Video nemá zvukovú stopu – prepis preskakujem.")
            return Transcript.empty(self._transcriber.name)

        audio_dir = temp_dir / "audio"
        chunk = self._transcriber.max_chunk_seconds
        if chunk is None or info.duration <= chunk:
            audio = self._ffmpeg.extract_audio(video, audio_dir)
            logger.info("Prepisujem reč (%s)…", self._transcriber.name)
            transcript = self._transcriber.transcribe(audio)
        else:
            parts: list[Transcript] = []
            count = math.ceil(info.duration / chunk)
            for index in range(count):
                start = index * chunk
                audio = self._ffmpeg.extract_audio(
                    video, audio_dir, start=start, duration=chunk, name=f"audio_{index:03d}"
                )
                logger.info("Prepisujem časť %d/%d (%s)…", index + 1, count, self._transcriber.name)
                parts.append(self._transcriber.transcribe(audio).shifted(start))
            transcript = merge_transcripts(parts, self._transcriber.name)
        logger.info(
            "Prepis hotový – segmenty: %d, jazyk: %s.", len(transcript.segments), transcript.language or "neurčený"
        )
        return transcript

    # ---------------------------------------------------------- obsah požiadavky
    def _build_request_content(
        self,
        *,
        video: Path,
        info: VideoInfo,
        frames: list[ExtractedFrame],
        cut_metrics: CutMetrics,
        speech_metrics: SpeechMetrics,
        transcript: Transcript,
        previous_blueprint: str | None,
    ) -> list[dict[str, Any]]:
        """Poskladá obsah správy: metadáta → snímky (s popiskami) → prepis → pokyny.

        Dlhý obsah ide na začiatok a samotná úloha na koniec – tak Claude
        pracuje s dlhým kontextom najlepšie.
        """
        header = "\n".join(
            [
                "# Analyzované video",
                f"- súbor: {video.name}",
                f"- dĺžka: {info.duration:.1f} s",
                f"- rozlíšenie: {info.width}×{info.height} ({info.orientation})",
                f"- snímková frekvencia: {info.fps:.2f} fps" if info.fps else "- snímková frekvencia: neznáma",
                f"- zvuková stopa: {'áno' if info.has_audio else 'nie'}",
                "",
                "# Strihové metriky (namerané ffmpeg detekciou zmien scény)",
                cut_metrics.to_prompt_text(),
                "",
                "# Metriky reči (vypočítané z prepisu)",
                speech_metrics.to_prompt_text(),
                "",
                "# Snímky",
                f"Nasleduje {len(frames)} snímok v chronologickom poradí. Popiska pred každou snímkou uvádza jej "
                "číslo, čas vo videu a zdroj: STRIH = prvá snímka po detegovanej zmene scény, "
                "vzorka = pravidelné vzorkovanie (zachytáva aj zmeny titulkov a gest v rámci záberu).",
            ]
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": header}]
        for index, frame in enumerate(frames, start=1):
            label = "STRIH (nová scéna)" if frame.source == "scene" else "vzorka"
            content.append(
                {
                    "type": "text",
                    "text": f"Snímka {index}/{len(frames)} · {format_timestamp(frame.timestamp)} · {label}",
                }
            )
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(frame.path.read_bytes()).decode("ascii"),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": (
                    "# Prepis reči s časovými značkami\n"
                    f'<transcript provider="{transcript.provider}" language="{transcript.language or "?"}">\n'
                    f"{transcript.to_prompt_text()}\n"
                    "</transcript>"
                ),
            }
        )
        if previous_blueprint:
            content.append(
                {"type": "text", "text": f"<existujuci_blueprint>\n{previous_blueprint}\n</existujuci_blueprint>"}
            )
        content.append(
            {
                "type": "text",
                "text": style_analysis_instructions(
                    scene_threshold=self._scene_threshold, has_previous_blueprint=bool(previous_blueprint)
                ),
            }
        )
        return content

    # -------------------------------------------------------------------- výstup
    def _read_previous_blueprint(self) -> str | None:
        if not self._style_guide_path.exists():
            logger.info("--merge: zatiaľ neexistuje žiadny blueprint, vytvorím nový.")
            return None
        return self._style_guide_path.read_text(encoding="utf-8").strip() or None

    def _write_blueprint(
        self,
        analysis_text: str,
        *,
        video: Path,
        video_hash: str,
        model: str,
        frames_sent: int,
        transcript: Transcript,
        cut_metrics: CutMetrics,
    ) -> Path:
        """Atómovo zapíše blueprint (najprv do .tmp, potom premenovanie)."""
        path = self._style_guide_path
        path.parent.mkdir(parents=True, exist_ok=True)
        generated = datetime.now(self._timezone).strftime("%Y-%m-%d %H:%M %Z")
        header = (
            "# Video Style Blueprint\n"
            f"Zdroj: {video.name} (SHA-256 {video_hash[:16]}…) · Vygenerované: {generated} · Model: {model}\n"
            f"Podklady: {frames_sent} snímok, {len(transcript.segments)} segmentov prepisu, "
            f"{cut_metrics.cut_count} detegovaných strihov\n\n"
        )
        if path.exists():
            backup = path.with_name(path.name + ".bak")
            shutil.copy2(path, backup)
            logger.info("Predchádzajúci blueprint zálohovaný do %s.", backup.name)
        temp_path = path.with_name(path.name + ".tmp")
        temp_path.write_text(header + analysis_text.strip() + "\n", encoding="utf-8")
        os.replace(temp_path, path)
        logger.info("Video Style Blueprint uložený: %s", path)
        return path


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
