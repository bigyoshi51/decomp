#!/usr/bin/env bash
# Per-worktree setup for 1080 Snowboarding agents.
# Invoked by scripts/spin-up-agent.sh from inside the new worktree.
set -euo pipefail

# The main checkout's directory name varies per machine ("1080 Snowboarding
# (USA)" on the original, "1080-decomp" on later clones) — derive it from git
# instead of hardcoding. The first `worktree` line is always the main worktree.
MAIN="$(git worktree list --porcelain | awk '/^worktree /{sub(/^worktree /,""); print; exit}')"
if [[ -z "$MAIN" || ! -f "$MAIN/baserom.z64" ]]; then
    echo "1080 agent-setup: cannot locate main checkout with baserom.z64 (got: '$MAIN')" >&2
    exit 1
fi

ln -sfn "$MAIN/tools/ido-static-recomp" tools/ido-static-recomp
ln -sfn "$MAIN/baserom.z64" baserom.z64

# assets/ is .gitignored AND the Makefile uses `find assets -name '*.bin'`,
# which skips symlinks — must be copied. ~17 MB.
# (If the main checkout has no assets yet, run `make setup` there first.)
if ! ls "$MAIN"/assets/*.bin >/dev/null 2>&1; then
    echo "1080 agent-setup: $MAIN/assets has no .bin files — run 'make setup' in the main checkout first" >&2
    exit 1
fi
mkdir -p assets
cp "$MAIN"/assets/*.bin assets/

# Don't pollute git status with the symlinked toolchain dir.
GIT_EXCLUDE="$(git rev-parse --git-path info/exclude)"
grep -qx "/tools/ido-static-recomp" "$GIT_EXCLUDE" 2>/dev/null || echo "/tools/ido-static-recomp" >> "$GIT_EXCLUDE"
