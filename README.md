# Cloud

Reference notes on Claude's cloud features.

## Docs

- [Create and edit files with Claude](docs/create-and-edit-files-with-claude.md): enabling code execution and file creation, network egress settings per plan, security considerations, approved domains, and example workflows.
- [Crypto trading bots: research notes](docs/crypto-trading-bots-2026.md): comparison of open-source and on-chain trading bots as of September 2026, security red flags, and a reality check on returns.
- [FL Studio piano roll MCP: local setup](docs/fl-studio-mcp-setup.md): install steps for macOS and Windows that connect Claude Code to FL Studio's piano roll (calvinw/fl-studio-mcp), with fixes for gaps in the upstream installer.

## Trading bot

- [trading-bot/](trading-bot/): Freqtrade set up for paper trading on OKX or Hyperliquid, with install and run scripts.

## Instagram bot

- [instagram-bot/](instagram-bot/): Instagram business account automation with the Meta Graph API and Claude Opus 5.5 – replies to comments and DMs, publishes scheduled posts from `queue/`, and learns an editing and caption style from a video (`--learn`). Setup guide in Slovak.

## Music remixing

- [claude-strudel-remixer/](claude-strudel-remixer/): stem separation with Demucs, BPM/key/LUFS analysis, and Strudel live-coding patterns for remixes.

## YouTube to FLAC

- [yt-flac/](yt-flac/): paste a YouTube link, get the best available audio saved as tagged FLAC with cover art. Double-click launcher for Windows.

## Rituál kontroly

- [ritual-kontroly/scenar.md](ritual-kontroly/scenar.md): psychological drama screenplay (Slovak), sequence 1 expanded with the "odchádzam" ritual, the night-time lock round and the son's internalised anger.
- [ritual-kontroly/scena-1.md](ritual-kontroly/scena-1.md): a second take on scene 1 (Slovak, second person, timestamped), with prompts for each shot.
- [ritual-kontroly/generate_movie.py](ritual-kontroly/generate_movie.py): renders the master shot or any shot from the shot list via Runway, Luma, Sora or Replicate (whichever API key is set); the master shot is saved as `ritual_kontroly.mp4`.
- [ritual-kontroly/animatic/](ritual-kontroly/animatic/): free, CPU-only animatic of the whole screenplay (~19 min) – SDXL-Turbo stills with slow camera moves, the Slovak text on screen and synthesized sound. `gen_images.py` makes the stills, `build.py` renders `ritual_kontroly_animatik.mp4`.
