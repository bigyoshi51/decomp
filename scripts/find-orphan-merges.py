#!/usr/bin/env python3
"""find-orphan-merges.py — surface landable stolen-prologue orphan merges.

A 1080 splat artifact: tiny "orphan" .s files (1-3 .word lines, NO `jr $ra`
= 0x03E00008) are the stolen leading instruction(s) of the NEXT function. The
successor then reads a register the orphan set, so it LOOKS caller-set but is a
stolen-prologue victim. Merging the orphan back into the successor's .s + promoting
the successor's NM wrap to a plain def yields a byte-exact match — IFF the
successor's existing C already compiles to produce the orphan's leading words
(`build[k:] == expected`, k = orphan word count). That happens when the C reads
the orphan's global early so IDO schedules the lui/lw pre-prologue.

This script lists the LANDABLE pairs: orphan .s adjacent (by VRAM) to a successor
that is a 90-99% NM wrap whose `build[k:] == expected` byte-for-byte. Run from a
1080 project/worktree dir (needs build/non_matching/, expected/, report.json).

History: the orphan vein was cracked 2026-05-25 (gl_func_0001FCD0, gl_func_0002D620,
titproc_uso_func_00001C68 landed). See docs/MATCHING_WORKFLOW.md and the
project_1080_orphan_fn_prologue_vein memo. The earlier predecessor-tail gate via
the EXPECTED .o symbol order was BUGGY (it skips orphan .s); .s-adjacency is the
truth. Fresh-decode successors (no NM wrap) usually FAIL (pre-prologue cap), so
this only reports successors that ALREADY have an NM wrap in the 90-99% band.
"""

import glob
import json
import os
import re
import subprocess
import sys


def func_words(o, name):
    """Return list of 8-hex-digit instruction words for `name` in object `o`."""
    try:
        d = subprocess.check_output(
            ["mips-linux-gnu-objdump", "-d", o], stderr=subprocess.DEVNULL
        ).decode()
    except Exception:
        return None
    out, seen = [], False
    for line in d.splitlines():
        if "<%s>:" % name in line:
            seen = True
            continue
        if seen:
            if re.match(r"^[0-9a-f]+ <", line):
                break
            m = re.match(r"\s*[0-9a-f]+:\s+([0-9a-f]{8})", line)
            if m:
                out.append(m.group(1))
    return out


def main():
    if not os.path.exists("report.json"):
        sys.exit("run from a 1080 project dir (no report.json here)")
    rpt = json.load(open("report.json"))
    pct = {
        fn["name"]: (fn.get("fuzzy_match_percent", 0), u["name"])
        for u in rpt["units"]
        for fn in u.get("functions", [])
    }
    landable = []
    for segdir in glob.glob("asm/nonmatchings/*/*"):
        if not os.path.isdir(segdir):
            continue
        segs = {}
        for s in glob.glob(segdir + "/*.s"):
            if "_pad" in s:
                continue
            ws = [w for w in open(s) if ".word" in w]
            if not ws:
                continue
            m = re.search(r"/\* [0-9A-Fa-f]+ ([0-9A-Fa-f]+)", ws[0])
            if not m:
                continue
            segs[int(m.group(1), 16)] = (os.path.basename(s)[:-2], ws)
        addrs = sorted(segs)
        for i, a in enumerate(addrs):
            fn, ws = segs[a]
            if not (1 <= len(ws) <= 3):
                continue
            if any("03E00008" in w for w in ws):  # has jr ra -> real fn, not orphan
                continue
            if i + 1 >= len(addrs):
                continue
            sfn, _ = segs[addrs[i + 1]]
            p, unit = pct.get(sfn, (None, None))
            if p is None or not (90 <= p < 100):
                continue
            k = len(ws)
            bo = "build/non_matching/" + unit + ".c.o"
            eo = "expected/" + unit + ".c.o"
            if not (os.path.exists(bo) and os.path.exists(eo)):
                continue
            b = func_words(bo, sfn)
            e = func_words(eo, sfn)
            if b and e and b[k:] == e:
                landable.append((p, sfn, unit.split("/")[-1], k, fn))
    print(
        "LANDABLE orphan-merges (succ 90-99%% NM wrap AND build[k:]==expected): %d"
        % len(landable)
    )
    for p, sfn, seg, k, orph in sorted(landable, reverse=True):
        print("  %5.1f%% %-32s [%s] k=%d orphan=%s" % (p, sfn, seg, k, orph))
    if not landable:
        print("  (none — the 90-99%% subset is exhausted; remaining orphan")
        print("   successors are plain-INCLUDE_ASM and need fresh multi-pass decode)")


if __name__ == "__main__":
    main()
