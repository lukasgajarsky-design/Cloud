#!/usr/bin/env bash
# Render queue: waits for running renders, then renders/encodes the remaining videos one after another.
set -u
cd "$(dirname "$0")/.."
F=${FRAMES:-/tmp/frames}
OUT=out
mkdir -p "$OUT"

encode() { # name fps duration [--fpv]
  local name=$1 fps=$2 dur=$3 flag=${4:-}
  python3 tools/make_audio.py "$F/$name" "$fps" "$dur" "$F/$name.wav" $flag
  ffmpeg -hide_banner -loglevel error -y -framerate "$fps" -i "$F/$name/%05d.jpg" -i "$F/$name.wav" \
    -vf "scale=1920:1080:flags=lanczos,format=yuv420p" -c:v libx264 -preset slow -crf 18 -profile:v high \
    -movflags +faststart -c:a aac -b:a 192k -shortest "$OUT/$name.tmp.mp4" && mv "$OUT/$name.tmp.mp4" "$OUT/$name.mp4"
  echo "encoded $OUT/$name.mp4"
}

duration() { node -e "
  const fs=require('fs');const fps=+process.argv[2];
  const n=fs.readdirSync(process.argv[1]).filter(f=>f.endsWith('.jpg')).length;console.log((n/fps).toFixed(2));" "$F/$1" "$2"; }

for name in "$@"; do
  # wait for an already running render of this video, else start one
  while pgrep -f "render/render.mjs $name " > /dev/null; do sleep 20; done
  node render/render.mjs "$name" "$F/$name" 25 > "$F/$name.log" 2>&1
  flag=""; [[ $name == fpv_* ]] && flag="--fpv"
  encode "$name" 25 "$(duration "$name" 25)" $flag
done
echo PIPELINE_DONE
