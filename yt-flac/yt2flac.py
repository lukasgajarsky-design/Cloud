#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "yt-dlp[default]>=2026.8.19",
#     "imageio-ffmpeg>=0.6.0",
#     "deno>=2.5",
# ]
# ///
"""Download the best audio track of a YouTube link and save it as FLAC.

Usage:
    uv run yt2flac.py URL [URL ...]       download one or more links
    uv run yt2flac.py                     ask for links one at a time
    uv run yt2flac.py -o D:\\Music URL     save somewhere else

Files go to <your home folder>/Music/YouTube FLAC unless -o or the
YT2FLAC_DIR environment variable says otherwise. Title, artist, date and
the video thumbnail (as cover art) are written into each file.
"""

import argparse
import os
import sys
from pathlib import Path

import yt_dlp

DEFAULT_DIR = Path.home() / "Music" / "YouTube FLAC"


def find_ffmpeg():
    """Bundled ffmpeg from imageio-ffmpeg, so nothing has to be installed by hand."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None  # fall back to ffmpeg on PATH


def find_deno():
    """yt-dlp needs a JavaScript runtime to unlock all YouTube formats."""
    try:
        import deno

        return deno.find_deno_bin()
    except Exception:
        return None  # fall back to deno on PATH


def build_options(out_dir, playlist, browser):
    opts = {
        # Best audio-only stream (Opus ~160 kb/s, or ~256 kb/s with Premium cookies).
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
        "windowsfilenames": True,
        "noplaylist": not playlist,
        "ignoreerrors": "only_download",
        "writethumbnail": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "flac"},
            {"key": "FFmpegMetadata", "add_metadata": True},
            {"key": "EmbedThumbnail"},
        ],
        # Keep the source sample rate and write 24-bit samples, so decoding the
        # lossy stream loses nothing further. Level 8 = smallest FLAC files.
        "postprocessor_args": {
            "extractaudio": ["-sample_fmt", "s32", "-compression_level", "8"],
        },
    }
    if ffmpeg := find_ffmpeg():
        opts["ffmpeg_location"] = ffmpeg
    if deno := find_deno():
        opts["js_runtimes"] = {"deno": {"path": deno}}
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


def download(urls, opts):
    failed = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        for url in urls:
            try:
                if ydl.download([url]):
                    failed.append(url)
            except yt_dlp.utils.DownloadError:
                failed.append(url)
    return failed


def ask_for_links():
    print("Paste a YouTube link and press Enter. Press Enter on an empty line to quit.")
    while True:
        try:
            url = input("\nLink: ").strip().strip('"')
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not url:
            return
        yield url


def main():
    parser = argparse.ArgumentParser(description="Save YouTube audio as FLAC.")
    parser.add_argument("urls", nargs="*", help="YouTube video or playlist links")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(os.environ.get("YT2FLAC_DIR", DEFAULT_DIR)),
        help=f"folder to save into (default: {DEFAULT_DIR})",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="when a link has &list=..., download the whole playlist instead of one song",
    )
    parser.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="use your YouTube login from this browser (firefox, chrome, edge, ...): "
        "gets Premium's higher-bitrate audio and age-restricted videos",
    )
    args = parser.parse_args()

    out_dir = args.output.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = build_options(out_dir, args.playlist, args.cookies_from_browser)
    print(f"Saving to: {out_dir}")

    if args.urls:
        failed = download(args.urls, opts)
    else:
        failed = []
        for url in ask_for_links():
            failed += download([url], opts)

    if failed:
        print("\nThese links failed:", *failed, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
