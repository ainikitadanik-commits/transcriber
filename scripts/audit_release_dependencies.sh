#!/bin/zsh

set -euo pipefail

RELEASE_PYTHON_FRAMEWORK="${RELEASE_PYTHON_FRAMEWORK:-}"
if [[ -n "$RELEASE_PYTHON_FRAMEWORK" ]]; then
  export DYLD_FRAMEWORK_PATH="${RELEASE_PYTHON_FRAMEWORK:h}"
  export DYLD_LIBRARY_PATH="$RELEASE_PYTHON_FRAMEWORK/Versions/3.12/lib"
fi

PYTHON="${1:-}"
LOCK="${2:-}"
INVENTORY_OUTPUT="${3:--}"

if [[ ! -x "$PYTHON" || ! -f "$LOCK" ]]; then
  echo "Usage: $0 /path/to/python /path/to/requirements-release.lock [inventory-output|-]" >&2
  exit 2
fi

TMP_DIR=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/transcriber-dependency-audit.XXXXXX")
trap '/bin/rm -rf "$TMP_DIR"' EXIT
EXPECTED="$TMP_DIR/expected.txt"
ACTUAL="$TMP_DIR/actual.txt"
REQUIRED_PYTHON=$(/usr/bin/awk -F': ' \
  '$1 == "# python-version" { print $2; exit }' "$LOCK")
ACTUAL_PYTHON=$("$PYTHON" -c \
  'import platform; print(platform.python_version())')

if [[ -z "$REQUIRED_PYTHON" || "$ACTUAL_PYTHON" != "$REQUIRED_PYTHON" ]]; then
  echo "Dependency audit failed: Python $ACTUAL_PYTHON does not match locked $REQUIRED_PYTHON." >&2
  exit 1
fi

: > "$EXPECTED"
while IFS= read -r requirement; do
  if [[ -z "$requirement" || "$requirement" == \#* ]]; then
    continue
  fi
  if [[ "$requirement" == -e\ * || "$requirement" == *"file://"* ||
    "$requirement" == *"local-gigaam-transcriber"* ]]
  then
    echo "Dependency audit failed: local/editable requirement is forbidden: $requirement" >&2
    exit 1
  fi
  if [[ ! "$requirement" =~ '^[A-Za-z0-9._-]+==[^[:space:]]+$' &&
    ! "$requirement" =~ '^[A-Za-z0-9._-]+ @ git\+https://.+@[0-9a-f]{40}$' ]]
  then
    echo "Dependency audit failed: requirement is not exactly pinned: $requirement" >&2
    exit 1
  fi
  if [[ "$requirement" == *" @ git+https://"* ]]; then
    REVISION="${requirement##*@}"
    if [[ ! "$REVISION" =~ '^[0-9a-f]{40}$' ]]; then
      echo "Dependency audit failed: VCS requirement is not pinned to a full commit." >&2
      exit 1
    fi
  fi
  printf '%s\n' "$requirement" >> "$EXPECTED"
done < "$LOCK"

"$PYTHON" -m pip freeze --all |
  while IFS= read -r installed; do
    if [[ "$installed" == -e\ *"#egg=local_gigaam_transcriber" ]]; then
      continue
    fi
    if [[ "$installed" == -e\ * || "$installed" == *"file://"* ]]; then
      echo "Dependency audit failed: unexpected local/editable install: $installed" >&2
      exit 1
    fi
    printf '%s\n' "$installed"
  done > "$ACTUAL"

LC_ALL=C /usr/bin/sort -f -o "$EXPECTED" "$EXPECTED"
LC_ALL=C /usr/bin/sort -f -o "$ACTUAL" "$ACTUAL"

if ! /usr/bin/cmp -s "$EXPECTED" "$ACTUAL"; then
  echo "Dependency audit failed: environment differs from release lock." >&2
  /usr/bin/diff -u "$EXPECTED" "$ACTUAL" >&2 || true
  exit 1
fi

if [[ "$INVENTORY_OUTPUT" != "-" ]]; then
  LOCK_SHA=$(/usr/bin/shasum -a 256 "$LOCK" | /usr/bin/awk '{ print $1 }')
  /bin/mkdir -p "${INVENTORY_OUTPUT:h}"
  {
    printf 'format=1\n'
    printf 'python_version=%s\n' "$ACTUAL_PYTHON"
    printf 'lock_sha256=%s\n' "$LOCK_SHA"
    printf 'packages_begin\n'
    /bin/cat "$ACTUAL"
  } > "$INVENTORY_OUTPUT"
fi

echo "Dependency audit passed: environment exactly matches ${LOCK:t}."
