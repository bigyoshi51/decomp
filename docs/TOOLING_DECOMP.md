# Tooling Decomp

> Decompilation tooling: m2c, Ghidra, the permuter, decomp.dev integration.

_9 entries. Auto-generated from per-memo notes; content may be rough on first pass — light editing welcome._

## Index

- [`discover --sort-by size` marks every INCLUDE_ASM placeholder as `[has source]` — write a sub-filter for genuinely-unstarted candidates](#feedback-discover-has-source-misleading) — Discover treats any mention of a symbol in `src/` as "has source", including bare `INCLUDE_ASM(...)` lines. For source-3 picks (small unstarted), use a Python filter that checks for an actual C function definition (`(void|int|...) name(...)` syntax), not just the symbol name.
- [Decomp prioritization — call-graph DFS from entry point beats by-segment-size mass-match](#feedback-decomp-call-graph-priority) — When a project has a clear entry point (USO loader → main loop → per-frame update), depth-first decomp from there reveals the actually-used code and naturally drives type discovery.
- [m2c on .word-only USO asm — assemble + objdump round-trip to get mnemonics](#feedback-m2c-word-only-asm) — splat emits `.word 0xNNNNNNNN` for USO functions whose lui-relocations spimdisasm can't resolve; m2c then errors with "Function contains no instructions". Round-trip the bytes through `mips-linux-gnu-as` + `objdump -d -M no-aliases` to get readable mnemonics for hand-paste into a temp .s.
- [Scanning NM wraps for near-misses: compare the LINKED elf, not the unlinked .o (jal/symbol immediates are 0 in the .o → false diffs)](#feedback-nm-wrap-scan-use-linked-elf) — _2026-05-23. To auto-find promotable NM wraps, building `build/non_matching/.../<file>.c.o` and diffing each function's words against `asm/.../<func>.s` reports a FALSE 1-diff for every resolved-call/symbol-ref function: in the unlinked .o, `jal target` is `0C000000` and `lui/addiu/lw` symbol immediates are 0, while the asm shows the resolved values. So `gl_func_00024080` (already episode'd, calls `gl_ref_00037F80`) shows as "1/8 regonly JAL" — a false positive. Only RELOC-FREE functions (no jal, no symbol lui/addiu) give a valid .o-vs-asm comparison; for everything else, link first and diff `build/tenshoe.elf` (default path) or the linked non_matching elf. Also: cross-check `ls episodes/<func>.json` — the scan resurfaces already-done functions whose `.NON_MATCHING` alias artifact looks like a near-miss._
- [decomp-permuter `import.py` needs a C body under `#ifdef NON_MATCHING` — bare `INCLUDE_ASM` invisible](#feedback-permuter-import-requires-ifdef-non-matching-body) — _When you intend to grind a function via permuter, the verified decode MUST be wrapped in `#ifdef NON_MATCHING / #else INCLUDE_ASM` (even at sub-80% fuzzy where the `/decompile` skill normally says "keep plain INCLUDE_ASM"). `import.py` parses C source for a function DEFINITION; `INCLUDE_ASM(funcname)` alone registers no function. Discovered 2026-05-16 via parallel-agent commits restoring DBEC/DDC0 C bodies as permuter seeds._
- [WORKING permuter setup (2026-05-23): `permuter_settings.toml` (compiler_type=ido) + import with full `CPPFLAGS=-I include -I src -DNON_MATCHING`](#feedback-permuter-working-setup-2026-05-23) — _The 0/6 F444 failure was a MISCONFIG, not a permuter limitation: no settings file and the import lacked `-DNON_MATCHING` (so it compiled the `#else INCLUDE_ASM` path, no C body) and `-I include -I src` (headers). Fixed; validated gl_func_0005C784 base 75→35 with 0 errors. This is the sanctioned last-mile match tool now that INSN_PATCH is banned._
- [Permuter "score 0" is a FALSE POSITIVE for pure spill-slot (sp-offset) swaps — its scorer normalizes sp-relative offsets; ALWAYS raw-byte-verify before logging an episode](#feedback-permuter-score-0-sp-offset-false-positive) — _gl_func_0005D054 (quaternion product): permuter reported base score 0 but `cmp` of the built .text vs target still differed by one x↔z spill-slot pair (32↔40(sp))._
- [CI / decomp.dev compares fresh build/.o vs committed expected/.o — `make expected` results MUST be git-committed for changes to show on the dashboard](#feedback-expected-must-be-committed-for-decomp-dev) — The land script and `scripts/refresh-report.sh` do NOT run `make expected`.
- [Ghidra struct annotation does NOT auto-propagate across xrefs — each function in a family needs its own prototype set](#feedback-ghidra-struct-annotation-doesnt-auto-propagate) — _Validated 2026-05-04 on 1080's rmon family.
- [Permuter DOES crack small (low-score) load-order / instruction-scheduling residuals — try it on 1-3 diff scheduling near-misses](#feedback-permuter-cracks-small-load-order) — _A 2-diff load-ORDER residual (base score 20) that ~10 hand C variants couldn't flip cracked at iteration 18 (~30s): the winning mutation combined two stores into `a0[0]=(a0[1]=a0)`, shifting IDO's tail scheduling. When diffs are operand/load ORDER (same opcodes/regs, reordered) — NOT $s-reg renumber — run the permuter with `--stop-on-zero`. Import: `C_INCLUDE_PATH=include python3 .../import.py src/<f>.c <clean-glabel.s> CPPFLAGS=-DNON_MATCHING`. Verified game_libs_func_00066440._
- [Permuter scores ≥1000 genuinely mean "structural issue, no match possible" — stop grinding (BUT 2026-05-23 refinement: it CAN crack record-append/pointer-arith $t-class register-renumber via shape-changing mutations — 2 episodes; resists loops/delay-slot/cursor/unfilled-delay/$s-$a-class)](#feedback-permuter-1000-plus-structural) — _Ran decomp-permuter random mode for ~3 minutes on `n64proc_uso_func_00000014` (12k+ iterations).
- [pyghidra-mcp setup notes for N64 decomp work — JDK 21, raw-binary load, MIPS:BE:32:default, ~7-min auto-analysis](#feedback-pyghidra-mcp-setup-for-n64-decomp) — pyghidra-mcp install gotchas verified 2026-05-04.
- [report.json was overstating because land script used `make expected` — RESOLVED 2026-05-04](#feedback-report-json-vs-decomp-dev-diverge) — _HISTORICAL — the land script's `make expected` blanket-cp build/→expected/ used to pollute expected/ with decomp-bodies build, inflating matched_code_percent by ~1pp (8.84% reported vs 7.68% truth).
- [When to consult Ghidra during /decompile (trigger list — m2c remains the default)](#feedback-when-to-consult-ghidra-during-decomp) — _1080 has a Ghidra project + MCP server, but reaching for Ghidra has cost (slower than m2c, GCC-flavored not IDO-flavored).


---

<a id="feedback-discover-has-source-misleading"></a>
## `discover --sort-by size` marks every INCLUDE_ASM placeholder as `[has source]` — write a sub-filter for genuinely-unstarted candidates

_Discover treats any mention of a symbol in `src/` as "has source", including bare `INCLUDE_ASM(...)` lines. For source-3 picks (small unstarted), use a Python filter that checks for an actual C function definition (`(void|int|...) name(...)` syntax), not just the symbol name._

**Symptom (verified 2026-05-08 on 1080):** Running `uv run decomp discover --sort-by size` and walking the head of the list — `__osSetFpcCsr` (libreultra `.s`, skip), `func_80009EA0` (`.rodata`, skip), `func_800073DC` (cap-confirmed fragment), `func_0000E9FC` (NM-86 cap-confirmed), `mgrproc_uso_func_000032F8` (reloc-encoding cap-confirmed) — produces zero genuinely-fresh candidates among the smallest 9 entries even though all are tagged `[has source]`. The "[has source]" tag is true (each appears in `src/`), but the content is just `INCLUDE_ASM("...", funcname);`, not a decompiled body.

**Sub-filter recipe:**
```python
# In project root. Walks asm/nonmatchings/, filters out functions whose
# only mention in src/ is an INCLUDE_ASM line. Keeps small candidates.
import os, re, subprocess
for root, _, files in os.walk('asm/nonmatchings'):
    for f in files:
        if not f.endswith('.s'): continue
        with open(os.path.join(root, f)) as fp:
            line1 = fp.readline()
        m = re.match(r'nonmatching\s+(\S+),\s+0x([0-9A-Fa-f]+)', line1)
        if not m: continue
        name, size = m.group(1), int(m.group(2), 16)
        if size > 0x60: continue
        r = subprocess.run(['grep', '-rln', name, 'src/'],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f'TRULY-UNSTARTED size={size} {name}'); continue
        # Has source — but is it a real C body?
        has_body = False
        for src in r.stdout.strip().split('\n'):
            with open(src) as sf: txt = sf.read()
            if re.search(r'\b(void|int|char|float|s32|u32|s8|u8|short)\s*\*?\s*'
                         + re.escape(name) + r'\s*\(', txt):
                has_body = True; break
        if not has_body:
            print(f'INCLUDE_ASM-only size={size} {name}')
```

**Why the gap:** Splat emits `INCLUDE_ASM(...)` lines for every disassembled function in the parent `.c` file at project setup, so EVERY function reads as `[has source]` from day 0. Discover's `[has source]` flag was designed to suppress trivial duplicates, not to mean "decompiled C exists" — but read naively it suggests prior work has already happened and biases away from these candidates.

**How to apply:**
- For source-3 picks (random-roll): run the sub-filter to find genuinely-unstarted small candidates (e.g. 8-byte save-arg sentinels, save-arg-+-return-1 stubs, `func_00000000` 1-call wrappers).
- The sub-filter is also useful for source-4 (untouched USOs): scan an entire USO segment in one pass for INCLUDE_ASM-only entries before deciding it's "exhausted" of small targets.
- Discover's tag remains correct for filtering parallel-agent-collisions (don't pick a function someone else is mid-decomp on) — the tag covers more, not less, than true "has body".

**Two further false-positive classes the sub-filter still misses (verified 2026-05-08 on 1080 kernel):**

1. **Symbol absorbed by larger-predecessor INCLUDE_ASM.** When splat emits multiple `.s` files for what's actually one function (e.g. `func_80008E08.s`, `func_80008E38.s` — both inside the predecessor `func_80008DF0`'s 0xA8-byte symbol that ends at 0x80008E98), only the LARGEST .s gets an INCLUDE_ASM line; the absorbed siblings have NO mention in `src/` at all. The sub-filter's `grep -rln name src/` returns empty, flagging them as "TRULY-UNSTARTED" — but their bytes are emitted via the predecessor's INCLUDE_ASM, and there's no work to do. To detect: check `undefined_syms_auto.txt` for an entry like `func_X = 0xX;` AND grep for the function in NEARBY `.s` files for the size-larger predecessor whose declared `nonmatching SIZE` covers the absorbed offset. If covered, skip — splat cruft, not work.

2. **Cap-doc'd structurally-uncapable functions wrapped under `_unreachable` stub names.** Functions documented as standalone-uncompilable (chained-suffix register inheritance, prologue-stolen-successor with too-deep predecessor tail, etc.) are sometimes wrapped as `extern void <func>_unreachable(...)` inside `#if 0 ... #endif` instead of the standard `#ifdef NON_MATCHING / #else INCLUDE_ASM`. The sub-filter's regex `(void|int|...) name(...)` doesn't match `name_unreachable(...)`, so these flag as INCLUDE_ASM-only. To detect: also grep for `<funcname>_unreachable` (or `<funcname>_alt`, etc.) and any `#if 0` block referencing the function name in its trailing comment. If present, skip — already cap-doc'd.

3. **Asm orphan post-merge** — `merge-fragments` consolidated bytes into the predecessor and re-exported the absorbed symbol via `undefined_syms_auto.txt`, but the absorbed `.s` file was left on disk. The asm file is unreferenced from any INCLUDE_ASM (no `INCLUDE_ASM(... funcname);` anywhere in `src/`), the symbol IS declared `extern` from one or more callers, and `undefined_syms_auto.txt` has a `funcname = 0xADDR;` line for it. Discover and the sub-filter both surface it as INCLUDE_ASM-only because the `extern` declarations satisfy "src mentions" but no real C body matches the regex. Real work was done (the merge); the asm file is just cleanup debris. Distinct from class 1 — class 1 is splat-cruft never-touched; class 3 is post-merge cleanup left undone. **To detect**: a one-liner — `grep -L 'INCLUDE_ASM.*funcname' src/**/*.c | wc -l` and `grep -c '^funcname' undefined_syms_auto.txt`; if no INCLUDE_ASM and undefined_syms_auto has the entry, the `.s` file is the orphan. **Action**: delete the `.s` file; build is unaffected (bytes come from the predecessor's INCLUDE_ASM, symbol resolution comes from undefined_syms_auto). Splat re-runs will re-emit it, so `git checkout --` revert any re-emission per the splat-rerun-gotchas note. Verified 2026-05-08 on `func_80009C30` (was absorbed into `func_80009B60`'s 0xE0-byte body).

All three classes consume tick budget if not pre-filtered. Adding `'has_unreachable_stub'` and `'absorbed_by_predecessor'` checks to the Python sub-filter would surface only fresh candidates. Untracked TODO; for now, when source-3 yields a fishy candidate (4-insn shared-tail epilogue, fragment lacking jr ra, `lui+addiu+...` setup-only body), skim adjacent `.s` files and `src/`'s nearby comments before grinding.

---

<a id="feedback-decomp-call-graph-priority"></a>
## Decomp prioritization — call-graph DFS from entry point beats by-segment-size mass-match

_When a project has a clear entry point (USO loader → main loop → per-frame update), depth-first decomp from there reveals the actually-used code and naturally drives type discovery. Mass-matching the largest segment first produces matched-but-disconnected wrappers that don't tell you anything._

**Rule:** When working a decomp project where the strategic goal is understanding (port, modding, deep analysis) — not just match-percentage — pick the next function by **traversing the call graph from a known entry point**, not by "biggest segment with most unmatched functions."

**Why call-graph DFS wins:**

1. **Reveals what code actually matters.** Many functions in middleware segments (e.g. 1080's game_libs, papermario's libgcc helpers) are linked-but-never-called dead utilities. Following the call graph from `main` skips those.
2. **Drives type discovery in the right order.** Each function call tells you the callee's parameter types. Each struct access tells you the struct's shape. By the time you've decompiled 50 reachable functions, you've SEEN the engine-state struct fields enough to type it.
3. **Builds a coherent narrative.** "Per-frame update calls physics calls collision detection" is something you can explain. "I matched 200 chain wrappers in game_libs" isn't.
4. **Type-just-in-time becomes natural.** When the 5th function accesses `gl_ref_00021CBC[3]`, you know it's the engine state's frame counter, and you can type it.

**Anti-pattern (and what we caught ourselves doing on 1080 in agent-d's session 2026-04-19):**

Mass-matching game_libs because it's the biggest segment with the most easy wins. We matched ~200 wrapper functions. They're matched, episode-logged, training data. But they don't tell us how snowboarding physics works, what the Player struct looks like, or how the renderer is structured. They're matched-but-meaningless coverage.

**How to apply:**

1. **Find the entry point.** For relocatable USO games like 1080, this is the first function in the main game USO's text section.
2. **Read its callees.** Each `jal` is a child node.
3. **For each child:** if same USO, decompile next. If cross-USO (e.g. `jal gl_func_00000000`), pull the right game_libs function.
4. **Decompile depth-first.** A leaf function is one that only calls libultra primitives or has no calls.
5. **Type structs as they reveal themselves.** Wait until 5+ accesses to triangulate the field, then refactor retroactively.
6. **Mass-match the rest as background.** Once the spine is done, the remaining wrappers are throughput work that doesn't block understanding.

**When mass-match IS the right move:**

- Pure training-data goal (`decomp/` repo's primary mission).
- Idle agent capacity that would otherwise waste cycles.
- Boundary cleanup before a complex segment.
- When a wrapper family is so large (50+ functions, all the same shape) that pattern-matching it once unlocks all of them in 30 minutes.

**Trigger to re-evaluate priority:** if you've matched 50 functions in a row that don't change your mental model of the game, you're mass-matching when you should be call-graph-DFS-ing.

**Origin:** 2026-04-19 1080 Snowboarding strategic conversation. After splatting all USOs (14 segments, ~1750 functions accessible), the question of "what to decompile next" surfaced the realization that defaulting to game_libs's biggest-segment status was wrong. The user explicitly wants 100% decomp ending in a clean PC-portable codebase — call-graph DFS from game.uso's entry better serves that goal than "match the most functions per day."

---

---

<a id="feedback-expected-must-be-committed-for-decomp-dev"></a>
## CI / decomp.dev compares fresh build/.o vs committed expected/.o — `make expected` results MUST be git-committed for changes to show on the dashboard

_The land script and `scripts/refresh-report.sh` do NOT run `make expected`. CI checks out the repo, builds fresh `build/.o`, then runs `objdiff-cli report` which compares against the COMMITTED `expected/.o` files. If the committed `expected/` is stale (older than the source changes), CI scores the new build against the old baseline and the % shown on decomp.dev is wrong/stale._

**Rule:** Whenever a function's `.o` BYTES change (decompile, NM-wrap, pragma addition, etc.), `expected/<file>.c.o` must be regenerated AND COMMITTED. Otherwise CI / decomp.dev shows the wrong %.

**Why this matters:**

- The local workflow runs `make expected` after a successful match → local `report.json` shows correct %. ✓
- The land script (`scripts/land-successful-decomp.sh`) regenerates `report.json` locally but does NOT touch `expected/`. ✗
- CI does NOT run `make expected` either — it reuses whatever's committed. ✗
- decomp.dev fetches the CI artifact `us_report` (= `report.json`), so it shows whatever CI computed. ✗

**Symptom:** local says 5.08 % matched, decomp.dev says 5.01 %. The 0.07 % gap = N functions whose source changed but whose `expected/.o` wasn't refreshed in the same commit.

**How to apply:**

After ANY change that affects compiled output (decomp, NM wrap, GLOBAL_ASM pragma add, asm-processor directive, OPT_FLAGS override):

1. `make RUN_CC_CHECK=0` — produces `build/<file>.c.o`
2. `make expected RUN_CC_CHECK=0` — copies `build/.o` → `expected/.o`
3. `git add expected/src/<file>.c.o` — STAGE the refreshed baseline
4. Commit BOTH the source change AND the expected refresh in the same commit (or as paired commits).
5. Push.

**The land script handles this automatically as of commit 24e6443 (2026-04-20).** After validating the named functions match exact, it runs `make expected RUN_CC_CHECK=0` and creates a follow-up commit ("Refresh expected/ baseline for <func> land") if any `expected/.o` files changed. Agents using `scripts/land-successful-decomp.sh` no longer need to remember step 2-4 above.

**For sweeping changes (e.g., trim-trailing-nops rollout):** ALWAYS commit the fresh `expected/` after the source-change commit. 22 expected/.o files were stale after the pad-sidecar rollout because I forgot this — committing them bumped the CI / decomp.dev % from 5.01 % → expected ~5.08 %.

**Edge case:** `expected/` files are binary blobs. `git diff --stat` shows them as 0 lines but Bin XXX -> YYY bytes. They're NOT compressible by .gitignore (`*.o` would gitignore them — they're force-tracked despite the pattern).

---

---

<a id="feedback-ghidra-struct-annotation-doesnt-auto-propagate"></a>
## Ghidra struct annotation does NOT auto-propagate across xrefs — each function in a family needs its own prototype set

_Validated 2026-05-04 on 1080's rmon family. Setting `RmonMsg *msg` on func_80006D0C makes its decomp use `msg->type / msg->id / msg->domain`. Sibling func_80006C64 (also takes RmonMsg per source) keeps showing `*(int*)(param_1+0xc)` until it's individually annotated. Batch-script the family to apply prototypes wholesale._

**The good news**: setting a function prototype + parameter type in Ghidra DOES change decomp output exactly as expected — `*(byte*)(param_1+4)` becomes `msg->type` etc. Validated end-to-end via direct pyghidra (bypassing pyghidra-mcp's MCP layer, which had separate hangs).

**The mediocre news**: this requires Ghidra's `Function.updateFunction()` with a fully-built signature (return type + parameter list) and `SourceType.USER_DEFINED`. The MCP server's `set_function_prototype` tool wraps this, but pyghidra-mcp had a hung-call bug in our session. Direct pyghidra worked first try.

**The annoying news**: type info **does not propagate across xrefs automatically**. If you annotate `func_80006D0C(RmonMsg *msg)`, callers and same-prototype siblings stay untyped. Each function in a family needs its own prototype set.

**Workflow recipe (1080 / rmon as the example):**

1. Find the family via `list_xrefs` to a known shared callee (e.g. `__rmonSendHeader` = FUN_000073f8 in our project — 27 rmon callers in one query).
2. Define the struct ONCE in the data type manager (Ghidra's data type categories are project-global).
3. Loop over the family, calling `func.updateFunction(...)` with the prototype.

Sketch:
```python
from java.util import ArrayList
from ghidra.program.model.listing import ParameterImpl, ReturnParameterImpl
from ghidra.program.model.listing.Function import FunctionUpdateType
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.data import IntegerDataType

# Inside a transaction:
RMON_FAMILY = ["func_80006C64", "func_80006D0C", "func_80006BD8", ...]
for name in RMON_FAMILY:
    f = ... # lookup function
    params = ArrayList()
    params.add(ParameterImpl("msg", rmon_msg_ptr, program))
    f.updateFunction(
        None,                                            # keep calling convention
        ReturnParameterImpl(IntegerDataType.dataType, program),
        params,
        FunctionUpdateType.DYNAMIC_STORAGE_FORMAL_PARAMS,
        True,                                            # force override
        SourceType.USER_DEFINED,
    )
```

Cost is one transaction per N functions — fast even for 30+ at once.

**Where the value still wins big**:
- Define struct once → applies to all N functions you annotate (vs m2c which has no project-level type memory).
- Field-name decomp is far easier to read than `*(byte*)(param_1+0x9)`.
- Cross-function consistency: if two functions both access `msg->domain`, you SEE that they do, by name. Easier to spot family patterns.

**Where it doesn't help**:
- "Annotate one function, see types everywhere" — no, doesn't work that way. Plan to batch-annotate.
- m2c-style codegen-fidelity for IDO matching — Ghidra's GCC-flavored output won't byte-match. Use Ghidra for *understanding*, m2c for *codegen*.

**Concrete in 1080**: see `scripts/ghidra-annotate-rmon.py` (committed) for a working example. Scales by adding to the family list.

---

---

<a id="feedback-permuter-cracks-small-load-order"></a>
## Permuter DOES crack small (low-score) load-order / instruction-scheduling residuals — try it on 1-3 diff scheduling near-misses before giving up

_Counter to the "permuter only floors" instinct: for a SMALL near-miss (base score ~20, 2 raw diffs) that's a pure instruction-SCHEDULING residual — not an $s-reg renumber — the permuter finds the fix fast. Verified 2026-05-28 `game_libs_func_00066440` (circular-dlist remove-self): the unlink's `next->prev = prev` loaded `a0->0` before `a0->4` in the target, and ~10 hand-written C variants couldn't flip that load order. Permuter cracked it at iteration 18 (~30s) — the winning mutation combined the two self-link stores into `a0[0] = (a0[1] = (int)a0)`, a shape change that shifted IDO's tail scheduling enough to flip the earlier load order (a non-obvious global effect no human would guess). Lesson: when a merge/decode lands at 1-3 diffs and the diffs are operand/load ORDER (same opcodes, same regs, reordered) rather than $s-reg renumber, run the permuter with `--stop-on-zero` — it's the right tool and it's fast here. Import recipe: clean target `.s` (just `glabel <fn>` + `.word` lines, no `nonmatching`/`endlabel`), then `C_INCLUDE_PATH=include python3 tools/decomp-permuter/import.py src/<seg>/<file>.c <clean.s> CPPFLAGS=-DNON_MATCHING` (C_INCLUDE_PATH lets cpp find common.h; equivalently pass `CPPFLAGS=-I include -I src -DNON_MATCHING`), then `permuter.py nonmatchings/<fn> --stop-on-zero -j2`. Distinct from [the ≥1000 structural-cap note below](#feedback-permuter-1000-plus-structural): that's about HIGH scores / $s-reg renumber where it floors; THIS is low-score scheduling where it wins._

**Calibration (2026-05-28, five cases tested) — what the permuter CRACKS vs FLOORS even at a LOW base score:**
- CRACKS: pure instruction/load SCHEDULING reorder (same opcodes+regs, only the emit *order* differs). `game_libs_func_00066440` 20→0.
- FLOORS (don't burn time): (1) **commutative operand-order** — FPU `mul.s`/`add.s` operand swap where a value is pinned by ABI (`$f0` call-return), `gl_func_00052104` 15→5; AND integer `beq`/`bnel` operand-order ($s-first vs $t-first emit normalization), `uso_skip_to_end` 20→10. (2) **register PLACEMENT** — value in `$v1`+`move v0,v1` vs direct `$v0`, `game_libs_func_0002831C` floored ~60. (3) **branch-likely LAYOUT** — `beqzl`-to-end arm placement, `game_libs_func_0005330C` floored ≥885. (4) **preheader loop-invariant-address-setup ordering** — the N `lui+addiu` that materialize loop-invariant pointers in the preheader, emitted in ascending- vs descending-reg order. LOOKS like a crackable scheduling reorder (same opcodes/regs, only order differs) but ISN'T: it's a deterministic IDO loop-hoist/preheader-schedule choice, not perturbed by C mutations. `gl_func_00033B6C` (4 pointer-setup addiu, s0..s3 vs s3..s0) floored at base 85 over ~28k iters (2026-05-29). Rule of thumb: if the 2 diffs are a *reorder of when instructions are emitted* WITHIN the function body, permute; if they're *which register/operand-slot holds a value*, *which arm is laid out where*, OR *the order of preheader loop-invariant address setup*, it's a structural cap — leave NM/INCLUDE_ASM.

<a id="feedback-permuter-1000-plus-structural"></a>
## Permuter scores ≥1000 genuinely mean "structural issue, no match possible" — stop grinding

_Ran decomp-permuter random mode for ~3 minutes on `n64proc_uso_func_00000014` (12k+ iterations). Best score 1030. Per the skill's score-band rubric, 1000+ is "structural issues remain" — and indeed the winning variant only hoisted a `base+0x40` expression into a named local, didn't change any $s-reg assignments. For reg-renumber issues specifically (where target has $s0=X but mine has $s0=Y despite identical logic), random-mode permuter won't crack it; only compiler-version differences or manual `register T x asm("$N")` can — and IDO rejects the latter._

**Origin (2026-04-21, n64proc_uso_func_00000014):**

Setup:
- Function had known 4-way $s-reg renumber mismatch (target s0=cur/s1=flag/s2=one/s3=base/s4=base10/s5=arg0, mine s0/s1/s2=base/s3=one/s4=arg0/s5=base10).
- Already documented as weight-driven in `feedback_ido_sreg_order_not_decl_driven.md` — decl order doesn't flip, literal 1s regress.

Permuter run:
```bash
python3 /home/dan/Documents/code/decomp/tools/decomp-permuter/import.py \
    src/n64proc_uso/n64proc_uso.c \
    asm/nonmatchings/n64proc_uso/n64proc_uso/n64proc_uso_func_00000014.s PERMUTER=1
python3 /home/dan/Documents/code/decomp/tools/decomp-permuter/permuter.py \
    nonmatchings/n64proc_uso_func_00000014 -j4
```
3 minutes, ~12k iterations. Best score: 1030. Dozens of `output-1030-N`, `output-1040-N`, `output-1080-N`, etc. saved.

Best output (score 1030) just added:
```c
int *new_var;                                    /* new local */
new_var = (int *) (((char *) base) + 0x40);      /* hoisted expr */
...
arg1 = *new_var;                                 /* use it */
```
Zero register-renumber changes. The permuter's randomization space didn't include anything that flipped the $s-allocator's weight calculation to match the target.

**Lesson:** for register-renumber-only diffs at the $s-reg level, random-mode permuter is ineffective. The allocator's weight formula is deterministic on the IR, and random C perturbations (hoisting, splitting, renaming) don't change the formula's output ORDER — they just shuffle which expressions exist. You need to change REF COUNTS materially, which is hard to do via random mutations.

**When to skip permuter on an NM wrap:**
- Existing comment notes "register renumber" or "$s-reg swap" as the remaining diff
- Existing comment notes "$a-class register pick" (e.g. target uses $a3, mine uses $a1) — 2026-04-21 update: these also don't crack. Ran permuter on `gl_func_0000D9B8` (base score 20, just 2 $a1/$a3 diff insns). Permuter ran 1000+ iterations, best stayed at 20. Even "close" scores (20 vs 1030) don't mean permuter can close them — reg-class picks are deterministic on IDO's side.
- **$t-class renumber also resists in practice (2026-05-28).** Despite the "$t-class CAN sometimes crack" note above, a concrete test on `gl_func_0000C28C` (59-insn struct-copy + dispatch; 2-insn diff = `lw/sw $t8` mine vs `$t9` target on the `arg0[4]=arg1->a` store) ran ~230s across 8 threads (`--stop-on-zero -j 8`) and never beat **base score 50** — the shape-changing mutation it found (splitting the store into `new_var = arg1->a; arg0[4] = new_var;`) scored an identical 50. The "2 episodes" of $t-renumber cracks were record-append/pointer-arith shapes with a genuinely different ALLOCNO COUNT achievable from C; a plain mid-function $t8↔$t9 swap on an otherwise-fixed shape is NOT reachable. Triage adjacent-$t renumbers as caps unless the diff is in heavy pointer-arith where ref-count can be materially changed.
- Prior passes already tried decl reordering + literal folding
- The skill's band rubric "1000+ structural" applies

When to TRY permuter:
- Remaining diff is 1-3 instructions in leaf-function **scheduling** (operand position in the stream, not register choice)
- Operand swaps on commutative ops (addu, or, and)
- Branch-likely conversion patterns
- Score likely 100-500 band AND the diff isn't a register-pick

**Key distinction:** permuter can flip instruction ORDER but not register ASSIGNMENT. If the target and mine differ only in "what register holds this value" (regardless of $s/$a/$t class), random-mode permuter cannot reach the target — the allocator's decision is deterministic given the RTL shape, and permuter's random C mutations usually preserve the shape enough that the allocator makes the same choice.

**Cost:** ~3 min + a few MB of output variants in `nonmatchings/<func>/`. Always clean up with `rm -rf nonmatchings/` after.

<a id="feedback-permuter-score-0-sp-offset-false-positive"></a>
### Permuter "score 0" is a FALSE POSITIVE for pure spill-slot (sp-offset) swaps — raw-byte-verify before logging an episode

**The permuter's asm scorer normalizes sp-relative offsets**, so two builds that differ ONLY in which stack slot a spilled value lands in score as identical (0) even though the **emitted bytes differ** (the `swc1`/`lwc1` immediate encodes the offset). A permuter "score 0" therefore does NOT prove a byte match — it proves a match modulo stack-slot assignment. **Always confirm with a raw byte-compare before logging an episode:**

```bash
mips-linux-gnu-objcopy -O binary --only-section=.text built.o built.bin
mips-linux-gnu-objcopy -O binary --only-section=.text target.o target.bin
cmp built.bin target.bin   # silent = real match; "differ" = NOT a match
```

**Worked example (2026-05-24, gl_func_0005D054 — quaternion/Hamilton product, reloc-free -O2, 56 insns).** Deterministic decode reached a *single* logical diff: all 16 `mul.s` (with the `a1[c]*a0[c]` operand order on each last-subtracted term), every `add.s`/`sub.s`, store order `a2[0,1,2,3]`, and the full schedule matched — but GCC assigned `x`'s spill slot to `40(sp)` and `z`'s to `32(sp)` where the target has them reversed (`x→32, z→40`). The permuter reported `base score = 0` and exited on `--stop-on-zero`; `cmp` of the .text still differed at the two `swc1` + one `lwc1`. **This is an honest cap, not an episode.**

**Why the slot pair won't flip from C:** spill slots are assigned in pseudo-regno order (`assign_stack_local` walks pseudos by number; first → lowest offset). The x↔z pair did NOT flip under any tried C structure — store-order permutations (only `a2[0,1,2,3]` keeps the w-store scheduling correct; others regress), declaration-order permutations (disturb the whole schedule → far worse), fully-inlined stores (62 diffs), `*a2++` pointer-postinc (8), temp copies (`float xx=x;`), and extra refs (`a2[2]=z` twice). It's a frame-layout artifact the IDO frontend's RTL doesn't expose to source-level control. Class: **spill-slot-assignment cap** — leave `#ifdef NON_MATCHING`. (Distinct from the $t-renumber class below, which the permuter CAN sometimes crack via shape mutation.)

**REFINEMENT 2026-05-23 — the permuter CAN crack SOME register-renumber near-misses (the "can't" above is for $s-reg/$a-class picks).** The blanket "permuter flips ORDER not ASSIGNMENT" holds for $s-reg priority and $a-class arg-reg picks (deterministic). But for **record-append / pointer-arithmetic functions with $t-class temp renumber** (same opcodes/order, only $t-numbering differs, e.g. 20/25–20/29 diffs, too pervasive for INSN_PATCH), the permuter DOES find SHAPE-CHANGING C variants that flip the $t allocation to match — because it mutates the RTL shape (not just hoisting). Winning mutations it found: route an address through an `int new_var = base + idx*8; arr = (int*)new_var;` intermediate, and reuse one local (`idx`) as both pointer-int and count. Cracked `game_libs_func_0005769C` (25 insns) and `_00057628` (29, masking) → byte-exact episodes, 2026-05-23. Use `-j6`, ~**280s** (180s only reached score 15 on the masking one; it needed the longer run). **Still resistant** (don't waste runs): loops (best score got WORSE — 20E78 125), delay-slot scheduling (2A9F0 55), cursor-vs-offset fold (1D17C 280), unfilled-jr-delay (571E4 35), arg-home spill. So: TRY the permuter on straight-line record-append/pointer-arith $t-renumber near-misses; SKIP loops / delay-slot / cursor / unfilled-delay / $s-$a-class. **Sub-refinement 2026-05-23 — record-append + RIGID HEAD also resists.** `game_libs_func_0005703C` (50 insns) is a flag-decode bit-test chain (`sll tN, v1, K; bgez tN, skip; ori v0,...` — high single-bit masks that don't fit `andi`'s 16-bit immediate, forced via `((unsigned)v1 << K) >> 31` per IDO_CODEGEN#feedback-ido-bit-N-test-via-sll-bgezl) FOLLOWED BY two record-appends. Structurally 100% exact (all opcodes/immediates/branch-offsets match; only 30/50 $t fields differ), reloc-free. Permuter -j6 285s got down to score-50 but NOT 0: it shape-mutates the record-append TAIL's $t-alloc, but the head's bit-test-chain $t numbering is rigid (each `>>31` test's pseudo creation order is fixed; tail mutations don't reach it). So the crackable class is PURE record-append; a record-append preceded by a non-trivial computed head (bit-test chain, arithmetic) keeps the head's $t-renumber and stays NM. Don't re-run the permuter on record-appends with a substantial head. **Sub-refinement 2026-05-23 — FP↔int register interplay also resists, even straight-line.** `game_libs_func_00029934` (17 insns, reloc-free, NO loop: `lwc1; trunc.w.s; mfc1; addu; srl+andi; table lh; sra/sll/sra`) — structurally exact, ~10 $t-renumber driven by the float-to-int (`trunc.w.s`/`mfc1`) result competing with the two int loads for registers. Permuter -j6 240s → best 45, not 0. The crackable class is pure-INTEGER record-append/pointer-arith; when the renumber is driven by FP→int reg interplay (mfc1 result + int loads), the permuter's int-shape mutations don't reach the FP-side allocation. SKIP the permuter on FP-flavored straight-line $t-renumber too. Also tiny (≤~8-insn) leaves resist for lack of mutation surface (27504 6-insn → best 2/6 only via an ugly mask-chain not worth episoding).

---

---

<a id="feedback-pyghidra-mcp-setup-for-n64-decomp"></a>
## pyghidra-mcp setup notes for N64 decomp work — JDK 21, raw-binary load, MIPS:BE:32:default, ~7-min auto-analysis

_pyghidra-mcp install gotchas verified 2026-05-04. Needs Ghidra 12.x + JDK 21 (NOT JDK 17). N64 ROMs need raw-binary load with explicit language="MIPS:BE:32:default" + loader="ghidra.app.util.opinion.BinaryLoader". Auto-analysis on 16 MB 1080 baserom takes ~7 min (one-time). Re-opening cached project: ~5 sec. pyghidra-mcp is a `uv tool` install — scripts must use ~/.local/share/uv/tools/pyghidra-mcp/bin/python, not the system python._

**Install (sudoless):**

```bash
# 1. pyghidra-mcp via uv (separate tool venv)
uv tool install pyghidra-mcp

# 2. Adoptium portable JDK 21 — Ghidra 12.x rejects JDK 17
mkdir -p /tmp/ghidra-spike && cd /tmp/ghidra-spike
curl -sL https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.5%2B11/OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11.tar.gz -o jdk21.tar.gz
tar xzf jdk21.tar.gz

# 3. Ghidra 12 (latest from GitHub releases)
GHIDRA_URL=$(curl -s https://api.github.com/repos/NationalSecurityAgency/ghidra/releases/latest | python3 -c "import json,sys; d=json.load(sys.stdin); print([a['browser_download_url'] for a in d['assets'] if 'PUBLIC' in a['name'] and a['name'].endswith('.zip')][0])")
curl -sL "$GHIDRA_URL" -o ghidra.zip && unzip -q ghidra.zip

# 4. Env vars (need on every shell)
export JAVA_HOME=/tmp/ghidra-spike/jdk-21.0.5+11
export PATH=$JAVA_HOME/bin:$PATH
export GHIDRA_INSTALL_DIR=/tmp/ghidra-spike/ghidra_12.0.4_PUBLIC
```

**N64 baserom load (the right magic):**

```python
import pyghidra
pyghidra.start()
from pyghidra import open_program

# IMPORTANT: don't use loader="BinaryLoader" — Ghidra needs the FQN
# IMPORTANT: language is "MIPS:BE:32:default", NOT "MIPS:BE:32:R3000"
# IMPORTANT: VR4300 is N64's CPU but Ghidra has no specific VR4300 lang ID;
#            "default" is the closest. The relevant Ghidra MIPS variants:
#            MIPS:BE:32:default, MIPS:BE:32:R6, MIPS:BE:32:micro,
#            MIPS:BE:64:default, MIPS:BE:64:micro, MIPS:BE:64:R6,
#            MIPS:BE:64:64-32addr (for embedded 32-bit-pointers-on-64-bit-CPU)

with open_program(
    rom_path,
    project_location=cache_dir,
    project_name="my_project",
    analyze=True,                          # ~7 min on 16 MB ROM, one-time
    language="MIPS:BE:32:default",
    loader="ghidra.app.util.opinion.BinaryLoader",
) as flat_api:
    program = flat_api.getCurrentProgram()
    ...
```

**Re-opening cached project (no re-analysis):**

```python
with open_program(rom_path, project_location=cache_dir, project_name="my_project",
                  analyze=False, language="MIPS:BE:32:default",
                  loader="ghidra.app.util.opinion.BinaryLoader") as flat_api:
    ...  # ~5 seconds
```

**Running scripts via pyghidra:**

`pyghidra-mcp` was installed via `uv tool install`, so its venv lives at `~/.local/share/uv/tools/pyghidra-mcp/`. Scripts that import `pyghidra` MUST use that interpreter:

```bash
~/.local/share/uv/tools/pyghidra-mcp/bin/python script.py
```

`python3 script.py` will fail with `ModuleNotFoundError: No module named 'pyghidra'`.

**Two-stage analysis (pyghidra-mcp's quirk):**

There are TWO analysis passes that happen, NOT one:

1. **Ghidra auto-analysis** (~7 min) — runs once on a fresh `.gpr` project, populates the function manager with detected functions. Triggered by `setup-ghidra.py` in our setup. Persistent in the project file.

2. **pyghidra-mcp's own indexing** (~3-5 min on top of #1) — builds a chromadb vector index for symbol search + verifies analysis is complete. Runs every time pyghidra-mcp starts. The first run takes longer (creating chromadb collection); subsequent runs are faster (chromadb cached at `<project>/<name>-pyghidra-mcp/chromadb/`).

The MCP server's flag `--wait-for-analysis` tells it to block on its own indexing pass before responding to tool calls. Without it, tool calls return `"Analysis incomplete for binary 'baserom.z64'. Wait and try tool call again."` — clients then need to retry.

**Use `--wait-for-analysis` in `.mcp.json`** so client code doesn't have to retry. The cost is the server takes 3-5 min to start the first time after a fresh `setup-ghidra.py` run.

**Pass `--project-path` as the .gpr file path, NOT the directory.**

```json
"args": [
  "--transport", "stdio",
  "--project-path", "/path/to/build/ghidra-project/tenshoe.gpr",
  "--wait-for-analysis"
]
```

If you pass `--project-path /path/to/build/ghidra-project --project-name tenshoe`, pyghidra-mcp will CREATE A SECOND empty project at `<path>/<name>/<name>.gpr` instead of opening yours. (Their docs say project-path accepts either a dir or a .gpr; for our use-case .gpr is correct.)

**`open_program` is deprecated and doesn't persist** — use `open_project` + `program_loader().loaders(BinaryLoader)` (singular `.loaders()` takes a Java Class, NOT a list) + explicit `loaded.save(monitor)` + `loaded.release(None)`. Then run analysis via `program_context(project, "/baserom.z64")` block + explicit `program.save(...)` after. Without explicit saves, work is in-memory only and discarded on context exit.

**Verified output quality (1080 baserom, 2026-05-04):**
- Auto-analysis time: 391.6s (~6.5 min)
- Functions discovered: 2,505 (vs 2,668 known — 94%)
- Decompile of small libultra helper (interrupt-bracket pattern at VRAM 0x80000118): clean readable C
- Decompile of rmon function (348 bytes at VRAM 0x80008430): structurally clean, struct field offsets clearly visible — the exact use case for which Ghidra is recommended over m2c

**What's MISSING from a vanilla load (worth setting up before productive use):**
- Image base = 0x0; addresses are file offsets, not VRAM. Set up memory blocks: kernel @ 0x80000000 (ROM 0x1000+), USOs at VRAM=0.
- Functions named `FUN_<addr>`. Import `symbol_addrs.txt` to get `func_80008430`-style names.
- USO segments overlap each other in VRAM=0 — would benefit from overlay memory blocks if Ghidra-side analysis cares about cross-USO disambiguation.

**Disk cost:** ~2.4 GB total (JDK + Ghidra + cached project + uv tool venv). Removable any time with `rm -rf /tmp/ghidra-spike` (cached project goes too — re-analysis required after).

**MCP integration sketch (.mcp.json snippet):**
```json
{
  "mcpServers": {
    "pyghidra-mcp": {
      "command": "/home/dan/.local/share/uv/tools/pyghidra-mcp/bin/pyghidra-mcp",
      "args": ["--transport", "stdio", "/path/to/baserom.z64"],
      "env": {
        "JAVA_HOME": "/tmp/ghidra-spike/jdk-21.0.5+11",
        "GHIDRA_INSTALL_DIR": "/tmp/ghidra-spike/ghidra_12.0.4_PUBLIC"
      }
    }
  }
}
```

This exposes `decompile_function`, `get_xrefs_to/from`, `set_function_prototype`, `rename_function`, `set_local_variable_type`, `set_decompiler_comment` etc. as MCP tools.

---

---

<a id="feedback-report-json-vs-decomp-dev-diverge"></a>
## report.json was overstating because land script used `make expected` — RESOLVED 2026-05-04

_HISTORICAL — the land script's `make expected` blanket-cp build/→expected/ used to pollute expected/ with decomp-bodies build, inflating matched_code_percent by ~1pp (8.84% reported vs 7.68% truth). Fixed 2026-05-04 by switching to refresh-expected-baseline.py and patching SUFFIX/TRUNCATE recipes to handle the INCLUDE_ASM case. Truth baseline numbers now apply._

> **STATUS — RESOLVED 2026-05-04 in `agent-e` (1080 project).** Land script now calls `python3 scripts/refresh-expected-baseline.py` instead of `make expected`. The refresh script was unblocked by patching `inject-suffix-bytes.py` and `truncate-elf-text.py` to recognize INCLUDE_ASM-mode (see `feedback_refresh_expected_baseline_blocks_on_yay0_rom_mismatch.md`). The committed `expected/` now reflects a truthful pure-asm baseline.
>
> **Truth values 2026-05-04 (post-fix):** 7.68% / 902-of-2668 funcs / 58860-of-766568 bytes. Both decomp.dev's 8.07% and the previously-stamped 8.84% were wrong — different shades of pollution. Commit `<TBD>` lands the truthful expected/ tree; expect decomp.dev to drop to ~7.68% on its next ingest.

**Root cause (for context):** The Makefile's `expected` target was a blanket cp — `cp build/*.o expected/*.o` after deleting expected/. The land script ran `make expected` after each landing to refresh CI's baseline, but at that moment `build/*.o` reflected decomp-bodies sources, not pure-INCLUDE_ASM. So expected/.<file>.o became byte-identical to build/.<file>.o for every touched file → objdiff reported 100% match for every function in those files, including NM-wrapped ones.

The ALSO-wrong number 8.07% (decomp.dev's view) came from a related but distinct effect: the previously-committed expected/.o files had wrong (smaller) function sizes. SUFFIX_BYTES is supposed to grow function st_size to include trailing stolen-prologue / continuation bytes; the polluted expected/.o had that growth ALREADY APPLIED at decomp-bodies size, but then incremental edits drifted the baseline. With proper refresh, total_code grew from 737844 → 766568 (+28724 bytes = correct accounting of SUFFIX_BYTES growth), which lowered the percentage even though matched_code stayed similar.

**Mechanism of the fix:**
1. `inject-suffix-bytes.py` — added a second skip path: check function's TRAILING n_bytes (within st_size) for already-equal-to-payload. INCLUDE_ASM build has the suffix baked into the .s symbol declaration so this skip fires.
2. `truncate-elf-text.py` — `.text size <= target` is now a no-op (informational print) instead of an error. INCLUDE_ASM emits exactly-asm-length .text which is naturally smaller than C-emit-and-clip target.
3. `refresh-expected-baseline.py` — switched `make → make objects` (C objects only, no link, no Yay0, no md5sum), so Yay0 ROM-checksum nondeterminism doesn't abort the parallel build before all USO .c.o files are produced.
4. `land-successful-decomp.sh` — `make expected` → `python3 scripts/refresh-expected-baseline.py`. Adds ~30-60s per landing for the clean-INCLUDE_ASM rebuild, but the baseline is now truthful.

**How to apply:**
- Trust the post-fix `report.json` (and decomp.dev once it ingests). They will match.
- For ad-hoc local truth: `git checkout HEAD -- expected/ && make clean && make RUN_CC_CHECK=0 objects && objdiff-cli report generate -o /tmp/r.json`.
- If you add a new post-cc recipe type, follow the "INCLUDE_ASM-aware skip path" pattern in `feedback_refresh_expected_baseline_blocks_on_yay0_rom_mismatch.md`. Otherwise it'll silently break refresh-expected-baseline.py the next time it runs.

---

---

<a id="feedback-when-to-consult-ghidra-during-decomp"></a>
## When to consult Ghidra during /decompile (trigger list — m2c remains the default)

_1080 has a Ghidra project + MCP server, but reaching for Ghidra has cost (slower than m2c, GCC-flavored not IDO-flavored). Use only when one of 4 triggers fires: struct shape unknown, function family ≥3, stuck wrap <50% fuzzy with structural unknowns, suspected fragment with `in_t9`/`in_stack_*` reads. Otherwise stick with m2c._

**Default**: use `m2c --target mips-ido-c` for initial C decomp. It's faster, IDO-flavored (matches our codegen target), works on a single .s file with no setup. Good enough for most functions.

**Switch to Ghidra ONLY when one of these triggers fires** (otherwise the cost of Ghidra setup + caching + GCC-flavored output isn't worth it):

1. **Struct shape unknown.** Function reads `*(T*)(arg + 0xN)` patterns and you don't know the struct. Ghidra's typed decomp (after annotating `arg` as `MyStruct *`) renders fields as `arg->fieldname`, exposes field types, and surfaces neighboring offsets you didn't notice in the asm. m2c can't do this — it has no project-level type memory.

2. **Family of related functions** (≥3 callers of a shared callee, or ≥3 functions taking the same struct). Ghidra's `list_xrefs` returns the entire family in one query (e.g. `list_xrefs to FUN_000073f8` returned 27 rmon callers); `grep -rn 'jal func_X' asm/` is slower and misses DATA xrefs. Then `scripts/ghidra-annotate-family.py` batches the struct annotation across the family.

3. **Stuck wrap <50% fuzzy with structural mismatch** (control flow unclear, your draft doesn't match any obvious shape). Ghidra's canonical form often reveals the function is much simpler than your draft. Verified 2026-05-04 on `func_80008030`: our 5-line build-up-and-return wrap was at 36% fuzzy; Ghidra showed the actual logic is `return (D_A4040010 & 3) == 0;` — a one-liner.

4. **Suspected fragment** (function has no prologue / starts mid-flow). Ghidra's decomp output uses `in_t9` / `in_a1` / `in_stack_0000002c` (uninitialized register / stack reads) → caller passes registers, not a standalone function. Diagnostic info you'd otherwise derive by reading asm. Verified on `func_80003FF0`.

**Don't reach for Ghidra**:
- **Yay0-COMPRESSED USO functions (game_uso / *-USO segments).** Ghidra analyzes the static ROM, where these segments are Yay0-COMPRESSED data, not code — so the USO functions are simply NOT in the project. Verified 2026-05-29: after a full `setup-ghidra.sh` (2505 fns), `ghidra-decompile-func.sh game_uso_func_0000D204` → `NOT FOUND`, and symbol-import logged `not-a-known-fn=1086` (the USO funcs). Ghidra only sees the UNCOMPRESSED kernel/game_libs code. For USO orchestrators, m2c also fails (`.word` form, see [m2c on .word-only USO asm](#feedback-m2c-word-only-asm)) and the data relocs aren't in the `.c.o`; hand-decode from `objdump -dr build/src/<seg>/<seg>.c.o` using the `&D_00000000 + offset` convention (single USO base symbol, links via undefined_syms) + `gl_func_00000000` calls + literal floats for inline `lui` consts.
- **Byte-correct matching.** Ghidra's GCC-flavored decomp won't byte-match IDO emit. Use it for *understanding*, not *codegen*.
- **Register-allocation grinding** (>90% fuzzy, just need to flip a register). Use the permuter.
- **Final-mile tightening** (>90% fuzzy in general). m2c output is closer-to-IDO; Ghidra's structural rephrasing actively hurts.
- **First time on a new project.** Ghidra setup (~7 min auto-analysis + ~5 min indexing on first MCP start) isn't worth it for a one-off. Wait until you have ≥10 candidate functions before setting it up.

**How to invoke** (1080 only):
- One-shot decomp: `bash scripts/ghidra-decompile-func.sh <func_name>`
- Family annotate: `python3 scripts/ghidra-annotate-family.py --struct-name RmonMsg --funcs A,B,C,...` (when written; current ref impl is `scripts/ghidra-annotate-rmon.py`)
- MCP queries from Claude Code (read-side only — write-side has had hangs).
- Setup: `bash scripts/setup-ghidra.sh` (~7 min one-time per worktree).

**Companion memos**:
- `feedback_pyghidra_mcp_setup_for_n64_decomp.md` — install + setup quirks (JDK 21, MIPS:BE:32:default, .gpr-not-dir, etc.)
- `feedback_ghidra_struct_annotation_doesnt_auto_propagate.md` — annotations don't propagate across xrefs; batch-script the family.

---

<a id="feedback-m2c-word-only-asm"></a>
## m2c on .word-only USO asm — assemble + objdump round-trip to get mnemonics

_splat emits `.word 0xNNNNNNNN` for USO functions whose lui-relocations spimdisasm can't resolve; m2c then errors with "Function contains no instructions". Round-trip the .word values through `mips-linux-gnu-as` + `objdump -d -M no-aliases` to get readable mnemonics for hand-paste into a temp .s._

**AUTOMATED 2026-05-24 — `scripts/disasm-func.py`.** No more hand round-trip:
`python3 scripts/disasm-func.py <func> --m2c` looks up the function's `st_value`
in `build/non_matching/**/*.c.o` (or `expected/**`), objdumps that byte range to
mnemonics, reformats to m2c-ready `.s` (`glabel` + `.L<addr>:` labels for branch
targets, operands joined), and pipes through `uv run m2c --target mips-ido-c`.
Without `--m2c` it prints the `.s`. Validated on `game_libs_func_00060F90`
(linked-list unlink) → clean pseudo-C. The function must already be built into a
`.o` (it is, via INCLUDE_ASM). This unblocks medium-function decode grinds on every
USO segment. (Manual round-trip below kept for reference.)

**GOTCHA — `disasm-func.py` mis-RESOLVES reloc'd `jal` targets in an unlinked `.o`; every call prints the SAME wrong name (verified 2026-06-04, func_8000745C).** When you disasm `build/non_matching/**/*.c.o` or `expected/**/*.c.o`, the R_MIPS_26 call targets are unresolved (address 0 + reloc), so objdump/disasm-func names them by the nearest symbol — usually whatever symbol owns offset 0 (e.g. `func_800066EC`). So a manual disasm diff shows BOTH your build AND expected calling `func_800066EC` for calls that are really to two DIFFERENT functions (the `.s` under `asm/nonmatchings/` has the correct names via its `/* … */` reloc comments). Do NOT conclude "I'm calling the wrong function" from a disasm-func call-target diff — it's a symbol-resolution artifact, identical in both objects. Trust objdiff's reloc-aware `fuzzy_match_percent` (it compares the reloc SYMBOL, not the resolved address) and read the real call names from the `asm/nonmatchings/<seg>/<func>.s` `jal` lines. Cost me a detour on func_8000745C before objdiff confirmed the calls were fine and the real residual was a `-1`-constant CSE/regalloc divergence.

**GOTCHA (bigger) — `disasm-func.py` shows the BUILT `.c.o`, which for an ALREADY-WRAPPED function is the CURRENT C body's compilation, NOT the target (verified 2026-06-06, gl_func_000717CC / gl_func_0006BC4C).** It objdumps `build/non_matching/**/*.c.o`. For an INCLUDE_ASM-only function that's the real target bytes (INCLUDE_ASM embeds the `.s`), so disasm-func + `--m2c` are correct. But once the function has a `#ifdef NON_MATCHING` body, the `.c.o` contains YOUR compiled body — so disasm-func "reconstructs" what's already there (I rebuilt gl_func_000717CC's existing 46% body believing it was the target, and it was actually a caller-set-$t6 cap). ALWAYS sanity-check: disasm-func's first instruction must equal the raw `.s` first `.word`; if not, you're looking at a wrapped body or a mis-resolved symbol. To see the TARGET regardless of wrap state, decode the raw `.s` `.word` blob directly: `python3 -c "import re,struct;ws=[int(m,16) for m in re.findall(r'\.word 0x([0-9A-Fa-f]{8})',open(S).read())];open('/tmp/t.bin','wb').write(b''.join(struct.pack('>I',w) for w in ws))"` then `mips-linux-gnu-objdump -D -b binary -m mips:4000 -EB /tmp/t.bin`. (To diff target-vs-built, decode BOTH this way — built via the .c.o symbol range.) **2026-06-06: this whole workaround is now packaged as `scripts/disasm-raw.py <func> [--m2c]`** — it does the blob decode automatically (always TARGET, branches in range) and `--m2c` reformats correctly (only branch mnemonics get `.L` labels, so `lui/ori` immediates aren't mangled; warns on past-end/inter-function tail-branch targets). Prefer it over `disasm-func.py` for anything that might be wrapped.

**GOTCHA — `report.json` is STALE for local candidate-picking; regenerate before filtering.** It's git-tracked and updated only by the land script, so a function it lists at 0%/"<5%" may already be 46%+ in your tree (gl_func_000717CC 2026-06-06). Picking "0% unwrapped" candidates off `report.json` surfaces already-wrapped caps. Always `make non_matching_objects RUN_CC_CHECK=0 && objdiff-cli report generate -o /tmp/rp.json` and filter `/tmp/rp.json`.

**LEVER — `switch` beats an `if (x==a) … else if (x==b) …` chain for small command dispatchers.** IDO compiles a `switch` over a few `case` constants into a `beql/beq` compare chain with the taken-case's first load hoisted into the delay slot — matching the typical hand-written dispatcher. The equivalent if-else-if chain emits `bne …; branch-away` instead and scores lower. gl_func_00051F5C jumped 67.7→81.9% just by switching the dispatch form to `switch`.

**GOTCHA — m2c renders a reloc'd `&D_00000000`-pointer store as `= 0` (verified 2026-05-29, mgrproc_uso_func_00002940).** When the asm is `lui rX,0x0; addiu rX,rX,0; sw rX, OFF(base)` (i.e. store the *address* `&D_00000000` into a field), m2c shows it as `field = 0` because the relocation target resolves to 0x0 and m2c can't see the reloc. So a field m2c claims is zeroed may actually hold a POINTER. Tell them apart by the insn count: a real zero-store is one `sw zero, OFF` (1 insn); a `&D` store is `lui;addiu;sw` (3 insns, with R_MIPS_HI16/LO16 relocs). If your NM body is ~2 insns short per such field, change `*(int*)(p+OFF) = 0;` to `*(char**)(p+OFF) = (char*)&D_00000000;`. Recovered 8 insns / +6.5pp on mgrproc_uso_func_00002940. Same root cause as the `*(s32 *)0x68`-style m2c renderings (those are `&D_00000000 + 0x68`).

**GOTCHA — m2c renders an FP comparison as a bogus INTEGER bit-test (verified 2026-06-05, gui_func_00000F04).** When the target gates a block on the sign of a truncated float (asm: `trunc.w.s; mfc1 rN,..; sll rN,..; bgez rN, skip` or a `c.lt.s`+`bc1t/bc1f`), m2c often can't model the FP/branch and emits a nonsense int mask like `if ((s32)f2 & 0x20000000)` (bit-29 is never a real test). Read the target's ACTUAL branch to recover the true condition: `bgez rN`→`if (x >= 0)` (so the *gated* body runs when `x < 0`), `bltz`→`if (x < 0)`, `c.lt.s f0,f1`+`bc1t`→`if (a < b)`. Two payoffs: (1) correctness; (2) the bogus int var (here `f10 = (int)f2`) is often held live ACROSS a call only to feed that fake test — once you rewrite the gate in terms of a value you already keep (`s4 = (int)f2*4`, test `s4 < 0`), that var dies early and you DROP a cross-call spill, shrinking the frame (0x130→0x128 on F04). So an m2c int-mask test on a float-derived value is both a decode bug AND a frame-reduction lever.

**Symptom:** an asm file under `asm/nonmatchings/<uso>/<uso>/<func>.s` is all `.word 0x…` lines with no mnemonics. Running `uv run m2c --target mips-ido-c <file>.s` errors with:

```
Decompilation failure in function <func>:
Function <func> contains no instructions. Maybe it is rodata?
```

**Why:** spimdisasm gives up on `lui $at, 0` followed by an unresolvable relocation (e.g. `lwc1 $f16, 0($at)` where `$at` should be patched by the USO loader). USO segments at synthetic VRAM=0 don't have global addresses to anchor the disasm, so the whole function falls back to `.word`. m2c only parses mnemonic instructions and treats `.word` as data.

**Fix — round-trip through binutils:**

```bash
# 1. Extract the .word values:
grep -oP '0x[0-9A-F]{8}' asm/nonmatchings/<uso>/<uso>/<func>.s > /tmp/words.txt

# 2. Wrap them in an assemblable .s file:
{ echo ".set noreorder"; echo ".text"; echo ".global _start"; echo "_start:"
  while read w; do echo ".word $w"; done < /tmp/words.txt; } > /tmp/decode.s

# 3. Assemble + disassemble to get mnemonics:
mips-linux-gnu-as -EB -march=vr4300 -o /tmp/decode.o /tmp/decode.s
mips-linux-gnu-objdump -d -M no-aliases /tmp/decode.o

# 4. Hand-paste mnemonics into a fresh .s with proper `glabel` and `.LXXXX:` labels,
#    then run m2c on THAT temp .s.
```

**Caveats:**
- `lui $at, 0` will look weird in objdump output (no symbol resolution) — you'll need to leave it as a literal `lui $at, 0` in the m2c input. m2c handles this fine; it just emits `*(T*)0` accesses, which you replace with `&D_00000000 + offset` in the C body.
- Branch targets (`bne … 0x20 <_start+0x20>`) need to be rewritten as `.LXXXX` labels matching the original ROM offsets — m2c errors with "Cannot find branch target" if the labels don't exist. Add label lines (`.LXXXX:`) at the appropriate offsets in your temp .s.
- If you forget a label, m2c's error names exactly which one, so iterate until it parses.
- **If you SCRIPT the relabel step** (regex-rewrite branch targets to `.LXXXX`), only rewrite operands of actual branch ops (`b/beq/bne/beqz/bnez/bgez/...`). A naive `,(0x[0-9a-f]+)$` substitution also matches the immediate in `lui rX, 0x2`, corrupting it to `lui rX, .L2` → m2c aborts with `lui/lis argument must be a literal or %hi/@ha/@h macro`. Guard the rewrite on the mnemonic. (Hit 2026-05-29 auto-synthesizing the temp .s for gl_func_0003829C.)

**When to use this:** any USO function whose .s is .word-only AND whose body is non-trivial (≥30 insns) — small functions you can decode by hand instruction-by-instruction faster than the round-trip. Used 2026-05-05 on `game_uso_func_00002744` (52 insns) — m2c produced a clean structural decode in one pass that would've taken 30+ minutes by hand.

**Long-term fix:** migrate USO disasm to spimdisasm proper (per `project_1080_uso_spimdisasm_migration_todo.md`) so the .s files have mnemonics from the start. Until then, the round-trip is the cheapest workaround.

---

---

<a id="feedback-permuter-import-requires-ifdef-non-matching-body"></a>
## decomp-permuter `import.py` needs a C body under `#ifdef NON_MATCHING` — bare `INCLUDE_ASM` invisible

_For the `<80% → keep INCLUDE_ASM` rule (`/decompile` skill threshold): if you intend to grind the function via permuter later, leave the verified C decode wrapped in `#ifdef NON_MATCHING` even when fuzzy is sub-80%. `import.py` parses the source file looking for a function DEFINITION that matches the target asm — bare `INCLUDE_ASM("...", funcname);` registers no function, and permuter setup fails with "no such function found"._

**Symptom:** `python3 decomp-permuter/import.py <src.c> <asm.s>` errors with no function matching the target name — even though `INCLUDE_ASM(funcname)` is right there in the .c file. The import is C-source-driven, not asm-symbol-driven.

**Recipe:** when documenting a sub-80% verified decode, wrap it:
```c
#ifdef NON_MATCHING
/* <doc comment with cap notes> */
void funcname(int a0, ...) {
    /* verified decode, even at 60-79% fuzzy */
}
#else
INCLUDE_ASM("asm/nonmatchings/<seg>", funcname);
#endif
```

The `#else INCLUDE_ASM` keeps the default build byte-exact via ROM bytes; the `#ifdef NON_MATCHING` block makes the function importable by permuter for later grinding. This is the EXCEPTION to the "<80% keep plain INCLUDE_ASM" rule: any function you plan to permuter-grind needs the NM wrap.

**Discovered 2026-05-16** when a parallel agent (per main commit `4c5f7158`) restored `game_libs_func_0003DBEC`'s C body under NON_MATCHING explicitly as a "permuter seed" — same gotcha as `game_libs_func_0003DDC0`. The verified-decode-as-INCLUDE_ASM-only pattern blocked permuter setup until the body was restored.

**Caveat (false-positive-episode risk):** the project-wide classifier flagged ~140 episodes as tautology-trap candidates because they were logged against NM-wrapped functions where the C body was 19–78% but the wrap inflated reported match. Permuter seeds DO NOT and SHOULD NOT log episodes — they're scaffold, not ground truth. Episode-logging guard remains "exact match only, via build/non_matching/.o byte-verify against expected/.o."

---

<a id="feedback-permuter-working-setup-2026-05-23"></a>
## WORKING permuter setup (2026-05-23) — the 0/6 was misconfiguration

The permuter is the **sanctioned last-mile match tool** (INSN_PATCH and all
instruction-byte patching were removed 2026-05-23 — see
`memory/feedback_no_instruction_forcing_matches_policy`). It only helps functions
already CLOSE (count-match, register-allocation/scheduling/branch-order diffs);
structural diffs (count-mismatch, wrong fields) need a C fix first.

Earlier runs scored 0/6 not because the permuter can't do it, but because it was
run **unconfigured**. Two fixes:

1. **`projects/1080-*/permuter_settings.toml`** (committed):
   ```toml
   compiler_type = "ido"
   [weight_overrides]
   perm_temp_for_expr = 100
   ```
   Without `compiler_type = "ido"` the permuter uses generic weights ill-suited
   to IDO codegen.

2. **Import with the FULL CPPFLAGS** (from the project worktree dir):
   ```bash
   python3 ../../tools/decomp-permuter/import.py \
       src/<seg>/<file>.c asm/nonmatchings/<seg>/<sub>/<func>.s \
       'CPPFLAGS=-I include -I src -DNON_MATCHING'
   python3 ../../tools/decomp-permuter/permuter.py nonmatchings/<func> --stop-on-zero
   ```
   - `-DNON_MATCHING` is MANDATORY: functions are `#ifdef NON_MATCHING { C } #else
     INCLUDE_ASM #endif`. Without it the build takes the `#else` (INCLUDE_ASM) path
     and there is **no C body to permute** (this silently broke old runs).
   - `-I include -I src` is MANDATORY (the PERMUTER make rule uses `$(CPPFLAGS)`;
     passing a bare `CPPFLAGS=-DNON_MATCHING` *clobbers* the include paths →
     `common.h: No such file`). Pass all three as one quoted arg.

When the permuter reaches **score 0**, the matching C is in
`nonmatchings/<func>/output-0-*/source.c`. Put that C into the function's
`#ifdef NON_MATCHING` block in src, rebuild, verify byte-exact against the `.s`
(`raw-diff=0`), and it's a **real match** — no patch, episode-worthy. `nonmatchings/`
is gitignored. Score bands still apply (≥1000 ≈ structural, stop and fix the C).- (5) **frame-SIZE differences** (not just spill-slot swaps) — when the target frame is e.g. 0x90 but your C emits 0x98 (an extra 8-byte spill/temp slot), the permuter is USELESS: its scorer normalizes ALL sp-relative offsets, so it neither sees the size diff nor the cascade of shifted sp-offsets it causes, and it will happily report a *lower* score for a variant that actually GREW the frame (verified `func_80000D2C` 2026-05-31: 28k iters, "score 15" while frame grew 0x98→0xA0, 18 raw diffs vs base 13). Frame-size caps need MANUAL spill-elimination (reduce live-range pressure), not the permuter. 

### Disassembling a raw-.word USO .s: extract symbolic jal/lui lines too, or the .bin is corrupt (2026-06-01)

A common quick-decode move is to scrape a USO `.s` for instruction words and `objdump -b binary` the result. PITFALL: splat renders RELOCATED instructions symbolically, e.g.
`    jal game_uso_func_000023D4   /* 002930 0C000000 -> game_uso_func_000023D4 */`
and `lui $a1, %hi(game_uso_D_...)  /* ... 3C050000 -> ... */`. Their hex word sits before `-> sym`, NOT before `*/`. A regex like `([0-9A-F]{8}) \*/` (matches only raw `/* a v HEX */ .word 0xHEX` lines) SILENTLY DROPS every jal/lui-with-reloc, so the rebuilt `.bin` is missing those instructions and every offset after the first dropped one is shifted — a fully corrupted disassembly. Symptom: your scrape reports "0 jals" on a function whose comment/decomp says it has N cross-USO calls (caught 2026-06-01 on game_uso_func_00000B3C: scrape said 0 jals, real count 22; led to a false "spurious gl_func" conclusion — the gate-revert saved it).

Fix: extract the hex from BOTH forms — match the THIRD hex field of the `/* rom vram HEX ... */` comment regardless of what follows (`r'/\*\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+([0-9A-Fa-f]{8})'`), not the `... HEX */` tail. Better: disassemble the actual built `.o` (`objdump -d build/non_matching/.../<file>.c.o`, reloc-aware) instead of scraping the `.s`. Corollary: gate-verified edits (build + objdiff per change) are still trustworthy even if your guiding disasm was flawed — that's why the C48C sub-init climb (27→48%) held up despite this tooling bug; the objdiff gate, not the scrape, confirmed each value.

### objdump `reg-names=n32` mislabels $8-$11 as a4-a7 (they're o32 t0-t3) (2026-06-02)

When disassembling 1080 (o32 ABI) code with `mips-linux-gnu-objdump -M no-aliases,reg-names=n32`, registers $8-$11 print as `a4,a5,a6,a7` — but 1080 is O32, where $8-$11 are `t0,t1,t2,t3` (temporaries), NOT argument registers (o32 args are only a0-a3 = $4-$7). Misreading `a4-a7` as call arguments will produce wrong C (e.g. inventing a 5th-8th register arg). Use plain `reg-names=o32` (or no reg-names override — gas default for the target is o32) when decoding 1080 USO functions. Caught while decoding titproc_uso_func_000005DC's s5-bitmask cases: `or a5,s5,at; ... sw a7,68(sp)` is `or t1,s5,at; ... sw t3,68(sp)` — temps building a bitmask spilled to a stack local, not arg-register setup.

## Ghidra reconstruction gotchas: FP constants are mis-displayed, and ~some gl_func USO names aren't in the project (2026-06-04)

Using `scripts/ghidra-decompile-func.sh <fn>` to drive an m2c-collapsed/stub reconstruction (the technique that took `gl_func_0005E288` 28.8→65% and `gl_func_0003CBB4` 13.8→17.2%) — two traps:

1. **Ghidra's FP constants are not trustworthy — cross-check every one against the asm.** On `gl_func_00036F0C` Ghidra rendered `fVar4 = 100.0` for the 0x40/0x80 flag scale, but the `.s` shows `lui $at, 0x4059` (= 3.390625f) TWICE plus a single `lui 0x42C8` (= 100.0f) — i.e. the 3.39 constant is the real pitch scale and Ghidra mislabeled it 100.0. Before trusting a reconstructed constant, grep the asm for the float-hi luis: `grep -oE '\.word 0x[0-9A-F]{8}' fn.s | <decode op==0x0F lui imm>` and map `imm0000` → IEEE754 (0x4059→3.39, 0x42C8→100, 0x4120→10, 0x4080→4, 0x42B2→89). A wrong constant silently caps the match.

2. **Not all `gl_func_*` USO symbols are in the Ghidra project.** `gl_func_0004FD18` and `gl_func_00020A28` return `NOT FOUND` (2505 fns imported, but some relocatable-USO names aren't named in the .gpr). When a target isn't found, fall back to m2c + manual asm decode; don't assume the reconstruction vein is available for every low-% function.

3. **Reconstructing an FP function faithfully from Ghidra often SPILLS where IDO keeps registers.** A direct translation of Ghidra's `if (d<0) d=-d;` abs blocks plus a multi-term dot product creates enough simultaneously-live FP values that IDO spills them all to stack — `gl_func_0003CBB4`'s reconstruction landed at frame -0xD0 (18 spill slots) vs the target's -0x50. The two-var Ghidra abs form (`if(delta<0){sd=delta;abs=-sd}else{abs=delta;sd=abs}`) did NOT help (regressed 17.2→15.5%) — the spill is driven by total live-FP pressure, not the abs shape. Getting these to high % is a register-pressure-reduction grind (fewer simultaneously-live temps), same class as the regalloc-dump caps — the structural reconstruction is the easy +pp; the last 50% is the grind.

4. **regalloc-dump triage (verified 2026-06-04, gl_func_0004880C): before grinding a `$s`-register near-miss with the `-Wo,-zdbug:6` dump, FIRST check whether the dump's final coloring already MATCHES the target.** The `./uoptlist` tail prints `<candidate>: <n> assigned (constrained) <hardreg>` (hardreg 16=$s0, 17=$s1, 18=$s2, …). On gl_func_0004880C the dump assigned a0→$s2, a1→$s1, i→$s0 — IDENTICAL to the target — yet the build still diffs at 99.2%, because the 3 `move $sN, <arg>` prologue-init instructions EMIT in a different ORDER (target s2,s0,s1; IDO s1,s2,s0). That is allocno/move-emission SCHEDULING, NOT coloring, and the dump cannot fix it (no candidate-priority knob changes instruction order; decl reorder doesn't flip it either — it's permuter-class). **Rule: the regalloc-dump only helps a near-miss whose COLORING differs (a true `$sX`↔`$sY` value swap). If `uoptlist` shows the colors already correct, stop — the residual is scheduling, and you're better off on the permuter or moving on.**

**Band survey (2026-06-04): the regalloc-dump vein is nearly empty — the `$s` near-miss band is emission-ORDER-dominated, not coloring.** Surveyed all game_libs ≤6-diff 95-99% `$s`-register near-misses: gl_func_0004880C (3d), gl_func_00033B6C (4d), gl_func_00041148 (4d) — every one is the SAME instructions (same `$s` coloring) emitted in a different ORDER (prologue arg-saves, or the pointer-init `addiu $sN,&base,off` block, emitted ascending `$s0..$s3` where the target is descending). True coloring swaps (same position, different `$s` register) were NOT found in the band. The decl/assign-separation trick (declare in coloring order, ASSIGN in target emission order) REGRESSES (gl_func_00033B6C 4→8 diffs): IDO re-couples the assignment order back into the coloring, so you can't get target-emission-order AND target-coloring at once — the first-emitted init takes the highest `$s`, exactly the FP `$f14`-first coupling in IDO_CODEGEN.md's "if(1){}" scope-caveat #2. Net: these are permuter-class scheduling caps; don't open the regalloc-dump for them.

## disasm-func --m2c can emit PHANTOM out-of-function labels (mis-based branches) (2026-06-10)

On timproc 1DB0, `scripts/disasm-func.py --m2c` failed with "label
.L1CC0 does not exist" -- implying a backward branch into the PREVIOUS
function. A direct word-scan (decode branch opcodes 1/4/5/6/7/20-23,
compute addr+4+off*4 against the symbol range) showed the only
out-of-range branch was FORWARD (bnezl -> +4 past the declared end, the
usual tail-fragment family). The tool mis-based at least one branch.
Rule: before acting on an m2c/disasm-func cross-function branch claim,
confirm with the direct word-scan -- it is ~10 lines of python and
decides merges definitively. (Same scan also catches the size-vs-word-
count mismatches from lowercase-hex comment lines that simple regexes
miss.)

## Candidate census: use report.json, never grep src for definitions (2026-06-10)

Three false "unstarted" candidates in one tick: grep-based "has no C
def" checks miss pointer-return defs (`void *fn(`), K&R implicit-int
defs (`fn(a0) int *a0; {`), and macro-wrapped forms. 1080 now has
`scripts/list-unstarted.py` (parses report.json fuzzy_match_percent,
sorts by size, flags BARE vs WRAPPED). Refresh report.json first. The
proc-USO family (boarder1/2, n64proc, eddproc, h2hproc, titproc) was
verified FULLY matched in the same pass -- don't re-census it.

## log-exact-episode routes to the CWD's episodes/, not the worktree's (87F4, 2026-06-10)

`uv run python -m decomp.main log-exact-episode` (run from the monorepo
root, as required for uv) writes to `<cwd>/episodes/` by default --
NOT the agent worktree's episodes/ that land-successful-decomp checks.
Symptoms in order: "missing episodes/<fn>.json" from the land script,
then a confusing ls (the monorepo's untracked episodes/ shadows it).
Fix: pass `--log-dir projects/<wt>/episodes` (or mv the json over).
Also: the positional function_name comes FIRST and --source-file is
required; and refresh-report dirties report.json, so `git checkout
HEAD -- report.json` before landing (the script refuses tracked
changes).

## Standalone-cc harnesses: never keep USO FW absolute-address reads as bare constants (940)

When pulling an NM body into a standalone test file, FW(p, o) forms
that read *(s32*)0xNN (USO D_-symbol references flattened to small
absolute addresses) MUST be rewritten as `extern char D_base;` +
offsets -- IDO compiles bare small-address loads differently (folds
the lui/addiu, can even drop a comparison arm from an OR-chain),
making the byte-diff meaningless. Symptom: standalone diff wildly
worse than the in-tree fuzzy, with structural "missing arms" the C
clearly contains. Seen on game_uso_func_00000940 (in-tree 88.66 vs
bogus standalone 73-diff).

## Ad-hoc .s word extraction: match the 3-field comment, not the rendering (3 failures in one session)

Raw-word USO .s files render lines THREE ways -- plain `.word 0x...`,
symbolic reloc lines (`lui $at, %hi(sym)` with `/* ... 3C010000 -> sym */`
or trailing `*/` only), and full-mnemonic lines (titproc style). Any
extraction regex keyed to `.word` or `-> ` silently DROPS words,
producing phantom out-branches, shifted byte-diffs, and bogus
"truncated symbol" conclusions (87F4 lost its lui; 116C appeared to
have 14 out-branches and a missing 0xD0 tail). The ONLY safe pattern:
`/\* [0-9A-Fa-f]+ ([0-9A-Fa-f]{8}) ([0-9A-Fa-f]{8}) \*/` -- every line
carries the addr+word pair in its comment regardless of rendering.
Better: use scripts/disasm-raw.py instead of ad-hoc regexes.

Addendum (2026-06-10, 940 in-tree): the raw-absolute gotcha is not
just a harness issue -- m2c lifts of USO code leave D-references as
bare `*(s32 *)0xNN` / `*(char *)0xNN` absolutes IN WRAP BODIES, which
compile to folded small-address loads (wrong shape AND wrong relocs).
Converting all 8 such sites in game_uso 940 to the
`*(int *)((char *)&D_00000000 + 0xNN)` extern form was worth +7.5pp
in-tree (89.74 -> 97.24). SWEEP LEAD: grep src/ for
`\*\((s32|u32|char|int) \*\)0x[0-9A-Fa-f]+\b` inside NM wraps -- every
m2c-lifted USO wrap is a candidate for the same mechanical fix.

CAVEAT to the raw-absolute sweep (2026-06-10): the conversion is
UNIT-CONVENTION-DEPENDENT. game_libs_post's 241 sites REGRESSED the
unit 47.0 -> 19.1 (reverted; the measure gate caught it): in game_libs
wraps, m2c's bare absolutes are placeholders for OTHER loaded bases
(not &D) -- converting adds wrong lui/addiu pairs and size-shifts
dozens of mid-% wraps. The conversion is only correct where the TARGET
materializes the D base at those sites (game_uso 940: +7.5pp; timproc
b5: +0.34pp). Rule: convert per-file ONLY with the unit measure gate,
and check a sample site's target asm for the lui/addiu+reloc pair
first. game_libs pools (post 204, game_libs.c 58, post0b 48) are OFF
the sweep list.

## uoptlist verbosity ceiling (2026-06-10): order questions yes, color questions no

-zdbug:6 gives the candidate/pseudo table (CREATION ORDER -- answers
temp-numbering and pseudo-order questions directly). :7 adds per-node
dataflow sets (av/ant live-range data, numlr counts). Higher values
(8/10/16/22/38/70) plateau at the :6 content; hex args don't parse.
The FINAL COLOR ASSIGNMENT (which lr -> which register) is not printed
at any probed level -- numcoloredlr prints 0 even for fns with v0/v1
pair residuals. Consequence for the "uoptlist queue": creation-order
class residuals (273B8 temp pattern, 5B5D8 skip) are inspectable;
pure coloring-choice residuals (E04 spill slot, ECEC/56814 pairs,
46C4C marshal-reuse) are NOT -- escalation would be reading uopt's
source in ido-static-recomp or patching more print paths (ecvt-style).

## Mnemonic-LCS diff for distributed-gap NM wraps (116C pass 5, +9.4pp in one block)

When an NM emit is N insns short and position-based word-diff shows
"everything differs", run difflib.SequenceMatcher over the two
MNEMONIC lists (opcodes only, build .o disasm vs target words disasm)
and print the delete/insert opcodes: missing CODE BLOCKS pop out as
contiguous `delete` runs (116C: one 27-insn run = an entire undecoded
sub-block; the rest were 2-3-insn shape gaps). Far faster than eyeball
side-by-side for 200+ insn fns; pairs with the multi-run convention --
each big delete run is one pass's decode target.

## m2c full-body graft: the cleanup-class checklist (90CC, 2.74->53.24)

For big-swing grafts of raw m2c output over a stub wrap (the pipeline:
.s comment words -> objdump 0-based blob -> label-resolved .s -> m2c),
the output needs a FIXED set of mechanical conversions before IDO
compiles it; apply in this order and re-grep after each:
1. collapsed callees: m2c emits bare `0(...)` calls for jal-0 -- regex
   `(?<![\w.])0\(` -> `func_00000000(`.
2. `->unkNN` -> `*(s32 *)((char *)(X) + 0xNN)` -- THREE forms: plain
   identifier, NEGATIVE offsets (`->unk-4`), and parenthesized bases
   (nested parens defeat one-shot regexes; fix leftovers by hand).
   TRAP: the identifier regex SPLITS hex literals -- `0x868C->unk1`
   matches `x868C` as the base, producing `0` + `(x868C)` garbage;
   sweep for `\bx[0-9A-Fa-f]{3,}\b` afterwards.
3. absolute derefs (`*0`, `*(s32 *)4`, `*(f32 *)0x8B0`, `*(void *)4`)
   -> `*(T *)((char *)&D_00000000 + N)`; mind that a naive `0` regex
   also hits the 0 in `0x..` (the `+ 0)x34` mangle) -- repair with
   `\+ 0\)x([0-9A-Fa-f]+)` -> `+ 0x\1)`.
4. `void *` locals -> `char *` (IDO rejects void* arithmetic); keep
   the signature.
5. float stores m2c typed as s32: `*(s32 *)(...) = (f32)` -> `*(f32 *)`.
6. m2c struct-ish stack vars (`spA.unkN`) -> `*((s32 *)&spA + N/4)` +
   declare the extra spilled words it references (sp60/sp64 class).
7. vtable calls `*(s32 *)((char *)(X) + 0xNN)(args)` -> cast through
   `((void (*)())...)`.
Each class is one regex; the whole graft (2106 insns) took ~7 cycles
of compile-and-fix. Expect 2-5% -> 40-55% structural in one tick.

Addendum to the graft checklist (7C1C, +38.5pp): (8) m2c emits
collapsed jal-0 calls as `NULL(...)` too (not just `0(...)`) -- handle
both; (9) double-chained `->unk` on parenthesized bases needs a
paren-BALANCED fixer (regex char classes fail on nested parens);
(10) anchor body edits at the DEF line including the `{` -- anchoring
on the function NAME alone finds the extern declaration first and
silently patches the wrong span (burned: a whole fixer pass no-op'd);
(11) if m2c says "label .LXXXX does not exist", the .s window is
UNDERSIZED (branch past declared end) -- re-extract through the gap
from the verified block asset / byte-exact ROM, not the .s.

Addendum (2E354): (12) inline jumptables in direct-linked game_libs --
extract-uso-jumptable.py needs a standalone USO module and does not
apply; SYNTHESIZE for m2c instead: case heads = the blocks after the
jr, delimited by unconditional-b convergence (block-walk); entries in
address order. The case ORDER is approximate -- expect m2c switch
structuring to wobble (flatten broken switches to goto-blocks with
case markers); refine later from the USO reloc records. (13) m2c
resolves REAL stored jal targets as absolute fn-ptr casts
`(T (*)(...))0xADDR(...)` -- convert to named externs (these are
recovered callee identities!). (14) ORDER MATTERS: run the *0/*(T*)N
absolute-deref conversions AFTER NULL->0 (or convert *NULL first) --
NULL->0 mints new `*0`s. (15) m2c `M2C_ERROR(unset register)` reads +
assignments from void-typed calls: placeholder with a loud marker
comment, fix in refinement.

Addendum (2BB7C): (16) YIELD PREDICTOR for graft target selection --
check the jumptable sltiu bounds vs fn size BEFORE grafting. Sparse
tables (bound ~= distinct case bodies; 2E354's 5/11) synthesize fine
(+39pp); DENSE tables (2BB7C: bounds 66/41/97 over 778 insns =
heavily shared bodies) defeat block-walk head inference and m2c's
structuring collapses (+14pp only). Dense-table fns should wait for
true table extraction from the USO reloc records, or be grafted with
tempered expectations. REFINED (2FB74): head COVERAGE is not
sufficient -- shared case TAILS + sparse case VALUES over wide ranges
(e.g. {24,34,0x104}) still interleave-collapse m2c's structuring under
an approximate order; such double-dispatchers are loader-RE-gated. ALSO low-yield: f64-HEAVY
fns (ldc1/sdc1/cvt.d density; m2c emits 'second half of f64'
placeholders) -- m2c f64 reconstruction + IDO f64 register pairing
diverge structurally (C234: +1pp). Check FP-width before grafting:
f32-heavy = sweet spot (+44..+75pp), f64-heavy = skip or temper.
THIRD low-yield class (454C4): BITWISE-FP -- float bits moved through
int regs (high 0x44xxxxxx COP1-move density; m2c types FP-reg temps as
s32, e.g. 's32 temp_f4'). m2c reconstructs bit-moves as int math; IDO
emits different sequences (+7pp only). REVISED 2026-06-10: 454C4
jumped 7.24->29.77 once its (u32)float FCSR-dance decompositions were
recomposed (now automatic in m2c-graft-clean.py) -- HIGH COP1 DENSITY
IS AMBIGUOUS between u32-cast dances (fixable) and true reinterpret
moves (the real cap). Diagnose by grepping the m2c output for the
2.1474836e9f signature BEFORE classifying as bitwise-FP. THRESHOLD CALIBRATION (5A2CC):
~11% COP1-move density still grafted fine (+47.9pp); ~15% (454C4)
killed it -- the line sits between, so measure density and temper
expectations in the 12-15% band. SHARPENED (5BE20, 19 COP1 + 12 f64 in
281 insns): bitwise-FP grafts can come out OVERSIZE (lw+mtc1 pairs vs
lwc1) past objdiff's alignment window -> fuzzy=None = ZERO metric
value (worse than the honest INCLUDE); and retyping the s32-typed
temp_fN vars INVERTS into cvt bloat when the values genuinely cross
int contexts. Mixed bitwise+f64 fns: skip the graft, leave bare,
typed hand decode only. Also: m2c recovering a RECURSIVE self-call
(jal to the fn's own address) needs the self-extern dropped -- the
def is the decl.

## game_libs jumptable TRUE-table extraction: negative result + leads (2026-06-10)

Searched for the 2E354/2BB7C jumptable words (data+0x5860/0x5880 per
the lw lo16s): NOT in assets/game_libs_post.bin (len 0x2d5c < the
offset!), NOT in game_libs_dl_data.bin (RSP ucode at that offset),
no pointer runs under raw/+0x24/-0x24 conventions anywhere in
post.bin. Conclusion: the lui %hi reloc does NOT resolve to the
post.bin data base; the true table lives wherever the BOOT-TIME
game_libs reloc processing maps it (possibly a heap-built table or
another section). UNLOCK PATH: RE the kernel's game_libs loader
(the reloc records at the segment tail -- 3-word (0x62-type, offset,
count) records decoded during the relayout ledger work) to learn the
hi16 resolution, THEN extract. Until then the dense-table fns keep
their approximate synthesized tables (graft items 12/16).

Addendum (4118): (17) GRAFT-VS-HAND-BODY crossover -- a full m2c graft
reliably beats stub/skeletal bodies (<40%: +14..+50pp observed) but
LOST to a 49.2% hand body (scored 48.1; m2c mixed ./->unk chains and
approximate tables cost more than the tail coverage gained). Rule:
below ~40% graft; above ~45% refine the hand body (LCS the gaps,
decode just the missing blocks). Always score-and-compare BEFORE
committing a graft over a hand body (monotonic rule). REFINED (4948):
the crossover is NOT purely %-based -- a 14.79% body beat a fresh
graft (14.60) because it already captured the m2c-equivalent skeleton.
The tell: graft score ~= existing score means the existing body IS
m2c-equivalent and the divergence is structural (register/shape/tail)
-- regeneration cannot help; only hand work moves it. The tell holds
at BOTH ends of the scale: at ~5% (4FD18: hand 4.56, fresh graft 5.30)
it means something STRUCTURAL is broken (caller-set regs, unalignable
shape) -- diagnose the mechanism, don't regenerate.

Addendum (B3C): (18) m2c "Label .LX refers to a delay slot" -- IDO
branch-likely targets another branch's delay insn. Fix iteratively:
move the label off the delay insn, add a continuation label right
after it, retarget the offending branch to an appended tail block
[duplicated delay insn; b continuation]. Loop until m2c passes (B3C
needed 3). FIXER GOTCHA (6E224): blanket deref-cast sweeps can match
their OWN OUTPUT across iterations, producing runaway chains
(*(s32 *)(s32 *)(s32 *)... ). Guard sweeps with (?<!\*\)) style
negative lookbehinds or collapse afterwards with
re.sub(r'(\*\(s32 \*\))(\(s32 \*\))+', r'', s). (19) m2c pointer-typed locals compared/arith'd with ints
need (s32) cast sweeps -- expect "Unacceptable operand of ==" tails.

Addendum (31F4C): (20) GRAFT PRE-FILTER -- if the disasm shows branch
targets far outside the fn (0x400xxxx-class) or backwards past the
start, dump the raw words first: 0x40xxxxxx = mfc0/mtc0 (CP0) words
that objdump renders as bogus branches. CP0 + zero-pad lead-ins +
busy-wait bne loops + cross-symbol backwards branches = a HANDWRITTEN
system block (permanent INCLUDE, reference_1080_mips3_runtime_helpers
class), not a splat fragment -- do not graft, merge, or decode. Caught
at game_libs [0x31DF8..0x32884) after one wasted m2c attempt; the
pre-filter costs one objdump grep. EXTENDED (6A5F0): k0-register
trampolines (3C1A/275A/03400008 = lui k0/addiu k0/jr k0) + sd/ld
64-bit saves (FFxx/DFxx opcodes) + CP0 density = the __osException
handler family -- same permanent-INCLUDE verdict, one more fingerprint
the pre-filter catches before m2c runs.

Addendum (3BE1C): (21) m2c can leak the literal `sp` stack symbol as a
pointer base (`*(s32 *)((char *)((sp + idx*4)) + 0xBC)`) when the fn
indexes its own stack frame as an array -- there is no C-expressible
equivalent under the graft conventions, so placeholder it with a
MARKED &D read (`/* sp-leak placeholder */`) and treat the marker as a
refinement site (the true form is a local array; declare one when
hand-refining). Also new mopped classes: hex-base `(void *)0xNNN->unkM`
(now in the cleaner), halfword *6-stride record reads (s16), and
comma-expression embedded stores.

Addendum (CI incident, 6B0FC/5A2CC): (22) GRAFT-PLACEMENT SAFETY --
when grafting onto a BARE INCLUDE (no existing wrap), rfind-based
'#ifdef'/'#else' anchors can match a PRECEDING function's wrap and
REPLACE THAT NEIGHBOR'S BODY silently (two wraps clobbered before CI
caught it). Rules: (a) after inserting, verify the new body's next
'#else' pairs with the SAME function's INCLUDE (one regex check);
(b) the local NM gate MUST be from-scratch (rm -rf
build/non_matching) after any wrap-structure change -- incremental
builds mask asm-processor's "symbol defined twice" that CI's clean
build hits; (c) the wrap-pairing audit (body -> next #else -> next
INCLUDE must name the same fn) across all touched fns costs seconds
and would have caught both. (d) EXTENSION (36224): an INCLUDE inside
an EXISTING wrap's #else accepts a nested insert that compiles but is
DEAD CODE (inner #ifdef NM inside outer #else never fires) -- the tell
is a perfectly FLAT score. Check for an enclosing wrap (is the nearest
preceding unmatched #ifdef/#else pair open?) before any insert.

Addendum (kernel 5C50): (23) KERNEL BOUNDARY CAVEAT -- the kernel
relayout verified SECTION bytes, not internal symbol boundaries;
unmatched kernel INCLUDEs still carry splat's boundary guesses. Tell:
a named jumptable whose ROM-true entries (readable directly from the
byte-exact ROM at VRAM-0x400+0x1000) land inside ANOTHER symbol's
span, and/or neighbors starting without prologues (bnez first insn =
fragment). Such regions need a boundary-merge analysis before any
graft/decode -- the kernel's symbolic .s feeds m2c directly once
boundaries are right (no raw-word pipeline needed there). METHOD
(5C50 region, 2026-06-10): derive the TRUE function map straight from
the byte-exact ROM -- disasm the region (kernel ROM offset = VRAM -
0x80000400 + 0x1000) and mark every `addiu sp,sp,-N` that follows a
`jr ra`+delay as a real prologue. The [0x5C50..0x65B0) region is 7
real functions where splat drew 9+; the map lives at the kernel_010
wrap. Caveat: validate jumptable attribution against the map before
trusting it (the E->F dispatch paradox is unresolved -- a dispatch
whose %lo-resolved table targets another mapped fn means either
misattributed relocs or a wrong boundary; resolve before decoding).

Addendum (1304C pass 7): (24) M2C GOTO-LOOP SNAPSHOT = PHANTOM S-REG.
When m2c renders a nested loop as goto-loop_N spaghetti, it can
materialize a SNAPSHOT local of a loop variable (taken before the
inner loop, compared at the back-edge) that the original C never had
-- the build then saves an extra callee-saved pair (move sN,tX +
bne sN,tY back-edge is the asm tell; prologue saves N+1 s-regs vs
target N with a SMALLER target frame... or larger if the original
kept values on the stack). Diagnose: disasm the build, find each
extra s-reg's first def; if it's a `move sN,<other loop reg>` right
before an inner loop, it's the snapshot artifact. Fix = re-derive the
nest as clean for-loops (score-volatile; do it in a focused pass, not
a cadence tick). VALIDATED on the source case (1304C pass 8): nested
fors + row<<5 recompute killed BOTH the snapshot s-reg and the offset
accumulator; register set matched the target exactly; +1.4pp
(86.32->87.76) and -0x20 frame in one edit.

Addendum (20A28): (25) `M2C unset $fN` / `M2C unset $vN` markers in
m2c output = CALLER-SET REGISTER detector -- the fn reads a register
the caller leaves set (here $f0 multiplied at 4 sites). IDO C cannot
express it: permanent structural cap (the caller-set-reg class, float
variant). Do NOT graft such output: m2c renders the read as `* 0`
placeholders, IDO constant-folds the expressions away, and the result
goes fuzzy=None (undersized/unalignable). Keep the existing measurable
body, classify at the wrap. Add `grep "M2C unset"` to the post-m2c
pre-filter alongside the 2.1474836e9f check. CORRECTED (47B40): run
the grep on the CLEANED output (or both) -- the raw m2c file can carry
the marker in a form the simple grep misses while the cleaned body
shows `/* M2C unset $t6 */` inline; 47B40's $t6+$f4 caller-set
markers slipped past the raw-file grep and were caught by eye in the
cleaned head.

Addendum (26D64): (26) M2C DUFF'S-DEVICE CASE FALL-INS -- on dense
dispatchers where a case head is also a branch target from another
arm, m2c emits `case 0xNN:` labels INSIDE else-branches or OUTSIDE
the switch's closing brace ("case or default label appears outside a
switch statement"). Flatten to a comment + duplicate the arm's logic
in place (the fixer's flatten rule). Costs structure: the target's
true shape is a goto-into-switch / shared-arm form, so expect a
modest score (26D64: 3.74->19.58 only). Also new cleaner classes:
(bitwise s8/s16) -> plain int casts, (bitwise uN) -> (uN).

## Reading the uoptlist global-coloring section (15F0 trace, 2026-06-10)

The -Wo,-zdbug:6 dump's tail (after "reg alloc preparation") is the
global coloring log, one line per candidate decision:
  `  90:   90 assigned (constrained)   3`
= candidate(live-range) 90, live-unit 90, got REGISTER 3 by a
CONSTRAINT (copy to/from a precolored node), where the number is the
MIPS register index (2=v0, 3=v1, 4-7=a0-a3, 8-15=t0-t7, 24=t8).
`live range 90: 90 split out 113` lines show live-range splitting;
`not colored (-ve save)` = spilled (negative save = not worth a reg).
For 15F0: the contested src temp IS candidate 90 -> reg 3 ($v1)
"(constrained)" -- v1 is forced by a constraint edge, not a free pick;
the C-side levers fail because they don't break that edge. Next: find
which copy creates the constraint (the candidate table's isop lines
referencing {90|x}) and restructure THAT expression. This makes the
temp-pool renumber class mechanically diagnosable: dump, find the
contested candidate's "(constrained)" line, trace its constraint
source. DEPTH 2 (15F0): live-range IDs in the coloring section are
SPARSE (14 ids vs finalnumlr=16 -- they are lr ids, not dense
indices); "(constrained) R" is a CONSTRAINED-POOL pick where v1
precedes t0 in the preference order for non-call-spanning temps. A
target coloring t0 where the build picks v1 therefore implies the
ORIGINAL's lr spanned a constrained point the rebuilt one doesn't --
the diagnosis question becomes "what made the original lr longer/
constrained", answerable only with uopt allocator internals
(preference-order + constrained-point semantics). Open research item;
candidates: ido-static-recomp uopt RE notes, community uopt source.
