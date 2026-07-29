#!/bin/zsh

set -euo pipefail

SOURCE_DIR="${0:A:h}"
SOURCE_APP="$SOURCE_DIR/Транскрибатор.app"
INSTALL_ROOT="$HOME/Applications"
INSTALLED_APP="$INSTALL_ROOT/Транскрибатор.app"
PREVIOUS_APP="$INSTALL_ROOT/Транскрибатор.previous.app"
STAGING_APP="$INSTALL_ROOT/.Транскрибатор.installing.$$"

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "Не найдено приложение рядом с установщиком: $SOURCE_APP" >&2
  exit 1
fi

/usr/bin/codesign --verify --deep --strict --verbose=2 "$SOURCE_APP"
SIGNATURE_INFO=$(/usr/bin/codesign -dvvv "$SOURCE_APP" 2>&1 || true)
if [[ "$SIGNATURE_INFO" != *"Authority=Developer ID Application:"* ]]; then
  echo "Установка остановлена: приложение не подписано Developer ID Application." >&2
  exit 1
fi
if ! /usr/sbin/spctl --assess --type execute --verbose=4 "$SOURCE_APP"; then
  echo "Установка остановлена: Gatekeeper не подтвердил приложение." >&2
  echo "Запросите у владельца сборки новый нотарифицированный DMG." >&2
  exit 1
fi

/bin/mkdir -p "$INSTALL_ROOT"
/bin/rm -rf "$STAGING_APP"
/usr/bin/ditto "$SOURCE_APP" "$STAGING_APP"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$STAGING_APP"
if ! /usr/sbin/spctl --assess --type execute --verbose=4 "$STAGING_APP"; then
  echo "Установка остановлена: копия приложения не прошла Gatekeeper." >&2
  /bin/rm -rf "$STAGING_APP"
  exit 1
fi

if [[ -d "$INSTALLED_APP" ]]; then
  /bin/rm -rf "$PREVIOUS_APP"
  /bin/mv "$INSTALLED_APP" "$PREVIOUS_APP"
fi

if ! /bin/mv "$STAGING_APP" "$INSTALLED_APP"; then
  if [[ -d "$PREVIOUS_APP" && ! -d "$INSTALLED_APP" ]]; then
    /bin/mv "$PREVIOUS_APP" "$INSTALLED_APP"
  fi
  exit 1
fi

echo "Транскрибатор установлен без прав администратора:"
echo "$INSTALLED_APP"
if [[ -d "$PREVIOUS_APP" ]]; then
  echo "Предыдущая версия сохранена для отката:"
  echo "$PREVIOUS_APP"
fi

exec /usr/bin/open "$INSTALLED_APP"
