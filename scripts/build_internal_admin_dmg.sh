#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
APP="${INTERNAL_APP:-$ROOT/dist/Транскрибатор.app}"
BUILD_ROOT="$ROOT/build/internal-admin-dmg"
STAGING="$BUILD_ROOT/staging"
DIST_ROOT="$ROOT/dist"
GUIDE="$ROOT/packaging/КАК ЗАПУСТИТЬ INTERNAL DMG.txt"

if [[ ! -d "$APP/Contents" || ! -f "$GUIDE" ]]; then
  echo "Internal app or installation guide is missing." >&2
  exit 1
fi

VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
  "$APP/Contents/Info.plist")
BUILD=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' \
  "$APP/Contents/Info.plist")
BUNDLE_ID=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' \
  "$APP/Contents/Info.plist")
SIGNATURE_INFO=$(/usr/bin/codesign -dvvv "$APP" 2>&1 || true)

if [[ "$SIGNATURE_INFO" == *"Authority=Developer ID Application:"* ]]; then
  echo "Developer ID app detected. Use scripts/build_product_dmg.sh." >&2
  exit 1
fi
if [[ "$SIGNATURE_INFO" != *"Signature=adhoc"* ]]; then
  echo "Internal DMG requires the verified ad-hoc development app." >&2
  exit 1
fi

/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
"$ROOT/scripts/audit_macho.sh" "$APP" 15.0
"$ROOT/scripts/audit_ffmpeg.sh" "$APP/Contents/Resources/bin/ffmpeg"
"$ROOT/scripts/audit_licenses.sh" \
  "$APP/Contents/Resources/runtime/transcriber-runtime" \
  "$APP/Contents/Resources/Лицензии" \
  "-"
"$ROOT/scripts/audit_signatures.sh" "$APP" 0

/bin/rm -rf "$BUILD_ROOT"
/bin/mkdir -p "$STAGING"
/usr/bin/ditto "$APP" "$STAGING/Транскрибатор.app"
/usr/bin/ditto "$GUIDE" "$STAGING/КАК ЗАПУСТИТЬ.txt"
/bin/ln -s /Applications "$STAGING/Applications"

ASSET_NAME="Транскрибатор-$VERSION-build-$BUILD-INTERNAL-macOS-arm64"
DMG="$DIST_ROOT/$ASSET_NAME.dmg"
SHA_FILE="$DMG.sha256"
MANIFEST="$DMG.manifest.txt"

/bin/rm -f "$DMG" "$SHA_FILE" "$MANIFEST"
/usr/bin/hdiutil create \
  -volname "Транскрибатор INTERNAL $VERSION" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$DMG"
/usr/bin/hdiutil verify "$DMG"

DMG_SHA=$(/usr/bin/shasum -a 256 "$DMG" | /usr/bin/awk '{ print $1 }')
printf '%s  %s\n' "$DMG_SHA" "${DMG:t}" > "$SHA_FILE"
{
  printf 'product=Транскрибатор\n'
  printf 'version=%s\n' "$VERSION"
  printf 'build=%s\n' "$BUILD"
  printf 'bundle_id=%s\n' "$BUNDLE_ID"
  printf 'architecture=arm64\n'
  printf 'minimum_macos=15.0\n'
  printf 'source_commit=%s\n' "$(/usr/bin/git -C "$ROOT" rev-parse HEAD)"
  printf 'distribution=internal-admin-test\n'
  printf 'signing=ad-hoc\n'
  printf 'notarization=none\n'
  printf 'gatekeeper_override=manual-admin-open-anyway\n'
  printf 'sha256=%s\n' "$DMG_SHA"
} > "$MANIFEST"

echo "$DMG"
echo "$SHA_FILE"
echo "$MANIFEST"
