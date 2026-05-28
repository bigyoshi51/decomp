#!/usr/bin/env python3
"""Bucket 95-99.99% NM near-misses by .text diff class.

For each near-miss function (report.json fuzzy in [min_pct, 100)), extract
the built vs expected .text bytes and classify the differing words:

  JAL-RELOC-NOISE : all diffs are `jal` words (op=3). Almost always an
                    ALREADY-MATCHED function — our .o carries an R_MIPS_26
                    reloc (jal 0) while expected/.o has the resolved target
                    baked in. objdiff (reloc-aware) scores these matched;
                    the raw-byte compare here does NOT apply relocs, so it
                    shows a false diff. Verify with `objdiff-cli` / report.json,
                    not this tool, for jal-only cases.
  SP-LAYOUT       : all diffs are sp-relative addiu/load/store (stack-slot
                    or frame-size). Declaration-order / frame-pack cap; the
                    permuter normalizes sp offsets so it can't help. Usually
                    a permanent NM cap (see gl_func_00008A40 doc).
  FP-OPERAND      : all diffs are COP1 ops (op=0x11). Typically mul.s/add.s
                    fresh-temp operand-order — IDO canonicalizes fs/ft
                    regardless of C operand order. Permuter-immune cap.
  REG-RENUMBER    : all diffs are SPECIAL (op=0) same-funct, differing only
                    in register fields. $a/$s-class picks are deterministic
                    on IDO's allocator — permuter-immune. $t-class in
                    pointer-arith CAN sometimes crack via shape-changing
                    permuter mutations (rare).
  MIXED           : anything else — includes delay-slot-fill choices,
                    branch-distance (often leaf-branch-past-end), structural
                    arg-handling diffs, AND jal-reloc-noise mixed with 1 real
                    diff. Inspect individually; most are documented caps.

Usage (from a 1080-agent-<letter> worktree, after building the NM objects):
    make RUN_CC_CHECK=0 build/non_matching/...   # build the .o's you care about
    python3 scripts/triage-nearmiss-diffclass.py [--min-pct 95] [--max-size 256]

Prints the bucket histogram + the low-diff-count members of each bucket
(those are the only plausible single-tick C-fix candidates; high-diff-count
members are structural and need multi-tick work or are already capped).
"""

import argparse
import glob
import json
import os
import re
import struct
import subprocess


def func_text(objfile, symbol):
    try:
        tab = subprocess.check_output(
            ["mips-linux-gnu-objdump", "-t", objfile], stderr=subprocess.DEVNULL
        ).decode()
    except subprocess.CalledProcessError:
        return None
    for line in tab.split("\n"):
        p = line.split()
        if not p or p[-1] != symbol or "*UND*" in line:
            continue
        try:
            addr = int(p[0], 16)
        except ValueError:
            continue
        size = None
        for pi in p[2:]:
            if len(pi) == 8 and all(c in "0123456789abcdef" for c in pi):
                s = int(pi, 16)
                if 0 < s < 0x100000:
                    size = s
                    break
        if size is None:
            continue
        try:
            text = subprocess.check_output(
                [
                    "mips-linux-gnu-objcopy",
                    "-O",
                    "binary",
                    "--only-section=.text",
                    objfile,
                    "/dev/stdout",
                ],
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            return None
        return text[addr : addr + size]
    return None


def find_pair(name):
    for root in ("build/non_matching", "build"):
        for o in glob.glob(f"{root}/src/**/*.c.o", recursive=True):
            try:
                tab = subprocess.check_output(
                    ["mips-linux-gnu-objdump", "-t", o], stderr=subprocess.DEVNULL
                ).decode()
            except subprocess.CalledProcessError:
                continue
            for line in tab.split("\n"):
                p = line.split()
                if p and p[-1] == name and "*UND*" not in line:
                    exp = "expected/" + os.path.relpath(o, root)
                    if os.path.exists(exp):
                        return o, exp
    return None, None


_SRC_CACHE = None


def _has_nm_body(name):
    """True if some src/*.c has a `#ifdef NON_MATCHING` block containing a
    definition of `name(` — i.e. there's a real C body to apply the CSE-bust
    lever to. Filters out bare-INCLUDE_ASM / structural-pass-comment-only
    functions that the byte heuristic flags spuriously."""
    global _SRC_CACHE
    if _SRC_CACHE is None:
        _SRC_CACHE = {}
        for src in glob.glob("src/**/*.c", recursive=True):
            try:
                _SRC_CACHE[src] = open(src).read()
            except OSError:
                pass
    pat = re.compile(rf"\b{re.escape(name)}\s*\(")
    for txt in _SRC_CACHE.values():
        for m in re.finditer(
            r"#ifdef NON_MATCHING(.*?)#(?:else|endif)", txt, re.DOTALL
        ):
            if pat.search(m.group(1)):
                return True
    return False


def classify(diffs):
    def op(w):
        return w >> 26

    def rs(w):
        return (w >> 21) & 0x1F

    def is_sp(w):
        # addiu/lw/sw/lwc1/swc1/ldc1/sdc1 with base = $sp(29)
        return op(w) in (9, 0x23, 0x2B, 0x31, 0x39, 0x35, 0x3D) and rs(w) == 29

    if all(op(x) == 3 for _, x, _ in diffs):
        return "JAL-RELOC-NOISE"
    if all(is_sp(x) for _, x, _ in diffs):
        return "SP-LAYOUT"
    if all(op(x) == 0x11 for _, x, _ in diffs):
        return "FP-OPERAND"
    if all(op(x) == 0 and op(y) == 0 and (x & 0x3F) == (y & 0x3F) for _, x, y in diffs):
        return "REG-RENUMBER"
    return "MIXED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pct", type=float, default=95.0)
    ap.add_argument("--max-size", type=lambda s: int(s, 0), default=0x100)
    args = ap.parse_args()

    with open("report.json") as f:
        report = json.load(f)

    names = []
    for u in report.get("units", []):
        for fn in u.get("functions", []):
            pct = fn.get("fuzzy_match_percent")
            sz = int(fn.get("size", 0) or 0)
            n = fn.get("name", "")
            if pct is None or pct < args.min_pct or pct >= 100:
                continue
            if sz == 0 or sz > args.max_size:
                continue
            names.append(n)

    from collections import Counter, defaultdict

    buckets = Counter()
    members = defaultdict(list)
    # Structural (size-mismatch) candidates are the genuinely C-fixable vein:
    # built .text size != target. The CSE-bust sub-class (expected has an
    # extra `lui ...,0x0` for a global load our C CSE-folds into a saved reg)
    # is the reliably-fixable one — see gl_func_00039C8C (landed 2026-05-28 via
    # extern char D_<fn>_<n>; =0x0 in undefined_syms_auto.txt as a distinct base).
    cse_bust = []
    structural = []
    for n in names:
        o, exp = find_pair(n)
        if not o:
            buckets["NOT-BUILT"] += 1
            continue
        b = func_text(o, n)
        e = func_text(exp, n)
        if b is None or e is None:
            buckets["NOT-BUILT"] += 1
            continue
        if len(b) != len(e):
            buckets["SIZE-MISMATCH(structural)"] += 1
            structural.append((n, len(e) - len(b)))
            # CSE-bust heuristic: expected has more `lui rX, 0x0` words than ours
            elui = sum(
                1
                for i in range(0, len(e), 4)
                if (struct.unpack(">I", e[i : i + 4])[0] >> 26) == 0x0F
                and (struct.unpack(">I", e[i : i + 4])[0] & 0xFFFF) == 0
            )
            olui = sum(
                1
                for i in range(0, len(b), 4)
                if (struct.unpack(">I", b[i : i + 4])[0] >> 26) == 0x0F
                and (struct.unpack(">I", b[i : i + 4])[0] & 0xFFFF) == 0
            )
            if elui > olui and _has_nm_body(n):
                cse_bust.append((n, len(e) - len(b)))
            continue
        diffs = []
        for i in range(0, min(len(b), len(e)), 4):
            x = struct.unpack(">I", b[i : i + 4])[0]
            y = struct.unpack(">I", e[i : i + 4])[0]
            if x != y:
                diffs.append((i, x, y))
        if not diffs:
            buckets["EXACT(.text)"] += 1
            continue
        c = classify(diffs)
        buckets[c] += 1
        members[c].append((n, len(diffs)))

    print(
        f"# Near-miss diff-class breakdown (fuzzy {args.min_pct}-99.99, "
        f"size<=0x{args.max_size:X})"
    )
    for k, v in buckets.most_common():
        print(f"  {k}: {v}")
    print("\n# Same-size diff buckets — low-diff members (mostly caps, inspect):")
    for c in ("MIXED", "REG-RENUMBER", "FP-OPERAND", "SP-LAYOUT"):
        ms = sorted(members.get(c, []), key=lambda x: x[1])[:10]
        if ms:
            print(f"  [{c}] " + ", ".join(f"{n}({d})" for n, d in ms))
    if structural:
        print("\n# SIZE-MISMATCH (structural, C-fixable vein). +N=missing N/4 insns:")
        print(
            "  "
            + ", ".join(
                f"{n}({d:+d})"
                for n, d in sorted(structural, key=lambda x: abs(x[1]))[:20]
            )
        )
    if cse_bust:
        print(
            "\n# *** CSE-BUST candidates (expected has extra `lui rX,0` — "
            "MOST LIKELY FIXABLE, like gl_func_00039C8C): ***"
        )
        print("  " + ", ".join(f"{n}({d:+d})" for n, d in cse_bust))


if __name__ == "__main__":
    main()
