#!/usr/bin/env bash
# Split a full-quality video into byte parts that fit the 20 MiB asset limit (the page joins them back for download).
# usage: split_parts.sh KEY   (reads out/final/KEY_1080p.mp4)
set -eu
cd "$(dirname "$0")/../out/final"
key=$1
rm -f "${key}"_1080p_part*.mp4
split -b 19M -d -a 2 --additional-suffix=.mp4 "${key}_1080p.mp4" "${key}_1080p_part"
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "${key}_1080p.mp4" > "${key}.duration"
cat "${key}"_1080p_part*.mp4 | cmp - "${key}_1080p.mp4" && echo "parts ok: $(ls ${key}_1080p_part*.mp4 | wc -l)"
ls -la "${key}_720p.mp4" "${key}"_1080p_part*.mp4
