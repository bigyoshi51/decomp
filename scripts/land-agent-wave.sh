#!/usr/bin/env bash
# Landing ritual (docs/HANDOFF_NEW_MACHINE.md §3) minus the push. usage: scripts/land-agent-wave.sh <hash>...
# Env: LAND_WT (landing worktree, default projects/1080-agent-d), LAND_SCRATCH (log dir), NO_RESET=1 (pick onto the current tree).
# Baseline routes per unit live in regen_unit(); see docs/MATCHING_WORKFLOW.md "#game-libs-fake-param-exact-sweep-agent-c".
# reset agent-d to origin/main, cherry-pick each hash (-X union),
# regenerate expected/<unit>.o for any conflicting binary via the unit's correct baseline route, then gate.
# A conflicting non-.o file aborts (needs a human). Never pushes.
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/home/danjs/code/decomp/tools/build-venv/bin:$PATH"
WT="${LAND_WT:-$SELF_DIR/../projects/1080-agent-d}"
S="${LAND_SCRATCH:-${TMPDIR:-/tmp}}"
cd "$WT" || exit 1
if [ "${NO_RESET:-0}" != 1 ]; then
  git fetch origin --quiet; git cherry-pick --abort 2>/dev/null; git checkout -q -B agent-d origin/main || exit 1
fi
echo "== base: $(git log --oneline -1 | cut -c1-80)"
strip_c() {  # strip decomp bodies from $1 (a .c) for a pure-INCLUDE_ASM baseline build
  python3 - "$1" <<'PY'
import importlib.util,sys
spec=importlib.util.spec_from_file_location("reb","scripts/refresh-expected-baseline.py"); reb=importlib.util.module_from_spec(spec); spec.loader.exec_module(reb)
p=sys.argv[1]; new,n=reb.strip_decomp_in_file(open(p).read(), reb.func_map(), None); open(p,'w').write(new); print('   stripped',n,'bodies')
PY
}
regen_unit() {  # $1 = expected/src/<seg>/<unit>.c.o
  local o="$1"; local c="${o#expected/}"; c="${c%.o}"; local b="build/${c}.o"
  echo "   regenerating baseline for $c"
  case "$c" in
    *game_libs_post1b.c)   # committed baseline = ROM-exact C-BUILD object (donor jal relocs)
      echo "   (post1b: C-build route)"; rm -f "$b"; make "$b" RUN_CC_CHECK=0 >"$S/regen-make.log" 2>&1 || { echo "   !! C-build failed"; tail -5 "$S/regen-make.log"; return 1; }
      cp "$b" "$o"; git add "$o" "$c"; return 0;;
    *src/game_libs/game_libs.c|*src/game_libs/game_libs_post1c.c)   # strip route with donor splicing BLANKED (tracked baselines carry 0 relocs)
      echo "   (game_libs.c: strip + EXPECTED_BASELINE=1 REPLACE_FUNC_BODY= route)"; cp "$c" "$S/regen-keep.c"; strip_c "$c"
      rm -f "$b"; make "$b" RUN_CC_CHECK=0 EXPECTED_BASELINE=1 REPLACE_FUNC_BODY= >"$S/regen-make.log" 2>&1 || { echo "   !! baseline make failed"; tail -5 "$S/regen-make.log"; cp "$S/regen-keep.c" "$c"; return 1; }
      cp "$b" "$o"; cp "$S/regen-keep.c" "$c"; rm -f "$b"; git add "$o" "$c"; return 0;;
  esac
  # default (tail, post, post0b, timproc_b5, arcproc, USOs): strip route, donors ACTIVE
  cp "$c" "$S/regen-keep.c"; strip_c "$c"
  rm -f "$b"; make "$b" RUN_CC_CHECK=0 EXPECTED_BASELINE=1 >"$S/regen-make.log" 2>&1 || { echo "   !! baseline make failed"; tail -5 "$S/regen-make.log"; cp "$S/regen-keep.c" "$c"; return 1; }
  cp "$b" "$o"; cp "$S/regen-keep.c" "$c"; rm -f "$b"; git add "$o" "$c"
}
for h in "$@"; do
  if ! git cherry-pick -X union "$h" >"$S/regen-pick.log" 2>&1; then
    bad=$(git diff --name-only --diff-filter=U | grep -v '^expected/.*\.o$')
    if [ -n "$bad" ]; then echo "!! non-.o conflict picking $h:"; echo "$bad"; git status --porcelain | grep '^UU'; exit 2; fi
    for o in $(git diff --name-only --diff-filter=U); do regen_unit "$o" || exit 3; done
    git -c core.editor=true cherry-pick --continue >/dev/null 2>&1 || { echo "!! continue failed"; git status --porcelain | head; exit 4; }
  fi
  echo "== picked: $(git log --oneline -1 | cut -c1-80)"
done
exec "$SELF_DIR/gate-landing-tree.sh"
