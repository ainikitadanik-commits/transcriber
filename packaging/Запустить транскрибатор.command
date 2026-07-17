#!/bin/zsh

set -u

DATA_ROOT="$HOME/Library/Application Support/Транскрибатор"
RUNTIME="$DATA_ROOT/runtime/0.1.0/transcriber-runtime"

if [[ ! -x "$RUNTIME/transcriber-runtime" ]]; then
  echo "Транскрибатор не установлен. Сначала откройте DMG и запустите «Установить транскрибатор.command»."
  read -k 1 "?Нажмите любую клавишу, чтобы закрыть окно."
  echo
  exit 1
fi

export TRANSCRIBER_DATA_DIR="$DATA_ROOT"
export TRANSCRIBER_GIGAAM_MODELS_DIR="$DATA_ROOT/models/gigaam"
export HF_HOME="$DATA_ROOT/models/huggingface"
export HF_HUB_DISABLE_TELEMETRY=1
export PATH="$DATA_ROOT/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$DATA_ROOT/input" "$DATA_ROOT/output" "$DATA_ROOT/logs"
exec "$RUNTIME/transcriber-runtime"
