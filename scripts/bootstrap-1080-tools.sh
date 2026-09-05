#!/usr/bin/env bash
# Install the non-ROM tooling used by projects/1080-decomp.
#
# This is intentionally safe to rerun. It downloads pinned IDO/objdiff
# binaries, installs an unprivileged MIPS binutils package when host binutils
# are absent, and shallow-clones the reference/permuter repositories.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="${1:-$REPO_ROOT/projects/1080-decomp}"
TOOLS_DIR="$REPO_ROOT/tools"
REFERENCES_DIR="$REPO_ROOT/references"
USER_BIN="${DECOMP_USER_BIN:-$HOME/.local/bin}"

IDO_RELEASE="v1.2"
IDO53_SHA256="ab5c741561f80913d58c8b074771f23941a3edd312505a8ebed6d1dfeb65e506"
IDO71_SHA256="0d411696e178fcca34c31c3bf02011b928d7fd9c1fa7f8bf45070e0781b58e15"
OBJDIFF_RELEASE="v3.8.0"
OBJDIFF_SHA256="bc1e047126f9c6914bd1695798175234642ab9eaf45e886f841b59a4231e1a81"

if [[ ! -d "$PROJECT_DIR" ]]; then
    echo "bootstrap-1080-tools: project not found: $PROJECT_DIR" >&2
    exit 1
fi

mkdir -p "$TOOLS_DIR" "$REFERENCES_DIR" "$USER_BIN"
TMP_DIR="$(mktemp -d)"
cleanup() {
    find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type f -delete 2>/dev/null || true
    rmdir "$TMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT

download_checked() {
    local url="$1"
    local destination="$2"
    local expected_sha="$3"
    local tmp="$TMP_DIR/$(basename "$destination").download"
    local actual_sha

    curl --fail --location --silent --show-error "$url" --output "$tmp"
    actual_sha="$(sha256sum "$tmp" | awk '{print $1}')"
    if [[ "$actual_sha" != "$expected_sha" ]]; then
        echo "bootstrap-1080-tools: checksum mismatch for $url" >&2
        echo "  got:  $actual_sha" >&2
        echo "  want: $expected_sha" >&2
        exit 1
    fi
    install -m 0755 "$tmp" "$destination"
}

install_ido() {
    local version="$1"
    local expected_sha="$2"
    local out_dir="$PROJECT_DIR/tools/ido-static-recomp/build/$version/out"
    local archive="$TMP_DIR/ido-$version.tar.gz"
    local url="https://github.com/decompals/ido-static-recomp/releases/download/$IDO_RELEASE/ido-$version-recomp-linux.tar.gz"
    local actual_sha

    if [[ -x "$out_dir/cc" ]]; then
        echo ">>> IDO $version already installed"
        return
    fi

    echo ">>> Installing IDO $version ($IDO_RELEASE)"
    curl --fail --location --silent --show-error "$url" --output "$archive"
    actual_sha="$(sha256sum "$archive" | awk '{print $1}')"
    if [[ "$actual_sha" != "$expected_sha" ]]; then
        echo "bootstrap-1080-tools: checksum mismatch for IDO $version" >&2
        exit 1
    fi
    mkdir -p "$out_dir"
    tar -xzf "$archive" -C "$out_dir"
    chmod +x "$out_dir"/*
}

clone_if_missing() {
    local url="$1"
    local destination="$2"

    if [[ -d "$destination/.git" ]]; then
        echo ">>> Already cloned: $destination"
        return
    fi
    if [[ -e "$destination" ]]; then
        echo "bootstrap-1080-tools: refusing to replace non-git path: $destination" >&2
        exit 1
    fi
    echo ">>> Cloning $url"
    git clone --depth 1 "$url" "$destination"
}

install_local_binutils() {
    local binutils_root="$TOOLS_DIR/mips-binutils"
    local wrapper="$SCRIPT_DIR/mips-binutils-wrapper.sh"
    local debs
    local tool

    if command -v mips-linux-gnu-as >/dev/null 2>&1 && \
            mips-linux-gnu-as --version >/dev/null 2>&1; then
        echo ">>> MIPS binutils already available"
        return
    fi

    if [[ ! -x "$binutils_root/usr/bin/mips-linux-gnu-as" ]]; then
        if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg-deb >/dev/null 2>&1; then
            echo "bootstrap-1080-tools: install binutils-mips-linux-gnu with your system package manager" >&2
            exit 1
        fi

        echo ">>> Installing MIPS binutils without root"
        (cd "$TMP_DIR" && apt-get download binutils-mips-linux-gnu)
        shopt -s nullglob
        debs=("$TMP_DIR"/binutils-mips-linux-gnu_*.deb)
        shopt -u nullglob
        if [[ "${#debs[@]}" -ne 1 ]]; then
            echo "bootstrap-1080-tools: expected one binutils package, found ${#debs[@]}" >&2
            exit 1
        fi
        mkdir -p "$binutils_root"
        dpkg-deb -x "${debs[0]}" "$binutils_root"
    else
        echo ">>> Repairing local MIPS binutils launchers"
    fi

    for tool in "$binutils_root"/usr/bin/mips-linux-gnu-*; do
        ln -sfn "$wrapper" "$USER_BIN/$(basename "$tool")"
    done

    if ! "$USER_BIN/mips-linux-gnu-as" --version >/dev/null 2>&1; then
        echo "bootstrap-1080-tools: local MIPS binutils failed to start" >&2
        exit 1
    fi
}

install_permuter_dependencies() {
    local permuter_dir="$TOOLS_DIR/decomp-permuter"
    local venv="$permuter_dir/.venv"
    local python="$venv/bin/python"

    if [[ -x "$python" ]] && "$python" -c 'import toml, nacl, Levenshtein' >/dev/null 2>&1; then
        echo ">>> decomp-permuter Python dependencies already installed"
        return
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo "bootstrap-1080-tools: uv is required to prepare decomp-permuter" >&2
        exit 1
    fi

    echo ">>> Installing decomp-permuter Python dependencies"
    if [[ ! -x "$python" ]]; then
        uv venv --python python3 "$venv"
    fi
    uv pip install --python "$python" pynacl toml Levenshtein
}

install_ido 5.3 "$IDO53_SHA256"
install_ido 7.1 "$IDO71_SHA256"

if command -v objdiff-cli >/dev/null 2>&1 && \
        objdiff-cli --version 2>/dev/null | grep -q '3\.8\.0'; then
    echo ">>> objdiff-cli $OBJDIFF_RELEASE already available"
else
    echo ">>> Installing objdiff-cli $OBJDIFF_RELEASE"
    download_checked \
        "https://github.com/encounter/objdiff/releases/download/$OBJDIFF_RELEASE/objdiff-cli-linux-x86_64" \
        "$USER_BIN/objdiff-cli" \
        "$OBJDIFF_SHA256"
    hash -r
fi

install_local_binutils

clone_if_missing https://github.com/simonlindholm/decomp-permuter.git "$TOOLS_DIR/decomp-permuter"
clone_if_missing https://github.com/n64decomp/libreultra.git "$REFERENCES_DIR/libreultra"
clone_if_missing https://github.com/zeldaret/oot.git "$REFERENCES_DIR/oot"
clone_if_missing https://github.com/pmret/papermario.git "$REFERENCES_DIR/papermario"
install_permuter_dependencies

PERMUTER_LINK="$PROJECT_DIR/tools/decomp-permuter"
if [[ -L "$PERMUTER_LINK" ]]; then
    ln -sfn ../../../tools/decomp-permuter "$PERMUTER_LINK"
elif [[ -e "$PERMUTER_LINK" ]]; then
    echo "bootstrap-1080-tools: refusing to replace non-symlink: $PERMUTER_LINK" >&2
    exit 1
else
    ln -s ../../../tools/decomp-permuter "$PERMUTER_LINK"
fi

echo
echo "1080 non-ROM tooling is ready:"
echo "  project:    $PROJECT_DIR"
echo "  objdiff:    $(command -v objdiff-cli)"
echo "  binutils:   $(command -v mips-linux-gnu-as)"
echo "  references: $REFERENCES_DIR"
echo "  permuter:   $TOOLS_DIR/decomp-permuter"
