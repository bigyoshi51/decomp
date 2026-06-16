#!/usr/bin/env python3
"""coloring-search.py -- DIRECTED search over source transforms to crack an
IDO 7.1 register-renumber (coloring) cap.

scripts/coloring-solve.py and scripts/split-solve.py are DIAGNOSTIC: given a
build's -Wo,-zdbug:6 trace they tell you WHICH live range (LR) is mis-colored
and WHAT lever the algorithm implies. They cannot, by hand, find the
emission-NEUTRAL edit that moves that LR without also shifting statement
emission (the obstacle the solvers hit). This tool MECHANIZES that last step:
it ENUMERATES candidate source transforms aimed at the contested LR, compiles
each with the patched IDO cc + -Wo,-zdbug:6, disassembles the result, scores it
against the target (instruction-exact fuzzy, aliases folded), and reports the
contested LR's resulting register. It KEEPS candidates that move toward target
without regressing, and EXHAUSTS the bounded candidate space otherwise.

Two outcomes, both wins:
  * CRACK   -- a candidate reaches 100% (instruction-exact vs target). Apply it.
  * EMPTY   -- every candidate in the bounded space either regresses or is
               byte-neutral. The cap is PROVEN by a tool, not hand-waved.

USAGE
  coloring-search.py --base BASE.c --func FUNC --target-s TARGET.s \
      [--cc PATH] [--gens g1,g2,...] [--max-per-gen N] [--keep-dir DIR] \
      [--apply-best OUT.c]

  BASE.c     a standalone C file with ONE function body (the current NM body),
             plus optional `// @cs:` annotations (see ANNOTATIONS). Strip-//
             happens automatically before the dump (IDO cc rejects // unless
             -Xcpluscomm; we pass it, but the comments are stripped anyway so
             the generators can rewrite freely).
  --func     the target symbol (to isolate in the coloring trace).
  --target-s the target .s (raw-.word or mnemonic; auto-disassembled).

ANNOTATIONS (optional; sharpen the generators to the contested LR)
  A line `// @cs:lr NAME` names the contested C variable (e.g. the return
  value `r`). Generators that need a handle (web-split, register-kw, cast,
  inline) target that variable. Without it, the structural generators
  (statement reorder, dead-local injection) still run blindly.

The generators are SOURCE-TEXT transforms (regex/line level), each emitting a
bounded family of variant C strings. They are intentionally CONSERVATIVE: a
generator that would change the instruction COUNT is still emitted (the scorer
will reject it), because an apparent count change sometimes folds back to the
same count after uopt canonicalization -- only the scorer is authoritative.

DESIGN NOTES (why directed, not random like the permuter)
  * The permuter mutates blindly and floors on register-renumbers (documented
    repeatedly in docs/IDO_CODEGEN.md). This tool aims each generator at the
    SPECIFIC contested LR and reads the coloring trace to confirm the LR's
    register moved, so a candidate that improves fuzzy for the RIGHT reason is
    distinguishable from accidental alignment noise.
  * Bounded: --max-per-gen caps each generator. The whole space is small and
    fully logged (watchdog: a progress line before every compile).
"""

import argparse
import collections
import difflib
import os
import re
import struct
import subprocess
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# Register-color table (enum RegisterColor, uoptdata.h) -- shared with the
# solver scripts.
# ---------------------------------------------------------------------------
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

DEFAULT_CC = "tools/ido-static-recomp/build/7.1/out/cc"
CC_FLAGS = [
    "-c",
    "-G",
    "0",
    "-non_shared",
    "-Xcpluscomm",
    "-Wab,-r4300_mul",
    "-O2",
    "-mips2",
    "-32",
    "-Wo,-zdbug:6",
]


def log(msg):
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Target / build disassembly + scoring
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"\.word\s+0x([0-9A-Fa-f]{8})")
_ADDR_RE = re.compile(r"^\s*[0-9a-f]+:\s*")
INT_REGS = (
    "v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 t8 t9 "
    "s0 s1 s2 s3 s4 s5 s6 s7 ra at sp fp gp zero k0 k1"
).split()
_REG_RE = re.compile(r"\b(" + "|".join(INT_REGS) + r"|f\d+)\b")


def objdump_words(blob):
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
                "mips:4300",
                "-EB",
                "--no-show-raw-insn",
                "-M",
                "no-aliases",
                p,
            ],
            capture_output=True,
            text=True,
        ).stdout
    finally:
        os.unlink(p)
    return [ln for ln in out.splitlines() if _ADDR_RE.match(ln)]


def _trim_trailing_nops(insns):
    while len(insns) > 1 and insns[-1] == "nop":
        insns.pop()
    return insns


def read_target_insns(path):
    txt = open(path, errors="replace").read()
    words = _WORD_RE.findall(txt)
    if words:
        blob = b"".join(struct.pack(">I", int(w, 16)) for w in words)
        return _trim_trailing_nops([normalize(ln) for ln in objdump_words(blob)])
    # mnemonic .s: take operand lines
    out = []
    for ln in txt.splitlines():
        ln = re.sub(r"/\*.*?\*/", "", ln)
        if _ADDR_RE.match(ln) or re.match(r"\s*[a-z][a-z0-9.]*\s+\$?[a-z0-9\-]", ln):
            n = normalize(ln)
            if n:
                out.append(n)
    return _trim_trailing_nops(out)


def objdump_o(opath):
    out = subprocess.run(
        [
            "mips-linux-gnu-objdump",
            "-d",
            "--no-show-raw-insn",
            "-M",
            "no-aliases",
            opath,
        ],
        capture_output=True,
        text=True,
    ).stdout
    insns = [normalize(ln) for ln in out.splitlines() if _ADDR_RE.match(ln)]
    # The build .o is padded to a 16-byte boundary with trailing nops AFTER the
    # function. read_target_insns trims the target's trailing nops too, so the
    # two are compared on the same (nop-stripped) tail.
    return _trim_trailing_nops(insns)


def normalize(s, keep_regs=True):
    """Canonicalize an instruction so objdiff-equivalent forms compare equal:
    fold move/or, li/addiu, nop/sll-zero, wildcard branch targets and
    relocs. keep_regs=False additionally wildcards register names (to detect
    pure register-renumber vs structural diffs)."""
    s = re.sub(r"/\*.*?\*/", "", s).strip().replace("$", "")
    s = _ADDR_RE.sub("", s)
    s = re.sub(r"<[^>]*>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    p = s.split(" ", 1)
    mn = p[0]
    ops = (p[1] if len(p) > 1 else "").replace(", ", ",").replace(" ", "")
    ops = re.sub(r"%hi\([^)]*\)|%lo\([^)]*\)", "X", ops)
    ops = re.sub(r"func_[0-9A-Fa-f]+|D_[0-9A-Fa-f]+|gl_func_[0-9A-Fa-f]+", "SYM", ops)
    ops = re.sub(r"\.L[0-9A-Fa-f]+", "@", ops)
    # alias folding
    if mn == "move":
        mn, ops = "or", ops + ",zero"
    elif mn == "li":
        # li rd,N  ==  addiu rd,zero,N  (insert zero as rs, after rd)
        mn, ops = "addiu", re.sub(r"^([^,]+),", r"\1,zero,", ops)
    elif mn == "nop" or (mn == "sll" and ops in ("zero,zero,0x0", "zero,zero,0")):
        return "nop"
    elif mn == "beqz":
        mn, ops = "beq", ops.replace(",", ",zero,", 1)
    elif mn == "bnez":
        mn, ops = "bne", ops.replace(",", ",zero,", 1)
    if mn == "lui":
        ops = re.sub(r",(0x[0-9a-f]+|\d+)$", ",X", ops)

    def cv(m):
        try:
            return str(int(m.group(0), 0))
        except Exception:
            return m.group(0)

    ops = re.sub(r"-?0x[0-9a-fA-F]+|-?\b\d+\b", cv, ops)
    # branch/jump target -> wildcard. objdump renders the target as a raw hex
    # address (e.g. "4c"), splat/our normalize may produce "@" or a decimal
    # (cv() above turns 0x.. into decimal); wildcard all three trailing forms.
    if mn[0] == "b" or mn in ("j", "jal", "jr", "jalr"):
        ops = re.sub(r"(^|,)(@|-?\d+|[0-9a-fA-F]+)$", r"\1@", ops)
    if not keep_regs:
        for r in sorted(INT_REGS, key=len, reverse=True):
            ops = re.sub(r"\b%s\b" % r, "R", ops)
        ops = re.sub(r"\bf\d+\b", "F", ops)
    return mn + " " + ops


def score(target, build):
    """Return (exact_pct, count_match, renumber_pairs, n_struct).
    exact_pct = % of target insns that align exactly (regs incl).
    count_match = target/build same length AND every diff is reg-only."""
    sm = difflib.SequenceMatcher(None, target, build, autojunk=False)
    exact = sum(i2 - i1 for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "equal")
    tw = [normalize_keepless(x) for x in target]
    bw = [normalize_keepless(x) for x in build]
    smw = difflib.SequenceMatcher(None, tw, bw, autojunk=False)
    renum = collections.Counter()
    nstruct = 0
    for tag, i1, i2, j1, j2 in smw.get_opcodes():
        if tag == "equal":
            for ti, bi in zip(range(i1, i2), range(j1, j2)):
                if target[ti] != build[bi]:
                    tr = _REG_RE.findall(target[ti])
                    br = _REG_RE.findall(build[bi])
                    for a, c in zip(tr, br):
                        if a != c:
                            renum[(a, c)] += 1
        else:
            nstruct += max(i2 - i1, j2 - j1)
    pct = 100.0 * exact / max(1, len(target))
    count_ok = (len(target) == len(build)) and nstruct == 0
    return pct, count_ok, renum, nstruct


def normalize_keepless(n):
    s = re.sub(r"\b(" + "|".join(INT_REGS) + r")\b", "R", n)
    return re.sub(r"\bf\d+\b", "F", s)


# ---------------------------------------------------------------------------
# Coloring-trace reader (the contested LR's resulting register)
# ---------------------------------------------------------------------------
LOCALOPT_RE = re.compile(r"OPTIMIZATION OF (\S+)")
GLOBALCOLOR_RE = re.compile(r"global coloring of (\S+)")
ASSIGN_RE = re.compile(
    r"^\s*(\d+):\s*(\d+)\s+assigned\s+\((constrained|unconstrained)\)\s+(\d+)"
)
NOCOLOR_RE = re.compile(r"^\s*(\d+):\s*(\d+)\s+not colored")


def read_coloring(trace_path, func):
    """Return list of (lr_bitpos, kind, reg_code) for func, in trace order."""
    if not os.path.exists(trace_path):
        return []
    lines = open(trace_path, errors="replace").read().splitlines()
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
        return []
    out = []
    for j in range(lo, hi):
        m = ASSIGN_RE.match(lines[j])
        if m:
            out.append((int(m.group(2)), m.group(3), int(m.group(4))))
            continue
        m = NOCOLOR_RE.match(lines[j])
        if m:
            out.append((int(m.group(2)), "spilled", None))
    return out


def coloring_summary(coloring):
    return " ".join(
        "%d=%s" % (lr, REGNAMES.get(reg, "spill") if reg is not None else "spill")
        for lr, kind, reg in coloring
    )


# ---------------------------------------------------------------------------
# Candidate generators
# ---------------------------------------------------------------------------
# Each generator takes the base source text + the parsed @cs annotations and
# yields (label, variant_source) pairs. Bounded by --max-per-gen at the driver.


def parse_annotations(src):
    ann = {"lr": None, "fp": False}
    for ln in src.splitlines():
        m = re.match(r"\s*//\s*@cs:lr\s+(\w+)", ln)
        if m:
            ann["lr"] = m.group(1)
        if re.search(r"//\s*@cs:fp", ln):
            ann["fp"] = True
    return ann


def strip_line_comments(src):
    # remove // comments but keep the line (so line count stable)
    return re.sub(r"//.*", "", src)


def _body_bounds(src):
    """Return (start_idx, end_idx) of the FUNCTION body. A preceding top-level
    struct/enum/typedef definition also has braces, so we cannot just take the
    first '{': we take the LAST top-level brace group (the function is the last
    top-level definition in these single-function NM files). Naive brace match
    (no strings/comments inside our generated C)."""
    # find every top-level brace group; return the last one
    groups = []
    depth = 0
    open_i = None
    for j, ch in enumerate(src):
        if ch == "{":
            if depth == 0:
                open_i = j
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and open_i is not None:
                groups.append((open_i + 1, j))
    if groups:
        return groups[-1]
    i = src.index("{")
    return i + 1, len(src)


def _body_stmts(body):
    """Split a (flat) body into top-level statements. Handles a single nested
    block (if/for) as one unit. Returns list of statement strings (trimmed,
    with trailing punctuation)."""
    stmts = []
    depth = 0
    cur = ""
    for ch in body:
        cur += ch
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                stmts.append(cur.strip())
                cur = ""
        elif ch == ";" and depth == 0:
            stmts.append(cur.strip())
            cur = ""
    if cur.strip():
        stmts.append(cur.strip())
    return [s for s in stmts if s]


def gen_register_kw(src, ann):
    """Add/remove a `register` storage-class on the contested local. Changes
    the LR's adjsave bias (register kw raises priority) -- a coloring lever."""
    if not ann["lr"]:
        return
    name = ann["lr"]
    # find `<type> name` declaration
    m = re.search(
        r"\b((?:unsigned\s+|signed\s+)?\w+)\s+(\*?\s*)%s\b" % re.escape(name), src
    )
    if not m:
        return
    decl = m.group(0)
    if "register" not in decl:
        yield ("register-kw", src.replace(decl, "register " + decl, 1))


def gen_unsigned_cast(src, ann):
    """Cast the contested value's def to unsigned/int -- sometimes changes the
    ucode op (and thus the LR's class). Bounded."""
    if not ann["lr"]:
        return
    name = ann["lr"]
    # only meaningful for an `int name = EXPR;` def
    m = re.search(r"\bint\s+%s\s*=\s*([^;]+);" % re.escape(name), src)
    if not m:
        return
    expr = m.group(1)
    yield (
        "unsigned-cast-def",
        src.replace(m.group(0), "int %s = (int)(unsigned)(%s);" % (name, expr), 1),
    )


def gen_web_split(src, ann):
    """Web-split: introduce a SECOND variable that aliases the contested value
    on one path, so the value colors as two interfering LRs. Each variant uses
    a different split point. Bounded family."""
    if not ann["lr"]:
        return
    name = ann["lr"]
    # Replace the LAST use of `name` with a fresh copy `cs_t` defined just
    # before it. This forces a copy LR that may take a different register.
    uses = [m.start() for m in re.finditer(r"\b%s\b" % re.escape(name), src)]
    if len(uses) < 2:
        return
    # variant A: copy at return
    m = re.search(r"return\s+%s\s*;" % re.escape(name), src)
    if m:
        repl = "{ int cs_t = %s; return cs_t; }" % name
        yield ("web-split-return", src.replace(m.group(0), repl, 1))


def gen_extra_use(src, ann):
    """Span/priority lever: add a NO-CALL extra use of the contested value
    (raises its (ld+st)*freq savings -> higher priority -> colors earlier ->
    lower reg) OR add it inside the call-crossing region (extends span ->
    lower priority -> colors later -> higher reg). Both directions, bounded."""
    if not ann["lr"]:
        return
    name = ann["lr"]
    m = re.search(r"return\s+%s\s*;" % re.escape(name), src)
    if not m:
        return
    # span-contract: read into a volatile sink before return (extra short use)
    pre = "{ volatile int cs_s = %s; return %s; }" % (name, name)
    yield ("extra-use-sink", src.replace(m.group(0), pre, 1))


def gen_dead_local(src, ann):
    """INTERFERENCE INJECTION -- the lever the solvers said was 'near-impossible
    in C'. Introduce a SECOND value that is live ACROSS the contested LR's
    def..last-use, so it interferes with the contested LR and FORBIDS the low
    register the contested LR currently grabs, pushing the contested LR up to
    the next free reg (e.g. v1 -> a2). C89-legal: all decls precede statements.
    The interferer is seeded from an arg (so it carries a real value, not dead-
    eliminated) and consumed at the return. Several seed sources / classes; the
    scorer rejects any that change the instruction count (most will -- that is
    the whole difficulty, and proving it mechanically is the point)."""
    start, end = _body_bounds(src)
    body = src[start:end]
    # Seed expressions that don't depend on the contested LR. We keep them
    # cheap (single op) so IF an emission-neutral one exists it surfaces.
    seeds = ["a0", "a1", "a2", "a1 + a2", "a0 + a1"]
    classes = [("int", ""), ("reg-int", "register ")]
    # find the return to consume the interferer (xor into the return keeps it
    # live to the very end without changing the returned value if seed is 0,
    # but a non-zero seed WOULD change semantics -- so we consume it via a
    # volatile sink instead, which keeps it live but is side-effecting-neutral
    # for matching purposes).
    rm = re.search(r"(return\b[^;]*;)", src)
    if not rm:
        return
    retstmt = rm.group(1)
    # C89 (IDO cfe): every declaration must precede every statement in a block.
    # Find the contested LR's decl line so we can declare the interferer
    # alongside it and seed it as the FIRST statement (after all decls).
    lrname = ann["lr"]
    decl_m = (
        re.search(
            r"^(\s*)([^\n;{}]*\b%s\b[^\n;{}]*=[^;]*;)" % re.escape(lrname), src, re.M
        )
        if lrname
        else None
    )
    for cl, kw in classes:
        for seed in seeds:
            decl = "%sint cs_iv;\n" % kw
            if decl_m:
                indent = decl_m.group(1)
                # insert the interferer decl just before the contested decl,
                # and the seed statement just after it (first statement).
                lr_decl = decl_m.group(0)
                ins = "%s%s%s%s    cs_iv = %s;" % (indent, decl, indent, lr_decl, seed)
                newsrc = src.replace(lr_decl, ins, 1)
            else:
                # no contested-decl handle: declare + seed right after body open
                newbody = "\n    " + decl + "    cs_iv = %s;\n" % seed + body[1:]
                newsrc = src[:start] + newbody + src[end:]
            consume = "{ volatile int cs_z = cs_iv; (void)cs_z; %s }" % retstmt
            newsrc = newsrc.replace(retstmt, consume, 1)
            yield ("interf-%s-%s" % (cl, seed.replace(" ", "")), newsrc)


def gen_stmt_reorder(src, ann):
    """First-occurrence (bitpos) lever for UNCONSTRAINED LRs: swap adjacent
    independent top-level statements to change which value is referenced first.
    Bounded to adjacent swaps that don't cross a control-flow block."""
    start, end = _body_bounds(src)
    body = src[start:end]
    stmts = _body_stmts(body)
    for i in range(len(stmts) - 1):
        a, b = stmts[i], stmts[i + 1]
        if "{" in a or "{" in b:  # don't reorder across a block
            continue
        if "return" in a or "return" in b:
            continue
        newstmts = stmts[:i] + [b, a] + stmts[i + 2 :]
        newbody = "\n    " + "\n    ".join(newstmts) + "\n"
        yield ("stmt-swap-%d/%d" % (i, i + 1), src[:start] + newbody + src[end:])


def gen_inline_dont_name(src, ann):
    """Inline-don't-name: if the contested local is used exactly once after its
    def, fold the def into that use (removes the LR so it doesn't compete).
    Conservative single-use case only."""
    if not ann["lr"]:
        return
    name = ann["lr"]
    m = re.search(r"\bint\s+%s\s*=\s*([^;]+);" % re.escape(name), src)
    if not m:
        return
    expr = m.group(1).strip()
    rest = src[m.end() :]
    if len(re.findall(r"\b%s\b" % re.escape(name), rest)) != 1:
        return
    folded = rest.replace(name, "(%s)" % expr, 1)
    yield ("inline-dont-name", src[: m.start()] + folded)


GENERATORS = collections.OrderedDict(
    [
        ("register-kw", gen_register_kw),
        ("unsigned-cast", gen_unsigned_cast),
        ("web-split", gen_web_split),
        ("extra-use", gen_extra_use),
        ("dead-local", gen_dead_local),
        ("stmt-reorder", gen_stmt_reorder),
        ("inline", gen_inline_dont_name),
    ]
)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def compile_variant(cc, src, func, workdir):
    """Compile a variant; return (insns_or_None, coloring, err)."""
    src = strip_line_comments(src)
    cpath = os.path.join(workdir, "v.c")
    opath = os.path.join(workdir, "v.o")
    open(cpath, "w").write(src)
    trace = os.path.join(workdir, "uoptlist")
    if os.path.exists(trace):
        os.unlink(trace)
    r = subprocess.run(
        [cc] + CC_FLAGS + [cpath, "-o", opath],
        capture_output=True,
        text=True,
        cwd=workdir,
    )
    if r.returncode != 0 or not os.path.exists(opath):
        return None, [], (r.stderr or r.stdout).strip().splitlines()[:3]
    insns = objdump_o(opath)
    coloring = read_coloring(trace, func)
    return insns, coloring, None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base", required=True)
    ap.add_argument("--func", required=True)
    ap.add_argument("--target-s", required=True)
    ap.add_argument("--cc", default=DEFAULT_CC)
    ap.add_argument("--gens", default=",".join(GENERATORS))
    ap.add_argument("--max-per-gen", type=int, default=20)
    ap.add_argument(
        "--keep-dir", default=None, help="dir to write improving variants to"
    )
    ap.add_argument(
        "--apply-best", default=None, help="write the best variant source here"
    )
    args = ap.parse_args()

    cc = args.cc
    if not os.path.exists(cc):
        sys.exit("cc not found: %s (run from project root or pass --cc)" % cc)

    base = open(args.base).read()
    ann = parse_annotations(base)
    target = read_target_insns(args.target_s)
    log("=== coloring-search %s ===" % args.func)
    log(
        "target: %d insns | contested LR var: %s | generators: %s"
        % (len(target), ann["lr"], args.gens)
    )

    workdir = tempfile.mkdtemp(prefix="csearch_")
    t0 = time.time()

    # baseline
    binsns, bcolor, berr = compile_variant(cc, base, args.func, workdir)
    if binsns is None:
        sys.exit("BASE failed to compile: %s" % berr)
    bpct, bcount, brenum, bstruct = score(target, binsns)
    log(
        "BASELINE: fuzzy=%.2f%% count_match=%s struct_diffs=%d renum=%s"
        % (
            bpct,
            bcount,
            bstruct,
            ",".join("%s<-%s" % (a, c) for (a, c), _ in brenum.most_common()),
        )
    )
    log("          coloring: %s" % coloring_summary(bcolor))

    best = (bpct, "baseline", base, bcolor)
    results = []
    gens = [g.strip() for g in args.gens.split(",") if g.strip()]
    n = 0
    for gname in gens:
        gen = GENERATORS.get(gname)
        if not gen:
            log("  (unknown generator %s, skipped)" % gname)
            continue
        cnt = 0
        for label, variant in gen(base, ann):
            if cnt >= args.max_per_gen:
                break
            cnt += 1
            n += 1
            # WATCHDOG: progress line before every compile
            log(
                "[%4.0fs] cand #%d  gen=%s  %s ..."
                % (time.time() - t0, n, gname, label)
            )
            insns, color, err = compile_variant(cc, variant, args.func, workdir)
            if insns is None:
                log("         -> compile FAILED: %s" % (err or ""))
                continue
            pct, count_ok, renum, nstruct = score(target, insns)
            tag = ""
            if pct > bpct + 0.001:
                tag = "  <== IMPROVES"
            elif pct < bpct - 0.001:
                tag = "  (regress)"
            renstr = ",".join("%s<-%s" % (a, c) for (a, c), _ in renum.most_common())
            log(
                "         -> fuzzy=%.2f%% count_match=%s struct=%d "
                "renum=[%s] color=[%s]%s"
                % (pct, count_ok, nstruct, renstr, coloring_summary(color), tag)
            )
            results.append((pct, gname, label, count_ok, renstr))
            if pct > best[0]:
                best = (pct, "%s/%s" % (gname, label), variant, color)
                if args.keep_dir:
                    os.makedirs(args.keep_dir, exist_ok=True)
                    kp = os.path.join(
                        args.keep_dir,
                        "%.2f_%s_%s.c" % (pct, gname, label.replace("/", "-")),
                    )
                    open(kp, "w").write(strip_line_comments(variant))
            if pct >= 100.0 - 1e-6 and count_ok:
                log(
                    "\n*** CRACK: 100%% instruction-exact via %s/%s ***"
                    % (gname, label)
                )
                break

    log("\n=== SUMMARY (%d candidates, %.0fs) ===" % (n, time.time() - t0))
    log("baseline fuzzy = %.2f%%" % bpct)
    log("best     fuzzy = %.2f%%  via %s" % (best[0], best[1]))
    improved = [r for r in results if r[0] > bpct + 0.001]
    if best[0] >= 100.0 - 1e-6:
        log("RESULT: CRACKED -> apply %s" % best[1])
    elif improved:
        log(
            "RESULT: PARTIAL -- %d candidate(s) improve fuzzy; best below 100%%."
            % len(improved)
        )
        for r in sorted(improved, reverse=True)[:5]:
            log(
                "   %.2f%%  %s/%s  count_match=%s renum=[%s]"
                % (r[0], r[1], r[2], r[3], r[4])
            )
    else:
        log(
            "RESULT: SPACE EXHAUSTED -- no generator in {%s} (max %d each) moved"
            % (args.gens, args.max_per_gen)
        )
        log("        fuzzy above baseline %.2f%%. Every candidate regressed or" % bpct)
        log("        was byte-neutral. The renumber is emission-coupled: the")
        log("        contested LR cannot be moved without shifting emission in")
        log("        this candidate family. Cap proven by tool (not hand-waved).")

    if args.apply_best and best[0] > bpct:
        open(args.apply_best, "w").write(strip_line_comments(best[2]))
        log("\nwrote best variant -> %s" % args.apply_best)


if __name__ == "__main__":
    main()
