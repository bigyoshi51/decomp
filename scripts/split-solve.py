#!/usr/bin/env python3
"""split-solve.py -- decode IDO 7.1 uopt's SPLIT-REJECTION phase.

The inverse-coloring solver (scripts/coloring-solve.py) models the GLOBAL
priority-coloring phase. Some renumber residuals are decided EARLIER/inside,
in globalcolor's per-LR SPLIT decision: when a live range's own value
(adjsave*span) is no greater than the cheapest register's cost, the LR is
SPLIT (uoptreg2.c:2144 `if (adjsave*unk1C <= best) split(...)`). The split
piece that falls out has its OWN compute_save/adjsave SIGN test
(uoptreg2.c:1400). If that sign is <=0 the piece is REJECTED ("not colored
(-ve save)") and ugen binds the value at translate-time to the first
available v-reg -- the $v1-vs-$a2 carrier class (gl_func_00035834, _525F0).

This tool reads a build's -Wo,-zdbug:6 (optionally +-dowhyuncolor) trace and:
  1. Finds every LR that was SPLIT (`live range B: B split out S`).
  2. For each, reports the outcome of BOTH pieces (colored R / rejected).
  3. Classifies split-rejection (BOTH pieces -ve save) vs ordinary
     wrong-carrier (split worked, R != target).
  4. With -dowhyuncolor, reports WHY rejected: sparse (savings<=move
     penalty), notwellformed, 0occur, calloverhead -- the adjsave inputs.
  5. Prescribes the source change to flip the adjsave sign of the no-call
     piece (the levers in docs/IDO_CODEGEN.md SPLIT-REJECTION PHASE).

Function-agnostic. Inputs:
  --trace      a -Wo,-zdbug:6 uoptlist (the current build's coloring)
  --func       function symbol to isolate (optional; default: whole trace)
  --reg-of B   (repeatable) the carrier register the TARGET uses for LR
               bitpos B, e.g. --reg-of 0=a2  to state "target puts LR 0 in a2"

Run the trace with:
  cc ... -Wo,-zdbug:6 -Wo,-dowhyuncolor file.c   (writes ./uoptlist)

The adjsave model (compute_save, uoptreg2.c:1400):
  adjsave = totalsave / span    (x2 if double)
  totalsave = sum over liveunits of:
     (load_count+store_count)*freq                         [+ savings]
     - movcost*freq  if needreglod & (loopfirst|!canmoverlod)  [reload pen]
     - movcost*freq  if hasstore & !deadout & needregsave & .. [storeback]
  span = #liveunits + card(reachingbbs), compressed (n>2 -> (n-2)/4+2)
  REJECT (unk23=2, "-ve save") iff adjsave <= 0.
  whyuncolored (with -dowhyuncolor) buckets the rejection:
    sparse        : savings (sum (ld+st)*freq) <= move-penalty
    notwellformed : freq*1.5 < move-penalty  (penalty dwarfs total freq)
    0occur        : no loads/stores at all
    calloverhead  : split piece collapsed (took all liveunits)
"""

import argparse
import re
import sys

REGNAMES = {
    0: "uncolored",
    1: "v0",
    2: "v1",
    3: "a0",
    4: "a1",
    5: "a2",
    6: "a3",
    7: "t0",
    8: "t1",
    9: "t2",
    10: "t3",
    11: "t4",
    12: "t5",
    13: "ra",
    14: "s0",
    15: "s1",
    16: "s2",
    17: "s3",
    18: "s4",
    19: "s5",
    20: "s6",
    21: "s7",
    22: "fp",
    23: "ra_ee",
    24: "f0",
    25: "f2",
    26: "f12",
    27: "f14",
    28: "f16",
    29: "f18",
    30: "f20",
    31: "f22",
    32: "f24",
    33: "f26",
    34: "f28",
    35: "f30",
}
NAME2CODE = {v: k for k, v in REGNAMES.items()}


def regname(c):
    return REGNAMES.get(c, "r%d" % c)


SPLIT_RE = re.compile(r"^\s*live range\s+(\d+):\s*(\d+)\s+split out\s+(\d+)\s*$")
NOCOLOR_RE = re.compile(r"^\s*(\d+):\s*(\d+)\s+not colored \(-ve save\)\s*$")
ASSIGN_RE = re.compile(
    r"^\s*(\d+):\s*(\d+)\s+assigned\s+\((constrained|unconstrained)\)\s+(\d+)\s*$"
)
NOTSPLIT_RE = re.compile(r"^\s*(\d+):\s*(\d+)\s+not colored, not splittable\s*$")
ITAB_RE = re.compile(
    r"^\s*\{\s*(\d+)\|\s*\d+\}\s+(\d+)\s+(isvar|isop)\s+(?:([PMR])\s+)?(\S+)(.*)$"
)
LOCALOPT_RE = re.compile(r"SECONDS IN LOCAL OPTIMIZATION OF (\S+)")
GLOBALCOLOR_RE = re.compile(r"SECONDS IN global coloring of (\S+)")
TRAILER_KEYS = (
    "numlr",
    "finalnumlr",
    "numsplitlu",
    "numcoloredlr",
    "num0occurlr",
    "numsparselr",
    "numnotwellformedlr",
    "numcalloverheadlr",
    "numcantcoloredlr",
)


def slice_func(lines, func):
    """Return (start,end) line indices for `func`'s region, or whole file."""
    if not func:
        return 0, len(lines)
    lo = hi = None
    for i, ln in enumerate(lines):
        m = LOCALOPT_RE.search(ln)
        if m and m.group(1) == func:
            lo = i
        m = GLOBALCOLOR_RE.search(ln)
        if m and m.group(1) == func and lo is not None:
            hi = i
            break
    if lo is None or hi is None:
        sys.exit(
            "func %s not found in trace (need LOCAL OPT + global coloring markers)"
            % func
        )
    # include the trailer block right after the global-coloring marker
    return lo, min(len(lines), hi + 60)


def parse_itab(lines, lo, hi):
    """bitpos -> dict(ichain, kind, cls, op, operands)."""
    itab = {}
    for j in range(lo, hi):
        m = ITAB_RE.match(lines[j])
        if m:
            ichain, bit, kind, cls, op, rest = (
                int(m.group(1)),
                int(m.group(2)),
                m.group(3),
                m.group(4) or "",
                m.group(5),
                m.group(6).strip(),
            )
            itab.setdefault(
                bit, dict(ichain=ichain, kind=kind, cls=cls, op=op, operands=rest)
            )
    return itab


def parse_decisions(lines, lo, hi):
    splits = []  # (parent_bit, parent_lr, child_lr)
    outcomes = {}  # lr_bit -> ('reject'|'assign'|'notsplit', reg_or_None, ichain_bit)
    trailer = {}
    for j in range(lo, hi):
        ln = lines[j]
        m = SPLIT_RE.match(ln)
        if m:
            splits.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
            continue
        m = NOCOLOR_RE.match(ln)
        if m:
            outcomes[int(m.group(2))] = ("reject", None, int(m.group(1)))
            continue
        m = ASSIGN_RE.match(ln)
        if m:
            outcomes[int(m.group(2))] = ("assign", int(m.group(4)), int(m.group(1)))
            continue
        m = NOTSPLIT_RE.match(ln)
        if m:
            outcomes[int(m.group(2))] = ("notsplit", None, int(m.group(1)))
            continue
        for k in TRAILER_KEYS:
            tm = re.search(r"\b" + k + r"=\s*(\d+)", ln)
            if tm:
                trailer[k] = int(tm.group(1))
    return splits, outcomes, trailer


def fmt_outcome(o):
    if o is None:
        return "(no outcome line -- colored in main loop / unconstrained-OK)"
    kind, reg, _ = o
    if kind == "reject":
        return "REJECTED (-ve save) -> ugen binds at translate (first free v-reg)"
    if kind == "assign":
        return "COLORED -> %s (code %d)" % (regname(reg), reg)
    if kind == "notsplit":
        return "REJECTED, not splittable"
    return str(o)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--trace", default="uoptlist")
    ap.add_argument("--func", default=None)
    ap.add_argument(
        "--reg-of",
        action="append",
        default=[],
        help="B=reg : target's carrier for LR bitpos B (e.g. 0=a2)",
    )
    args = ap.parse_args()

    want = {}
    for spec in args.reg_of:
        b, _, r = spec.partition("=")
        want[int(b)] = NAME2CODE.get(r.strip(), None)

    lines = open(args.trace, errors="replace").read().splitlines()
    lo, hi = slice_func(lines, args.func)
    itab = parse_itab(lines, lo, hi)
    splits, outcomes, trailer = parse_decisions(lines, lo, hi)

    print("=== split-solve: %s ===" % (args.func or "whole trace"))
    print(
        "trailer:",
        " ".join("%s=%s" % (k, trailer[k]) for k in TRAILER_KEYS if k in trailer),
    )
    nsplit = trailer.get("numsplitlu", 0)
    nsparse = trailer.get("numsparselr", 0)
    print(
        "splits seen in trace:",
        len(splits),
        "| numsplitlu=%d numsparselr=%d" % (nsplit, nsparse),
    )

    # All colorings -- so you can see WHICH LR carries the contested value,
    # which may NOT be the split LR (the split is often on a cross-call ARG,
    # while the contested value is an M-local colored by lowest-free-reg).
    print("all coloring outcomes (LR bitpos -> result):")
    for lr in sorted(outcomes):
        kind, reg, ich = outcomes[lr]
        info = itab.get(lr, itab.get(ich, {}))
        tag = "%s%s" % (
            info.get("cls", ""),
            (" " + info.get("op", "")) if info.get("op") else "",
        )
        print("   LR %-4d %-50s [%s]" % (lr, fmt_outcome(outcomes[lr]), tag.strip()))
    print()
    print("NOTE: the contested register (your target's carrier) may belong to an")
    print("LR that was COLORED by lowest-free-reg, not to the split LR. If the")
    print("split LR is a cross-call ARG (cls P) and your value is an M-local,")
    print("the residual is a lowest-free-reg tie (coloring-solve.py), and the")
    print("split-rejection is incidental. To move the value off the low reg you")
    print("must FORBID that reg (an interfering LR colored there) -- usually no")
    print("structure-preserving C handle exists if it's the sole reg-wanting value.")
    print()

    if not splits:
        print("NO live-range splits in this function. Not a split-rejection cap.")
        print("If a value is in the wrong register here, it's an ordinary coloring-")
        print("order / lowest-free-reg issue -- use scripts/coloring-solve.py.")
        return

    for parent_bit, parent_lr, child_lr in splits:
        info = itab.get(parent_bit, {})
        print(
            "LR bitpos %d (ichain %s, %s %s %s) SPLIT -> child LR %d"
            % (
                parent_bit,
                info.get("ichain", "?"),
                info.get("kind", ""),
                info.get("cls", ""),
                info.get("op", ""),
                child_lr,
            )
        )
        o_parent = outcomes.get(parent_lr)
        o_child = outcomes.get(child_lr)
        print("   original piece (LR %d): %s" % (parent_lr, fmt_outcome(o_parent)))
        print("   split-out piece (LR %d): %s" % (child_lr, fmt_outcome(o_child)))

        both_reject = (
            o_parent
            and o_parent[0] in ("reject", "notsplit")
            and o_child
            and o_child[0] in ("reject", "notsplit")
        )
        any_assign = (o_parent and o_parent[0] == "assign") or (
            o_child and o_child[0] == "assign"
        )

        if both_reject:
            print("   >>> SPLIT-REJECTION CLASS: both pieces -ve save.")
            print("       Mechanism (compute_save, uoptreg2.c:1400): each piece's")
            print("       savings (sum (ld+st)*freq) <= its move penalty")
            if nsparse:
                print(
                    "       (-dowhyuncolor: numsparselr=%d confirms savings<=penalty)."
                    % nsparse
                )
            tgt = want.get(parent_bit)
            if tgt is not None:
                print(
                    "       TARGET carries this value in %s (code %d) -- so the"
                    % (regname(tgt), tgt)
                )
                print("       target's split produced a COLORABLE no-call piece there.")
            print("       PRESCRIPTION (flip adjsave sign of the no-call sub-range):")
            print(
                "        1. Give the no-call path its own def (firstisstr seed) so the"
            )
            print(
                "           BFS seeds the no-call piece: add an explicit store of the"
            )
            print("           value on the path that does NOT cross the call.")
            print(
                "        2. Shorten the call-crossing piece: don't keep the value live"
            )
            print(
                "           across the later call(s) -- compute the post-call result as"
            )
            print("           a fresh short LR instead of reloading the same value.")
            print("        3. Add a no-call USE so adjsave*span > best and it colors")
            print("           WITHOUT splitting (a real read emitting a load).")
            print(
                "       NOT a coloring-order change; this is upstream of color choice."
            )
        elif any_assign:
            print("   >>> ordinary split (a piece COLORED). If carrier != target,")
            print("       it's lowest-free-reg / bitpos -- use coloring-solve.py.")
        print()


if __name__ == "__main__":
    main()
