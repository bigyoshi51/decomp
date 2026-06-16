#!/usr/bin/env python3
"""coloring-solve.py -- inverse register-coloring solver for IDO 7.1 uopt.

IDO's allocator is Chow-Hennessy priority-based coloring (references/ido,
src/uopt/uoptreg2.c). It is fully deterministic given the ucode it is fed,
and -Wo,-zdbug:6 emits a complete trace of every coloring decision. This
tool INVERTS that trace: given a target function's actual register
assignment and the current build's coloring trace, it computes WHICH live
ranges (LRs) must change register and -- from the algorithm's rules -- what
ordering/span change in the source would force that change.

It is function-agnostic. Inputs:
  --trace      a -Wo,-zdbug:6 uoptlist (the current build's coloring)
  --func       the function symbol (e.g. func_0001304C) to isolate in the trace
  --target-s   the target .s (asm/nonmatchings/.../<func>.s) [optional]
  --build-s    the build's disassembled .s for the same func [optional]

What it produces:
  1. The per-function coloring trace, decoded: LR bitpos -> register name,
     constrained vs unconstrained, color order (= priority order for the
     constrained phase; = bitpos order for the unconstrained phase).
  2. The function's frame/spill picture: LRs "not colored (-ve save)" =
     spill homes; LRs "split out" = live-range-split.
  3. If both .s files are given: a register-usage delta (which physical
     registers carry more/fewer values in target vs build) -- the symptom.
  4. Algorithm-derived levers for moving a value between registers.

The coloring rules it encodes (from uoptreg2.c globalcolor):
  * Register color codes (enum RegisterColor, uoptdata.h):
      1..13  = v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 ra   (caller-saved "er")
      14..23 = s0 s1 s2 s3 s4 s5 s6 s7 fp ra             (callee-saved "ee")
      24..35 = f0 f2 f12 f14 f16 f18 f20 f22 f24 f26 f28 f30 (fp)
  * CONSTRAINED LRs are colored first, in MAX-adjsave (priority) order.
    adjsave = compute_save = (frequency-weighted loads+stores saved minus
    reload/store-back cost) / span-factor. Longer span -> lower priority.
  * UNCONSTRAINED LRs are colored last, in plain BITPOS (first-occurrence)
    order.
  * Register choice: scan caller-saved ascending, then callee-saved; STRICT
    '<' on cost => the LOWEST-NUMBERED equal-cost non-forbidden register
    wins. So among equal-priority/equal-cost LRs, the one colored EARLIER
    grabs the lower register.
  * If best-reg cost >= LR value, the LR is SPLIT instead of colored.
  * adjsave <= 0 => "not colored (-ve save)" => spilled to a memory home.

LEVERS (how a source edit changes the inputs):
  * To move a value to a LOWER register: color it EARLIER. Either (a) raise
    its priority (more uses / shorter span -> higher adjsave), or (b) if it
    is unconstrained, move its first occurrence (bitpos) earlier (statement
    order / nesting -- NOT decl order).
  * To move a value to a HIGHER register (e.g. v0 -> a0, the 1304C base-ptr
    case): color it LATER. LOWER its priority by LENGTHENING its span (hold
    it live across more BBs) or reducing its use frequency, so other LRs
    color first and take the low registers; it lands in what's left (an arg
    register). This is the SPAN-EXTENSION lever.
  * To flip WHICH of two equal LRs gets the lower register: change their
    relative first-occurrence (bitpos) order.
  * To take a value OUT of registers entirely (into a spill home): kill its
    priority (inline its recompute so each use is a fresh short LR).
"""

import argparse
import collections
import re
import sys

# enum RegisterColor (references/ido/src/uopt/uoptdata.h:48)
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
CALLER_SAVED = set(range(1, 14))  # v0..ra : the cheap class
CALLEE_SAVED = set(range(14, 24))  # s0..ra_ee : firstUseCost penalty
ARG_REGS = {3: "a0", 4: "a1", 5: "a2", 6: "a3"}


def regname(code):
    return REGNAMES.get(code, "r%d" % code)


# ---------------------------------------------------------------------------
# Trace parsing
# ---------------------------------------------------------------------------
class Decision:
    __slots__ = ("ichain_bitpos", "lr_bitpos", "kind", "reg", "split_to", "order")

    def __init__(self, ichain_bitpos, lr_bitpos, kind, reg=None, split_to=None):
        self.ichain_bitpos = ichain_bitpos
        self.lr_bitpos = lr_bitpos
        self.kind = kind  # 'constrained' | 'unconstrained' | 'spilled' | 'split'
        self.reg = reg  # register code, or None
        self.split_to = split_to
        self.order = None  # coloring order index within its phase


# itab line:  {NNN|K}   BIT kind   op  {l} {r}
ITAB_RE = re.compile(r"^\s*\{\s*(\d+)\|\s*(\d+)\}\s+(\d+)\s+(isvar|isop)\s+(\S+)(.*)$")
# coloring decision lines:
ASSIGN_RE = re.compile(
    r"^\s*(\d+):\s*(\d+)\s+assigned\s+\((constrained|unconstrained)\)\s+(\d+)\s*$"
)
NOCOLOR_RE = re.compile(r"^\s*(\d+):\s*(\d+)\s+not colored \(-ve save\)\s*$")
SPLIT_RE = re.compile(r"^\s*live range\s+(\d+):\s*(\d+)\s+split out\s+(\d+)\s*$")
LOCALOPT_RE = re.compile(r"SECONDS IN LOCAL OPTIMIZATION OF (\S+)")
REGALLOC_RE = re.compile(r"SECONDS IN reg alloc preparation of (\S+)")
GLOBALCOLOR_RE = re.compile(r"SECONDS IN global coloring of (\S+)")
ITAB_HDR_RE = re.compile(r"^\s*index\s+bit\s+kind\s+op")


def parse_trace(path, func):
    """Return (decisions, itab) for the requested function.

    decisions: list[Decision] in trace (= coloring) order.
    itab: dict bitpos -> (ichain_id, kind, op, operands_raw, frame_off)
          (whatever portion of the itab the dump captured for this func)
    """
    lines = open(path, errors="replace").read().splitlines()
    # locate the function's region: from its "reg alloc preparation" line to
    # its "global coloring" line is where the coloring decisions live; the
    # itab dump precedes it (after "LOCAL OPTIMIZATION OF <func>").
    lo_idx = hi_idx = ra_idx = None
    for i, ln in enumerate(lines):
        m = LOCALOPT_RE.search(ln)
        if m and m.group(1) == func:
            lo_idx = i
        m = REGALLOC_RE.search(ln)
        if m and m.group(1) == func:
            ra_idx = i
        m = GLOBALCOLOR_RE.search(ln)
        if m and m.group(1) == func and ra_idx is not None:
            hi_idx = i
            break
    if ra_idx is None or hi_idx is None:
        sys.exit(
            "func %s not found in trace (need reg-alloc + global-coloring markers)"
            % func
        )

    # itab dump: scan from lo_idx forward to the first 'index bit kind' header
    itab = {}
    if lo_idx is not None:
        j = lo_idx
        while j < ra_idx and not ITAB_HDR_RE.match(lines[j]):
            j += 1
        j += 1
        while j < ra_idx:
            m = ITAB_RE.match(lines[j])
            if m:
                ichain_id, bit, kind, op, rest = (
                    int(m.group(1)),
                    int(m.group(3)),
                    m.group(4),
                    m.group(5),
                    m.group(6),
                )
                frame_off = None
                # "isvar  M  8  -244vreg" / "isvar P 8 0vreg"
                fm = re.search(r"(isvar\s+[PM])\s+\d+\s+(-?\d+)vreg", lines[j])
                if fm:
                    frame_off = int(fm.group(2))
                if bit not in itab:
                    itab[bit] = dict(
                        ichain=ichain_id,
                        kind=kind,
                        op=op,
                        operands=rest.strip(),
                        frame_off=frame_off,
                        cls=(
                            "P"
                            if "isvar   P" in lines[j]
                            else ("M" if "isvar   M" in lines[j] else "op")
                        ),
                    )
            j += 1

    # coloring decisions between ra_idx and hi_idx
    decisions = []
    order_c = order_u = 0
    for j in range(ra_idx, hi_idx):
        ln = lines[j]
        m = ASSIGN_RE.match(ln)
        if m:
            d = Decision(int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4)))
            if d.kind == "constrained":
                d.order = order_c
                order_c += 1
            else:
                d.order = order_u
                order_u += 1
            decisions.append(d)
            continue
        m = NOCOLOR_RE.match(ln)
        if m:
            decisions.append(Decision(int(m.group(1)), int(m.group(2)), "spilled"))
            continue
        m = SPLIT_RE.match(ln)
        if m:
            decisions.append(
                Decision(
                    int(m.group(1)), int(m.group(2)), "split", split_to=int(m.group(3))
                )
            )
            continue
    return decisions, itab


# ---------------------------------------------------------------------------
# .s parsing : physical register usage histogram
# ---------------------------------------------------------------------------
SREG_RE = re.compile(
    r"\$(v0|v1|a0|a1|a2|a3|t0|t1|t2|t3|t4|t5|t6|t7|t8|t9|"
    r"s0|s1|s2|s3|s4|s5|s6|s7|ra|gp|sp|fp|zero|at|k0|k1|"
    r"f\d+)\b"
)


def parse_s_regs(path):
    hist = collections.Counter()
    if not path:
        return hist
    for ln in open(path, errors="replace"):
        # strip comment block /* ... */
        code = re.sub(r"/\*.*?\*/", "", ln)
        # take the instruction operands (after the mnemonic)
        for r in SREG_RE.findall(code):
            hist[r] += 1
    return hist


# ---------------------------------------------------------------------------
# Instruction-stream diff (register-renumber detection)
# ---------------------------------------------------------------------------
ALIAS_MN = {"move": "or", "nop": "nop"}
INT_REGS = [
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
    "ra",
    "at",
    "sp",
    "fp",
    "gp",
    "zero",
    "k0",
    "k1",
]


def _norm_insn(s, keep_regs=True):
    """Canonicalize an instruction for structural comparison. objdiff scores
    aliases (move/or, li/addiu) and branch targets as equal, so we normalize
    those. If keep_regs is False, register names are wildcarded -- used to
    decide whether two instructions differ ONLY by register (a coloring
    renumber) vs structurally."""
    s = re.sub(r"/\*.*?\*/", "", s).strip().replace("$", "")
    s = re.sub(r"^\s*[0-9a-f]+:\s*", "", s)
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    p = s.split(" ", 1)
    mn = p[0]
    ops = p[1] if len(p) > 1 else ""
    ops = ops.replace(", ", ",").replace(" ", "")
    ops = re.sub(r"<[^>]*>", "", ops)
    ops = re.sub(r"\((0x[0-9a-fA-F]+)>>16\)", "HI", ops)
    ops = re.sub(r"\((0x[0-9a-fA-F]+)&0xFFFF\)", "LO", ops)
    ops = re.sub(r"%hi\([^)]*\)", "HI", ops)
    ops = re.sub(r"%lo\([^)]*\)", "LO", ops)
    ops = re.sub(r"\.L[0-9A-Fa-f]+", "@", ops)
    ops = re.sub(r"func_[0-9A-Fa-f]+", "FN", ops)
    ops = re.sub(r"D_[0-9A-Fa-f]+", "SYM", ops)
    if mn == "move":
        mn, ops = "or", ops + ",zero"
    elif mn == "li":
        mn, ops = "addiu", "zero," + ops  # rough; addiu rd,zero,N
    if mn == "lui":
        ops = re.sub(r",\d+$", ",HI", ops)
    # branch/jump target token (label or hex addr) -> wildcard
    if mn[0] == "b" or mn in ("j", "jal", "jr"):
        ops = re.sub(r",(@|[0-9a-f]{2,5})$", ",@", ops)
        ops = re.sub(r"^(@|[0-9a-f]{2,5})$", "@", ops)

    # numeric literals -> decimal
    def cv(m):
        try:
            return str(int(m.group(0), 0))
        except Exception:
            return m.group(0)

    ops = re.sub(r"-?0x[0-9a-fA-F]+|-?\b\d+\b", cv, ops)
    if not keep_regs:
        for r in sorted(INT_REGS, key=len, reverse=True):
            ops = re.sub(r"\b%s\b" % r, "R", ops)
        ops = re.sub(r"\bf\d+\b", "F", ops)
    return mn + " " + ops


def diff_streams(target_s, build_s):
    """Align target vs build instruction streams; classify diffs as
    register-renumber (same op, regs differ) vs structural (op/shape differs).
    """
    import difflib

    t_raw = [
        ln
        for ln in (re.sub(r"/\*.*?\*/", "", ln) for ln in open(target_s))
        if ln.strip()
        and not ln.strip().startswith(("glabel", "nonmatching", ".", "/*"))
    ]
    b_raw = [ln for ln in open(build_s) if ln.strip()]
    t = [x for x in (_norm_insn(ln) for ln in t_raw) if x]
    b = [x for x in (_norm_insn(ln) for ln in b_raw) if x]
    tw = [x for x in (_norm_insn(ln, keep_regs=False) for ln in t_raw) if x]
    bw = [x for x in (_norm_insn(ln, keep_regs=False) for ln in b_raw) if x]

    sm = difflib.SequenceMatcher(None, t, b, autojunk=False)
    exact = sum(i2 - i1 for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "equal")
    print(
        "\n--- INSTRUCTION-STREAM DIFF (target=%d build=%d insns) ---"
        % (len(t), len(b))
    )
    print(
        "  exact-aligned (incl. reg names): %d  (%.1f%%)"
        % (exact, 100.0 * exact / max(1, len(t)))
    )

    # Re-align on the register-WILDCARDED streams: where these match but the
    # reg-keeping streams don't, the diff is PURELY a register renumber.
    smw = difflib.SequenceMatcher(None, tw, bw, autojunk=False)
    renumber = collections.Counter()  # (target_reg -> build_reg) at renumber sites
    struct_blocks = []
    for tag, i1, i2, j1, j2 in smw.get_opcodes():
        if tag == "equal":
            for ti, bi in zip(range(i1, i2), range(j1, j2)):
                if t[ti] != b[bi]:
                    # same shape modulo regs -> extract the reg pairing
                    tr = re.findall(r"\b(" + "|".join(INT_REGS) + r"|f\d+)\b", t[ti])
                    br = re.findall(r"\b(" + "|".join(INT_REGS) + r"|f\d+)\b", b[bi])
                    for a, c in zip(tr, br):
                        if a != c:
                            renumber[(a, c)] += 1
        else:
            struct_blocks.append((tag, i1, i2, j1, j2, t[i1:i2], b[j1:j2]))
    wmatch = sum(i2 - i1 for tag, i1, i2, _, _ in smw.get_opcodes() if tag == "equal")
    print(
        "  shape-aligned (reg-wildcarded): %d  (%.1f%%)"
        % (wmatch, 100.0 * wmatch / max(1, len(tw)))
    )
    print(
        "  => %d insns are SHAPE-CORRECT but REGISTER-RENUMBERED (coloring residual)"
        % (wmatch - exact + sum(1 for _ in ()))
    )

    if renumber:
        print("\n  REGISTER-RENUMBER pairs (target_reg <- build_reg : count):")
        for (a, c), n in renumber.most_common():
            print("    $%-4s <- $%-4s   x%d" % (a, c, n))
        print(
            "  Interpretation: the build colors these values one position off."
            "\n  Use the coloring trace above to find the LRs holding them and"
            "\n  adjust their coloring ORDER (priority/bitpos) per the levers."
        )
    if struct_blocks:
        print("\n  STRUCTURAL diffs (op/shape differs -- NOT just coloring):")
        for tag, i1, i2, j1, j2, tb, bb in struct_blocks[:15]:
            print("    [%s] T[%d:%d] B[%d:%d]" % (tag, i1, i2, j1, j2))
            for x in tb[:4]:
                print("      T %s" % x)
            for x in bb[:4]:
                print("      B %s" % x)


# ---------------------------------------------------------------------------
# Analysis / solver
# ---------------------------------------------------------------------------
def analyze(decisions, itab, target_hist, build_hist, func):
    print("=" * 72)
    print("COLORING-SOLVE  %s" % func)
    print("=" * 72)

    constrained = [d for d in decisions if d.kind == "constrained"]
    unconstrained = [d for d in decisions if d.kind == "unconstrained"]
    spilled = [d for d in decisions if d.kind == "spilled"]
    splits = [d for d in decisions if d.kind == "split"]

    print(
        "\nLR census: %d colored constrained, %d colored unconstrained, "
        "%d spilled (-ve save), %d split"
        % (len(constrained), len(unconstrained), len(spilled), len(splits))
    )

    # --- which LR has the largest live range / lowest priority? ---
    # We can't read adjsave directly, but the CONSTRAINED phase colors in
    # max-priority order, so the LAST constrained LR colored has the lowest
    # priority among the constrained set. The unconstrained set (colored
    # after) are the lowest-priority overall. The base-pointer-in-arg-reg
    # cap is: target's longest-span LR colors LAST and lands in an arg reg.
    def show(d):
        ib = d.lr_bitpos
        meta = itab.get(ib, {})
        anno = ""
        if meta:
            anno = "  [ichain {%s} %s %s off=%s]" % (
                meta.get("ichain"),
                meta.get("op"),
                meta.get("cls"),
                meta.get("frame_off"),
            )
        r = regname(d.reg) if d.reg is not None else "-"
        arg = "  <-- ARG REG" if d.reg in ARG_REGS else ""
        ee = "  (callee-saved, firstUseCost paid)" if d.reg in CALLEE_SAVED else ""
        return "lr %4d  ord %3s  %-13s -> %-5s%s%s%s" % (
            ib,
            d.order if d.order is not None else "-",
            d.kind,
            r,
            anno,
            arg,
            ee,
        )

    print(
        "\n--- CONSTRAINED phase (colored by MAX priority; earlier = higher "
        "priority = grabs lower reg) ---"
    )
    for d in constrained:
        print("  " + show(d))
    if unconstrained:
        print(
            "\n--- UNCONSTRAINED phase (colored in BITPOS order; lowest "
            "priority overall) ---"
        )
        for d in unconstrained:
            print("  " + show(d))
    if splits:
        print("\n--- SPLIT (live-range split: cost >= value) ---")
        for d in splits:
            print(
                "  lr %d split out to %d  [%s]"
                % (d.lr_bitpos, d.split_to, itab.get(d.lr_bitpos, {}).get("op", "?"))
            )

    # arg-register occupants in the build (the cap symptom is when target
    # puts a long-lived base ptr in a0 but build does not)
    arg_occupants = [d for d in decisions if d.reg in ARG_REGS]
    print("\n--- ARG-REGISTER occupants in the BUILD ---")
    if not arg_occupants:
        print(
            "  (none -- build colors nothing into a0..a3; "
            "if target uses an arg reg for a held value, that LR must be "
            "DEMOTED in priority so it colors last)"
        )
    for d in arg_occupants:
        print("  " + show(d))

    # --- target vs build register histogram delta ---
    if target_hist and build_hist:
        print("\n--- PHYSICAL REGISTER USE: target vs build (.s histograms) ---")
        allregs = sorted(set(target_hist) | set(build_hist), key=lambda r: (r[0], r))
        print("  %-5s %6s %6s %6s" % ("reg", "target", "build", "delta"))
        for r in allregs:
            t, b = target_hist.get(r, 0), build_hist.get(r, 0)
            if t != b:
                print(
                    "  %-5s %6d %6d %+6d  %s"
                    % (
                        r,
                        t,
                        b,
                        t - b,
                        "<-- target uses MORE" if t > b else "<-- build uses MORE",
                    )
                )
        print("  (regs with equal counts omitted)")

    # --- derived levers ---
    print("\n--- ALGORITHM-DERIVED LEVERS ---")
    print("  * A value the TARGET holds in an ARG register (a0..a3) but the")
    print("    BUILD holds in a low caller reg (v0/v1) is colored TOO EARLY in")
    print("    the build: its priority is too high. To push it to an arg reg,")
    print("    color it LAST -> LOWER its priority via SPAN EXTENSION (hold it")
    print("    live across more BBs) so every short per-block deref colors")
    print("    first and takes v0/v1; the held value lands in a0.")
    print("  * Two equal LRs swapping low registers (e.g. t4<->t5): change")
    print("    their relative FIRST-OCCURRENCE order in the source. If one is")
    print("    CONSTRAINED and the other UNCONSTRAINED, the constrained one")
    print("    colors first (grabs the lower reg) regardless of bitpos --")
    print("    make the wanted-lower one constrained, or both unconstrained.")
    print("  * 'not colored (-ve save)' LR = a spill home (frame word). To")
    print("    remove a spill, raise that LR's priority (more uses, shorter")
    print("    span). To ADD a spill home that the target has, declare a dead")
    print("    local (kills the slot) -- see the dead-local frame lever.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--trace", required=True, help="-Wo,-zdbug:6 uoptlist")
    ap.add_argument("--func", required=True, help="function symbol")
    ap.add_argument("--target-s", help="target .s")
    ap.add_argument("--build-s", help="build's disassembled .s")
    args = ap.parse_args()

    decisions, itab = parse_trace(args.trace, args.func)
    target_hist = parse_s_regs(args.target_s)
    build_hist = parse_s_regs(args.build_s)
    analyze(decisions, itab, target_hist, build_hist, args.func)
    if args.target_s and args.build_s:
        diff_streams(args.target_s, args.build_s)


if __name__ == "__main__":
    main()
