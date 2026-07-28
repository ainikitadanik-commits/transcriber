#!/bin/zsh

set -euo pipefail

TARGET="${1:-}"
MAX_MACOS="${2:-15.0}"
INVENTORY_OUTPUT="${MACHO_INVENTORY_OUTPUT:-}"

if [[ -z "$TARGET" || ! -e "$TARGET" ]]; then
  echo "Usage: $0 /path/to/app-or-binary [maximum-macOS-version]" >&2
  exit 2
fi

TMP_DIR=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/transcriber-macho-audit.XXXXXX")
trap '/bin/rm -rf "$TMP_DIR"' EXIT
INVENTORY="$TMP_DIR/MACHO-INVENTORY.tsv"

printf 'path\tarchitectures\tminimum_macos\n' > "$INVENTORY"

count=0
failed=0

version_is_at_most() {
  /usr/bin/awk -v actual="$1" -v maximum="$2" '
    BEGIN {
      split(actual, a, ".");
      split(maximum, m, ".");
      for (i = 1; i <= 4; i++) {
        av = a[i] + 0;
        mv = m[i] + 0;
        if (av < mv) exit 0;
        if (av > mv) exit 1;
      }
      exit 0;
    }
  '
}

while IFS= read -r file; do
  DESCRIPTION=$(/usr/bin/file -b "$file")
  if [[ "$DESCRIPTION" != *"Mach-O"* ]]; then
    continue
  fi

  count=$((count + 1))
  ARCHITECTURES=$(/usr/bin/lipo -archs "$file")
  BUILD_INFO=$(xcrun vtool -show-build "$file" 2>/dev/null || true)
  MINIMUM_MACOS=$(printf '%s\n' "$BUILD_INFO" |
    /usr/bin/awk '$1 == "minos" { print $2; exit }')
  RELATIVE_PATH="${file#$TARGET/}"
  if [[ "$file" == "$TARGET" ]]; then
    RELATIVE_PATH="${file:t}"
  fi

  printf '%s\t%s\t%s\n' \
    "$RELATIVE_PATH" "$ARCHITECTURES" "${MINIMUM_MACOS:-UNKNOWN}" >> "$INVENTORY"

  if [[ "$ARCHITECTURES" != "arm64" ]]; then
    echo "Mach-O audit failed: $file has architectures '$ARCHITECTURES', expected arm64." >&2
    failed=1
  fi

  if [[ -z "$MINIMUM_MACOS" ]]; then
    echo "Mach-O audit failed: cannot determine minimum macOS for $file." >&2
    failed=1
  elif ! version_is_at_most "$MINIMUM_MACOS" "$MAX_MACOS"; then
    echo "Mach-O audit failed: $file requires macOS $MINIMUM_MACOS (maximum $MAX_MACOS)." >&2
    failed=1
  fi
done < <(/usr/bin/find "$TARGET" -type f -print)

if [[ "$count" -eq 0 ]]; then
  echo "Mach-O audit failed: no Mach-O files found under $TARGET." >&2
  exit 1
fi

if [[ -n "$INVENTORY_OUTPUT" ]]; then
  /bin/mkdir -p "${INVENTORY_OUTPUT:h}"
  /usr/bin/ditto --noextattr --noqtn --norsrc "$INVENTORY" "$INVENTORY_OUTPUT"
fi

if [[ "$failed" -ne 0 ]]; then
  exit 1
fi

echo "Mach-O audit passed: $count arm64 files require macOS $MAX_MACOS or earlier."
