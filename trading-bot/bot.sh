#!/usr/bin/env bash
# Runs a freqtrade subcommand with the right stack of config files.
#   ./bot.sh trade                       paper-trade on OKX
#   VENUE=hyperliquid ./bot.sh trade     paper-trade on Hyperliquid (on-chain)
#   ./bot.sh backtesting --timerange 20260801-
set -euo pipefail
cd "$(dirname "$0")"

[[ $# -ge 1 ]] || { sed -n '2,5p' "$0"; exit 1; }
subcommand="$1"
shift

venue="${VENUE:-okx}"
configs=(-c user_data/config.json)
case "$venue" in
    okx) ;;
    hyperliquid) configs+=(-c user_data/config.hyperliquid.json) ;;
    *) echo "Unknown VENUE '$venue' (use okx or hyperliquid)" >&2; exit 1 ;;
esac
[[ -f user_data/config.proxy.json ]] && configs+=(-c user_data/config.proxy.json)
[[ -f user_data/config.private.json ]] && configs+=(-c user_data/config.private.json)

extra=()
if [[ "$subcommand" == "trade" ]]; then
    extra+=(--db-url "sqlite:///user_data/tradesv3.dryrun-${venue}.sqlite")
fi

# ${extra[@]+...} keeps bash 3.2 (macOS) happy when the array is empty under set -u
exec .venv/bin/freqtrade "$subcommand" "${configs[@]}" ${extra[@]+"${extra[@]}"} "$@"
