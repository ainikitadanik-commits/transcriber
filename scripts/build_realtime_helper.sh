#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
OUTPUT="$ROOT/build/realtime-capture"
SDK="/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk"
MODULE_CACHE="$ROOT/build/swift-module-cache"

mkdir -p "${OUTPUT:h}" "$MODULE_CACHE"
xcrun swiftc \
  -parse-as-library \
  -O \
  -sdk "$SDK" \
  -module-cache-path "$MODULE_CACHE" \
  -target arm64-apple-macos15.0 \
  -framework AVFoundation \
  -framework CoreMedia \
  -framework ScreenCaptureKit \
  "$ROOT/native/realtime_capture.swift" \
  -o "$OUTPUT"

echo "$OUTPUT"
