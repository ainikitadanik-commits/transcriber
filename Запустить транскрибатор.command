#!/bin/zsh

set -u

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR" || exit 1
export PATH="$HOME/homebrew/bin:/opt/homebrew/bin:$PATH"

if [[ ! -x "$PROJECT_DIR/.venv/bin/transcribe-ui" ]]; then
  echo "Среда транскрибатора не установлена."
  echo "Откройте README.md и выполните раздел «Запуск из исходников»."
  read -k 1 "?Нажмите любую клавишу, чтобы закрыть окно."
  echo
  exit 1
fi

exec "$PROJECT_DIR/.venv/bin/transcribe-ui"
