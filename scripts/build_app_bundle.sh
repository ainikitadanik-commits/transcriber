#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
VERSION="0.2.3"
BUILD_ROOT="$ROOT/build/product"
DIST_ROOT="$ROOT/dist"
RUNTIME="$DIST_ROOT/transcriber-runtime"
APP="$DIST_ROOT/Транскрибатор.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
SIGN_IDENTITY="${SIGN_IDENTITY:--}"
SDK="${SDKROOT:-$(xcrun --show-sdk-path)}"
MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-15.0}"
RELEASE_BUILD="${RELEASE_BUILD:-0}"
RELEASE_LOCK="$ROOT/packaging/requirements-release.lock"
RELEASE_PYTHON_FRAMEWORK="${RELEASE_PYTHON_FRAMEWORK:-}"

if [[ -n "$RELEASE_PYTHON_FRAMEWORK" ]]; then
  export DYLD_FRAMEWORK_PATH="${RELEASE_PYTHON_FRAMEWORK:h}"
  export DYLD_LIBRARY_PATH="$RELEASE_PYTHON_FRAMEWORK/Versions/3.12/lib"
fi

if [[ "$RELEASE_BUILD" == "1" ]]; then
  PYTHON="${RELEASE_PYTHON:-$BUILD_ROOT/release-venv/bin/python}"
  if [[ ! -x "$PYTHON" ]]; then
    echo "Release Python not found: $PYTHON" >&2
    echo "Run scripts/prepare_release_environment.sh first." >&2
    exit 1
  fi
  "$ROOT/scripts/audit_release_dependencies.sh" "$PYTHON" "$RELEASE_LOCK" "-"
else
  PYTHON="${TRANSCRIBER_BUILD_PYTHON:-$ROOT/.venv/bin/python}"
fi

export PYINSTALLER_CONFIG_DIR="$BUILD_ROOT/pyinstaller-cache"
export MPLCONFIGDIR="$BUILD_ROOT/matplotlib-cache"
export MACOSX_DEPLOYMENT_TARGET

if [[ "$RELEASE_BUILD" == "1" && "$SIGN_IDENTITY" == "-" ]]; then
  echo "Release build requires a real Developer ID Application identity." >&2
  exit 1
fi

if [[ "${REBUILD_RUNTIME:-0}" == "1" || ! -x "$RUNTIME/transcriber-runtime" ]]; then
  rm -rf "$RUNTIME"
  "$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --name transcriber-runtime \
    --distpath "$DIST_ROOT" \
    --workpath "$BUILD_ROOT/pyinstaller" \
    --specpath "$BUILD_ROOT" \
    --paths "$ROOT/src" \
    --collect-all gigaam \
    --collect-submodules pyannote.audio \
    --collect-data pyannote.audio \
    --collect-data docx \
    --copy-metadata python-docx \
    --copy-metadata transformers \
    --collect-submodules scipy._external.array_api_compat \
    --add-data "$ROOT/src/transcriber/web/templates:transcriber/web/templates" \
    --add-data "$ROOT/src/transcriber/web/static:transcriber/web/static" \
    --add-data "$ROOT/packaging/docx-parts:docx/parts" \
    "$ROOT/packaging/runtime_entry.py"
fi

rm -rf "$APP"
mkdir -p \
  "$CONTENTS/MacOS" \
  "$RESOURCES/runtime" \
  "$RESOURCES/models/gigaam" \
  "$RESOURCES/bin" \
  "$RESOURCES/Лицензии"

mkdir -p "$RESOURCES/runtime/transcriber-runtime"
/usr/bin/rsync -a --exclude ".DS_Store" \
  "$RUNTIME/" "$RESOURCES/runtime/transcriber-runtime/"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$ROOT/packaging/app/Info.plist" "$CONTENTS/Info.plist"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$ROOT/packaging/app/Transcriber.icns" "$RESOURCES/Transcriber.icns"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$ROOT/packaging/Лицензии" "$RESOURCES/Лицензии"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$ROOT/docs/PRIVACY.md" "$RESOURCES/Приватность.md"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$ROOT/docs/PRIVACY.md" "$RESOURCES/Лицензии/Приватность.md"

for model in \
  v3_e2e_rnnt.ckpt \
  v3_e2e_rnnt_tokenizer.model \
  v3_e2e_ctc.ckpt \
  v3_e2e_ctc_tokenizer.model
do
  /usr/bin/ditto --noextattr --noqtn --norsrc \
    "$HOME/.cache/gigaam/$model" \
    "$RESOURCES/models/gigaam/$model"
done

FFMPEG="${TRANSCRIBER_FFMPEG_BINARY:-$BUILD_ROOT/vendor/ffmpeg}"
if [[ ! -x "$FFMPEG" ]]; then
  echo "Не найдена продуктовая LGPL-сборка FFmpeg." >&2
  echo "Сначала выполните scripts/build_ffmpeg_lgpl.sh." >&2
  exit 1
fi
"$ROOT/scripts/audit_ffmpeg.sh" "$FFMPEG"
/usr/bin/ditto --noextattr --noqtn --norsrc "$FFMPEG" "$RESOURCES/bin/ffmpeg"
/bin/chmod +x "$RESOURCES/bin/ffmpeg"

FFMPEG_LICENSES="$RESOURCES/Лицензии/FFmpeg"
mkdir -p "$FFMPEG_LICENSES"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$BUILD_ROOT/vendor/ffmpeg-7.1.tar.xz" \
  "$FFMPEG_LICENSES/ffmpeg-7.1.tar.xz"
/usr/bin/ditto --noextattr --noqtn --norsrc \
  "$BUILD_ROOT/vendor/ffmpeg-7.1/COPYING.LGPLv2.1" \
  "$FFMPEG_LICENSES/COPYING.LGPLv2.1"
"$FFMPEG" -version > "$FFMPEG_LICENSES/CONFIGURATION.txt" 2>&1

PYTHON_LICENSES="$RESOURCES/Лицензии/Python packages"
mkdir -p "$PYTHON_LICENSES"
find "$RUNTIME/_internal" -type f \
  \( -iname "LICENSE*" -o -iname "NOTICE*" -o -iname "COPYING*" \) \
  -print0 |
  while IFS= read -r -d '' license_file; do
    relative="${license_file#$RUNTIME/_internal/}"
    destination="$PYTHON_LICENSES/$relative"
    mkdir -p "${destination:h}"
    /usr/bin/ditto --noextattr --noqtn --norsrc \
      "$license_file" "$destination"
  done

"$ROOT/scripts/audit_licenses.sh" \
  "$RUNTIME" \
  "$RESOURCES/Лицензии"

if [[ "$RELEASE_BUILD" == "1" ]]; then
  /usr/bin/ditto --noextattr --noqtn --norsrc \
    "$RELEASE_LOCK" \
    "$RESOURCES/Лицензии/requirements-release.lock"
  "$ROOT/scripts/audit_release_dependencies.sh" \
    "$PYTHON" \
    "$RELEASE_LOCK" \
    "$RESOURCES/Лицензии/DEPENDENCY-INVENTORY.txt"
fi

mkdir -p "$BUILD_ROOT/swift-module-cache"
xcrun swiftc \
  -parse-as-library \
  -O \
  -sdk "$SDK" \
  -module-cache-path "$BUILD_ROOT/swift-module-cache" \
  -target arm64-apple-macos15.0 \
  -framework AppKit \
  -framework AVFoundation \
  -framework CoreAudio \
  -framework CoreMedia \
  -framework UniformTypeIdentifiers \
  -framework WebKit \
  "$ROOT/native/realtime_capture.swift" \
  -o "$CONTENTS/MacOS/Transcriber"

/usr/bin/plutil -lint "$CONTENTS/Info.plist"

MACHO_INVENTORY_OUTPUT="$RESOURCES/Лицензии/MACHO-INVENTORY.tsv" \
  "$ROOT/scripts/audit_macho.sh" "$APP" "$MACOSX_DEPLOYMENT_TARGET"

"$ROOT/scripts/sign_app_bundle.sh" \
  "$APP" \
  "$SIGN_IDENTITY" \
  "$ROOT/packaging/app/Transcriber.entitlements"

"$ROOT/scripts/audit_signatures.sh" \
  "$APP" \
  "$RELEASE_BUILD"

echo "$APP"
