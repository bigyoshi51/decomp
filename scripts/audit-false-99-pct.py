#!/usr/bin/env python3
"""Find functions where report.json says <100% fuzzy but byte_verify passes.

These are "false 99% caps" — the .o has reloc-table differences (extra
R_MIPS_26 / R_MIPS_HI16 / R_MIPS_LO16 entries our build emits but the
expected/.o doesn't), but the .text bytes are identical. Such functions
match at ROM level even though objdiff scores them <100.

Usage (from a 1080-agent-<letter> worktree):
    python3 scripts/audit-false-99-pct.py [--min-pct 99]

Output: one line per function — name, report fuzzy, size, episode-status.
Functions with no episode yet are landing candidates: log an episode then
run scripts/land-successful-decomp.sh as usual; the land script's
byte_verify will accept them.
"""

import argparse
import glob
import json
import os
import re
import subprocess


def func_bytes(objfile, symbol):
    """Extract a function's .text bytes from an .o by symbol address+size.

    Reads the size from the symbol table entry (skips UND entries with
    size 0 — those would produce bogus byte slices using a callsite-
    supplied size that doesn't correspond to a real function body).
    Mirrors land-successful-decomp.sh's byte_verify size-discovery."""
    try:
        tab = subprocess.check_output(
            ["mips-linux-gnu-objdump", "-t", objfile], stderr=subprocess.DEVNULL
        ).decode()
    except subprocess.CalledProcessError:
        return None
    for line in tab.split("\n"):
        parts = line.split()
        if not parts or parts[-1] != symbol:
            continue
        if "*UND*" in line:
            continue
        try:
            addr = int(parts[0], 16)
        except ValueError:
            continue
        size = None
        for p in parts[2:]:
            if len(p) != 8 or not all(c in "0123456789abcdef" for c in p):
                continue
            s = int(p, 16)
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


def find_obj_root(name):
    """Mirror land-script logic: route to build/non_matching if src has
    INCLUDE_ASM(name), else build/."""
    pat = re.compile(rf"INCLUDE_ASM\([^)]*\b{re.escape(name)}\b")
    for src in glob.glob("src/**/*.c", recursive=True):
        try:
            if pat.search(open(src).read()):
                return "build/non_matching"
        except (OSError, UnicodeDecodeError):
            continue
    return "build"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--min-pct",
        type=float,
        default=99.0,
        help="Only consider functions with report fuzzy >= this",
    )
    args = ap.parse_args()

    with open("report.json") as f:
        report = json.load(f)

    candidates = []
    for unit in report.get("units", []):
        for fn in unit.get("functions", []):
            pct = fn.get("fuzzy_match_percent")
            size = int(fn.get("size", 0) or 0)
            name = fn.get("name", "")
            if pct is None or pct >= 100.0 or pct < args.min_pct:
                continue
            if size == 0 or size > 0x400:
                continue
            candidates.append((name, size, pct))

    matches = []
    for name, size, pct in candidates:
        root = find_obj_root(name)
        for base_o in glob.glob(f"{root}/src/**/*.c.o", recursive=True):
            rel = os.path.relpath(base_o, root)
            exp_o = os.path.join("expected", rel)
            if not os.path.exists(exp_o):
                continue
            ba = func_bytes(base_o, name)
            if ba is None:
                continue
            ea = func_bytes(exp_o, name)
            if ea is None:
                continue
            if ba == ea:
                has_ep = os.path.exists(f"episodes/{name}.json")
                matches.append((name, pct, size, has_ep))
            break

    no_ep = [m for m in matches if not m[3]]
    with_ep = [m for m in matches if m[3]]

    print(
        f"# False 99% caps found: {len(matches)} "
        f"({len(no_ep)} without episode, {len(with_ep)} already logged)"
    )
    print()
    if no_ep:
        print("# LANDABLE (no episode yet — log episode + run land script):")
        for name, pct, size, _ in sorted(no_ep, key=lambda x: -x[1]):
            print(f"  {name}  fuzzy={pct:.4f}  size={size}")
    if with_ep:
        print()
        print("# Already landed (episode exists; 99% is just reloc-noise):")
        for name, pct, size, _ in sorted(with_ep, key=lambda x: -x[1])[:5]:
            print(f"  {name}  fuzzy={pct:.4f}  size={size}")
        if len(with_ep) > 5:
            print(f"  ... +{len(with_ep) - 5} more")


if __name__ == "__main__":
    main()
