#!/usr/bin/env bash
# Create a parallel agent worktree for a decomp project.
#
# Usage:
#   scripts/spin-up-agent.sh <project> [letter]
#
# Picks the next free agent letter (a..z) if not given. Creates a git worktree
# at projects/<prefix>-agent-<letter>/ on branch agent-<letter> (forked from
# main), then runs the project's .agent-setup snippet to symlink toolchain
# dirs, copy assets, etc.
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <project-name> [letter]" >&2
    echo "  project-name: a directory under projects/ (e.g., '1080 Snowboarding (USA)')" >&2
    exit 2
fi

PROJECT="$1"
LETTER="${2:-}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
PROJECT_DIR="$REPO_ROOT/projects/$PROJECT"

if [[ ! -d "$PROJECT_DIR" ]]; then
    echo "Project not found: $PROJECT_DIR" >&2
    exit 1
fi

# Worktree dirs are named after the project's first whitespace-delimited token
# (e.g. "1080" from "1080 Snowboarding (USA)"). Override with $WORKTREE_PREFIX.
PREFIX="${WORKTREE_PREFIX:-${PROJECT%% *}}"

if [[ -z "$LETTER" ]]; then
    EXISTING_WT=$(git -C "$PROJECT_DIR" worktree list --porcelain | grep -oP "${PREFIX}-agent-\K[a-z]" || true)
    EXISTING_BR=$(git -C "$PROJECT_DIR" for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/ \
                  | grep -oP 'agent-\K[a-z]$' || true)
    USED=$(printf '%s\n%s\n' "$EXISTING_WT" "$EXISTING_BR" | sort -u | grep -v '^$' || true)
    for L in {a..z}; do
        if ! grep -qx "$L" <<< "$USED"; then
            LETTER="$L"
            break
        fi
    done
    if [[ -z "$LETTER" ]]; then
        echo "No free agent letters." >&2
        exit 1
    fi
fi

WORKTREE_NAME="${PREFIX}-agent-${LETTER}"
WORKTREE_PATH="$REPO_ROOT/projects/$WORKTREE_NAME"
BRANCH="agent-${LETTER}"

if [[ -e "$WORKTREE_PATH" ]]; then
    echo "Worktree path already exists: $WORKTREE_PATH" >&2
    exit 1
fi

echo ">>> Creating worktree $WORKTREE_PATH on branch $BRANCH"
if git -C "$PROJECT_DIR" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$PROJECT_DIR" worktree add "$WORKTREE_PATH" "$BRANCH"
else
    git -C "$PROJECT_DIR" worktree add "$WORKTREE_PATH" -b "$BRANCH" main
fi

SETUP="$REPO_ROOT/scripts/agent-setups/${PREFIX}.sh"
if [[ -f "$SETUP" ]]; then
    echo ">>> Running $SETUP"
    (cd "$WORKTREE_PATH" && bash "$SETUP")
else
    echo "(no $SETUP — skipping project-specific setup)"
fi

echo
echo "Worktree ready: $WORKTREE_PATH"
echo "Branch:         $BRANCH"
echo
echo "  cd \"$WORKTREE_PATH\""
