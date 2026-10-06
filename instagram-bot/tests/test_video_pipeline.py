"""Integračné testy režimu --learn so skutočným ffmpeg (Claude a ASR sú falošné)."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from instagram_bot.exceptions import (
    ClaudeError,
    FFmpegNotFoundError,
    StyleLearningError,
)
from instagram_bot.models import ClaudeTextResult
from instagram_bot.storage import StateStore
from instagram_bot.video.ffmpeg import ExtractedFrame, FFmpegToolkit
from instagram_bot.video.frames import (
    deduplicate_frames,
    select_frames,
    uniform_subsample,
)
from instagram_bot.video.metrics import compute_cut_metrics, compute_speech_metrics
from instagram_bot.video.style_learner import VideoStyleLearner
from instagram_bot.video.transcription import Transcript, TranscriptSegment


class FakeTranscriber:
    name = "fake"
    max_chunk_seconds: float | None = None

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path) -> Transcript:
        self.calls.append(audio_path)
        assert audio_path.exists() and audio_path.stat().st_size > 0
        return Transcript(
            segments=(
                TranscriptSegment(0.2, 1.8, "Toto je hook, ktorý ťa zastaví."),
                TranscriptSegment(2.0, 5.5, "Tri tipy. Prvý tip je rýchly! Sleduj do konca."),
            ),
            language="sk",
            provider=self.name,
        )


class FakeStyleAssistant:
    model = "claude-opus-5-5"

    def __init__(self, error: Exception | None = None) -> None:
        self.content: list[dict[str, Any]] | None = None
        self.error = error

    def analyze_video_style(self, content: list[dict[str, Any]]) -> ClaudeTextResult:
        self.content = content
        if self.error:
            raise self.error
        return ClaudeTextResult(
            text="## 1. DNA videa v skratke\n- strih každé 2 s", model=self.model, input_tokens=5000, output_tokens=900
        )


@pytest.fixture
def captured_temp_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Path]:
    """Zachytí dočasné priečinky, aby sa dalo overiť ich vymazanie."""
    created: list[Path] = []
    original = tempfile.mkdtemp

    def tracking_mkdtemp(*args: Any, **kwargs: Any) -> str:
        path = original(*args, dir=str(tmp_path), **{k: v for k, v in kwargs.items() if k != "dir"})
        created.append(Path(path))
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", tracking_mkdtemp)
    return created


def make_learner(
    tmp_path: Path, assistant: FakeStyleAssistant, transcriber: FakeTranscriber | None = None
) -> VideoStyleLearner:
    return VideoStyleLearner(
        ffmpeg=FFmpegToolkit(timeout_seconds=120),
        transcriber=transcriber or FakeTranscriber(),
        assistant=assistant,  # type: ignore[arg-type]
        store=StateStore(tmp_path / "state.db"),
        style_guide_path=tmp_path / "config" / "style_guide.txt",
        timezone=ZoneInfo("Europe/Bratislava"),
        max_frames=60,
    )


def test_ffmpeg_detects_scenes_and_samples(sample_video: Path, tmp_path: Path) -> None:
    toolkit = FFmpegToolkit(timeout_seconds=120)
    info = toolkit.probe(sample_video)
    assert info.duration == pytest.approx(6.0, abs=0.1) and info.has_audio and info.width == 640
    scenes = toolkit.extract_scene_frames(sample_video, tmp_path / "s", threshold=0.3, max_side=768, jpeg_quality=5)
    assert [round(f.timestamp) for f in scenes] == [2, 4]
    samples = toolkit.extract_sampled_frames(sample_video, tmp_path / "f", fps=1.0, max_side=320, jpeg_quality=5)
    assert len(samples) == 6 and samples[3].timestamp == pytest.approx(3.0)
    with Image.open(samples[0].path) as image:
        assert max(image.size) == 320  # zmenšené na dlhšiu stranu
    audio = toolkit.extract_audio(sample_video, tmp_path / "a")
    assert audio.stat().st_size > 0


def test_missing_ffmpeg_gives_install_instructions() -> None:
    with pytest.raises(FFmpegNotFoundError) as excinfo:
        FFmpegToolkit("ffmpeg-ktory-neexistuje", "ffprobe-ktory-neexistuje").ensure_available()
    assert "sudo apt install -y ffmpeg" in str(excinfo.value) and "brew install ffmpeg" in str(excinfo.value)


def test_learn_end_to_end_writes_blueprint_and_cleans_temp(
    sample_video: Path, tmp_path: Path, captured_temp_dirs: list[Path]
) -> None:
    assistant = FakeStyleAssistant()
    learner = make_learner(tmp_path, assistant)
    result = learner.learn(sample_video)

    assert not result.skipped and result.cut_metrics is not None and result.cut_metrics.cut_count == 2
    blueprint = result.output_path.read_text(encoding="utf-8")
    assert blueprint.startswith("# Video Style Blueprint") and "DNA videa" in blueprint

    # Jedna multimodálna požiadavka: snímky v base64 + prepis + pokyny na konci.
    content = assistant.content or []
    images = [block for block in content if block["type"] == "image"]
    assert len(images) == result.frames_sent >= 3
    assert base64.b64decode(images[0]["source"]["data"])[:3] == b"\xff\xd8\xff"  # JPEG
    texts = "\n".join(block["text"] for block in content if block["type"] == "text")
    assert "Toto je hook" in texts and "[00:00.2 → 00:01.8]" in texts
    assert "STRIH (nová scéna)" in texts and "strihy za minútu: 20.0" in texts
    assert content[-1]["type"] == "text" and "Povinná štruktúra" in content[-1]["text"]

    # Dočasný priečinok so snímkami je po analýze vymazaný.
    assert captured_temp_dirs and not any(path.exists() for path in captured_temp_dirs)

    # Druhé spustenie s tým istým videom sa preskočí (SQLite), --force analyzuje znova.
    assert learner.learn(sample_video).skipped is True
    assert learner.learn(sample_video, force=True).skipped is False
    assert result.output_path.with_name("style_guide.txt.bak").exists()


def test_temp_dir_is_cleaned_even_when_claude_fails(
    sample_video: Path, tmp_path: Path, captured_temp_dirs: list[Path]
) -> None:
    learner = make_learner(tmp_path, FakeStyleAssistant(error=ClaudeError("výpadok", retryable=True)))
    with pytest.raises(ClaudeError):
        learner.learn(sample_video)
    assert captured_temp_dirs and not any(path.exists() for path in captured_temp_dirs)
    assert not (tmp_path / "config" / "style_guide.txt").exists()


def test_learn_rejects_unsupported_input(tmp_path: Path) -> None:
    bad = tmp_path / "video.avi"
    bad.write_bytes(b"x")
    with pytest.raises(StyleLearningError, match="mp4"):
        make_learner(tmp_path, FakeStyleAssistant()).learn(bad)


# ------------------------------------------------------- deduplikácia a metriky
def _image(path: Path, color: tuple[int, int, int], stripe: bool = False) -> Path:
    image = Image.new("RGB", (160, 90), color)
    if stripe:
        for x in range(0, 160, 20):
            for y in range(90):
                image.putpixel((x, y), (255, 255, 255))
    image.save(path, "JPEG", quality=90)
    return path


def test_deduplication_removes_identical_consecutive_frames(tmp_path: Path) -> None:
    red = _image(tmp_path / "a.jpg", (200, 0, 0))
    red_copy = tmp_path / "b.jpg"
    red_copy.write_bytes(red.read_bytes())
    striped = _image(tmp_path / "c.jpg", (0, 0, 200), stripe=True)
    frames = [
        ExtractedFrame(red, 0.0, "sample"),
        ExtractedFrame(red_copy, 1.0, "sample"),
        ExtractedFrame(striped, 2.0, "scene"),
    ]
    kept = deduplicate_frames(frames, max_distance=6)
    assert [f.path.name for f in kept] == ["a.jpg", "c.jpg"]


def test_frame_selection_prioritizes_scene_cuts() -> None:
    frames = [ExtractedFrame(Path(f"s{i}"), float(i), "sample") for i in range(100)]
    frames += [ExtractedFrame(Path(f"c{i}"), i + 0.5, "scene") for i in range(0, 100, 10)]
    selected = select_frames(sorted(frames, key=lambda f: f.timestamp), 30)
    assert len(selected) == 30 and sum(f.source == "scene" for f in selected) == 10
    assert uniform_subsample(list(range(10)), 3) == [0, 4, 9]


def test_cut_and_speech_metrics() -> None:
    metrics = compute_cut_metrics([2.0, 2.1, 4.0], duration=6.0)
    assert metrics.cut_times == (2.0, 4.0)  # strih 2.1 s zlúčený (blesk/prechod)
    assert metrics.shot_lengths == (2.0, 2.0, 2.0) and metrics.cuts_per_minute == pytest.approx(20.0)
    transcript = Transcript(
        segments=(TranscriptSegment(0.0, 6.0, "Jedna dva tri. Štyri päť šesť!"),), language="sk", provider="x"
    )
    speech = compute_speech_metrics(transcript)
    assert speech.word_count == 6 and speech.words_per_minute == pytest.approx(60.0)
    assert speech.average_sentence_words == pytest.approx(3.0)
