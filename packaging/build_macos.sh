#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
VERSION="0.1.1"
BUILD_ROOT="$ROOT/build/macos"
DIST_ROOT="$ROOT/dist"
DMG_ROOT="$BUILD_ROOT/dmg"
PAYLOAD="$DMG_ROOT/.payload"
PYTHON="$ROOT/.venv/bin/python"
export PYINSTALLER_CONFIG_DIR="$BUILD_ROOT/pyinstaller-cache"
export MPLCONFIGDIR="$BUILD_ROOT/matplotlib-cache"

rm -rf "$BUILD_ROOT" "$DIST_ROOT/transcriber-runtime"
mkdir -p "$BUILD_ROOT" "$DIST_ROOT" "$PAYLOAD/runtime" "$PAYLOAD/models/gigaam" "$PAYLOAD/bin" "$DMG_ROOT/Лицензии"

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
  --collect-submodules scipy._external.array_api_compat \
  --add-data "$ROOT/src/transcriber/web/templates:transcriber/web/templates" \
  --add-data "$ROOT/src/transcriber/web/static:transcriber/web/static" \
  --add-data "$ROOT/packaging/docx-parts:docx/parts" \
  "$ROOT/packaging/runtime_entry.py"

/usr/bin/ditto "$DIST_ROOT/transcriber-runtime" "$PAYLOAD/runtime/transcriber-runtime"

for model in v3_e2e_rnnt.ckpt v3_e2e_rnnt_tokenizer.model v3_e2e_ctc.ckpt v3_e2e_ctc_tokenizer.model; do
  /usr/bin/ditto "$HOME/.cache/gigaam/$model" "$PAYLOAD/models/gigaam/$model"
done

FFMPEG=$("$PYTHON" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')
/usr/bin/ditto "$FFMPEG" "$PAYLOAD/bin/ffmpeg"
/bin/chmod +x "$PAYLOAD/bin/ffmpeg"

/usr/bin/ditto "$ROOT/packaging/Установить транскрибатор.command" "$DMG_ROOT/Установить транскрибатор.command"
/usr/bin/ditto "$ROOT/packaging/Запустить транскрибатор.command" "$DMG_ROOT/Запустить транскрибатор.command"
/usr/bin/ditto "$ROOT/packaging/Инструкция по установке.txt" "$DMG_ROOT/Инструкция по установке.txt"
/usr/bin/ditto "$ROOT/packaging/Лицензии" "$DMG_ROOT/Лицензии"
/bin/chmod +x "$DMG_ROOT/Установить транскрибатор.command" "$DMG_ROOT/Запустить транскрибатор.command"

/usr/bin/codesign --force --deep --sign - "$PAYLOAD/runtime/transcriber-runtime/transcriber-runtime"
/usr/bin/codesign --force --sign - "$PAYLOAD/bin/ffmpeg"

(
  cd "$PAYLOAD"
  find runtime models bin -type f | LC_ALL=C sort | while IFS= read -r file; do
    shasum -a 256 "$file"
  done > checksums.sha256
)

DMG="$DIST_ROOT/Транскрибатор-${VERSION}-macOS-arm64.dmg"
rm -f "$DMG"
if [[ "${SKIP_DMG:-0}" == "1" ]]; then
  echo "$DMG_ROOT"
  exit 0
fi
/usr/bin/hdiutil create -volname "Транскрибатор $VERSION" -srcfolder "$DMG_ROOT" -ov -format UDZO "$DMG"

echo "$DMG"
