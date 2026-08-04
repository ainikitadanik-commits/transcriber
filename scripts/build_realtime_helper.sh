#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
OUTPUT="$ROOT/build/realtime-capture"
SDK="$(xcrun --sdk macosx --show-sdk-path)"
MODULE_CACHE="$ROOT/build/swift-module-cache"

mkdir -p "${OUTPUT:h}" "$MODULE_CACHE"
xcrun swiftc \
  -parse-as-library \
  -O \
  -sdk "$SDK" \
  -module-cache-path "$MODULE_CACHE" \
  -target arm64-apple-macos15.0 \
  -framework AppKit \
  -framework AVFoundation \
  -framework CoreAudio \
  -framework UniformTypeIdentifiers \
  -framework WebKit \
  "$ROOT/native/realtime_capture.swift" \
  -o "$OUTPUT"

echo "$OUTPUT"
