#!/bin/zsh

set -euo pipefail

INSTALL_ROOT="$HOME/Applications"
INSTALLED_APP="$INSTALL_ROOT/Транскрибатор.app"
PREVIOUS_APP="$INSTALL_ROOT/Транскрибатор.previous.app"
FAILED_APP="$INSTALL_ROOT/.Транскрибатор.rollback.$$"

if [[ ! -d "$PREVIOUS_APP" ]]; then
  echo "Предыдущая версия для отката не найдена: $PREVIOUS_APP" >&2
  exit 1
fi

/usr/bin/codesign --verify --deep --strict --verbose=2 "$PREVIOUS_APP"
SIGNATURE_INFO=$(/usr/bin/codesign -dvvv "$PREVIOUS_APP" 2>&1 || true)
if [[ "$SIGNATURE_INFO" != *"Authority=Developer ID Application:"* ]]; then
  echo "Откат остановлен: предыдущая версия не подписана Developer ID Application." >&2
  exit 1
fi

if [[ -d "$INSTALLED_APP" ]]; then
  /bin/mv "$INSTALLED_APP" "$FAILED_APP"
fi

if ! /bin/mv "$PREVIOUS_APP" "$INSTALLED_APP"; then
  if [[ -d "$FAILED_APP" && ! -d "$INSTALLED_APP" ]]; then
    /bin/mv "$FAILED_APP" "$INSTALLED_APP"
  fi
  exit 1
fi

/bin/rm -rf "$FAILED_APP"
echo "Предыдущая версия восстановлена:"
echo "$INSTALLED_APP"
exec /usr/bin/open "$INSTALLED_APP"
