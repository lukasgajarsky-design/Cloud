#!/usr/bin/env bash
# Installs the remixer on macOS or Linux: FFmpeg and Node.js, then .venv with Demucs and the analysis libraries.
set -euo pipefail
cd "$(dirname "$0")"

os=$(uname -s)
arch=$(uname -m)
# A shell running under Rosetta reports x86_64 on Apple Silicon too
if [[ $os == Darwin && $arch == x86_64 && $(sysctl -n hw.optional.arm64 2>/dev/null) != 1 ]]; then
    echo "❌ Intel Mac nie je podporovaný: Demucs 4.1 a PyTorch preň nemajú hotové balíčky." >&2
    echo "   Použi Mac s Apple Silicon (M1 a novší), Windows PC alebo Linux." >&2
    exit 1
fi

missing=()
command -v ffmpeg >/dev/null || missing+=(ffmpeg)
command -v node >/dev/null || missing+=(node)
if ((${#missing[@]})); then
    if [[ $os == Darwin ]] && command -v brew >/dev/null; then
        echo "📦 Inštalujem cez Homebrew: ${missing[*]}"
        brew install "${missing[@]}"
    elif [[ $os == Darwin ]]; then
        echo "❌ Chýba: ${missing[*]}. Nainštaluj Homebrew (https://brew.sh) a spusti: brew install ${missing[*]}" >&2
        exit 1
    else
        echo "❌ Chýba: ${missing[*]}. Na Ubuntu/Debiane: sudo apt install ffmpeg nodejs npm" >&2
        exit 1
    fi
fi

if [[ ! -x .venv/bin/python ]]; then
    if command -v uv >/dev/null; then
        # uv downloads Python 3.12 if it isn't installed; --seed adds pip, which setup_and_verify.py uses
        uv venv --python 3.12 --seed .venv
    else
        python=""
        for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
            if command -v "$candidate" >/dev/null &&
                "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
                python=$candidate
                break
            fi
        done
        if [[ -z $python ]]; then
            echo "❌ Treba Python 3.10 alebo novší (macOS: brew install python@3.12), alebo uv: https://docs.astral.sh/uv/" >&2
            exit 1
        fi
        "$python" -m venv .venv
    fi
fi
.venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 10))' ||
    { echo "❌ .venv má Python starší ako 3.10. Zmaž priečinok .venv a spusti install.sh znova." >&2; exit 1; }

# Without an NVIDIA GPU, PyPI's Linux PyTorch would pull gigabytes of CUDA libraries Demucs can't use
if [[ $os == Linux && $arch == x86_64 ]] && ! command -v nvidia-smi >/dev/null; then
    echo "📦 Inštalujem PyTorch bez CUDA (počítač nemá NVIDIA GPU)..."
    .venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
fi

.venv/bin/python setup_and_verify.py

echo
echo "✅ Hotovo. Skopíruj skladbu do input/ (napr. input/moja-skladba.wav),"
echo "   otvor tento priečinok v Claude Code a napíš: Remixni input/moja-skladba.wav"
