#!/usr/bin/env bash
# Installs Freqtrade into ./.venv and prepares user_data/ for paper trading.
set -euo pipefail

FREQTRADE_VERSION="2026.8"
cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python "freqtrade==${FREQTRADE_VERSION}"
else
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
        || { echo "Python 3.11 or newer is required" >&2; exit 1; }
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install "freqtrade==${FREQTRADE_VERSION}"
fi

.venv/bin/freqtrade create-userdir --userdir user_data

# Behind a TLS-intercepting proxy (e.g. a Claude Code cloud session), ccxt ignores
# HTTPS_PROXY and the system CA bundle unless told otherwise.
if [[ -n "${HTTPS_PROXY:-}" && -n "${SSL_CERT_FILE:-}" ]]; then
    cat > user_data/config.proxy.json <<EOF
{
    "exchange": {
        "enable_ws": false,
        "ccxt_config": {
            "requests_trust_env": true,
            "aiohttp_trust_env": true,
            "cafile": "${SSL_CERT_FILE}"
        }
    }
}
EOF
    echo "Wrote user_data/config.proxy.json for the HTTPS proxy."
fi

.venv/bin/freqtrade --version
echo "Installed. Next: ./bot.sh download-data --days 60 --timeframes 5m 1h"
