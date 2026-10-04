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

If you are signed in to YouTube in Firefox, that login is used (Premium
audio, age-restricted videos, fewer bot checks). Use --no-cookies to turn
this off, or --cookies-from-browser to pick another browser.
"""

import argparse
import os
import sys
from pathlib import Path

import yt_dlp
from yt_dlp.cookies import CookieLoadError, LenientSimpleCookie, extract_cookies_from_browser

DEFAULT_DIR = Path.home() / "Music" / "YouTube FLAC"
DEFAULT_BROWSER = "firefox"
# yt-dlp treats a session as signed in when LOGIN_INFO and one of these exist.
SID_COOKIES = {"SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID"}


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


def youtube_login(browser, profile):
    """Return None if the browser holds a signed-in YouTube session, else why not."""
    try:
        jar = extract_cookies_from_browser(browser, profile)
    except FileNotFoundError:
        return f"{browser} isn't installed or has no profile"
    except Exception as err:
        return f"couldn't read {browser}'s cookies ({err})"
    # Same check as yt-dlp: only unexpired cookies that would be sent to YouTube.
    cookies = LenientSimpleCookie(jar.get_cookie_header("https://www.youtube.com"))
    if "LOGIN_INFO" in cookies and any(cookies[n].value for n in SID_COOKIES & cookies.keys()):
        return None
    # The browser may not have saved a fresh login to disk yet; closing it does.
    return f"not signed in to YouTube in {browser} (if you are, close {browser} and try again)"


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
        opts["cookiesfrombrowser"] = browser
    if playlist:
        # Pause between songs so long playlists stay under YouTube's rate limits.
        opts["sleep_interval"], opts["max_sleep_interval"] = 5, 10
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
            except CookieLoadError:
                # The browser rewrote its cookie file since the startup check.
                print("Couldn't read the browser login this time; trying without it.")
                no_login = {k: v for k, v in opts.items() if k != "cookiesfrombrowser"}
                failed += download([url], no_login)
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
        metavar="BROWSER[:PROFILE]",
        default=DEFAULT_BROWSER,
        help=f"use your YouTube login from this browser (default: {DEFAULT_BROWSER}): "
        "gets Premium's higher-bitrate audio and age-restricted videos",
    )
    parser.add_argument(
        "--no-cookies",
        action="store_true",
        help="don't use any browser login",
    )
    args = parser.parse_args()

    out_dir = args.output.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Saving to: {out_dir}")

    browser = None
    if not args.no_cookies:
        name, _, profile = args.cookies_from_browser.partition(":")
        name = name.lower()
        problem = youtube_login(name, profile or None)
        if problem:
            print(f"Downloading without a YouTube login: {problem}.")
        else:
            print(f"Using your YouTube login from {name}.")
            browser = (name, profile or None)
    opts = build_options(out_dir, args.playlist, browser)

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
