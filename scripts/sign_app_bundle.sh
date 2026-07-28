#!/bin/zsh

set -euo pipefail

APP="${1:-}"
SIGN_IDENTITY="${2:--}"
ENTITLEMENTS="${3:-}"

if [[ ! -d "$APP/Contents" || -z "$ENTITLEMENTS" || ! -f "$ENTITLEMENTS" ]]; then
  echo "Usage: $0 /path/to/App.app signing-identity /path/to/entitlements.plist" >&2
  exit 2
fi

SIGN_ARGS=(--force --options runtime --sign "$SIGN_IDENTITY")
APP_ENTITLEMENTS="$ENTITLEMENTS"
if [[ "$SIGN_IDENTITY" != "-" ]]; then
  SIGN_ARGS+=(--timestamp)
else
  echo "Local ad-hoc signing selected. This artifact is not a release candidate." >&2
fi

TMP_DIR=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/transcriber-signing.XXXXXX")
trap '/bin/rm -rf "$TMP_DIR"' EXIT
MACHO_LIST="$TMP_DIR/macho.txt"
BUNDLE_LIST="$TMP_DIR/bundles.txt"

if [[ "$SIGN_IDENTITY" == "-" ]]; then
  APP_ENTITLEMENTS="$TMP_DIR/local-adhoc.entitlements"
  /bin/cp "$ENTITLEMENTS" "$APP_ENTITLEMENTS"
  /usr/libexec/PlistBuddy \
    -c "Add :com.apple.security.cs.disable-library-validation bool true" \
    "$APP_ENTITLEMENTS"
fi

: > "$MACHO_LIST"
while IFS= read -r file; do
  DESCRIPTION=$(/usr/bin/file -b "$file")
  if [[ "$DESCRIPTION" == *"Mach-O"* ]]; then
    printf '%s\n' "$file" >> "$MACHO_LIST"
  fi
done < <(/usr/bin/find "$APP" -type f -print)

/usr/bin/awk -F/ '{ print NF "\t" $0 }' "$MACHO_LIST" |
  LC_ALL=C /usr/bin/sort -rn |
  /usr/bin/cut -f2- |
  while IFS= read -r code; do
    DESCRIPTION=$(/usr/bin/file -b "$code")
    if [[ "$SIGN_IDENTITY" == "-" && "$DESCRIPTION" == *"executable"* ]]; then
      /usr/bin/codesign \
        "${SIGN_ARGS[@]}" \
        --entitlements "$APP_ENTITLEMENTS" \
        "$code"
    else
      /usr/bin/codesign "${SIGN_ARGS[@]}" "$code"
    fi
  done

/usr/bin/find "$APP" -type d \
  \( -name '*.framework' -o -name '*.bundle' -o -name '*.plugin' -o -name '*.xpc' \) \
  -print > "$BUNDLE_LIST"

/usr/bin/awk -F/ '{ print NF "\t" $0 }' "$BUNDLE_LIST" |
  LC_ALL=C /usr/bin/sort -rn |
  /usr/bin/cut -f2- |
  while IFS= read -r bundle; do
    /usr/bin/codesign "${SIGN_ARGS[@]}" "$bundle"
  done

/usr/bin/codesign \
  "${SIGN_ARGS[@]}" \
  --entitlements "$APP_ENTITLEMENTS" \
  "$APP"

while IFS= read -r code; do
  /usr/bin/codesign --verify --strict --verbose=2 "$code"
done < "$MACHO_LIST"

/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"

echo "$APP"
