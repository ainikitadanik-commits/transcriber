#!/bin/zsh

set -u

APP="$HOME/Applications/Транскрибатор.app"

if [[ ! -d "$APP" ]]; then
  /usr/bin/osascript -e \
    'display alert "Транскрибатор не установлен" message "Не найдено приложение в папке ~/Applications." as critical'
  exit 1
fi

exec /usr/bin/open "$APP"
