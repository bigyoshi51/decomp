#!/usr/bin/env python3
"""m2c-hybrid-emit.py -- coalesce m2c SSA temps into per-register variables.

Hybrid of m2c's two emit modes: keeps the default (SSA) emit's structure
(score-faithful) while collapsing the temp_<reg>_<n> population toward the
--reg-vars emit's one-variable-per-register shape (frame-faithful).

WHY (gl_func_000578B4 diagnosis, 2026-06-11): a big SSA graft's frame bloat
is NOT temp-count register pressure -- IDO colors short-lived temps fine
(pass-6: a 21-temp arm rewritten with 5 locals was codegen-equivalent).
The bloat is spill/home SLOTS: uopt's global coloring leaves ~142 webs
"not colored (-ve save)" and reserves a per-VARIABLE home in the frame.
Distinct C variables get distinct homes; textually-disjoint webs merged
into ONE variable share ONE home. So renaming temps of the same register
with non-overlapping live ranges into a single variable shrinks the frame.
(Measured on 578B4: not-colored webs 142 -> 90, total candidates ~4x
fewer -- the allocator DOES see fewer/joined webs, hence the per-class
tuning below.)

SAFETY MODEL: m2c temps are SSA (def dominates uses; phi values become
var_*, which this script never touches). In loop-free structured code,
per-path execution order == textual order, so two temps whose textual
[first-line, last-line] ranges are disjoint can never clobber each other.
Loops: any range that PARTIALLY intersects a loop span is expanded to the
whole span (a value flowing into/out of a loop must not share a slot with
in-loop temps); gotos/labels in the body disable coalescing entirely
unless --force.

Types are PRESERVED: temps only merge with temps of the IDENTICAL
normalized type (never blanket-retype -- that breaks m2c pointer
arithmetic scaling; see docs/TOOLING_DECOMP.md reg-vars caveat).

CALIBRATION (gl_func_000578B4, 9.7KB, 2026-06-11): coalescing is NOT
codegen-neutral -- uopt's candidate count drops ~4x (webs join), so
tune per register CLASS and keep what scores: a/v merges +4.7pp,
t1-t5/t8 neutral-positive (frame down), --include-vars +1.0pp,
--pad to the exact target frame +0.01pp; t0 and ra merges HURT
(-5/-2.5pp). Winning recipe there:
  --regs a0,a1,a2,a3,v0,v1,t1,t2,t3,t4,t5,t8 --include-vars --pad 2
=> 75.07 -> 81.22, frame 1280 -> 496 EXACT.
NEGATIVE (game_uso_func_000044F4): on a fresh SSA graft whose bloat
is var_s0 phi-webs (callee-saved, call-crossing), v-merges are
score-neutral and s-merges CRASH the score (51.2 -> 39.1); the lever
only pays when the residual is spill-home frame bloat, not structure.

Usage:
  m2c-hybrid-emit.py <file.c> <func_name> [options]

Options:
  --in-place            rewrite the file (default: write to stdout)
  --classes a,v,t,s,f   only coalesce these register classes (default all)
  --regs a0,v1,t2,...   only coalesce these exact registers
  --include-vars        also coalesce var_<reg> phi variables
  --pad N               add N volatile pad slots (hit the exact target frame)
  --no-call-cross       only merge ranges that do not cross a call site
  --stats               print per-class before/after counts to stderr
  --force               coalesce even if the body contains goto/labels
"""

import argparse
import re
import sys
from collections import defaultdict

TEMP_RE = re.compile(r"\b(?:temp|var)_([a-z]+[0-9]*)(?:_(\d+))?\b")
DECL_RE = re.compile(
    r"^(\s*)([A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*)*\s*\**)\s*"
    r"((?:temp|var)_[a-z]+[0-9]*(?:_\d+)?)\s*;\s*$"
)
LOOP_RE = re.compile(r"\b(for|while|do)\b")
CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
NONCALL_NAMES = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "FW",
    "FH",
    "FB",
    "FWU",
    "FHU",
    "FBU",
}


def find_function(lines, func):
    """Return (start, end) line indexes (inclusive) of func's definition."""
    sig_re = re.compile(r"^[A-Za-z_][\w\s\*]*\b%s\s*\(" % re.escape(func))
    for i, line in enumerate(lines):
        if sig_re.match(line) and not line.rstrip().endswith(";"):
            depth = 0
            seen_open = False
            for j in range(i, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                if "{" in lines[j]:
                    seen_open = True
                if seen_open and depth == 0:
                    return i, j
            break
    raise SystemExit("function %s not found (or unbalanced braces)" % func)


def strip_code(line):
    """Remove string/char literals and comments so identifier scans are clean."""
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r"/\*.*?\*/", "", line)
    line = re.sub(r"//.*$", "", line)
    return line


def loop_spans(body, base):
    """Line spans (start,end) of loop bodies inside the function."""
    spans = []
    for i in range(len(body)):
        code = strip_code(body[i])
        if LOOP_RE.search(code):
            depth = 0
            seen_open = False
            for j in range(i, len(body)):
                c = strip_code(body[j])
                depth += c.count("{") - c.count("}")
                if "{" in c:
                    seen_open = True
                if seen_open and depth <= 0:
                    spans.append((base + i, base + j))
                    break
    return spans


def reg_class(reg):
    if reg.startswith("f"):
        return "f"
    if reg in ("hi", "lo"):
        return "hilo"
    return reg[0]  # a, v, t, s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("func")
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--classes", default="")
    ap.add_argument(
        "--regs",
        default="",
        help="comma list of exact registers to coalesce "
        "(e.g. a0,a1,t6); overrides --classes",
    )
    ap.add_argument("--no-call-cross", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--include-vars",
        action="store_true",
        help="also coalesce m2c var_<reg> phi variables "
        "(textual-range rule; safe only in loop-free bodies)",
    )
    ap.add_argument(
        "--pad",
        type=int,
        default=0,
        metavar="N",
        help="insert N 'volatile s32 hybrid_pad_K;' decls at the "
        "top of the function (phantom frame slots, 4B each) to "
        "grow the frame to the target size after coalescing",
    )
    ap.add_argument(
        "--per-register",
        action="store_true",
        help="merge ALL same-(reg,type) temps into one var, "
        "ignoring live ranges (UNSAFE unless verified)",
    )
    args = ap.parse_args()

    classes = set(args.classes.split(",")) if args.classes else None
    regs = set(args.regs.split(",")) if args.regs else None

    with open(args.file) as f:
        lines = f.read().split("\n")

    fstart, fend = find_function(lines, args.func)
    body = lines[fstart : fend + 1]

    stripped = [strip_code(line) for line in body]

    if any(
        re.search(r"\bgoto\b", s) or re.match(r"\s*(?!default\b|case\b)\w+\s*:\s*$", s)
        for s in stripped
    ):
        if not args.force:
            raise SystemExit(
                "body contains goto/labels; textual live ranges are unsafe "
                "(rerun with --force to override)"
            )

    # --- collect decls ---------------------------------------------------
    decls = {}  # name -> (line_idx_in_body, normalized_type, reg)
    for i, line in enumerate(body):
        m = DECL_RE.match(line)
        if m:
            typ = " ".join(m.group(2).split())
            typ = re.sub(r"\s*\*", " *", typ)
            name = m.group(3)
            prefix = "temp_" if name.startswith("temp_") else "var_"
            base = name[len(prefix) :]
            reg = (
                base.rsplit("_", 1)[0] if re.match(r"[a-z]+[0-9]*_\d+$", base) else base
            )
            decls[name] = (i, typ, reg, prefix)

    # --- live ranges (statement lines only, skip decl lines) -------------
    decl_lines = {v[0] for v in decls.values()}
    occ = defaultdict(list)  # name -> [line_idx]
    first_is_def = {}
    crosses_call = defaultdict(bool)
    for i, s in enumerate(stripped):
        if i in decl_lines:
            continue
        for m in re.finditer(r"\b(?:temp|var)_[a-z]+[0-9]*(?:_\d+)?\b", s):
            name = m.group(0)
            if name in decls:
                occ[name].append(i)
                if name not in first_is_def:
                    # the first textual occurrence must be a def: either a
                    # plain statement `name = ...` or a comma-expression def
                    # `(name = f(...), ...)` -- check the text right after
                    # the first in-line occurrence for an assignment.
                    rest = s[m.end() :]
                    first_is_def[name] = bool(re.match(r"\s*=[^=]", rest))

    spans = loop_spans(body, 0)

    def expand(rng):
        s, e = rng
        changed = True
        while changed:
            changed = False
            for ls, le in spans:
                inter = not (e < ls or s > le)
                inside = s >= ls and e <= le
                if inter and not inside:
                    ns, ne = min(s, ls), max(e, le)
                    if (ns, ne) != (s, e):
                        s, e = ns, ne
                        changed = True
        return s, e

    call_lines = set()
    for i, s in enumerate(stripped):
        for m in CALL_RE.finditer(s):
            if m.group(1) not in NONCALL_NAMES:
                call_lines.add(i)
                break

    ranges = {}
    for name, lns in occ.items():
        if not first_is_def.get(name, False):
            continue  # first occurrence isn't a plain def -> skip (unsafe)
        s, e = expand((min(lns), max(lns)))
        ranges[name] = (s, e)
        if any(s < cl < e for cl in call_lines):
            crosses_call[name] = True

    # --- group & interval-schedule ---------------------------------------
    groups = defaultdict(list)  # (reg, type) -> [name]
    for name, (dline, typ, reg, prefix) in decls.items():
        if name not in ranges:
            continue
        if prefix == "var_" and not args.include_vars:
            continue
        if regs is not None:
            if reg not in regs:
                continue
        elif classes is not None and reg_class(reg) not in classes:
            continue
        groups[(reg, typ)].append(name)

    rename = {}
    removed_decls = set()
    stats = defaultdict(lambda: [0, 0])
    for (reg, typ), names in sorted(groups.items()):
        names.sort(key=lambda n: ranges[n][0])
        stats[reg_class(reg)][0] += len(names)
        if args.per_register:
            primary = names[0]
            for n in names[1:]:
                rename[n] = primary
                removed_decls.add(decls[n][0])
            stats[reg_class(reg)][1] += 1
            continue
        slots = []  # [(end, primary_name, crosses_call_any)]
        for n in names:
            s, e = ranges[n]
            placed = False
            for k in range(len(slots)):
                send, sprim, scall = slots[k]
                if send < s:
                    if args.no_call_cross and (scall or crosses_call[n]):
                        continue
                    rename[n] = sprim
                    removed_decls.add(decls[n][0])
                    slots[k] = (e, sprim, scall or crosses_call[n])
                    placed = True
                    break
            if not placed:
                slots.append((e, n, crosses_call[n]))
        stats[reg_class(reg)][1] += len(slots)

    # --- rewrite ----------------------------------------------------------
    if rename:
        pat = re.compile(r"\b(%s)\b" % "|".join(re.escape(n) for n in rename))
        new_body = []
        for i, line in enumerate(body):
            if i in removed_decls:
                continue
            new_body.append(pat.sub(lambda m: rename[m.group(1)], line))
        lines[fstart : fend + 1] = new_body

    if args.pad:
        # insert after the function's opening brace line
        for i in range(fstart, len(lines)):
            if "{" in lines[i]:
                pads = ["    volatile s32 hybrid_pad_%d;" % k for k in range(args.pad)]
                lines[i + 1 : i + 1] = pads
                break

    if args.stats or not rename:
        total_b = sum(v[0] for v in stats.values())
        total_a = sum(v[1] for v in stats.values())
        print(
            "coalesced %d temps -> %d vars (%s)"
            % (
                total_b,
                total_a,
                ", ".join(
                    "%s: %d->%d" % (k, v[0], v[1]) for k, v in sorted(stats.items())
                ),
            ),
            file=sys.stderr,
        )

    out = "\n".join(lines)
    if args.in_place:
        with open(args.file, "w") as f:
            f.write(out)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
