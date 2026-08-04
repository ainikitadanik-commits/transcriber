#!/bin/zsh

set -euo pipefail

ROOT="${0:A:h:h}"
LOCK="$ROOT/packaging/requirements-release.lock"
TARGET="${RELEASE_VENV:-$ROOT/build/product/release-venv}"
BOOTSTRAP_PYTHON="${BOOTSTRAP_PYTHON:-$ROOT/.venv/bin/python}"
BOOTSTRAP_PYTHON_FRAMEWORK="${BOOTSTRAP_PYTHON_FRAMEWORK:-}"

if [[ -n "$BOOTSTRAP_PYTHON_FRAMEWORK" ]]; then
  export RELEASE_PYTHON_FRAMEWORK="$BOOTSTRAP_PYTHON_FRAMEWORK"
  export DYLD_FRAMEWORK_PATH="${BOOTSTRAP_PYTHON_FRAMEWORK:h}"
  export DYLD_LIBRARY_PATH="$BOOTSTRAP_PYTHON_FRAMEWORK/Versions/3.12/lib"
fi

if [[ ! -x "$BOOTSTRAP_PYTHON" ]]; then
  echo "Bootstrap Python not found: $BOOTSTRAP_PYTHON" >&2
  exit 1
fi

PYTHON_VERSION=$("$BOOTSTRAP_PYTHON" -c \
  'import platform; print(platform.python_version())')
REQUIRED_PYTHON=$(/usr/bin/awk -F': ' \
  '$1 == "# python-version" { print $2; exit }' "$LOCK")
if [[ -z "$REQUIRED_PYTHON" || "$PYTHON_VERSION" != "$REQUIRED_PYTHON" ]]; then
  echo "Release environment requires locked Python $REQUIRED_PYTHON, found $PYTHON_VERSION." >&2
  exit 1
fi

/bin/rm -rf "$TARGET"
"$BOOTSTRAP_PYTHON" -m venv "$TARGET"
RELEASE_PYTHON="$TARGET/bin/python"

typeset -a BOOTSTRAP_REQUIREMENTS
BOOTSTRAP_REQUIREMENTS=("${(@f)$(/usr/bin/awk \
  '/^(pip|setuptools)==/ { print }' "$LOCK")}")

"$RELEASE_PYTHON" -m pip install \
  --disable-pip-version-check \
  --no-deps \
  "${BOOTSTRAP_REQUIREMENTS[@]}"

PIP_CONSTRAINT="$LOCK" \
  "$RELEASE_PYTHON" -m pip install \
  --disable-pip-version-check \
  --no-build-isolation \
  --requirement "$LOCK"

"$ROOT/scripts/audit_release_dependencies.sh" \
  "$RELEASE_PYTHON" \
  "$LOCK" \
  "-"

echo "$RELEASE_PYTHON"
