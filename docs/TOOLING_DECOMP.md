# Tooling Decomp

> Decompilation tooling: m2c, Ghidra, the permuter, decomp.dev integration.

_7 entries. Auto-generated from per-memo notes; content may be rough on first pass — light editing welcome._

## Index

- [Decomp prioritization — call-graph DFS from entry point beats by-segment-size mass-match](#feedback-decomp-call-graph-priority) — When a project has a clear entry point (USO loader → main loop → per-frame update), depth-first decomp from there reveals the actually-used 
- [CI / decomp.dev compares fresh build/.o vs committed expected/.o — `make expected` results MUST be git-committed for changes to show on the dashboard](#feedback-expected-must-be-committed-for-decomp-dev) — The land script and `scripts/refresh-report.sh` do NOT run `make expected`. CI checks out the repo, builds fresh `build/.o`, then runs `objd
- [Ghidra struct annotation does NOT auto-propagate across xrefs — each function in a family needs its own prototype set](#feedback-ghidra-struct-annotation-doesnt-auto-propagate) — Validated 2026-05-04 on 1080's rmon family. Setting `RmonMsg *msg` on func_80006D0C makes its decomp use `msg->type / msg->id / msg->domain`
- [Permuter scores ≥1000 genuinely mean "structural issue, no match possible" — stop grinding](#feedback-permuter-1000-plus-structural) — Ran decomp-permuter random mode for ~3 minutes on `n64proc_uso_func_00000014` (12k+ iterations). Best score 1030. Per the skill's score-band
- [pyghidra-mcp setup notes for N64 decomp work — JDK 21, raw-binary load, MIPS:BE:32:default, ~7-min auto-analysis](#feedback-pyghidra-mcp-setup-for-n64-decomp) — pyghidra-mcp install gotchas verified 2026-05-04. Needs Ghidra 12.x + JDK 21 (NOT JDK 17). N64 ROMs need raw-binary load with explicit langu
- [report.json was overstating because land script used `make expected` — RESOLVED 2026-05-04](#feedback-report-json-vs-decomp-dev-diverge) — HISTORICAL — the land script's `make expected` blanket-cp build/→expected/ used to pollute expected/ with decomp-bodies build, inflating mat
- [When to consult Ghidra during /decompile (trigger list — m2c remains the default)](#feedback-when-to-consult-ghidra-during-decomp) — 1080 has a Ghidra project + MCP server, but reaching for Ghidra has cost (slower than m2c, GCC-flavored not IDO-flavored). Use only when one

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
- Prior passes already tried decl reordering + literal folding
- The skill's band rubric "1000+ structural" applies

When to TRY permuter:
- Remaining diff is 1-3 instructions in leaf-function **scheduling** (operand position in the stream, not register choice)
- Operand swaps on commutative ops (addu, or, and)
- Branch-likely conversion patterns
- Score likely 100-500 band AND the diff isn't a register-pick

**Key distinction:** permuter can flip instruction ORDER but not register ASSIGNMENT. If the target and mine differ only in "what register holds this value" (regardless of $s/$a/$t class), random-mode permuter cannot reach the target — the allocator's decision is deterministic given the RTL shape, and permuter's random C mutations usually preserve the shape enough that the allocator makes the same choice.

**Cost:** ~3 min + a few MB of output variants in `nonmatchings/<func>/`. Always clean up with `rm -rf nonmatchings/` after.

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

