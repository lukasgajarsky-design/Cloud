# YouTube to FLAC

Give it a YouTube link and it saves the audio as a FLAC file in `Music\YouTube FLAC` in your user folder, with title, artist, date and the video thumbnail as cover art.

It uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to pick YouTube's best audio-only stream, then converts it to FLAC with ffmpeg. ffmpeg and the JavaScript runtime YouTube now requires (Deno) come as Python packages, so the only thing to install is [uv](https://docs.astral.sh/uv/).

## About "highest quality"

YouTube only stores lossy audio: Opus at up to about 160 kb/s for most videos (about 256 kb/s for YouTube Premium accounts on some music), or AAC at 128 kb/s. The script always takes the best stream on offer and saves it without resampling, as 24-bit FLAC. FLAC is lossless, so nothing more is lost, but it cannot bring back what YouTube's encoding removed. A FLAC from YouTube is many times larger than the original stream and sounds the same. For real lossless audio, buy the track (Bandcamp, Qobuz) or use a lossless streaming service.

Only download what you have the right to: your own uploads, Creative Commons or public-domain music, or where the rights holder allows it. YouTube's terms forbid downloading other content.

## Install (Windows)

1. Install uv. Open **Command Prompt** (not as administrator) and run:

   ```bat
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Skip this if you already set up uv for the trading bot.

2. Get this folder onto your PC. With git:

   ```bat
   cd /d %USERPROFILE%
   git clone -b claude/inspiring-ramanujan-4iyy3s https://github.com/lukasgajarsky-design/Cloud.git
   ```

   Or download `yt2flac.py` and `yt2flac.bat` from GitHub and put them in the same folder.

## Use

**Double-click `yt2flac.bat`**, paste a link, press Enter. Paste the next link when it's done, or press Enter on an empty line to quit. The first run takes a minute to download Python, yt-dlp, ffmpeg and Deno; later runs start in a few seconds.

From Command Prompt you can pass links directly, one or several:

```bat
cd /d %USERPROFILE%\Cloud\yt-flac
yt2flac.bat https://www.youtube.com/watch?v=VIDEO_ID
yt2flac.bat LINK1 LINK2 LINK3
```

Options (after `yt2flac.bat` or `uv run yt2flac.py`):

| Option | What it does |
|---|---|
| `-o D:\Music\FLAC` | Save somewhere else. Setting the `YT2FLAC_DIR` environment variable does the same permanently. |
| `--playlist` | When a link contains `&list=...`, download the whole playlist. Without it, only the one song is downloaded. Plain playlist links (`youtube.com/playlist?list=...`) always download the whole playlist. |
| `--cookies-from-browser edge` | Take the YouTube login from another browser instead of Firefox. Add `:PROFILE` for a specific Firefox profile, e.g. `firefox:abcd1234.default-release`. On Windows, Firefox works most reliably: yt-dlp often can't read Chrome's cookies there. |
| `--no-cookies` | Download without any YouTube login. |

With `--playlist`, the script waits 5–10 seconds between songs to stay under YouTube's rate limits.

`yt2flac.bat` updates yt-dlp on every run, because YouTube changes often and old versions stop working. Running `uv run yt2flac.py` directly skips that; add `--upgrade-package yt-dlp` after `uv run` if downloads start failing.

## YouTube login from Firefox

If you're signed in to YouTube in Firefox, the script uses that login automatically and prints `Using your YouTube login from firefox.` at the start. With it you get Premium's higher-bitrate audio (if you have Premium), age-restricted videos, and fewer "not a bot" checks. Firefox can stay open, and yt-dlp uses your most recently used Firefox profile.

If it prints `Downloading without a YouTube login` instead, it says why:

- `firefox isn't installed or has no profile`: Firefox wasn't found.
- `not signed in to YouTube in firefox`: sign in at youtube.com in Firefox. If you already are, close Firefox and run the script again: Firefox sometimes hasn't saved a new login to disk yet.

yt-dlp's documentation warns that downloading with an account can get it banned, temporarily or permanently, especially with many downloads in a short time. Use an account you can afford to lose, or `--no-cookies`.

## macOS and Linux

Install uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`), then:

```bash
cd yt-flac
./yt2flac.py https://www.youtube.com/watch?v=VIDEO_ID   # or: uv run yt2flac.py ...
```

Files go to `~/Music/YouTube FLAC`.

## If something fails

- **HTTP Error 403** or **Sign in to confirm you're not a bot**: YouTube is blocking your IP. This happens on VPNs and cloud servers. Turn the VPN off, and check the script says it's using your Firefox login.
- **Video unavailable** or **age-restricted**: sign in to YouTube in Firefox and run it again.
- **The provided YouTube account cookies are no longer valid**: YouTube renewed your login in Firefox mid-run. Run the script again.
- Anything else: run `uv run --upgrade yt2flac.py LINK` once to update everything.

## Using it with Claude

A Claude Code session on your own PC (the desktop app's Code tab, or the `claude` command in a terminal) can run this for you: give it a link and ask it to run `yt-flac\yt2flac.bat LINK`. A cloud session like the one that wrote this script can't save files to your PC, and YouTube blocks downloads from cloud servers.
