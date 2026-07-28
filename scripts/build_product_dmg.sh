#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
APP="${PRODUCT_APP:-$ROOT/dist/Транскрибатор.app}"
BUILD_ROOT="$ROOT/build/product-dmg"
DIST_ROOT="$ROOT/dist"
STAGING="$BUILD_ROOT/staging"
NOTARY_PROFILE="${NOTARY_PROFILE:-}"
DEPENDENCY_INVENTORY="$APP/Contents/Resources/Лицензии/DEPENDENCY-INVENTORY.txt"
EMBEDDED_LOCK="$APP/Contents/Resources/Лицензии/requirements-release.lock"

if [[ ! -d "$APP/Contents" ]]; then
  echo "Product app not found: $APP" >&2
  exit 1
fi

VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
  "$APP/Contents/Info.plist")
BUNDLE_ID=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' \
  "$APP/Contents/Info.plist")
SIGNATURE_INFO=$(/usr/bin/codesign -dvvv "$APP" 2>&1 || true)

if [[ "$SIGNATURE_INFO" != *"Authority=Developer ID Application:"* ]]; then
  echo "Product DMG requires a real Developer ID Application signature." >&2
  echo "Ad-hoc applications are local builds and are not release candidates." >&2
  exit 1
fi

if [[ ! -f "$DEPENDENCY_INVENTORY" || ! -f "$EMBEDDED_LOCK" ]]; then
  echo "Product DMG requires an embedded release dependency inventory and lock." >&2
  exit 1
fi

LOCK_SHA=$(/usr/bin/awk -F= '$1 == "lock_sha256" { print $2; exit }' \
  "$DEPENDENCY_INVENTORY")
ACTUAL_LOCK_SHA=$(/usr/bin/shasum -a 256 "$EMBEDDED_LOCK" |
  /usr/bin/awk '{ print $1 }')
if [[ -z "$LOCK_SHA" || "$LOCK_SHA" != "$ACTUAL_LOCK_SHA" ]]; then
  echo "Product DMG dependency lock checksum does not match its inventory." >&2
  exit 1
fi

"$ROOT/scripts/audit_macho.sh" "$APP" 15.0
"$ROOT/scripts/audit_ffmpeg.sh" "$APP/Contents/Resources/bin/ffmpeg"
"$ROOT/scripts/audit_licenses.sh" \
  "$APP/Contents/Resources/runtime/transcriber-runtime" \
  "$APP/Contents/Resources/Лицензии" \
  "-"
"$ROOT/scripts/audit_signatures.sh" "$APP" 1

/bin/rm -rf "$BUILD_ROOT"
/bin/mkdir -p "$STAGING"

if [[ -n "$NOTARY_PROFILE" ]]; then
  APP_ZIP="$BUILD_ROOT/Transcriber-$VERSION.app.zip"
  /usr/bin/ditto -c -k --keepParent "$APP" "$APP_ZIP"
  xcrun notarytool submit "$APP_ZIP" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
fi

/usr/bin/ditto --noextattr --noqtn --norsrc "$APP" "$STAGING/Транскрибатор.app"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$ROOT/scripts/install_product_app.command" \
  "$STAGING/Установить Транскрибатор.command"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$ROOT/scripts/rollback_product_app.command" \
  "$STAGING/Откатить Транскрибатор.command"
/bin/chmod +x \
  "$STAGING/Установить Транскрибатор.command" \
  "$STAGING/Откатить Транскрибатор.command"

if [[ -n "$NOTARY_PROFILE" ]]; then
  ASSET_NAME="Transcriber-$VERSION-macOS-arm64"
  NOTARIZATION_STATUS="accepted-and-stapled"
else
  ASSET_NAME="Transcriber-$VERSION-candidate-macOS-arm64"
  NOTARIZATION_STATUS="not-requested"
fi

DMG="$DIST_ROOT/$ASSET_NAME.dmg"
SHA_FILE="$DMG.sha256"
MANIFEST="$DMG.manifest.txt"

/bin/rm -f "$DMG" "$SHA_FILE" "$MANIFEST"
/usr/bin/hdiutil create \
  -volname "Транскрибатор $VERSION" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$DMG"

if [[ -n "$NOTARY_PROFILE" ]]; then
  xcrun notarytool submit "$DMG" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
fi

/usr/bin/hdiutil verify "$DMG"
"$ROOT/scripts/audit_signatures.sh" "$APP" 1

if [[ -n "$NOTARY_PROFILE" ]]; then
  /usr/sbin/spctl --assess --type execute --verbose=4 "$APP"
fi

DMG_SHA=$(/usr/bin/shasum -a 256 "$DMG" | /usr/bin/awk '{ print $1 }')
printf '%s  %s\n' "$DMG_SHA" "${DMG:t}" > "$SHA_FILE"
{
  printf 'product=Транскрибатор\n'
  printf 'version=%s\n' "$VERSION"
  printf 'bundle_id=%s\n' "$BUNDLE_ID"
  printf 'architecture=arm64\n'
  printf 'maximum_macos_minos=15.0\n'
  printf 'source_commit=%s\n' "$(/usr/bin/git -C "$ROOT" rev-parse HEAD)"
  printf 'signing=Developer ID Application\n'
  printf 'notarization=%s\n' "$NOTARIZATION_STATUS"
  printf 'dependency_lock_sha256=%s\n' "$LOCK_SHA"
  printf 'install_target=~/Applications/Транскрибатор.app\n'
  printf 'rollback_target=~/Applications/Транскрибатор.previous.app\n'
  printf 'sha256=%s\n' "$DMG_SHA"
} > "$MANIFEST"

echo "$DMG"
echo "$SHA_FILE"
echo "$MANIFEST"
