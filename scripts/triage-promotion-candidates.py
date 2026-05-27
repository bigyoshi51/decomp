#!/usr/bin/env python3
"""Triage 90-99% NM wraps by diff class to find tractable promotion candidates.

Runs objdiff against every 90-99% function and classifies the residual diffs:
  - REG_RENUMBER: only operand register names differ (e.g. $t6 vs $t7)
  - JAL_RELOC: only `jal gl_func_*` (reloc-blind diff, usually link-resolvable)
  - SCHEDULE_REORDER: instructions out of order
  - OFFSET_DIFF: lw/sw offsets differ (frame-slot rearrangement)
  - INSN_DIFF: opcode-level diff (insn type changed)
  - MIXED: combination

Heuristic for "easy": single diff class, small diff count, no scheduling reorder.

Run from the project root (where report.json + expected/ live).

USAGE:
  python3 triage-promotion-candidates.py        # default: 90-99% candidates
  python3 triage-promotion-candidates.py --low  # 80-99% candidates (broader)

The --low mode scans more candidates (3-4x runtime) but surfaces additional
struct-assign / reg-renumber opportunities.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPORT = Path("report.json")
PROJECT_ROOT = Path(".")


def parse_args_text(s):
    """Extract argument tokens from an `args_text` string."""
    return re.findall(r"[a-zA-Z_$][\w$]*|\$\w+|-?0x[0-9a-fA-F]+|-?\d+", s or "")


def classify_pair(left, right):
    """Classify a single (left, right) instruction pair diff."""
    li = left.get("instruction", {})
    ri = right.get("instruction", {})
    lf = li.get("formatted", "")
    rf = ri.get("formatted", "")
    if lf == rf:
        return "OK"
    lp = lf.split(None, 1)
    rp = rf.split(None, 1)
    lm = lp[0] if lp else ""
    rm = rp[0] if rp else ""
    if lm != rm:
        return "INSN_DIFF"
    largs = lp[1] if len(lp) > 1 else ""
    rargs = rp[1] if len(rp) > 1 else ""
    # mnemonic same; classify by what differs
    if "jal" in lm and "gl_func_00000000" in largs and "gl_func_00000000" in rargs:
        return "JAL_RELOC"
    if "lui" in lm and "D_00000000" in largs and "D_00000000" in rargs:
        return "JAL_RELOC"
    # Operand-level diff. Check if it's just register names.
    larg_tokens = parse_args_text(largs)
    rarg_tokens = parse_args_text(rargs)

    # If everything matches except register names, REG_RENUMBER
    def regname(tok):
        return (
            tok
            in (
                "zero",
                "at",
                "v0",
                "v1",
                "a0",
                "a1",
                "a2",
                "a3",
                "t0",
                "t1",
                "t2",
                "t3",
                "t4",
                "t5",
                "t6",
                "t7",
                "t8",
                "t9",
                "s0",
                "s1",
                "s2",
                "s3",
                "s4",
                "s5",
                "s6",
                "s7",
                "k0",
                "k1",
                "gp",
                "sp",
                "fp",
                "ra",
            )
            or tok.startswith("f")
            and tok[1:].isdigit()
        )

    diff_regs = []
    diff_other = []
    for ltok, rtok in zip(larg_tokens, rarg_tokens):
        if ltok != rtok:
            if regname(ltok) and regname(rtok):
                diff_regs.append((ltok, rtok))
            else:
                diff_other.append((ltok, rtok))
    if diff_other:
        # offset/literal differences
        for ltok, rtok in diff_other:
            if ltok.startswith("0x") and rtok.startswith("0x"):
                return "OFFSET_DIFF"
        return "INSN_DIFF"
    if diff_regs:
        return "REG_RENUMBER"
    return "INSN_DIFF"


def get_objdiff(unit_path, fn_name):
    expected = f"expected/{unit_path}.c.o"
    built = f"build/non_matching/{unit_path}.c.o"
    if not Path(expected).exists() or not Path(built).exists():
        return None
    out = Path("/tmp/triage_diff.json")
    r = subprocess.run(
        ["objdiff-cli", "diff", "-1", expected, "-2", built, fn_name, "-o", str(out)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    try:
        d = json.load(open(out))
    except Exception:
        return None
    rsym = None
    for s in d.get("right", {}).get("symbols", []):
        if s.get("name") == fn_name:
            rsym = s
            break
    if not rsym:
        return None
    lsym = None
    for s in d.get("left", {}).get("symbols", []):
        if s.get("name") == fn_name:
            lsym = s
            break
    if not lsym:
        return None
    return lsym, rsym


def main():
    low_mode = "--low" in sys.argv
    pct_floor = 80 if low_mode else 90
    r = json.load(open(REPORT))
    candidates = []
    for u in r.get("units", []):
        unit = u.get("name", "")
        for fn in u.get("functions", []):
            fm = fn.get("fuzzy_match_percent")
            sz = int(fn.get("size", 0) or 0)
            n = fn.get("name", "")
            if fm is None:
                continue
            if pct_floor <= fm < 100 and 0x20 <= sz <= 0x100:
                candidates.append((fm, sz, n, unit))
    candidates.sort(reverse=True)
    print(f"Scanning {len(candidates)} candidates...")

    results = []
    for pct, sz, name, unit in candidates[:200]:
        diff = get_objdiff(unit, name)
        if not diff:
            continue
        lsym, rsym = diff
        li = lsym.get("instructions", [])
        ri = rsym.get("instructions", [])
        if len(li) != len(ri):
            results.append((pct, sz, name, "SIZE_DIFF", len(li), len(ri), unit))
            continue
        classes = []
        for lins, rins in zip(li, ri):
            c = classify_pair(lins, rins)
            if c != "OK":
                classes.append(c)
        if not classes:
            continue  # already match
        # categorize
        unique = set(classes)
        if unique == {"JAL_RELOC"}:
            verdict = "JAL_ONLY (likely byte-exact post-link)"
        elif unique == {"REG_RENUMBER"}:
            verdict = f"REG_RENUMBER_ONLY ({len(classes)} diffs)"
        elif unique == {"OFFSET_DIFF"}:
            verdict = f"OFFSET_ONLY ({len(classes)} diffs)"
        elif unique <= {"JAL_RELOC", "REG_RENUMBER"}:
            jc = sum(1 for c in classes if c == "JAL_RELOC")
            rc = sum(1 for c in classes if c == "REG_RENUMBER")
            verdict = f"JAL+REG ({jc}j {rc}r)"
        else:
            verdict = f"MIXED ({len(classes)}: {sorted(unique)})"
        results.append((pct, sz, name, verdict, unit))

    # Sort by tractability: JAL_ONLY first (often post-link byte-exact),
    # then REG_RENUMBER_ONLY w/ few diffs, then OFFSET_ONLY, then MIXED.
    def tract(r):
        v = r[3]
        if "JAL_ONLY" in v:
            return 0
        if "REG_RENUMBER_ONLY" in v:
            try:
                nd = int(re.search(r"(\d+)", v).group(1))
                return 1 + nd * 0.01
            except (AttributeError, ValueError):
                return 2
        if "OFFSET_ONLY" in v:
            try:
                nd = int(re.search(r"(\d+)", v).group(1))
                return 2 + nd * 0.01
            except (AttributeError, ValueError):
                return 3
        if "JAL+REG" in v:
            return 3
        return 4

    results.sort(key=tract)

    # Summary stats by verdict class
    from collections import Counter

    verdict_counts = Counter()
    for r in results:
        v = r[3] if len(r) == 5 else r[3]
        if "JAL_ONLY" in v:
            verdict_counts["JAL_ONLY"] += 1
        elif "REG_RENUMBER_ONLY" in v:
            verdict_counts["REG_RENUMBER_ONLY"] += 1
        elif "OFFSET_ONLY" in v:
            verdict_counts["OFFSET_ONLY"] += 1
        elif "JAL+REG" in v:
            verdict_counts["JAL+REG"] += 1
        elif "MIXED" in v:
            verdict_counts["MIXED"] += 1
        else:
            verdict_counts["OTHER"] += 1
    print("\nSummary by verdict class:")
    for v, n in sorted(verdict_counts.items(), key=lambda x: -x[1]):
        print(f"  {v:24} {n:>4}")

    print("\nTop 30 promotion candidates by tractability:\n")
    print(f"{'PCT':>7} {'SIZE':>5} {'NAME':<40} {'VERDICT':<35} UNIT")
    for r in results[:30]:
        if len(r) == 7:
            pct, sz, name, verdict, ll, rl, unit = r
            print(
                f"{pct:7.2f} {sz:5d} {name:<40} {verdict:<35} {unit} (sizes {ll},{rl})"
            )
        else:
            pct, sz, name, verdict, unit = r
            print(f"{pct:7.2f} {sz:5d} {name:<40} {verdict:<35} {unit}")


if __name__ == "__main__":
    main()
