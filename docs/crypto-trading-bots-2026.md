# Crypto trading bots: research notes (September 2026)

Six parallel research passes on 2026-09-27 looked for the best currently working crypto trading bot to self-host:

1. open-source landscape and maintenance (repos cloned and inspected)
2. community reports and hosted services
3. features and install requirements from official docs
4. security vetting and scam patterns
5. web3 / on-chain bots, using DeFiLlama and other app directories
6. adoption data from GitHub-derived databases (ecosyste.ms, star-history, PyPI and Docker Hub stats)

All six ranked **Freqtrade** first. It is installed for paper trading in [`trading-bot/`](../trading-bot/).

## Ranking

| # | Project | Stars | Last release | License | Adoption | Paper mode without keys | Security risk |
|---|---|---|---|---|---|---|---|
| 1 | [Freqtrade](https://github.com/freqtrade/freqtrade) | 54.8k | 2026.8 (2026-08-31), monthly releases | GPL-3.0 | 18.0M Docker pulls, 73k PyPI downloads/month | Yes (dry-run) | Low: PyPI build provenance, no known CVEs |
| 2 | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | 29.4k | v1.231.0 stable, v2.0.0rc5 | LGPL-3.0 | 326k PyPI downloads/month, ~55 active devs | Yes (sandbox) | Low: signed images, SBOM, security policy |
| 3 | [Hummingbot](https://github.com/hummingbot/hummingbot) | 20.1k | v2.17.0 (2026-09-22) | Apache-2.0 | 183k Docker pulls | Yes (paper connectors) | Low to medium |
| 4 | [OctoBot](https://github.com/Drakkar-Software/OctoBot) | 6.6k | 2.1.1 (2026-03), 3.0 in beta | GPL-3.0 | 1.45M Docker pulls | Yes (simulator) | Medium: official compose mounts the Docker socket; CVE-2021-36711 (fixed) |
| 5 | [Jesse](https://github.com/jesse-ai/jesse) | 8.6k | v3.2.3 (2026-09-27) | MIT core, **paid** live/paper plugin | 62k Docker pulls | No (paid only) | Medium |
| 6 | [Passivbot](https://github.com/enarjord/passivbot) | 2.1k | v8.1.0 (2026-08-10) | Unlicense | Source only | No | Medium: one main maintainer, no PyPI package |

When to pick something other than Freqtrade:

- **Hummingbot**: market making, cross-exchange arbitrage, or DEX swaps through its Gateway (Jupiter, Uniswap and others).
- **NautilusTrader**: you are an engineer building your own trading system; it is a framework, not a turnkey bot.
- **OctoBot**: you want a point-and-click web UI and accept a weaker backtester.

Abandoned: Superalgos (last real merge 2024-11), Gekko, Zenbot, Kelp (archived), ccxt/binance-trade-bot.

## Web3 and on-chain

- **Freqtrade on Hyperliquid** is the only on-chain option found that paper-trades with **no wallet or key at all**. Hyperliquid spot and perpetuals are supported; historical data is limited to recent candles.
- **Hummingbot + Gateway** covers DEX pools (Jupiter, Raydium, Meteora, Orca, Uniswap, PancakeSwap); testing needs a throwaway devnet or testnet key.
- **Hosted Telegram/web bots** (GMGN, Axiom, Maestro, Trojan, Photon, BONKbot, Banana Gun) are closed source, cannot be self-installed, and hold your keys on their servers. Several have had exploits or insider incidents: Maestro (Oct 2023, ~280 ETH), Banana Gun (Sep 2024, ~$3M), GMGN (Oct 2025), and allegations of insider trading by Axiom staff (Feb 2026).
- **AI agent kits** (ElizaOS, Coinbase AgentKit, Solana Agent Kit, Olas) trade on-chain but need a funded or testnet wallet and are experimental.

## Newer projects (2024-2026)

| Project | Stars | Verdict |
|---|---|---|
| [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | 34.2k (created 2026-04) | Looks legitimate (university lab, 80 PR authors). Too new to rely on; worth watching. |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | ~109k | Legitimate research framework, stock-focused, no exchange connectors. |
| [NoFxAiOS/nofx](https://github.com/NoFxAiOS/nofx) | 13.0k | Real usage, but in Nov 2025 SlowMist found 1,000+ deployments exposing keys; installer uses `curl \| bash` and referral links. |
| [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | 22.6k | No LICENSE file, so not legally open source. |
| OpenByteInc/QuantDinger | 12.2k | Suspicious star growth, `irm \| iex` installer, pushes a paid API. |

## Red flags (scams are common in this space)

- A new repo with one or two commits but thousands of stars or forks. Star farms exist ([Check Point](https://research.checkpoint.com/2024/stargazers-ghost-network/)).
- Any request for a seed phrase or wallet private key, or to "deploy this contract in Remix and fund it". Every such "MEV/arbitrage bot" is a drainer. One campaign of Claude-branded YouTube tutorials took 274.6 ETH from 224 victims in 2026 ([TRM Labs](https://www.trmlabs.com/resources/blog/fake-ai-trading-bots-are-getting-victims-to-build-their-own-drainers)).
- Obfuscated code, hardcoded wallet addresses, bundled binaries, install-time scripts, or dependencies with look-alike names. Examples: GitVenom ([Securelist](https://securelist.com/gitvenom-campaign/115694/)) and a hijacked GitHub org serving Polymarket bots ([StepSecurity](https://www.stepsecurity.io/blog/malicious-polymarket-bot-hides-in-hijacked-dev-protocol-github-org-and-steals-wallet-keys)).
- Promised returns ("5-25% a month").

## Reality check

- A bot executes a strategy; it does not find an edge. Freqtrade's own demo strategy made +7.8% in a backtest from 2026-08-01 to 2026-09-27 while holding the same coins gained +45.7%.
- A reported Reddit retest of 571 public Freqtrade strategies found none that beat buy-and-hold, and a fee-inclusive 200-day test of three strategies had the same result.
- Plain grid strategies have roughly zero expected value before fees ([arXiv 2506.11921](https://arxiv.org/html/2506.11921v1)).
- In the Oct 10 2025 crash, $19B of leveraged positions were liquidated in a day; leveraged bots took the worst of it.
- 3Commas leaked ~100k customer API keys in Dec 2022. Only give a bot trade-only keys with withdrawals disabled and an IP allowlist.
- The US CFTC's advisory is titled "[AI won't turn trading bots into money machines](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html)".

## Sources

- Official docs: [freqtrade.io](https://www.freqtrade.io/en/stable/), [hummingbot.org](https://hummingbot.org/), [nautilustrader.io](https://nautilustrader.io/docs/latest/), [octobot.cloud](https://www.octobot.cloud/), [docs.jesse.trade](https://docs.jesse.trade/)
- Adoption data: repos.ecosyste.ms, star-history.com, pypistats.org, hub.docker.com (retrieved 2026-09-27)
- Web3 fees and volumes: DeFiLlama API (retrieved 2026-09-27)
- Security: [SlowMist on NOFX](https://slowmist.medium.com/threat-intelligence-analysis-of-the-nofx-ai-automated-trading-vulnerability-e4f4664ad1e6), [JFrog on ccxt-mexc-futures](https://jfrog.com/blog/malicious-pypi-package-hijacks-mexc-orders-steals-crypto-tokens/), [OSV CVE-2021-36711](https://osv.dev/vulnerability/CVE-2021-36711)
- Community: [elseboard Freqtrade review](https://www.elseboard.com/post/freqtrade-review-what-github-and-reddit-users-are-saying-about-the-automated-trading-bot), [Hummingbot review](https://finestel.com/blog/hummingbot-review/), [NautilusTrader field report](https://hasanjaved.me/blog/nautilus-trader-production-field-report/)
