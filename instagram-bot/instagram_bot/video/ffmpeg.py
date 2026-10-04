"""Obal nad systémovými nástrojmi ``ffmpeg`` a ``ffprobe`` (volanie cez ``subprocess``).

Bezpečnosť: príkazy sa spúšťajú ako zoznam argumentov BEZ shellu (``shell=False``),
takže názov súboru nemôže podstrčiť vlastný príkaz. Cesty sa navyše prevádzajú
na absolútne – súbor s názvom začínajúcim pomlčkou sa tak nedá zameniť za prepínač.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from ..exceptions import FFmpegError, FFmpegNotFoundError

logger = logging.getLogger(__name__)

INSTALL_HINT: Final[str] = """\
ffmpeg/ffprobe nie je nainštalovaný alebo nie je v systémovej premennej PATH.
Nainštaluj ho podľa svojho systému:
  • Ubuntu / Debian:   sudo apt update && sudo apt install -y ffmpeg
  • Fedora:            sudo dnf install -y ffmpeg-free   (alebo ffmpeg z RPM Fusion)
  • Arch Linux:        sudo pacman -S ffmpeg
  • macOS (Homebrew):  brew install ffmpeg
  • Windows:           winget install --id Gyan.FFmpeg   (alebo: choco install ffmpeg)
                       a potom otvor NOVÝ terminál, aby sa načítal PATH.
Overenie: ffmpeg -version && ffprobe -version
Ak máš ffmpeg mimo PATH, nastav v .env FFMPEG_BINARY a FFPROBE_BINARY na plné cesty."""

_SHOWINFO_TIME = re.compile(r"Parsed_showinfo.*?pts_time:\s*(-?[0-9]+(?:\.[0-9]+)?)")
_STDERR_TAIL_LINES: Final[int] = 15

FrameSource = Literal["scene", "sample"]


@dataclass(frozen=True)
class VideoInfo:
    """Základné technické údaje o videu z ``ffprobe``."""

    duration: float
    width: int
    height: int
    fps: float | None
    has_audio: bool
    video_codec: str | None

    @property
    def orientation(self) -> str:
        if self.height > self.width:
            return "na výšku (vertikálne)"
        if self.width > self.height:
            return "na šírku (horizontálne)"
        return "štvorcové"


@dataclass(frozen=True)
class ExtractedFrame:
    """Snímka uložená na disk s časom vo videu a zdrojom (strih / pravidelná vzorka)."""

    path: Path
    timestamp: float
    source: FrameSource


class FFmpegToolkit:
    """Všetky operácie s ffmpeg/ffprobe, ktoré pipeline potrebuje."""

    def __init__(
        self, ffmpeg_binary: str = "ffmpeg", ffprobe_binary: str = "ffprobe", timeout_seconds: float = 3600
    ) -> None:
        self._ffmpeg = ffmpeg_binary
        self._ffprobe = ffprobe_binary
        self._timeout = timeout_seconds
        # Novšie ffmpeg používa -fps_mode, staršie (< 5.1) len -vsync. Zistíme za behu.
        self._fps_mode_flag = "-fps_mode"

    # ----------------------------------------------------------- dostupnosť nástroja
    def ensure_available(self) -> str:
        """Overí, že ffmpeg aj ffprobe existujú, a vráti riadok s verziou ffmpeg.

        :raises FFmpegNotFoundError: so zrozumiteľným návodom na inštaláciu.
        """
        for binary in (self._ffmpeg, self._ffprobe):
            if shutil.which(binary) is None:
                raise FFmpegNotFoundError(f"Nenašiel som program '{binary}'.\n\n{INSTALL_HINT}")
        output = self._run([self._ffmpeg, "-hide_banner", "-version"], purpose="zistenie verzie ffmpeg")
        return (output.stdout.splitlines() or ["ffmpeg (neznáma verzia)"])[0]

    # ------------------------------------------------------------------ informácie
    def probe(self, video: Path) -> VideoInfo:
        """Zistí dĺžku, rozlíšenie, fps a či video obsahuje zvukovú stopu."""
        result = self._run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate",
                "-of",
                "json",
                str(video.resolve()),
            ],
            purpose="analýza videa (ffprobe)",
        )
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise FFmpegError("ffprobe vrátil neplatný JSON.") from exc

        streams = data.get("streams") or []
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video_stream is None:
            raise FFmpegError(f"Súbor {video.name} neobsahuje video stopu.")
        try:
            duration = float((data.get("format") or {}).get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        return VideoInfo(
            duration=duration,
            width=int(video_stream.get("width") or 0),
            height=int(video_stream.get("height") or 0),
            fps=_parse_rate(video_stream.get("avg_frame_rate")),
            has_audio=any(s.get("codec_type") == "audio" for s in streams),
            video_codec=video_stream.get("codec_name"),
        )

    # -------------------------------------------------------------------- snímky
    def extract_scene_frames(
        self, video: Path, out_dir: Path, *, threshold: float, max_side: int, jpeg_quality: int
    ) -> list[ExtractedFrame]:
        """Uloží prvú snímku každej novej scény (detekcia ``select=gt(scene,prah)``).

        Časy snímok zisťujeme z filtra ``showinfo`` (``pts_time``), takže presne
        vieme, v ktorej sekunde nastal strih – z toho rátame rytmus strihu.
        """
        video_filter = f"select=gt(scene\\,{threshold:.3f}),showinfo,{_scale_filter(max_side)}"
        return self._extract(video, out_dir, "scene", video_filter, jpeg_quality)

    def extract_sampled_frames(
        self, video: Path, out_dir: Path, *, fps: float, max_side: int, jpeg_quality: int
    ) -> list[ExtractedFrame]:
        """Uloží snímky v pravidelnom intervale (napr. 1 snímka za sekundu).

        Zachytí aj zmeny, ktoré nie sú strihom (nový titulok, gesto, zoom).
        """
        video_filter = f"fps={fps:.4f},showinfo,{_scale_filter(max_side)}"
        frames = self._extract(video, out_dir, "sample", video_filter, jpeg_quality)
        if frames and all(frame.timestamp == 0.0 for frame in frames[1:]):
            # Záložný výpočet času, ak by showinfo nevrátil časy.
            frames = [ExtractedFrame(f.path, index / fps, "sample") for index, f in enumerate(frames)]
        return frames

    # --------------------------------------------------------------------- audio
    def extract_audio(
        self,
        video: Path,
        out_dir: Path,
        *,
        start: float | None = None,
        duration: float | None = None,
        name: str = "audio",
    ) -> Path:
        """Extrahuje zvukovú stopu ako mono 16 kHz (ideálne pre rozpoznávanie reči).

        Primárne MP3 (malý súbor pre upload na ASR API); ak ffmpeg nemá enkodér
        ``libmp3lame``, použije sa AAC v kontajneri M4A.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        attempts = (("libmp3lame", ".mp3"), ("aac", ".m4a"))
        last_error: FFmpegError | None = None
        for codec, extension in attempts:
            out_path = out_dir / f"{name}{extension}"
            args = [self._ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
            if start is not None:
                args += ["-ss", f"{start:.3f}"]
            args += ["-i", str(video.resolve())]
            if duration is not None:
                args += ["-t", f"{duration:.3f}"]
            args += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", codec, "-b:a", "48k", str(out_path)]
            try:
                self._run(args, purpose="extrakcia audia")
            except FFmpegError as exc:
                last_error = exc
                if "Unknown encoder" in str(exc) or "Encoder not found" in str(exc):
                    continue
                raise
            if out_path.exists() and out_path.stat().st_size > 0:
                return out_path
            last_error = FFmpegError("ffmpeg nevytvoril zvukový súbor.")
        raise last_error or FFmpegError("Extrakcia audia zlyhala.")

    # -------------------------------------------------------------------- interné
    def _extract(
        self, video: Path, out_dir: Path, prefix: FrameSource, video_filter: str, jpeg_quality: int
    ) -> list[ExtractedFrame]:
        out_dir.mkdir(parents=True, exist_ok=True)
        pattern = out_dir / f"{prefix}_%06d.jpg"

        def build(fps_flag: str) -> list[str]:
            return [
                self._ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-y",
                "-loglevel",
                "info",  # showinfo loguje na úrovni info
                "-i",
                str(video.resolve()),
                "-an",
                "-sn",
                "-dn",
                "-vf",
                video_filter,
                fps_flag,
                "vfr",
                "-q:v",
                str(jpeg_quality),
                str(pattern),
            ]

        try:
            result = self._run(build(self._fps_mode_flag), purpose=f"extrakcia snímok ({prefix})")
        except FFmpegError as exc:
            if self._fps_mode_flag == "-fps_mode" and "fps_mode" in str(exc):
                logger.info("Staršia verzia ffmpeg – používam -vsync namiesto -fps_mode.")
                self._fps_mode_flag = "-vsync"
                result = self._run(build(self._fps_mode_flag), purpose=f"extrakcia snímok ({prefix})")
            else:
                raise

        times = [float(match) for match in _SHOWINFO_TIME.findall(result.stderr or "")]
        files = sorted(out_dir.glob(f"{prefix}_*.jpg"))
        if len(times) != len(files):
            logger.warning(
                "Počet časových značiek (%d) nesedí s počtom snímok (%d) – časy môžu byť nepresné.",
                len(times),
                len(files),
            )
        if len(times) < len(files):
            times += [times[-1] if times else 0.0] * (len(files) - len(times))
        return [
            ExtractedFrame(path=path, timestamp=max(0.0, t), source=prefix)
            for path, t in zip(files, times, strict=False)
        ]

    def _run(self, args: Sequence[str], *, purpose: str) -> subprocess.CompletedProcess[str]:
        """Spustí príkaz bez shellu a pri chybe vyhodí výnimku s koncom chybového výstupu."""
        logger.debug("Spúšťam: %s", " ".join(args))
        try:
            result = subprocess.run(  # zoznam argumentov, bez shellu
                list(args),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise FFmpegNotFoundError(f"Program '{args[0]}' sa nepodarilo spustiť.\n\n{INSTALL_HINT}") from exc
        except subprocess.TimeoutExpired as exc:
            raise FFmpegError(f"{purpose}: ffmpeg nedobehol do {self._timeout:.0f} s.") from exc
        if result.returncode != 0:
            tail = "\n".join((result.stderr or "").strip().splitlines()[-_STDERR_TAIL_LINES:])
            raise FFmpegError(f"{purpose} zlyhala (návratový kód {result.returncode}):\n{tail}")
        return result


def _scale_filter(max_side: int) -> str:
    """Zmenší snímku tak, aby dlhšia strana mala najviac ``max_side`` px (bez zväčšovania).

    Menšie snímky = menej tokenov a menšia požiadavka; titulky ostanú čitateľné.
    Pri viac ako 20 obrázkoch v požiadavke API vyžaduje max. 2000 px na stranu.
    """
    return f"scale='if(gte(iw,ih),min({max_side},iw),-2)':'if(gte(iw,ih),-2,min({max_side},ih))':flags=lanczos"


def _parse_rate(value: str | None) -> float | None:
    """Prevedie zlomok fps z ffprobe (napr. ``30000/1001``) na číslo."""
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return float(numerator) / float(denominator) if float(denominator) else None
        return float(value)
    except ValueError:
        return None
