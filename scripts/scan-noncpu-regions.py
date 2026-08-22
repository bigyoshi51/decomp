#!/usr/bin/env python3
"""Scan a project's 0%/INCLUDE_ASM function .s files for non-CPU-code signals.

Two passes over every asm/nonmatchings/**/*.s whose function is at 0% fuzzy
(or absent) in report.json:

Pass 1 — foreign-ISA / handwritten signals:
  imem_jal   jal/j target in SP IMEM 0x04000000..0x04002000 (RSP ucode)
  cop2/lswc2 COP2 (0x12) + lwc2 (0x32) + swc2 (0x3A) density >= 1%  (RSP vector)
  addi       opcode 0x08 (IDO only ever emits addiu)
  kreg       k0/k1/gp as ALU/load destination
  mtc0/mfc0  COP0 moves (handwritten CP0 code — or RSP-COP0 misread)
  bad_op     reserved/invalid primary opcodes
  ascii_run  >=4 consecutive words of printable ASCII (string data)
  mono_run   >=16 consecutive strictly-increasing words (table data)

Pass 2 — strict CPU-plausibility:
  bad%       invalid-encoding density under a strict o32+MIPS3 decoder
  badbr%     fraction of branch targets outside [start, end+4] of the body
  jrra       absence of any `jr $ra` word

Interpretation (validated on 1080, 2026-08-22):
  RSP ucode blob     -> imem_jal + cop2 density + addi + kreg together
  string/table data  -> ascii_run / mono_run + bad_op density
  handwritten CPU    -> mtc0/mfc0/kreg but bad% ~= 0  (exception handlers,
                        TLB helpers, libgcc 64-bit shifts) — NOT reclassifiable
  splat fragments    -> bad% == 0 with high badbr% (branches into neighbor fn)

Require MULTIPLE independent signals before reclassifying; single-signal hits
must be hand-disassembled (mips-linux-gnu-objdump -EB -m mips:4300).

Usage: scan-noncpu-regions.py <project-dir>
"""

import json
import os
import re
import sys
from collections import defaultdict

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
WORD_RE = re.compile(r"/\* ([0-9A-F]+) ([0-9A-F]+) ([0-9A-F]{8}) \*/")

rep = json.load(open(os.path.join(ROOT, "report.json")))
fuzzy = {}
for u in rep["units"]:
    for f in u.get("functions", []):
        fuzzy[f["name"]] = f.get("fuzzy_match_percent", 0.0) or 0.0

SPECIAL_OK = set(range(0x40)) - {
    0x01,
    0x05,
    0x0A,
    0x0B,
    0x0E,
    0x15,
    0x1D,
    0x1E,
    0x1F,
    0x28,
    0x29,
    0x35,
    0x37,
    0x39,
    0x3D,
}
OP_OK = {
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    0x0A,
    0x0B,
    0x0C,
    0x0D,
    0x0E,
    0x0F,
    0x10,
    0x11,
    0x14,
    0x15,
    0x16,
    0x17,
    0x18,
    0x19,
    0x20,
    0x21,
    0x22,
    0x23,
    0x24,
    0x25,
    0x26,
    0x27,
    0x28,
    0x29,
    0x2A,
    0x2B,
    0x2C,
    0x2D,
    0x2E,
    0x2F,
    0x30,
    0x31,
    0x34,
    0x35,
    0x37,
    0x38,
    0x39,
    0x3C,
    0x3D,
    0x3F,
}
REGIMM_OK = (0, 1, 2, 3, 0x10, 0x11, 0x12, 0x13)


def pass1(words):
    n = len(words)
    s = defaultdict(int)
    ascii_run = mono = 0
    prev = None
    for w in words:
        op = w >> 26
        if op in (2, 3):
            tgt = (w & 0x3FFFFFF) << 2
            if 0x04000000 <= tgt < 0x04002000:
                s["imem_jal"] += 1
        if op == 0x12:
            s["cop2"] += 1
        if op in (0x32, 0x3A):
            s["lswc2"] += 1
        if op == 0x08:
            s["addi"] += 1
        if op == 0x10:
            rs = (w >> 21) & 0x1F
            if rs == 0:
                s["mfc0"] += 1
            elif rs == 4:
                s["mtc0"] += 1
        rt = (w >> 16) & 0x1F
        rd = (w >> 11) & 0x1F
        if op == 0 and (w & 0x3F) < 0x30 and rd in (26, 27, 28) and w:
            s["kreg"] += 1
        if op in (
            0x08,
            0x09,
            0x0A,
            0x0B,
            0x0C,
            0x0D,
            0x0E,
            0x0F,
            0x20,
            0x21,
            0x23,
            0x24,
            0x25,
            0x27,
        ) and rt in (26, 27, 28):
            s["kreg"] += 1
        if op in (0x13, 0x1B, 0x1E, 0x33, 0x37, 0x3B, 0x3F, 0x1C, 0x1D):
            s["bad_op"] += 1
        bs = w.to_bytes(4, "big")
        ascii_run = ascii_run + 1 if all(0x20 <= b < 0x7F for b in bs) else 0
        s["max_ascii"] = max(s["max_ascii"], ascii_run)
        mono = mono + 1 if (prev is not None and prev < w) else 0
        s["max_mono"] = max(s["max_mono"], mono)
        prev = w
    sigs = []
    if s["imem_jal"]:
        sigs.append(f"imem_jal={s['imem_jal']}")
    vec = s["cop2"] + s["lswc2"]
    if vec / n >= 0.01:
        sigs.append(f"cop2/lswc2={vec}({vec * 100 // n}%)")
    if s["addi"]:
        sigs.append(f"addi={s['addi']}")
    if s["kreg"] >= 2:
        sigs.append(f"kreg={s['kreg']}")
    if s["mtc0"]:
        sigs.append(f"mtc0={s['mtc0']}")
    if s["mfc0"]:
        sigs.append(f"mfc0={s['mfc0']}")
    if s["bad_op"]:
        sigs.append(f"bad_op={s['bad_op']}")
    if s["max_ascii"] >= 4:
        sigs.append(f"ascii_run={s['max_ascii']}")
    if s["max_mono"] >= 16:
        sigs.append(f"mono_run={s['max_mono']}")
    return sigs


def pass2(words):
    n = len(words)
    bad = nbr = badbr = jrra = 0
    for i, w in enumerate(words):
        op = w >> 26
        ok = (
            (op == 0 and (w & 0x3F) in SPECIAL_OK)
            or (op == 1 and ((w >> 16) & 0x1F) in REGIMM_OK)
            or (op not in (0, 1) and op in OP_OK)
        )
        if not ok:
            bad += 1
        if w == 0x03E00008:
            jrra += 1
        if op in (4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17) or (
            op == 1 and ((w >> 16) & 0x1F) in REGIMM_OK
        ):
            off = w & 0xFFFF
            if off >= 0x8000:
                off -= 0x10000
            nbr += 1
            if not (0 <= i + 1 + off <= n + 4):
                badbr += 1
    return bad * 100 / n, badbr * 100 / max(nbr, 1), nbr, jrra


for dirp, _, files in os.walk(os.path.join(ROOT, "asm/nonmatchings")):
    for fn in sorted(files):
        if not fn.endswith(".s"):
            continue
        if fuzzy.get(fn[:-2], 0.0) > 0.0:
            continue
        txt = open(os.path.join(dirp, fn)).read()
        if ".rodata" in txt.split("\n", 1)[0]:
            continue  # already data
        words = [int(m.group(3), 16) for m in WORD_RE.finditer(txt)]
        if len(words) < 8:
            continue
        sigs = pass1(words)
        badpct, badbrpct, nbr, jrra = pass2(words)
        if badpct > 3:
            sigs.append(f"strict_bad={badpct:.1f}%")
        if badbrpct > 20 and nbr >= 3:
            sigs.append(f"badbr={badbrpct:.0f}%")
        if len(sigs) >= (1 if "strict_bad" in " ".join(sigs) else 2):
            rel = os.path.relpath(os.path.join(dirp, fn), ROOT)
            detail = "; ".join(sigs)
            head = f"{len(sigs)} sig | {len(words):4d}w | jrra={jrra}"
            print(f"{head} | {rel} | {detail}")
