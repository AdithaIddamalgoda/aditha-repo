#!/usr/bin/env bash
# Rebuild six_to_picnic.mp4 from source. Keys/crops the generated sprites first (animation/rigged/, gitignored). Frames are piped Playwright -> ffmpeg (never written to disk);
# the only intermediate is the WAV, which is removed afterwards. Output stays well under 30 MB (13 Mbit/s cap).
set -euo pipefail
cd "$(dirname "$0")"
TMP="${TMPDIR:-/tmp}/six_to_picnic_audio.wav"
python3 rig_sprites.py >/dev/null
python3 audio.py "$TMP"
NODE_PATH="${NODE_PATH:-/opt/node-tools/node_modules}" node render.js --out ../six_to_picnic.mp4 --audio "$TMP"
rm -f "$TMP"
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration,size -of default=nw=1 ../six_to_picnic.mp4
