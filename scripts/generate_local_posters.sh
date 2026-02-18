#!/usr/bin/env bash
set -euo pipefail

ROOT="/media/library/Anime"

gen_from_video () {
  local vid="$1" out="$2"
  ffmpeg -y -ss 20 -i "$vid" -frames:v 1 -q:v 2 "$out" >/dev/null 2>&1 || \
  ffmpeg -y -ss 3 -i "$vid" -frames:v 1 -q:v 2 "$out" >/dev/null 2>&1
}

find "$ROOT" -mindepth 2 -maxdepth 2 -type d | while read -r season_dir; do
  show_dir="$(dirname "$season_dir")"
  season_poster="$season_dir/season-poster.jpg"
  show_poster="$show_dir/poster.jpg"

  # choose first decodable video
  found=""
  while read -r vid; do
    if gen_from_video "$vid" "$season_poster"; then
      found="yes"
      break
    fi
  done < <(find "$season_dir" -maxdepth 1 -type f \( -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.m4v' -o -iname '*.avi' \) | sort)

  [ -z "$found" ] && continue

  if [ ! -f "$show_poster" ] && [ -f "$season_poster" ]; then
    cp "$season_poster" "$show_poster"
  fi
done

echo "posters_generated"