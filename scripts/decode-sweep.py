#!/usr/bin/env python3
"""decode-sweep.py -- automate the deterministic m2c-graft decode-error
transforms (docs/TOOLING_DECOMP graft-cleanup items 21 & 22 + struct-copy
collapse) that drive the 40%->70% climb on big struct-heavy functions.

WHY: these three transforms were done BY HAND on every big function and are
the biggest mechanical %-movers post-graft -- field-width retype was +17.9pp
on 2E354 alone, global-base split +20pp, struct-copy collapse the 00004118
lesson. They are deterministic from the TARGET asm: derive a per-offset access
catalog from the function's own bytes, then rewrite the m2c body to match.

INPUT  : a .c file that already contains an `#ifdef NON_MATCHING` body for FN
         (the m2c graft), plus the target asm reachable via disasm-raw.py /
         the function's expected .o.
OUTPUT : the same file, transformed in place (or to stdout), with each
         transform applied INCREMENTALLY and objdiff-GATED -- a transform is
         kept only if it improves the function's fuzzy_match_percent (or holds
         fuzzy flat while opcode-LCS rises); regressions are reverted.

TRANSFORMS:
  1. field-width-retype  -- catalog (base+off)->width from lb/lbu/lh/lhu/lw/
     lwc1 etc; retype mistyped *(s32*)((char*)base+off) derefs to the
     cataloged width. The TELL of a mistype: build emits lwl/lwr|swl/swr
     unaligned pairs where target has clean byte/half ops.
  2. global-base-split   -- *(T*)0xADDR and lw N(zero) absolute derefs ->
     *(T*)((char*)&D_00000000 + 0xADDR) so IDO does the hi/lo split; table
     address call-args -> (s32)((char*)&D_00000000 + off) address form.
  3. struct-copy-collapse -- contiguous N-word field copies -> single
     exact-width struct/Quad cast (NOT whole-struct overshoot -- 00004118).

GATING: --gate (default) rebuilds the NM .o and re-reads fuzzy after each
transform, reverting any that don't help. --no-gate applies blindly (fast
preview; you still must build+measure yourself). Idempotent / re-runnable.

Usage:
  decode-sweep.py <file.c> <func_name> [options]

Options:
  --unit NAME          objdiff unit (default: inferred from file path,
                       e.g. src/foo/foo.c -> src/foo/foo)
  --no-gate            apply every transform without rebuilding/measuring
  --only LIST          comma list of transforms to run
                       (retype,global,structcopy; default all)
  --stdout             write result to stdout instead of in place
  --report PATH        objdiff report json path (default /tmp/decode-sweep.json)
  --keep-flat          keep a transform if fuzzy is flat (default: needs >0)
  -v / --verbose       per-transform change detail
"""

import argparse
import glob
import json
import os
import re
import struct
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# body location (mirrors m2c-hybrid-emit.find_function)
# ---------------------------------------------------------------------------


def find_function(lines, func):
    """Return (start, end) inclusive line indexes of func's definition body."""
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
    raise SystemExit("decode-sweep: function %s not found in file" % func)


# ---------------------------------------------------------------------------
# target access catalog (from the raw .word disasm of the function)
# ---------------------------------------------------------------------------

LOAD_STORE = {
    "lb": "s8",
    "lbu": "u8",
    "sb": "b8",
    "lh": "s16",
    "lhu": "u16",
    "sh": "h16",
    "lw": "w32",
    "sw": "w32",
    "lwc1": "f32",
    "swc1": "f32",
    "ldc1": "f64",
    "sdc1": "f64",
    "lwl": "U",
    "lwr": "U",
    "swl": "U",
    "swr": "U",  # unaligned: the mistype tell
}

# canonical C type per catalog width (None = leave m2c's type alone)
WIDTH_TO_CTYPE = {
    "s8": "s8",
    "u8": "u8",
    "s16": "s16",
    "u16": "u16",
    "w32": None,  # already s32-ish; never narrow a 32-bit slot
    "f32": "f32",
    "f64": "f64",
}


def find_target_s(name):
    """Path to the function's asm/nonmatchings/.../<name>.s, or None."""
    fs = glob.glob("asm/nonmatchings/**/%s.s" % name, recursive=True)
    return fs[0] if fs else None


def load_target_words(text):
    """Extract the raw .word list from an .s body (USO raw-word format)."""
    return [int(m, 16) for m in re.findall(r"\.word 0x([0-9A-Fa-f]{8})", text)]


def mnemonic_lines(text):
    """Extract (addr, 'mnem operands') from a mnemonic-format .s body
    (kernel/bootup splat output that DOES carry decoded mnemonics)."""
    body = []
    for ln in text.splitlines():
        # /* ROM VADDR BYTES */  mnem  ops...
        m = re.match(r"\s*/\*[^*]*\*/\s+([a-z][\w.]*)\s+(.*)", ln)
        if m:
            body.append((0, (m.group(1) + " " + m.group(2)).strip()))
    return body


def disasm_words(words):
    """objdump a raw big-endian word blob -> list of (addr, mnemonic_line)."""
    blob = b"".join(struct.pack(">I", w) for w in words)
    fd, p = tempfile.mkstemp(suffix=".bin")
    os.write(fd, blob)
    os.close(fd)
    try:
        out = subprocess.run(
            [
                "mips-linux-gnu-objdump",
                "-D",
                "-b",
                "binary",
                "-m",
                "mips:4000",
                "-EB",
                "-M",
                "no-aliases",
                p,
            ],
            capture_output=True,
            text=True,
        ).stdout
    finally:
        os.unlink(p)
    body = []
    for ln in out.splitlines():
        m = re.match(r"\s+([0-9a-f]+):\s+[0-9a-f]{8}\s+(.*)", ln)
        if m:
            body.append((int(m.group(1), 16), m.group(2).strip()))
    return body


# memory operand: "<mnem> <rt>, <signed-off>(<base>)"
MEM_RE = re.compile(r"^(\w+)\s+\$?\w+,\s*(-?(?:0x[0-9a-fA-F]+|\d+))\(\$?(\w+)\)")


def build_catalog(body):
    """Return {base_reg: {offset_int: set(widths)}} and a flag list of
    offsets that the target accesses via unaligned (lwl/lwr) pairs (the
    mistype tell)."""
    catalog = {}
    unaligned = set()  # (base, offset)
    for _addr, insn in body:
        m = MEM_RE.match(insn)
        if not m:
            continue
        mnem, off, base = m.group(1), m.group(2), m.group(3)
        if mnem not in LOAD_STORE:
            continue
        offv = int(off, 16) if off.lower().startswith(("0x", "-0x")) else int(off)
        width = LOAD_STORE[mnem]
        if width == "U":
            unaligned.add((base, offv))
            continue
        catalog.setdefault(base, {}).setdefault(offv, set()).add(width)
    return catalog, unaligned


def target_catalog(name):
    """Build the access catalog for FN from its .s, handling BOTH the USO
    raw-`.word` format (objdump the byte blob) and the mnemonic format
    (parse decoded ops directly). Returns (catalog, unaligned) or
    ({}, set()) if no .s is found."""
    path = find_target_s(name)
    if not path:
        return {}, set()
    text = open(path).read()
    words = load_target_words(text)
    if words:
        body = disasm_words(words)
    else:
        body = mnemonic_lines(text)
    return build_catalog(body)


def dominant_width(widths):
    """Collapse a set of catalog widths to a single unambiguous C type, or
    None if mixed/ambiguous (then leave m2c's type alone)."""
    # store widths (b8/h16) are size-only; fold to their load counterparts
    norm = set()
    for w in widths:
        norm.add({"b8": "u8", "h16": "u16"}.get(w, w))
    # signed/unsigned byte clash, or int/float clash on the same slot ->
    # ambiguous union, leave alone
    bytes_ = {w for w in norm if w in ("s8", "u8")}
    halfs = {w for w in norm if w in ("s16", "u16")}
    words = {w for w in norm if w == "w32"}
    floats = {w for w in norm if w in ("f32", "f64")}
    families = [f for f in (bytes_, halfs, words, floats) if f]
    if len(families) != 1:
        return None  # mixed family = union/ambiguous
    fam = families[0]
    if len(fam) == 1:
        # map catalog width -> C type; w32 -> None (never narrow a word slot)
        return WIDTH_TO_CTYPE.get(next(iter(fam)))
    # same family, signed+unsigned clash (s8+u8): ambiguous, leave alone
    return None


# ---------------------------------------------------------------------------
# objdiff fuzzy measurement
# ---------------------------------------------------------------------------


def infer_unit(file_path):
    """src/foo/bar.c -> src/foo/bar (the objdiff unit name)."""
    p = file_path
    i = p.find("src/")
    if i >= 0:
        p = p[i:]
    return re.sub(r"\.c$", "", p)


def build_unit(unit, verbose=False):
    """make build/non_matching/<unit>.c.o RUN_CC_CHECK=0. Returns True on ok."""
    obj = "build/non_matching/%s.c.o" % unit
    r = subprocess.run(["make", obj, "RUN_CC_CHECK=0"], capture_output=True, text=True)
    if r.returncode != 0:
        if verbose:
            sys.stderr.write(r.stdout[-2000:] + r.stderr[-2000:])
        return False
    return True


def measure_fuzzy(unit, func, report_path):
    """Generate an objdiff report and return func's fuzzy_match_percent and
    the unit's fuzzy_match_percent. Returns (fn_fuzzy, unit_fuzzy) or
    (None, None)."""
    r = subprocess.run(
        ["objdiff-cli", "report", "generate", "-o", report_path],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None, None
    rep = json.load(open(report_path))
    for u in rep["units"]:
        if u["name"] == unit:
            ufuzzy = u["measures"]["fuzzy_match_percent"]
            for fnent in u.get("functions", []):
                if fnent["name"] == func:
                    return fnent["fuzzy_match_percent"], ufuzzy
            return None, ufuzzy
    return None, None


# ---------------------------------------------------------------------------
# transforms (each: body_str, catalog, unaligned, verbose -> (new_body, nchanges))
# ---------------------------------------------------------------------------


# the canonical m2c-graft-clean deref form:
#   *(TYPE *)((char *)(BASE_EXPR) + 0xOFF)
# TYPE is the m2c-assigned width (almost always s32); BASE_EXPR may itself
# contain a single matched paren group (e.g. another deref). We capture the
# innermost (char *)(...) + 0xNN so retypes don't reach across nested derefs.
DEREF_RE = re.compile(
    r"\*\((?P<typ>[suf](?:8|16|32|64)) \*\)"
    r"\(\(char \*\)\((?P<base>[^()]*(?:\([^()]*\))?[^()]*)\) \+ "
    r"(?P<off>0x[0-9A-Fa-f]+)\)"
)

# m2c var/temp names embed the originating register: var_s2 / temp_s3_4 / etc.
# Register suffix of an m2c name -- MIPS GPR/FPR register tokens only.
REG_SUFFIX = re.compile(
    r"^(?:var|temp)_((?:[savt][0-9])|(?:t[0-9])|(?:s[0-9])|(?:a[0-3])"
    r"|(?:v[01])|(?:f[0-9]+)|fp|gp|ra|sp)(?:_\d+)?$"
)


def base_register(base_expr):
    """If base_expr is a bare m2c var/temp whose name encodes a register,
    return that register; else None. Conservative: only single-token bases."""
    tok = base_expr.strip()
    m = REG_SUFFIX.match(tok)
    if m:
        return m.group(1)
    return None


def offset_global_width(catalog, off):
    """If EVERY base that accesses this offset agrees on one unambiguous
    sub-word C type, return it; else None. Used only when the base register
    can't be resolved (arg/sp/expression bases)."""
    seen = set()
    for base, offs in catalog.items():
        if off in offs:
            ctype = dominant_width(offs[off])
            if ctype is None:
                return None
            seen.add(ctype)
    if len(seen) == 1:
        ctype = next(iter(seen))
        # never globally narrow a word; only confidently retype sub-word
        if ctype in ("s8", "u8", "s16", "u16", "f32"):
            return ctype
    return None


def t_field_width_retype(body, catalog, unaligned, verbose=False):
    """Retype mistyped *(s32*)((char*)BASE + 0xOFF) derefs to the width the
    target asm actually uses at (base-register, offset). Base-register match
    is high-confidence; an offset-global agreement is the fallback for
    arg/sp/expression bases. NEVER narrows a 32-bit (w32) slot and NEVER
    touches an ambiguous (mixed-family / signed-clash) slot -- that is the
    no-blanket-retype rule (578B4-pass-5 lesson)."""
    changes = [0]

    def repl(m):
        typ, base, off = m.group("typ"), m.group("base"), m.group("off")
        offv = int(off, 16)
        reg = base_register(base)
        ctype = None
        if reg is not None and reg in catalog and offv in catalog[reg]:
            ctype = dominant_width(catalog[reg][offv])
            # don't widen/keep w32 here (None means leave alone)
        elif reg is None:
            ctype = offset_global_width(catalog, offv)
        if ctype is None or ctype == typ:
            return m.group(0)
        # only retype FROM s32 (m2c's default) -- preserve any width m2c got
        # right (e.g. an f32 it already inferred), and never up/down-cast a
        # pointer-typed slot (those aren't [suf]NN in this form anyway).
        if typ != "s32":
            return m.group(0)
        # w32 target -> keep s32 (dominant_width already returns None for w32)
        changes[0] += 1
        if verbose:
            sys.stderr.write("  retype %s+%s  s32 -> %s\n" % (base, off, ctype))
        return "*(%s *)((char *)(%s) + %s)" % (ctype, base, off)

    new_body = DEREF_RE.sub(repl, body)
    return new_body, changes[0]


# a bare absolute deref m2c emits for a global/table access materialized with
# lui+ori: *(T *)0xADDR  (T any scalar, ADDR >= 0x100 to avoid catching small
# struct-offset literals that are really null-base errors handled elsewhere).
ABS_DEREF_RE = re.compile(
    r"\*\((?P<typ>(?:[suf](?:8|16|32|64))|void) \*\)"
    r"0x(?P<addr>[0-9A-Fa-f]{3,})"
)
# the m2c "unaligned" cast artifact that ALWAYS accompanies a field m2c typed
# too wide -- strip it (the width fix is transform 1's job).
UNALIGNED_CAST_RE = re.compile(r"\(unaligned (?:[suf](?:8|16|32|64))\)\s*")


def t_global_base_split(body, catalog, unaligned, verbose=False):
    """Rewrite absolute global/table derefs *(T*)0xADDR into the &D_00000000
    base form so IDO materializes the address as lui %hi + lo16 (the target's
    GLOBAL hi/lo split) instead of lui+ori of a bare immediate. Also strips
    m2c's `(unaligned sN)` cast artifacts (the width itself is fixed by the
    retype pass). m2c-graft-clean already converts the f32/s32/u8/u16 forms;
    this pass catches the widths it misses (s8/s16/u32/u64/void and the bare
    `*(s16 *)0xADDR` halfword form) so the graft compiles + hi/lo-splits."""
    changes = [0]

    def repl_abs(m):
        typ, addr = m.group("typ"), m.group("addr")
        # leave already-split forms and tiny literals alone; require >= 0x100
        if int(addr, 16) < 0x100:
            return m.group(0)
        t = "s32" if typ == "void" else typ
        changes[0] += 1
        if verbose:
            sys.stderr.write(
                "  global-base *(%s *)0x%s -> &D_0+0x%s\n" % (typ, addr, addr)
            )
        return "*(%s *)((char *)&D_00000000 + 0x%s)" % (t, addr)

    new_body, nc = UNALIGNED_CAST_RE.subn("", body)
    if nc and verbose:
        sys.stderr.write("  stripped %d (unaligned sN) cast artifacts\n" % nc)
    changes[0] += nc
    new_body = ABS_DEREF_RE.sub(repl_abs, new_body)
    return new_body, changes[0]


def t_struct_copy_collapse(body, catalog, unaligned, verbose=False):
    """Stub -- implemented in a later commit."""
    return body, 0


TRANSFORMS = {
    "retype": t_field_width_retype,
    "global": t_global_base_split,
    "structcopy": t_struct_copy_collapse,
}


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def extract_body(lines, func):
    s, e = find_function(lines, func)
    return s, e, "\n".join(lines[s : e + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("func")
    ap.add_argument("--unit", default=None)
    ap.add_argument("--no-gate", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--report", default="/tmp/decode-sweep.json")
    ap.add_argument("--keep-flat", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    unit = args.unit or infer_unit(args.file)
    only = set(args.only.split(",")) if args.only else set(TRANSFORMS)

    with open(args.file) as f:
        lines = f.read().split("\n")
    fstart, fend, body = extract_body(lines, args.func)

    catalog, unaligned = target_catalog(args.func)
    if not catalog:
        sys.stderr.write(
            "decode-sweep: no usable target .s catalog for %s; catalog-driven "
            "transforms (retype/structcopy) will be no-ops\n" % args.func
        )
    if args.verbose:
        sys.stderr.write(
            "catalog: %d bases, %d cataloged offsets, %d "
            "unaligned tells\n"
            % (len(catalog), sum(len(v) for v in catalog.values()), len(unaligned))
        )

    # baseline fuzzy
    base_fuzzy = None
    if not args.no_gate:
        if not build_unit(unit, args.verbose):
            sys.exit("decode-sweep: baseline build failed for %s" % unit)
        base_fuzzy, _ = measure_fuzzy(unit, args.func, args.report)
        sys.stderr.write("[gate] baseline fuzzy %s = %s\n" % (args.func, base_fuzzy))

    def write_body(new_body):
        bl = new_body.split("\n")
        lines[fstart : fend + 1] = bl
        out = "\n".join(lines)
        with open(args.file, "w") as f:
            f.write(out)
        return len(bl)

    report = []  # (name, nchanges, kept, fuzzy_before, fuzzy_after)
    cur = base_fuzzy
    for name in ("retype", "global", "structcopy"):
        if name not in only:
            continue
        new_body, n = TRANSFORMS[name](body, catalog, unaligned, args.verbose)
        if n == 0:
            report.append((name, 0, None, cur, cur))
            continue
        if args.no_gate:
            body = new_body
            report.append((name, n, "applied", None, None))
            continue
        # gate: write, rebuild, measure
        prev_lines = lines[fstart : fend + 1][:]
        nlines = write_body(new_body)
        fend = fstart + nlines - 1
        ok = build_unit(unit, args.verbose)
        fn_fuzzy = None
        if ok:
            fn_fuzzy, _ = measure_fuzzy(unit, args.func, args.report)
        improved = (
            ok
            and fn_fuzzy is not None
            and cur is not None
            and (fn_fuzzy > cur + 1e-6 or (args.keep_flat and fn_fuzzy >= cur - 1e-6))
        )
        if improved:
            body = new_body
            report.append((name, n, "KEPT", cur, fn_fuzzy))
            cur = fn_fuzzy
        else:
            # revert
            lines[fstart : fend + 1] = prev_lines
            fend = fstart + len(prev_lines) - 1
            with open(args.file, "w") as f:
                f.write("\n".join(lines))
            report.append((name, n, "reverted", cur, fn_fuzzy))

    # final
    if args.stdout:
        sys.stdout.write("\n".join(lines))

    sys.stderr.write("\n=== decode-sweep report (%s) ===\n" % args.func)
    for name, n, kept, fb, fa in report:
        if n == 0:
            sys.stderr.write("  %-12s no changes\n" % name)
        elif kept == "applied":
            sys.stderr.write("  %-12s %d changes applied (no gate)\n" % (name, n))
        else:
            sys.stderr.write(
                "  %-12s %d changes  %-9s  %s -> %s\n"
                % (
                    name,
                    n,
                    kept,
                    "%.2f" % fb if fb is not None else "?",
                    "%.2f" % fa if fa is not None else "?",
                )
            )
    if base_fuzzy is not None and cur is not None:
        sys.stderr.write(
            "  TOTAL fuzzy %.2f -> %.2f (%+.2fpp)\n"
            % (base_fuzzy, cur, cur - base_fuzzy)
        )


if __name__ == "__main__":
    main()
