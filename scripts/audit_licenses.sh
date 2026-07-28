#!/bin/zsh

set -euo pipefail

RUNTIME="${1:-}"
LICENSE_ROOT="${2:-}"
INVENTORY_OUTPUT="${3:-$LICENSE_ROOT/PYTHON-PACKAGE-INVENTORY.tsv}"

if [[ ! -d "$RUNTIME/_internal" || ! -d "$LICENSE_ROOT" ]]; then
  echo "Usage: $0 /path/to/transcriber-runtime /path/to/license-root [inventory-output]" >&2
  exit 2
fi

TMP_DIR=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/transcriber-license-audit.XXXXXX")
trap '/bin/rm -rf "$TMP_DIR"' EXIT
INVENTORY="$TMP_DIR/PYTHON-PACKAGE-INVENTORY.tsv"

printf 'package\tversion\tlicense_source\tstatus\n' > "$INVENTORY"

count=0
missing=0
typeset -A included_packages

while IFS= read -r dist_info; do
  METADATA="$dist_info/METADATA"
  if [[ ! -f "$METADATA" ]]; then
    echo "License audit failed: missing METADATA in $dist_info." >&2
    missing=$((missing + 1))
    continue
  fi

  NAME=$(/usr/bin/awk -F ': ' '$1 == "Name" { print $2; exit }' "$METADATA")
  VERSION=$(/usr/bin/awk -F ': ' '$1 == "Version" { print $2; exit }' "$METADATA")
  NORMALIZED=$(printf '%s' "$NAME" |
    /usr/bin/tr '[:upper:]' '[:lower:]' |
    /usr/bin/tr '._' '-')
  EXPLICIT_LICENSE_DIR="$LICENSE_ROOT/Python packages/$NORMALIZED"
  RUNTIME_LICENSE=$(/usr/bin/find "$dist_info" -type f \
    \( -iname 'LICENSE*' -o -iname 'NOTICE*' -o -iname 'COPYING*' \) \
    -print -quit)

  count=$((count + 1))
  included_packages[$NORMALIZED]=1

  if [[ -n "$RUNTIME_LICENSE" ]]; then
    SOURCE="${RUNTIME_LICENSE#$RUNTIME/_internal/}"
    STATUS="runtime"
  elif [[ -n "$(/usr/bin/find "$EXPLICIT_LICENSE_DIR" -type f -print -quit 2>/dev/null)" ]]; then
    SOURCE="${EXPLICIT_LICENSE_DIR#$LICENSE_ROOT/}"
    STATUS="explicit"
  else
    SOURCE="-"
    STATUS="MISSING"
    missing=$((missing + 1))
    echo "License audit failed: no license material for $NAME $VERSION." >&2
  fi

  printf '%s\t%s\t%s\t%s\n' "$NAME" "$VERSION" "$SOURCE" "$STATUS" >> "$INVENTORY"
done < <(/usr/bin/find "$RUNTIME/_internal" -maxdepth 1 -type d -name '*.dist-info' -print |
  LC_ALL=C /usr/bin/sort)

for required in python-docx transformers; do
  if [[ -z "${included_packages[$required]:-}" ]]; then
    echo "License audit failed: required package $required is absent from runtime inventory." >&2
    missing=$((missing + 1))
  fi
  if [[ -z "$(/usr/bin/find "$LICENSE_ROOT/Python packages/$required" \
    -type f -name 'LICENSE*' -print -quit 2>/dev/null)" ]]
  then
    echo "License audit failed: explicit $required license is absent." >&2
    missing=$((missing + 1))
  fi
done

if [[ "$count" -eq 0 ]]; then
  echo "License audit failed: no Python package metadata found." >&2
  exit 1
fi

if [[ "$INVENTORY_OUTPUT" != "-" ]]; then
  /bin/mkdir -p "${INVENTORY_OUTPUT:h}"
  /usr/bin/ditto --noextattr --noqtn --norsrc "$INVENTORY" "$INVENTORY_OUTPUT"
fi

if [[ "$missing" -ne 0 ]]; then
  exit 1
fi

echo "License audit passed: $count Python packages have mapped license material."
