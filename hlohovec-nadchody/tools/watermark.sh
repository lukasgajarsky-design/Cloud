#!/usr/bin/env bash
# Re-encode a rendered video from its frames with the author watermark.
# usage: watermark.sh FRAMES_DIR AUDIO.wav OUT_PREFIX
#   -> OUT_PREFIX_1080p.mp4 (full quality) and OUT_PREFIX_720p.mp4 (<= 19.5 MiB, for the web page)
set -eu
frames=$1; audio=$2; out=$3
font=/usr/share/fonts/opentype/inter/Inter-SemiBold.otf
text='Vytvoril\: Lukáš Gajarský'
n=$(ls "$frames"/*.jpg | wc -l)
dur=$(python3 -c "print($n/25)")
wm() { # fontsize x y
  echo "drawtext=fontfile=$font:text='$text':fontsize=$1:fontcolor=white@0.86:shadowcolor=black@0.55:shadowx=2:shadowy=2:x=$2:y=h-$3"
}
# full quality 1080p
ffmpeg -hide_banner -loglevel error -y -framerate 25 -i "$frames/%05d.jpg" -i "$audio" \
  -vf "scale=1920:1080:flags=lanczos,$(wm 27 26 52),format=yuv420p" \
  -c:v libx264 -preset slow -crf 19 -maxrate 12M -bufsize 24M -profile:v high \
  -c:a aac -b:a 192k -shortest -movflags +faststart "${out}_1080p.mp4"
# web 720p, two-pass to a size that fits a 20 MiB upload
vkbps=$(python3 -c "print(int((19.3*8*1024*1024/$dur - 96000)/1000))")
vf="scale=1280:720:flags=lanczos,$(wm 18 17 35),format=yuv420p"
ffmpeg -hide_banner -loglevel error -y -framerate 25 -i "$frames/%05d.jpg" -vf "$vf" -c:v libx264 -preset veryslow -b:v ${vkbps}k \
  -pass 1 -passlogfile "${out}_pass" -an -f mp4 /dev/null
ffmpeg -hide_banner -loglevel error -y -framerate 25 -i "$frames/%05d.jpg" -i "$audio" -vf "$vf" -c:v libx264 -preset veryslow -b:v ${vkbps}k \
  -pass 2 -passlogfile "${out}_pass" -profile:v high -c:a aac -b:a 96k -shortest -movflags +faststart "${out}_720p.mp4"
rm -f "${out}_pass"*
ls -la "${out}_1080p.mp4" "${out}_720p.mp4"
