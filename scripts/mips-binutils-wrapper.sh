#!/usr/bin/env bash
# Launch a locally extracted Ubuntu MIPS binutils executable with its bundled
# shared libraries. This script is reached through mips-linux-gnu-* symlinks.
set -euo pipefail

TOOL_NAME="$(basename "$0")"
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BINUTILS_ROOT="$REPO_ROOT/tools/mips-binutils"
TOOL_PATH="$BINUTILS_ROOT/usr/bin/$TOOL_NAME"

shopt -s nullglob
LIBOPCODES=("$BINUTILS_ROOT"/usr/lib/*/libopcodes-*-mips.so)
shopt -u nullglob

if [[ ! -x "$TOOL_PATH" ]]; then
    echo "mips-binutils-wrapper: executable not found: $TOOL_PATH" >&2
    exit 1
fi
if [[ "${#LIBOPCODES[@]}" -eq 0 ]]; then
    echo "mips-binutils-wrapper: bundled libraries not found under $BINUTILS_ROOT/usr/lib" >&2
    exit 1
fi

LIB_DIR="$(dirname "${LIBOPCODES[0]}")"
export LD_LIBRARY_PATH="$LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$TOOL_PATH" "$@"
