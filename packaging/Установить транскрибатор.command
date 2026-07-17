#!/bin/zsh

set -euo pipefail

SOURCE_DIR="${0:A:h}"
PAYLOAD="$SOURCE_DIR/.payload"
DATA_ROOT="$HOME/Library/Application Support/Транскрибатор"
LAUNCHER_DIR="$HOME/Applications/Транскрибатор"

echo "Устанавливаем транскрибатор в пользовательскую папку…"
mkdir -p "$DATA_ROOT/runtime/0.1.0" "$DATA_ROOT/models/gigaam" "$DATA_ROOT/bin" "$LAUNCHER_DIR"

echo "Проверяем комплект…"
(
  cd "$PAYLOAD"
  /usr/bin/shasum -a 256 -c checksums.sha256 --quiet
)

/usr/bin/ditto "$PAYLOAD/runtime/transcriber-runtime" "$DATA_ROOT/runtime/0.1.0/transcriber-runtime"
/usr/bin/ditto "$PAYLOAD/models/gigaam" "$DATA_ROOT/models/gigaam"
/usr/bin/ditto "$PAYLOAD/bin/ffmpeg" "$DATA_ROOT/bin/ffmpeg"
/usr/bin/ditto "$SOURCE_DIR/Запустить транскрибатор.command" "$LAUNCHER_DIR/Запустить транскрибатор.command"
/bin/chmod +x "$DATA_ROOT/runtime/0.1.0/transcriber-runtime/transcriber-runtime"
/bin/chmod +x "$DATA_ROOT/bin/ffmpeg" "$LAUNCHER_DIR/Запустить транскрибатор.command"

# The user explicitly opened this internal installer. Remove the download
# quarantine from the verified payload so macOS can load its ad-hoc signed
# Python framework without administrator rights.
/usr/bin/xattr -dr com.apple.quarantine "$DATA_ROOT/runtime/0.1.0" "$DATA_ROOT/bin" 2>/dev/null || true
/usr/bin/xattr -d com.apple.quarantine "$LAUNCHER_DIR/Запустить транскрибатор.command" 2>/dev/null || true

echo
echo "Готово. Файл запуска находится здесь:"
echo "$LAUNCHER_DIR/Запустить транскрибатор.command"
echo
echo "Откройте папку «Программы» в домашней папке и запускайте транскрибатор двойным нажатием на этот файл."
read -k 1 "?Нажмите любую клавишу, чтобы закрыть окно."
echo
