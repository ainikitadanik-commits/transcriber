#!/bin/zsh

set -euo pipefail

FFMPEG="${1:-}"

if [[ -z "$FFMPEG" || ! -x "$FFMPEG" ]]; then
  echo "Usage: $0 /path/to/ffmpeg" >&2
  exit 2
fi

VERSION_TEXT=$("$FFMPEG" -version 2>&1)
LICENSE_TEXT=$("$FFMPEG" -L 2>&1)
FILTERS_TEXT=$("$FFMPEG" -hide_banner -filters 2>&1)
MUXERS_TEXT=$("$FFMPEG" -hide_banner -muxers 2>&1)
PROTOCOLS_TEXT=$("$FFMPEG" -hide_banner -protocols 2>&1)

for required_flag in --disable-network --disable-everything; do
  if [[ "$VERSION_TEXT" != *"$required_flag"* ]]; then
    echo "FFmpeg audit failed: missing $required_flag." >&2
    exit 1
  fi
done

for forbidden_flag in --enable-gpl --enable-nonfree; do
  if [[ "$VERSION_TEXT" == *"$forbidden_flag"* ]]; then
    echo "FFmpeg audit failed: forbidden $forbidden_flag is enabled." >&2
    exit 1
  fi
done

if [[ "$LICENSE_TEXT" != *"GNU Lesser General Public"* ]]; then
  echo "FFmpeg audit failed: binary does not report an LGPL license." >&2
  exit 1
fi

for filter in ebur128 highpass loudnorm; do
  if ! /usr/bin/awk -v required="$filter" '$2 == required { found = 1 } END { exit !found }' \
    <<< "$FILTERS_TEXT"
  then
    echo "FFmpeg audit failed: missing filter $filter." >&2
    exit 1
  fi
done

if ! /usr/bin/awk '$2 == "null" { found = 1 } END { exit !found }' \
  <<< "$MUXERS_TEXT"
then
  echo "FFmpeg audit failed: missing null muxer." >&2
  exit 1
fi

for protocol in file pipe; do
  if ! /usr/bin/awk -v required="$protocol" '$1 == required { found = 1 } END { exit !found }' \
    <<< "$PROTOCOLS_TEXT"
  then
    echo "FFmpeg audit failed: missing protocol $protocol." >&2
    exit 1
  fi
done

echo "FFmpeg audit passed: LGPL, network disabled, required filters/muxer/protocols present."
