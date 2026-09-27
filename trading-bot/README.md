# Paper-trading crypto bot (Freqtrade)

[Freqtrade](https://github.com/freqtrade/freqtrade) 2026.8, set up for **paper trading only**: it follows live market prices and simulates trades with a pretend 1,000 USDT wallet. No exchange account, API key, or wallet is needed, and no real money can move.

Why Freqtrade: it came out on top of a six-way research pass (open-source activity, community reports, features, security, web3/on-chain options, GitHub adoption data). See [the research notes](../docs/crypto-trading-bots-2026.md).

## Install

Needs Python 3.11+ (or [uv](https://docs.astral.sh/uv/)) on Linux, macOS or WSL. For plain Windows, see below.

```bash
cd trading-bot
./install.sh
```

This installs the pinned Freqtrade release from PyPI into `.venv/` and creates the `user_data/` folders. The release's PyPI provenance attestation (built by `github.com/freqtrade/freqtrade`) can be checked with:

```bash
uvx pypi-attestations verify pypi --repository https://github.com/freqtrade/freqtrade \
  pypi:freqtrade-2026.8-py3-none-any.whl
```

### Windows (Command Prompt, no WSL needed)

Use a normal Command Prompt, not "Run as administrator".

```bat
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close the window and open a new Command Prompt so `uv` is on the PATH, then:

```bat
cd /d %USERPROFILE%
git clone -b claude/inspiring-ramanujan-4iyy3s https://github.com/lukasgajarsky-design/Cloud.git
cd Cloud\trading-bot
uv venv --python 3.12 .venv
uv pip install freqtrade==2026.8
.venv\Scripts\activate
freqtrade create-userdir --userdir user_data
freqtrade download-data -c user_data\config.json --days 60 --timeframes 5m 1h
freqtrade trade -c user_data\config.json
```

For Hyperliquid, use `freqtrade trade -c user_data\config.json -c user_data\config.hyperliquid.json`. In a new window, run `cd /d %USERPROFILE%\Cloud\trading-bot` and `.venv\Scripts\activate` first. `install.sh` and `bot.sh` are for Linux, macOS and WSL only.

## Use

```bash
./bot.sh download-data --days 60 --timeframes 5m 1h   # historical candles (OKX, no key needed)
./bot.sh backtesting --timerange 20260801-            # test the strategy on that history
./bot.sh trade                                        # paper-trade live on OKX (Ctrl+C to stop)
VENUE=hyperliquid ./bot.sh trade                      # paper-trade live on Hyperliquid (on-chain perps)
./bot.sh show-trades --db-url sqlite:///user_data/tradesv3.dryrun-okx.sqlite
```

`bot.sh` passes any Freqtrade subcommand through with the right config files stacked:

| File | Purpose | Committed |
|---|---|---|
| `user_data/config.json` | Base settings: `dry_run: true`, OKX spot, 6 USDT pairs, `SampleStrategy`, 5m candles | Yes |
| `user_data/config.hyperliquid.json` | Switches to Hyperliquid perpetuals in USDC (`VENUE=hyperliquid`) | Yes |
| `user_data/config.proxy.json` | Proxy/CA settings, written by `install.sh` only when `HTTPS_PROXY` and `SSL_CERT_FILE` are set | No |
| `user_data/config.private.json` | Your own overrides (Telegram, web UI, keys) | No |

Hyperliquid offers no historical data download in this Freqtrade release, so backtesting only works on OKX.

## What to expect

`SampleStrategy` is Freqtrade's demo strategy, not a money-maker. Backtested on OKX from 2026-08-01 to 2026-09-27 it made **+7.8%**, while simply holding the same coins gained **+45.7%**. Reports collected during research say the same about most public strategies. Treat this as a sandbox for learning and testing your own strategies. Paper-trade any strategy for weeks before considering real money.

## If you ever go live

Not set up here on purpose. If you decide to:

- Use a **sub-account** holding only what you can afford to lose.
- Create **trade-only** API keys: withdrawals disabled, IP allowlist on.
- Put keys in `user_data/config.private.json` (git-ignored) or environment variables such as `FREQTRADE__EXCHANGE__KEY`. Never commit them.
- For Hyperliquid, use an **API wallet** from app.hyperliquid.xyz/API, never your main wallet's private key or seed phrase.
- Set `"dry_run": false` only in the private file, and start small.
- Enable the web UI only on `127.0.0.1` with a strong password.

## Notes for Claude Code cloud sessions

- Exchange traffic goes through a TLS-intercepting proxy; `install.sh` writes `config.proxy.json` so ccxt uses it and trusts its CA, and turns off websockets (they time out through the proxy; Freqtrade falls back to REST polling).
- Binance's main API returns HTTP 451 (region-blocked) and Bybit returns 403 from these servers, which is why OKX is the default venue.
- Hyperliquid occasionally returns HTTP 429 (rate limit) on the shared egress IP; retry after a minute.
- The container is temporary: everything outside git (the `.venv`, data, trade databases) is lost when the session ends. Re-run `./install.sh` in a new session.
