#!/usr/bin/env bash
# §2 gate (docs/HANDOFF_NEW_MACHINE.md §2) on the landing worktree. Env: LAND_WT (default projects/1080-agent-d), LAND_SCRATCH (log dir).
#: make + cmp, non_matching_objects, refresh-report, exact-set diff vs origin/main, sentinels. Never pushes.
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/home/danjs/code/decomp/tools/build-venv/bin:$PATH"
WT="${LAND_WT:-$SELF_DIR/../projects/1080-agent-d}"
LOG="${LAND_SCRATCH:-${TMPDIR:-/tmp}}/gate-landing"
cd "$WT" || exit 1
echo "== HEAD: $(git log --oneline -1)"
echo "== gate: make"; make RUN_CC_CHECK=0 -j8 >"$LOG-make.log" 2>&1; echo "   make exit=$?"
if cmp tenshoe.z64 baserom.z64; then echo "   ROM: BYTE-IDENTICAL"; else echo "   ROM: !! MISMATCH"; exit 3; fi
echo "== gate: non_matching_objects"
make non_matching_objects RUN_CC_CHECK=0 -j8 >"$LOG-nm.log" 2>&1 || make non_matching_objects RUN_CC_CHECK=0 -j8 >"$LOG-nm.log" 2>&1; echo "   nm exit=$?"
echo "== gate: refresh-report"; bash scripts/refresh-report.sh >"$LOG-report.log" 2>&1; echo "   refresh exit=$?"
git show origin/main:report.json > "$LOG-base-report.json"
python3 - "$LOG-base-report.json" report.json <<'PY'
import json,sys
def exact(p):
    r=json.load(open(p)); return {fn['name'] for u in r['units'] for fn in u.get('functions',[]) if fn.get('fuzzy_match_percent')==100.0}, r['measures']
b,bm=exact(sys.argv[1]); n,nm=exact(sys.argv[2])
print(f"   exact: {bm['matched_functions']}/{bm['total_functions']} -> {nm['matched_functions']}/{nm['total_functions']}  code% {bm.get('matched_code_percent'):.2f} -> {nm.get('matched_code_percent'):.2f}")
lost=sorted(b-n); gained=sorted(n-b)
print(f"   gained: {gained}"); print(f"   LOST: {lost}" if lost else "   lost: none")
r=json.load(open(sys.argv[2])); fz={fn['name']:fn.get('fuzzy_match_percent') for u in r['units'] for fn in u.get('functions',[])}
sent=['gl_func_000551E0','gl_func_00055B10','gl_func_0000EBC8','gl_func_0000C5B0','game_libs_func_00062F08']
print("   sentinels:", {s:fz.get(s) for s in sent})
PY
echo "== done. report.json left modified in $WT for commit; NOT pushed."
