#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
VERSION="3.12.10"
TOOLCHAIN="$ROOT/build/toolchain"
PACKAGE="$TOOLCHAIN/python-$VERSION-macos11.pkg"
EXPANDED="$TOOLCHAIN/python-pkg-expanded"
FRAMEWORK="$TOOLCHAIN/Python.framework"
PREFIX="$FRAMEWORK/Versions/3.12"
URL="https://www.python.org/ftp/python/$VERSION/python-$VERSION-macos11.pkg"
SHA256="8373e58da4ea146b3eb1c1f9834f19a319440b6b679b06050b1f9ee3237aa8e4"

/bin/mkdir -p "$TOOLCHAIN"
if [[ ! -f "$PACKAGE" ]]; then
  /usr/bin/curl -fL --retry 3 "$URL" -o "$PACKAGE"
fi

ACTUAL_SHA256=$(/usr/bin/shasum -a 256 "$PACKAGE" | /usr/bin/awk '{print $1}')
if [[ "$ACTUAL_SHA256" != "$SHA256" ]]; then
  echo "Python package checksum mismatch." >&2
  exit 1
fi
/usr/sbin/pkgutil --check-signature "$PACKAGE"

/bin/rm -rf "$EXPANDED" "$FRAMEWORK"
/usr/sbin/pkgutil --expand-full "$PACKAGE" "$EXPANDED"
/bin/mkdir -p "$FRAMEWORK"
/usr/bin/ditto \
  "$EXPANDED/Python_Framework.pkg/Payload" \
  "$FRAMEWORK"

/usr/bin/find "$FRAMEWORK" -type f -print0 |
  while IFS= read -r -d '' binary; do
    DESCRIPTION=$(/usr/bin/file -b "$binary")
    if [[ "$DESCRIPTION" != *"Mach-O"* ]]; then
      continue
    fi
    /usr/bin/otool -L "$binary" |
      /usr/bin/tail -n +2 |
      /usr/bin/awk '{print $1}' |
      while IFS= read -r dependency; do
        if [[ "$dependency" == /Library/Frameworks/Python.framework/Versions/3.12/* ]]
        then
          suffix="${dependency#/Library/Frameworks/Python.framework/Versions/3.12/}"
          /usr/bin/install_name_tool \
            -change "$dependency" "$PREFIX/$suffix" "$binary"
        fi
      done
    current_id=$(/usr/bin/otool -D "$binary" 2>/dev/null |
      /usr/bin/tail -n +2 |
      /usr/bin/head -1)
    if [[ "$current_id" == /Library/Frameworks/Python.framework/Versions/3.12/* ]]
    then
      suffix="${current_id#/Library/Frameworks/Python.framework/Versions/3.12/}"
      /usr/bin/install_name_tool -id "$PREFIX/$suffix" "$binary"
    fi
  done

/usr/bin/find "$FRAMEWORK" -type f \
  \( -name '*.so' -o -name '*.dylib' -o -name 'Python' \
    -o -name 'python3.12' -o -name 'python3.12-intel64' \) \
  -print0 |
  while IFS= read -r -d '' binary; do
    /usr/bin/codesign --force --sign - "$binary"
  done

PYTHON="$PREFIX/bin/python3.12"
/usr/bin/codesign --verify --strict "$PYTHON"
"$PYTHON" -c \
  'import platform, ssl; assert platform.python_version() == "3.12.10"; print(ssl.OPENSSL_VERSION)'
"$ROOT/scripts/audit_macho.sh" "$PYTHON" "15.0"

echo "$PYTHON"
