#!/bin/zsh

set -euo pipefail

APP="${1:-}"
REQUIRE_DEVELOPER_ID="${2:-0}"

if [[ ! -d "$APP/Contents" ]]; then
  echo "Usage: $0 /path/to/App.app [require-Developer-ID:0|1]" >&2
  exit 2
fi

if [[ "$REQUIRE_DEVELOPER_ID" != "0" && "$REQUIRE_DEVELOPER_ID" != "1" ]]; then
  echo "Signature audit failed: require-Developer-ID must be 0 or 1." >&2
  exit 2
fi

count=0
failed=0

while IFS= read -r file; do
  DESCRIPTION=$(/usr/bin/file -b "$file")
  if [[ "$DESCRIPTION" != *"Mach-O"* ]]; then
    continue
  fi

  count=$((count + 1))
  if ! /usr/bin/codesign --verify --strict --verbose=2 "$file"; then
    failed=1
    continue
  fi

  SIGNATURE_INFO=$(/usr/bin/codesign -dvvv "$file" 2>&1 || true)
  if [[ "$SIGNATURE_INFO" != *"runtime"* ]]; then
    echo "Signature audit failed: hardened runtime flag is absent on $file." >&2
    failed=1
  fi

  if [[ "$REQUIRE_DEVELOPER_ID" == "1" ]]; then
    if [[ "$SIGNATURE_INFO" != *"Authority=Developer ID Application:"* ]]; then
      echo "Signature audit failed: Developer ID Application authority is absent on $file." >&2
      failed=1
    fi
    if [[ "$SIGNATURE_INFO" == *"TeamIdentifier=not set"* ]]; then
      echo "Signature audit failed: TeamIdentifier is absent on $file." >&2
      failed=1
    fi
  fi
done < <(/usr/bin/find "$APP" -type f -print)

if [[ "$count" -eq 0 ]]; then
  echo "Signature audit failed: no Mach-O files found." >&2
  exit 1
fi

if ! /usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"; then
  failed=1
fi

if [[ "$failed" -ne 0 ]]; then
  exit 1
fi

echo "Signature audit passed: $count Mach-O files are valid and hardened."
