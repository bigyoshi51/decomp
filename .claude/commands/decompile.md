Decompile a function in the N64 decomp project. The user may provide a function name as an argument, or you should pick the next best candidate.

## Finding the project

The decomp project lives under `projects/`. Find the splat YAML config and the `src/` directory.

If multiple agents are working simultaneously, each agent should work in its own git worktree. Worktrees for 1080 Snowboarding live at `projects/1080-agent-<letter>/` on branch `agent-<letter>`, with shared toolchain links and a local `assets/` copy. Before starting, check `git worktree list` and:
- If you already have a worktree, work there.
- If not, create one with `scripts/spin-up-agent.sh <project>` from the repo root — it picks the next free letter and runs the project's `.agent-setup` recipe (symlinks, asset copy, local gitignore). Don't repeat the recipe by hand.
- Never commit on `main` while another agent is also active — coordinate via worktrees or stop.

## Strategy: check project memory before picking a function

Before grabbing the smallest unmatched function, check whether the project has a documented strategy:
- `~/.claude/projects/.../memory/project_<projname>_strategy.md` — high-level priorities
- `~/.claude/projects/.../memory/project_<projname>_*_map.md` — per-segment call graphs and decomp ordering

For 1080 Snowboarding specifically (per `project_1080_strategy.md`):
- **Goal: 100 % decomp first, then PC port** — clean separation, decomp completes first.
- **Prioritize call-graph DFS from game.uso entry points**, NOT biggest-segment-first. See `feedback_decomp_call_graph_priority.md`.
- **Type structs just-in-time** when 5+ functions access them. Don't pre-type, don't defer forever.
- **Mass-match wrappers is BACKGROUND filler**, not the primary strategy. Don't grind game_libs wrappers when the call graph from game.uso has unmatched functions ahead.
- **Defer constructors** (large funcs with many `alloc()` cross-calls) until the structs they touch are typed.

## Picking a function

If no function is specified, **roll for a source at random per /decompile run** — no strict priority. This spreads coverage, avoids agent collisions, and surfaces different techniques over time.

**Actually roll.** Run preflight first — it restores tracked files (e.g. `report.json`), warns on parallel-agent merge artifacts, checks branch staleness, AND prints your rolled source on its last line:

```bash
scripts/decomp-preflight.sh
```

Use the `source=N` line from its output and commit to that number. Don't pick in your head — "random" by hand clumps on whatever you did last time. Don't skip preflight; the gotchas it catches are repeat offenders (see `feedback_report_json_tracked.md`, `feedback_parallel_agent_wrap_nesting.md`).

Sources (indexed 1-5):

1. **An existing NM wrap at 80-99%** — `grep -rn "#ifdef NON_MATCHING" src/`. Analysis is already done; a new technique may promote it to exact (e.g. the "pass unused a0 to callee" fix).
2. **A sibling of a recently-matched function** — same offset range, similar asm shape. See `feedback_mirror_function.md`.
3. **A small unstarted function (size-sort)** — `uv run decomp discover --sort-by size`. Fresh exploration. Caveat for 1080: discover misses prefixed USO names (`gl_func_*`, `game_uso_func_*`, etc.) — walk `asm/nonmatchings/<seg>/<seg>/` directly for those.
4. **A small unstarted function in an untouched USO** — scan for the standard accessor templates (int reader / float reader / Vec3 reader / Quad4 reader). One C body matches the same template in every USO at different offsets. See `feedback_uso_accessor_template_reuse.md`.
5. **A strategy-memo pick** — if `project_<name>_strategy.md` or `project_<name>_*_map.md` names a priority (e.g. call-graph DFS from an entry point), follow it.

**Commit to the first candidate the source yields — don't re-roll or silently pivot.** The source's natural first candidate (first NM wrap grep'd, first unmatched sibling, first size-sort entry, first spine function in the memo) IS the candidate. You may skip only for the reasons in the short list below; anything else is you avoiding work. If the candidate looks hard, that's the job — grind, or wrap it NM with whatever partial C you get. **An empty /decompile run is not an option — every invocation commits a diff** (a match + episode, an NM wrap, or a fragment merge/split).

**Always skip (short list — anything else, you grind):**
- Functions that are all `.word` directives (data misidentified as code)
- Handwritten — `.s` file has `/* Handwritten function */` comment, or it's a libreultra `.s` file (per `reference_libreultra.md`)
- Recently-reverted — `git log --all --grep=<func>` shows a `Revert "..."` commit (unless you have a new technique to try; document what's different in your commit message)

**Constructors are NOT a skip reason.** They need to be done eventually, and the partial C you produce while grinding (named struct offsets, inferred field types, documented callee signatures) IS the struct-typing work. A 60 % NM wrap for a constructor with offsets like `a0->field_28 = &D_00000000` is the source-of-truth for what field 0x28 means — future passes tighten it. Don't let "struct not typed yet" be an excuse; typing happens BY doing the decomp.

**Fragments are NOT a skip reason** — if the candidate is a splat mis-split (no prologue, undefined regs at entry, or trails into the next function), step 1a's boundary check runs `split-fragments.py` or the `merge-fragments` skill to fix the boundary, then decompilation proceeds normally.

**Multi-run decomps are normal.** For a 1+ KB function, one /decompile run reads the asm and writes initial C — probably 40-60 % match. Commit as NM with a real C body (no `INCLUDE_ASM`-only fallback). The next run tightens structure, the next tightens register allocation, etc. Each run's commit is a monotonic NM-% improvement until it hits 100 %. A single /decompile run isn't expected to produce a 1.5 KB exact match from scratch; it IS expected to produce forward progress on whatever you started.

**Anti-pattern to catch yourself in:** "I scanned 5 candidates and all were {constructors | FPU-heavy | documented-NM-ceilings} so I ended the /decompile run without a commit." That IS the bail pattern — it means the easy work is done for this project, and the remaining work is intrinsically hard. Pick the first non-skip candidate from your rolled source and commit to it, even if it's a 2 KB orchestrator. The resulting NM wrap is the commit.

## Decompilation workflow

1. **Read the assembly**: Read the function's `.s` file from `asm/nonmatchings/`

1a. **Boundary sanity check** — before grinding, verify the `.s` file contains ONE function. Splat/generate-uso-asm can mis-split boundaries in FOUR directions:

   **Quick pre-check:** `grep -c "03E00008" <asm_file>.s`. If the count is >1, the file contains multiple function bodies (each `jr $ra` ends one). For big strategy-memo picks, ALWAYS run this — the memo's "1.7 KB self-contained algorithm" label is unreliable on relocatable USO code because splat can't see function boundaries without symbol info.

   - **Too big, bundled leaf** (this file is merged with the NEXT function's leaf body): look for `jr $ra` + delay slot followed by non-nop instructions still inside the declared `nonmatching SIZE`. If the tail reads caller-save registers (`$a0`-`$a3`) without initializing them, it's a second function whose caller sets those args. Run `scripts/split-fragments.py <func_name>` to split before decompiling. See `feedback_splat_fragment_split_no_prologue_leaf.md`.
   - **Too big, N-function bundle** (this file is 3+ distinct functions splat couldn't separate — common in USO segments): multiple `jr $ra` sequences in the middle of the declared size, each followed by a new prologue (`addiu $sp, $sp, -N`). Run `split-fragments.py` recursively on each newly-split-off function until no more splits happen. See `feedback_strategy_memo_size_misleading.md`.
   - **Too small** (this file is a tail of the PREVIOUS function): the file has no `addiu $sp` prologue and starts with loads/stores using uninitialized `$t` registers. Use the `merge-fragments` skill to merge back. See `feedback_splat_fragment_via_register_flow.md`.
   - **Prologue-stolen successor** (this `.s` starts with `addiu $sp` but immediately uses `$v0`/`$tN` as a base register without setting it): check the predecessor's `.s` tail — if it ends with `lui rX, 0; addiu rX, rX, N` (or `lui rX, 0; lw rX, N(rX)`) where `rX` matches the unset register the successor reads, those 2 insns belong logically to the successor's prologue but are inside the predecessor's symbol. C-only emit always duplicates them at the successor's start (+8 bytes vs expected). Fix: write the C body normally with `*(int*)((char*)&D_00000000 + N)` accesses, then add `build/src/<seg>/<file>.c.o: PROLOGUE_STEALS := <func_name>=8` to the Makefile (after the existing per-`.o` overrides). The build pipeline runs `scripts/splice-function-prefix.py` post-cc to remove the redundant 8-byte prefix. See `feedback_prologue_stolen_successor_no_recipe.md`.
   - If any boundary bug is present, fix THAT first — the function can never match while boundaries are wrong. Skipping just defers the problem.

1b. **Reference search — ALWAYS do this before grinding**: many libultra, rmon, and libc helpers are already decompiled in sibling N64 projects. For any function whose asm suggests it's part of libultra (`__os*`, `os*`, `__rmon*`, `__ll_*`) or a libgcc helper (`ddiv`, `dmultu`, `dsllv`, etc), run:

    ```bash
    /home/dan/Documents/code/decomp/scripts/decomp-search osSetEventMesg
    ```

    This greps across local clones of `libreultra`, `oot`, and `papermario` at `/home/dan/Documents/code/decomp/references/`. A hit usually means you can copy the signature and body directly (watch for compiler differences — OoT uses GCC, we use IDO, so the exact bytes may differ, but the structure and logic are reusable).

    Also decode any **hardware register addresses** (`0x04000000`, `0xA4600010`, etc.) via:
    ```bash
    grep -E "0x04000000|0xa4600010" /home/dan/Documents/code/decomp/references/indexes/hw_registers.h
    ```

    For register-name lookups (e.g. "what address is `SP_STATUS_REG`?"):
    ```bash
    /home/dan/Documents/code/decomp/scripts/decomp-search --reg SP_STATUS_REG
    ```

    **If libreultra has the function as a `.s` file (hand-written assembly)** — like `__osSetFpcCsr`, `__osDisableInt` — it's meant to stay as INCLUDE_ASM. Don't try to write inline-asm C for IDO; it doesn't parse GCC's `__asm__` syntax. The target ROM has those same bytes.

    **Last resort when stuck**: search https://decomp.me for scratches of this function (browser only — API is Cloudflare-gated). Paste your asm into the search; any matched scratch shows the exact C that matched elsewhere.

1c. **Ghidra (1080 only, optional, decision-by-trigger)** — 1080 has a persistent Ghidra project at `projects/1080-*/build/ghidra-project/tenshoe.gpr` with all 2,500+ named functions and the entire ROM analyzed. Ghidra complements m2c with: typed-struct decomp output (`msg->id` instead of `*(int*)(arg+0xc)`), instant cross-references (`list_xrefs`), and persistent type annotations across queries.

   Use Ghidra ONLY when one of these triggers fires (otherwise stick with m2c — faster, IDO-flavored):
   - **Struct shape unknown**: function reads `*(T*)(arg + 0xN)` patterns and you don't know the struct → set the struct + prototype, re-decompile to see field names.
   - **Family of related functions** (≥3 callers of a shared callee): use `list_xrefs` to enumerate the family in one call (vs grep), then batch-annotate.
   - **Stuck partial wrap with structural mismatch** (fuzzy <50%, control flow unclear): Ghidra's canonical-form output often reveals the function is much simpler than your draft (e.g., `return (X & 3) == 0;` instead of build-up-and-return).
   - **Suspected fragment**: Ghidra's output uses `in_t9` / `in_stack_*` (uninitialized regs/stack reads) → not a standalone function, caller passes registers. Diagnostic signal.

   Don't reach for Ghidra: byte-correct matching (Ghidra's GCC-flavored decomp won't byte-match IDO emit), register-allocation grinding (use the permuter), final-mile tightening at >90% (m2c is closer-to-IDO).

   **Tools** (1080 worktrees only):
   - `bash scripts/ghidra-decompile-func.sh <func_name>` — one-shot decomp via cached project
   - `python3 scripts/ghidra-annotate-family.py --struct-name RmonMsg --funcs func_A,func_B` — batch struct annotation
   - `bash scripts/setup-ghidra.sh` — initial project build (~7 min one-time, ~5 sec incremental)
   - MCP server (via `.mcp.json`) for in-Claude queries — read-side reliable; write-side has had hangs (`set_function_prototype`). Prefer direct CLI scripts for write operations.
   - See `feedback_pyghidra_mcp_setup_for_n64_decomp.md` and `feedback_ghidra_struct_annotation_doesnt_auto_propagate.md` for setup quirks and the no-auto-propagation caveat.

2. **Get initial C with m2c**: Run `uv run m2c --target mips-ido-c <asm_file>` to get pseudo-C. This gives a starting point but often needs adjustment.

3. **Write the C code**: Replace the `INCLUDE_ASM` line in the source file with:
   - Forward declarations for any called functions
   - The decompiled C function
   - Keep it simple — match the assembly's logic exactly, don't over-abstract

4. **Build**: Run `make RUN_CC_CHECK=0` from the project directory

5. **Compare**: Check if the function matches byte-for-byte:
   ```python
   import struct
   rom = open("baserom.z64", "rb").read()
   built = open("build/<target>.z64", "rb").read()
   for i in range(<func_rom_start>, <func_rom_end>, 4):
       b = struct.unpack('>I', rom[i:i+4])[0]
       c = struct.unpack('>I', built[i:i+4])[0]
       if b != c:
           print(f"0x{i:06X}: base=0x{b:08X} built=0x{c:08X}")
   ```

6. **Iterate if not matching — DO NOT GIVE UP EASILY**: Try at least 8-10 structurally different variations before moving on. Compile standalone first (`tools/gcc_2.7.2/linux/gcc -O2 -g2 -G0 -mips3 -mgp32 -mfp32 -Wa,--vr4300mul-off -S -o /tmp/test.s /tmp/test.c`) and compare the `.s` output against the original. This is faster than full ROM builds.

   Common issues and fixes:
   - **Wrong register allocation (leaf functions)**: In leaf functions, variable-to-register mapping is very sensitive to expression structure. Try:
     - Split `val = *ptr + 1` into `val = *ptr; val++;` — this can change which $a register gets assigned
     - `val = *ptr; val += 1;` produces `addu` (register add) while `val++` may produce `addiu` (immediate add)
     - Reorder variable declarations
     - Modify args in-place (`arg2 -= n`) instead of separate local variables
   - **Wrong register allocation (non-leaf)**: Saved registers ($s0-$s7) are assigned by the global allocator in `docs/gcc-2.7.2/global.c`. The exact priority formula is:
     ```
     priority = floor_log2(n_refs) * n_refs / live_length * 10000 * size
     ```
     Higher priority → lower register number ($s0 before $s1 before $s2). When priorities are equal, the tiebreaker is allocno number (first-encountered pseudo wins).

     **Debugging register allocation**: Use `cc1 -dg` to dump the `.greg` file showing exact pseudo→hard register mapping:
     ```bash
     export COMPILER_PATH=tools/gcc_2.7.2/linux
     tools/gcc_2.7.2/linux/cc1 /tmp/test.c -O2 -G0 -mips3 -mgp32 -mfp32 -dg -o /tmp/test.s
     # Check /tmp/test.c.greg for "Register dispositions" and RTL
     ```

     **Practical techniques**:
     - Separate temporary variables for values that don't survive function calls (keeps them in $a/$v regs instead of $s)
     - Example: `chunkSize = arg2; func(chunkSize);` keeps chunkSize in $a2. But `bytesTransferred = arg2; result = func(bytesTransferred);` may put bytesTransferred in $s0 if reused later.
     - To boost a variable's priority: add more uses (refs) or shorten its live range
     - To lower a variable's priority: lengthen its live range (define it earlier, use it later)
     - Combining operations into one expression (e.g., passing `(val & ~mask) | arg1` inline to a function) reduces ref counts for intermediate variables, changing priorities
   - **Branch-likely (`beql`/`bnel`) not emitted**: GCC 2.7.2 emits branch-likely for specific patterns:
     - `if (cond) { *ptr = val; return val; }` with no else → `bnel`/`beql` with store in delay slot
     - BUT only when the branch target is the function epilogue (not a common store block)
     - Use `goto label` to a shared store+return point — this produces `beql` where `if/return` blocks don't
     - Wrapping code in `if (val >= 7) { ... } store: *arg0 = val; return val;` with gotos inside produces the right beql pattern
   - **`return` vs `break` in loops**: `return totalBytes` inside a loop skips cleanup code (produces `beql` to epilogue). `break` goes to after the loop where cleanup still runs. Check if the asm's early exit skips `jal` cleanup calls.
   - **Filled delay slots in -g2 functions**: GCC's `reorg.c` fills delay slots REGARDLESS of `-g2`. The `-g2` flag only affects the assembler's reordering. So `jr $ra; addiu $sp` can appear in `-g2` functions — this is normal, not a flag mismatch.
   - **Shared reload after conditional store**: When both branches of an if/else converge on a reload from memory (e.g., `brightness = D_801E64B8`), GCC shares the reload at the merge point. If your C produces duplicate reloads (one in the if-body, one after), use a separate variable: `diff = D_801E64B8; diff -= target;` rather than `brightness = D_801E64B8; brightness -= target;` after already using `brightness` for the store.
   - **If/else arm swapping**: GCC may lay out if/else arms in the opposite order. If the compiled code uses `bnez` where the original uses `beqz` (or vice versa), try swapping the if/else arms in C.
   - **Unsigned comparison**: `(u32)arg > 0x8000U` produces `sltu`. Plain `arg > 0x8000` with signed types produces `slt`. Check the asm opcode.
   - **Instruction scheduling barrier**: GCC's scheduler may hoist loads before stores when there's no data dependency. Use `__asm__("")` as a scheduling barrier between statements to prevent reordering. Example: `D_801F6450 = val; __asm__(""); dir = D_801E64C0;` prevents the load from being hoisted before the store.
   - **Float comparison register assignment**: `a < b` and `b > a` are semantically identical but produce different register assignments for `c.lt.s`. If the float comparison has swapped registers, try writing it the other way (`D_801F644C > D_80100120` instead of `D_80100120 < D_801F644C`).
   - **Pointer-based access for address computation**: If the original uses `la $v0, SYMBOL` + `lwc1 $f6, 0($v0)` (pointer pattern) instead of direct `lui+lwc1`, use `f32 *ptr = &SYMBOL; *ptr += val;` in C to match.
   - **Wrong stack frame size**: Try `char pad[4]` to add 8 bytes of stack frame padding without generating extra instructions. GCC optimizes away unused locals but still allocates stack space for them. Also try reordering variable declarations.
   - **Register swap ($s0/$s1/$s2 wrong assignment)**: Use `register s32 var asm("$16")` to force specific $s register. GCC 2.7.2 honors this. Combine with `__asm__ volatile("addu %0, %1, $0" : "=r"(dst) : "r"(src))` to force register copies that GCC would optimize away.
   - **Loop head address cached in $s instead of reloaded**: If the original reloads `&HEAD` from scratch at the loop end but GCC caches it in $s, use `__asm__ volatile("addu %0, %1, $0" : "=r"(head) : "r"(&HEAD))` inside the if-block to force the copy. For simpler loops, `__asm__ volatile("la %0, SYMBOL" : "=r"(var))` at the loop end.
   - **Load-delay scheduling (i++ placement in CRC/loop)**: Split the expression: `tbl_val = table[...]; __asm__(""); i++; result = (result << 8) ^ tbl_val;` — this places `i++` between the `lw` (table load) and the `sll/xor` (shift/combine), matching the original's load-delay-slot scheduling.
   - **Trailing nop alignment**: If the function is 4 bytes shorter than the original (missing a trailing nop), add `__asm__(".align 3");` after the function closing brace to pad to 8-byte alignment.
   - **Post-increment in function args for delay slot scheduling**: `func(dst++, ...)` generates "setup arg, increment, call" which places the increment before the jal — matching original delay slot patterns. Use when the original has `addu $a0, $s1; addiu $s1, $s1, 1; jal func`.
   - **Unsigned vs signed shift**: `u32 >> 16` produces `srl` (logical), `s32 >> 16` produces `sra` (arithmetic). If the original uses `srl`, make the variable `u32`.
   - **`char pad[4]` for stack frame padding**: Adds 8 bytes to the stack frame without generating any extra instructions. GCC allocates space for unused locals but optimizes away their access. Use when the original frame is 8 bytes larger than what GCC produces.
   - **Wrong instruction for constant**: `-2` vs `~1` vs `0xFFFFFFFE` can produce different instructions
   - **Optimization level**: Check if this file needs `-O0`, `-O1`, or `-O3` instead of `-O2` (add per-file override in Makefile)
   - **Function emit is +8 bytes vs expected, with leading lui+addiu that doesn't appear in expected**: prologue-stolen successor — the implicit base-register setup lives in the predecessor's symbol. DON'T grind register-allocation knobs. Add `build/src/<seg>/<file>.c.o: PROLOGUE_STEALS := <func_name>=8` to the Makefile (the build pipeline runs `scripts/splice-function-prefix.py` post-cc to remove the redundant prefix). See step 1a's "Prologue-stolen successor" boundary case and `feedback_prologue_stolen_successor_no_recipe.md`.

6b. **Use objdiff-cli for instruction-level diffing** (much better than raw hex comparison):
   ```bash
   # Side-by-side mnemonic diff of a specific function:
   objdiff-cli diff -u src/D910 func_8010CD28

   # Full progress report (JSON):
   objdiff-cli report generate

   # Re-generate expected baseline after matching changes:
   make expected RUN_CC_CHECK=0
   ```
   objdiff shows exactly which instructions differ with mnemonics, registers, and immediates — far more readable than comparing hex words. Use it instead of the Python ROM-comparison script when grinding on diffs.
   For final exact-match verification, also compare built vs expected with
   `objdump -M no-aliases`. Plain aliased disassembly can hide real mismatches
   such as `beq` vs `beql` / `beqzl`, `bne` vs `bnel`, or `or reg,src,zero`
   rendered as `move`. A function is only exact if the no-alias disassembly
   still matches and `report.json` reports it as exact.

7. **When matched**: Verify the build/object matches, then log the episode immediately. A decompile is not done until `episodes/<func>.json` exists in the same worktree and is ready to commit with the code change.

8. **Log the episode**: After every successful match, run the canonical CLI (writes `episodes/<func>.json` in the canonical `Episode`/`Step` schema; **do NOT** use the old `decomp.episode.log_success`):
   ```bash
   uv run python -m decomp.main log-exact-episode func_XXXXXXXX \
       --source-file src/<file>.c \
       --asm-file asm/nonmatchings/<segment>/func_XXXXXXXX.s \
       --log-dir episodes \
       --segment <segment> \
       --compiler <compiler> \
       --compiler-flags="<flags>" \
       --verification "Verified with objdiff / project build." \
       --assistant-text "Manual exact match. Key matching notes here."
   ```
   Optional: `--m2c-file <path>` or `--m2c-text <text>` to seed the initial step. The land script validates the schema — file existence alone isn't enough.

9. **Commit**: After logging the episode, commit the changes immediately:
   ```bash
   git add src/<file>.c episodes/<func_name>.json
   git commit -m "Decompile <func_name> (<brief description>, <N> instructions)"
   ```
   Commit after EACH matched function — don't batch. This keeps the history clean and makes it easy to bisect regressions.

9a. **Land successful decompiles immediately**: If you are working in a branch/worktree, every successful decompile must be landed to `main` and pushed to `origin/main` right away with its corresponding `episodes/<func_name>.json` in the same landed history. The required sequence is:

   ```bash
   ./scripts/land-successful-decomp.sh <func_name>
   ```

   In 1080 Snowboarding, this script rebases the current worktree branch onto
   `origin/main`, regenerates `report.json`, and refuses to land unless the
   named function is reported as an exact match in `report.json`
   (`fuzzy_match_percent == 100.0` is acceptable here), has no `INCLUDE_ASM`
   fallback still present in `src/`, and has a matching
   `episodes/<func_name>.json` that passes the canonical schema validator. If
   any of those checks fail, the function is not exact yet: keep it wrapped as
   `NON_MATCHING` and do not log an episode.
   If the checks pass, the script fast-forwards the main worktree, pushes
   `origin/main`, and refreshes `report.json` in both worktrees. If you need to
   do it manually, the fallback sequence is:

   ```bash
   # from your worktree branch
   git fetch origin
   git rebase origin/main

   # from the main worktree
   git fetch origin
   git merge --ff-only origin/main
   git merge --ff-only <worktree-branch>
   git push origin main
   objdiff-cli report generate > report.json
   ```

   Do not stop at a branch-local commit for a successful exact match. Do not merge or push a successful decompile while leaving its episode behind. If you have unrelated WIP in the worktree, stash it first, land the successful decompile, then restore the WIP.

9b. **Update the README on milestones**: The project README has a per-segment progress table. Keep it fresh — the user explicitly rejected the old 2pp threshold as "extremely silly" and switched to 0.1pp. Trigger a README refresh when:

   - **A new segment is set up** (e.g., first time adding `bootup_uso` or `game_libs` to the build). Add its row to the table, mention any new decomp pattern.
   - **A tracked number drifts by ≥0.1 percentage points** from what's in the README (for any segment or the overall total). `scripts/refresh-report.sh` prints a staleness warning when this happens.
   - **A segment crosses a round-number milestone** (25 %, 50 %, 75 %, 100 % of that segment's functions or code).
   - **The "not tracked" list changes** — e.g., we start tracking a USO overlay that was previously opaque.

   How to check: compare `report.json` against the table in `README.md`. If an update is warranted, edit the README inline (don't spawn a separate branch) and land it with the current decomp commit or as a standalone "Update README progress stats" commit. Regenerate the report first: `objdiff-cli report generate -o report.json`. Keep the table concise — this is a project README, not a changelog.

10. **NON_MATCHING functions — preserve partial C, don't delete it**: if a function is decompiled but the build % is below 100, **do NOT revert to a bare `INCLUDE_ASM` line**. Instead, wrap the decompiled C in `#ifdef NON_MATCHING ... #else INCLUDE_ASM(...); #endif`. This preserves the C for reference, keeps the default build at 0 ROM diffs (INCLUDE_ASM path), and lets future agents or `decomp-permuter` pick up from the partial.

   **Template:**
   ```c
   #ifdef NON_MATCHING
   /* <diff summary: % match, what's left different, what you tried>
    * Bytes match except for [describe the diff]. */
   void gl_func_XXXXXXXX(...) {
       /* decompiled body */
   }
   #else
   INCLUDE_ASM("asm/nonmatchings/game_libs/game_libs", gl_func_XXXXXXXX);
   #endif
   ```

   **Do NOT log an episode** for a NON_MATCHING function. Episodes are the training dataset for exact matches only (asm → C triples where the C compiles to the exact bytes). A NON_MATCHING function's C would train on incorrect output. Commit the NON_MATCHING wrap as `Wrap gl_func_XXXXXXXX as NON_MATCHING (<reason>)` without a corresponding `.json` in `episodes/`.

   **No threshold.** Any decoded C body goes in an `#ifdef NON_MATCHING` wrap — 40 %, 60 %, 80 %, 99 %. The previous "≥80 % only" rule turned out to be arbitrary (decoded control flow at 60-75 % is still useful reference) and forced awkward source-comment workarounds. The wrapped C is strictly more useful than nothing: compilable, permuter-testable, grep-discoverable. Include the match %, what's still different, and what you tried in the comment so the next pass has context. Exact byte-matching remains the final standard — a 60 % wrap IS progress but it's not a match; only log episodes for 100 %.

## IDO-specific notes (for 1080 Snowboarding and other IDO projects)

- **Compiler**: IDO 7.1 (`tools/ido-static-recomp/build/7.1/out/cc`)
- **Flags**: `-O2 -G 0 -mips2 -32 -non_shared -Xcpluscomm -Wab,-r4300_mul` (game code) or `-O1` (libultra)
- **`register` keyword**: IDO respects `register` as a STRONG hint. Use `register s32 sr = __osDisableInt();` to get `$s0` allocation instead of stack spill. This is REQUIRED for all interrupt-bracket functions (osSetEventMesg, osSetThreadPri, etc.)
- **`or` vs `addu` for `move`**: IDO uses `or rd, rs, $zero` (opcode 0x25). GCC uses `addu rd, rs, $zero` (opcode 0x21). This is the key differentiator between IDO and GCC compiled code.
- **`beq` operand order**: IDO always puts `$s` registers first in `beq rs, rt`. If the original has `$t` first, this is a cosmetic diff — use NON_MATCHING wrapper.
- **Mixed -O1/-O2**: libultra functions use `-O1`. Game code uses `-O2`. 1080's kernel has 103 O1/O2 transitions — functions are split into 26 files in `src/kernel/` with per-file Makefile overrides.
- **Decompiling a function that needs a different opt level than its file**:
  1. Check the function's asm for O1 indicators: leaf function with stack frame (`addiu $sp, -8`), stores all args to stack at entry, reloads from stack with `$t` regs
  2. If the function is O1 but its file is O2 (or vice versa), create a NEW file:
     - Add `src/kernel/kernel_NNN.c` with the function (plus the next INCLUDE_ASM function to absorb alignment padding)
     - Remove the function from its current file
     - Add `build/src/kernel/kernel_NNN.c.o: OPT_FLAGS := -O1` to Makefile
     - Add `build/src/kernel/kernel_NNN.c.o(.text);` to the linker script in the correct position
     - Remove the function's INCLUDE_ASM from its old file
  3. Some very small functions (return constant, no-ops) produce identical code at both O1 and O2 — these can be decompiled in-place without a file split
- **`volatile` struct for rmon**: rmon debug functions store to stack structs that only callees read. IDO -O2 eliminates these as dead stores. Use `volatile` on the struct to preserve them.
- **rmon packet builder pattern (IDO -O1)**: Many rmon functions build a header struct on the stack and call `func_800073F8` (__rmonSendHeader). To match at -O1:
  1. Use **typed structs** for both the message input and the packet output — this keeps the message pointer in one `$t` register across all field accesses (without typed structs, IDO reloads from stack for each access)
  2. **Declaration order controls stack layout**: declare `ptr` before `struct` to put the pointer at a higher stack offset (e.g., `RmonMsg* p = msg; RmonHdr hdr;` puts `p` at sp+0x2C, `hdr` at sp+0x18)
  3. **Statement order controls instruction scheduling**: the order you write struct field assignments affects IDO's instruction interleaving. Match the asm's store order exactly (e.g., `hdr.type = ...` before `hdr.flags = 0` if that's the asm order)
  4. For functions with **multiple msg field accesses** (type, domain, id), use a local pointer copy (`RmonMsg* p = msg`) — IDO keeps `p` in `$t6` for all accesses. For functions with **only one** msg access, skip the local copy
  5. The `sb` in the `jal` delay slot is IDO's scheduler moving the last struct store after argument setup — this happens automatically when statement order is right
  6. For struct fields inside **if/else branches**: if the asm uses `addiu $tN, $sp, base; sw $val, offset($tN)` (register-based addressing) instead of `sw $val, combined_offset($sp)` (direct), use `*(s32*)((char*)&hdr + 0x14) = val` instead of `hdr.field = val`. The `char*` cast forces IDO to compute the struct base address with `addiu` inside each branch
- **`unsigned short` for thread state**: Thread state fields loaded with `lhu` need `unsigned short` type. `short` produces `lh` (signed load).
- **asm-processor**: Use three-phase pattern with `skip_instr_count=1` patch for IDO. `build.py` wrapper or manual Phase 1 (preprocess) → Phase 2a (compile) → Phase 2b (post-process).

## Compiler details (Glover / GCC projects)

- **Compiler**: KMC GCC 2.7.2 (`tools/gcc_2.7.2/linux/gcc`) with KMC assembler (GAS 2.6, patched)
- **Default flags**: `-G0 -mips3 -mgp32 -mfp32 -Wa,--vr4300mul-off -Wa,--no-float-doubleword -O2 -g2`
- **Assembler patch**: `--no-float-doubleword` expands `l.d`/`s.d` to `lwc1`/`swc1` pairs instead of `ldc1`/`sdc1`. Required for Glover — original ROM uses `lwc1` pairs for all double loads. Affects both symbol-addressed and register-offset forms.
- **Per-file overrides**: Some files use `-O0` or `-O3`. If a function won't match at `-O2`, try other levels.
- **The `-g2` flag matters**: It's passed to both the compiler (cc1) and assembler (as). The KMC assembler disables delay slot reordering when `-g` >= 1 is present. This means `-g2` produces UNFILLED delay slots (`addiu $sp; jr $ra; nop`), while no `-g` produces FILLED delay slots (`jr $ra; addiu $sp` in delay slot).
- **Most Glover functions use unfilled delay slots** (compiled with `-g2`). ~160 game segment functions have filled delay slots (compiled without `-g`). Check the original ROM's epilogue pattern to determine which flag to use.
- **`-g2` does NOT change instruction selection** — only assembler reordering and debug metadata. The `.s` output is identical between `-g0` and `-g2`.

## General notes (any project)

- Do NOT use unicode/emoji in C source — the assembler uses EUC-JP encoding
- Empty functions (`void f(void) {}`) should stay as `INCLUDE_ASM` — the compiler typically omits the delay slot nop
- Forward declarations for called functions go right before the decompiled function
- When assigning `0xFF` to a `s8` variable, the compiler sign-extends to `-1` (`0xFFFFFFFF`). Use `u8` type instead.
- The INCLUDE_ASM macro must use `.set noreorder` / `.set reorder` boundaries to prevent cross-function delay slot optimization. This is already done in `common.h`.
- **Always test one function at a time with clean builds (`rm -rf build/`)**. Batching multiple decompiled functions can cause cascading failures where one mismatch shifts everything after it.
- **Test standalone first**: compile the function in an isolated .c file to verify codegen matches before inserting into the main source. This isolates boundary issues from codegen issues. **Count instructions correctly**: `objdump -d` shows `...` for alignment nop padding — don't count that as an instruction. The actual code size is in the `nonmatching` header (e.g., `0xD4` = 0xD4/4 = 53 instructions).
- **Arg passthrough**: m2c often misses when `$a0` passes through to a callee unchanged. If the callee loads into `$a1` instead of `$a0`, the function likely has an extra first parameter that passes through. Check: does the asm save `$a1`/`$a2` but not `$a0`?
- **Forward declarations with `()` (empty parens)**: In C89, `void func()` means unspecified args (accepts any). Use this when the same function is called with different arg counts from different callers (passthrough pattern).
- **Cross-function `.L` labels**: When decompiling a function whose `.L` labels are referenced by other INCLUDE_ASM functions, add the labels to `undefined_syms_auto.txt` with absolute addresses (e.g., `.L80118088 = 0x80118088;`).
- **DO NOT GIVE UP EASILY.** Try at least 8-10 structurally different C variations before moving on. The "DO NOT GIVE UP" guidance in the iteration step (above) lists the common knobs to flip — go through them systematically.

## 1080 Snowboarding project notes

These apply only to the 1080 Snowboarding decomp (`projects/1080-*`), NOT to other IDO/N64 projects.

- **Repo and worktrees**: standalone repo at `bigyoshi51/1080-decomp`. Multiple agents work in parallel via `projects/1080-agent-<letter>/` worktrees. See `reference_worktrees.md` and `feedback_push_after_merge.md`.
- **Strategy memos to consult before picking a function**: `project_1080_strategy.md`, `project_1080_game_uso_map.md`, `feedback_decomp_call_graph_priority.md`. The current attack order is call-graph DFS from game.uso, NOT biggest-segment-first.
- **USO segments**: `kernel`, `bootup_uso`, `game_libs`, `game_uso` (and 14 other USOs). USO functions use prefixed names: `gl_func_*` (game_libs), `game_uso_func_*`, `gui_func_*`, etc. The discover tool currently only lists bare `func_*` names — walk `asm/nonmatchings/<segment>/<segment>/` directly for USO functions.
- **Yay0-compressed USOs** (`game_uso`, `mgrproc_uso`, `game`, `timproc`): the source `.c.o` is built normally, then its `.text` is extracted, compressed with `crunch64.yay0`, and packed into block-bin objects. See `feedback_uso_yay0_compressed.md` and the Makefile rules under `build/assets/<seg>_blockN_yay0.bin`. A failed Yay0 build usually means the C produced wrong bytes — check the uncompressed `.text.bin` against baserom-decompressed before suspecting compression.
- **Cross-USO templates**: 4 standard accessor templates (int reader / float reader / Vec3 reader / Quad4 reader) appear byte-identical at different offsets in EVERY USO. See `feedback_uso_accessor_template_reuse.md`. Always look for these first when entering a new USO.
- **Cross-USO call placeholders**: `gl_func_00000000` (callee=0) and `D_00000000` / `gl_data_00000000` (data=0) are runtime-patched relocations. See `feedback_game_libs_jal_targets.md`. K&R-declared `gl_func_00000000` cannot be called with float args directly — see `feedback_ido_knr_float_call.md`.
- **Mixed -O1/-O2 in kernel**: 26 files in `src/kernel/` with per-file Makefile overrides. See `project_o1o2_split.md`.
- **Reference search before grinding**: `/home/dan/Documents/code/decomp/scripts/decomp-search <name>` greps libreultra/oot/papermario clones. See `reference_decomp_references.md` and `reference_libreultra.md`.
- **IDO-specific gotchas worth re-reading before grinding**: `feedback_ido_register.md`, `feedback_ido_local_ordering.md`, `feedback_ido_unused_arg_save.md`, `feedback_ido_v0_reuse_via_locals.md`, `feedback_ido_inline_deref_v0.md`, `feedback_ido_split_or_constant.md`, `feedback_ido_no_gcc_register_asm.md` (don't borrow `register T x asm("$N")` from Glover — IDO rejects), `feedback_ido_unfilled_store_return.md`, `feedback_ido_unspecified_args.md`, `feedback_ido_buf_array_alignment.md`, `feedback_ido_narrow_arg_promotion.md`, `feedback_ido_goto_epilogue.md`, `feedback_ido_mfc1_from_c.md`, `feedback_function_trailing_nop_padding.md`.
- **Splat re-runs clobber files**: `tenshoe.ld`, `include_asm.h`, `include/macro.inc`, `undefined_syms_auto.txt`, and existing `asm/nonmatchings/<seg>/` get overwritten. Always `git checkout --` after running splat. See `feedback_splat_rerun_gotchas.md`.
- **Pattern mass-match background work**: `feedback_pattern_mass_match.md` describes the bytecode-signature scan + template emitter for repeated wrappers. Use it as background filler only — call-graph DFS is the primary strategy.

## Glover project notes

These apply only to the Glover decomp (`projects/Glover (USA)/`), NOT to 1080 or other GCC projects.

- **Compiler tools**: original KMC binaries at `tools/kmc-gcc-original/`; reconstructed mirrors at `tools/gcc_2.7.2/linux/`. Validation per `project_kmc_validation.md` confirmed the reconstruction matches KMC byte-for-byte; all remaining mismatches are source-code issues, not compiler reconstruction issues.
- **Build status**: NOT yet matching baserom. See `project_matching_build.md` for the YAML/linker alignment settings that get us close.
- **Per-file `-g` flags**: most game segment functions are `-g2` (unfilled delay slots). ~160 functions in the game segment compile WITHOUT `-g` (filled delay slots). See `project_compiler_findings.md`.
- **Assembler patch**: `--no-float-doubleword` flag in our patched KMC GAS expands `l.d`/`s.d` to `lwc1`/`swc1` pairs. Required because the original ROM uses `lwc1` pairs for all double loads. See `project_assembler_patch.md`.
- **Known 1-byte ROM diff at 0x0C4B2C**: ignore this when verifying overall ROM match.
- **18020.c fragments**: the 18020 segment has known function fragments that need merging. Use the `merge-fragments` skill (covered in `project_fragment_plan.md`).
- **D910.c debug functions**: this file holds the rmon/debug code. Many functions need `-O1` overrides; some use `volatile` structs to defeat dead-store elimination.
- **`ObjectNode` struct**: shared object/scene node type used across the game segment. Type it once and reuse — don't redeclare per-function.
- **Decompile status**: see `project_decompile_status.md` for currently-matched Glover functions, blocked functions, and the techniques that worked.

## Using decomp-permuter

The permuter randomly modifies C source to find versions that match the target binary. It's most effective **near the end** — when the logic is right but register allocation or minor instruction differences remain. If there are fundamental structural differences (wrong control flow, missing variables), fix those by hand first.

### When to use it

- **Good time**: You have the right logic, correct instruction count, but 2-5 instruction diffs (wrong registers, swapped operands, etc.)
- **Bad time**: ROM size differs, or the function structure is completely wrong. Fix the C structure manually first.
- **Score 0 = perfect match.** Lower scores are better. A score of 100-300 means you're close; 1000+ means structural issues remain.

### Setup and import

```bash
cd projects/Glover\ \(USA\)/

# 1. Write your best C attempt into the source file (replace INCLUDE_ASM)

# 2. Import the function for permutation:
python3 /home/dan/Documents/code/decomp/tools/decomp-permuter/import.py \
    src/<file>.c asm/nonmatchings/<segment>/<func>.s RUN_CC_CHECK=0

# 3. IMPORTANT: Fix the generated compile.sh — import.py creates a broken
#    one-liner. Split the export and gcc onto separate lines:
#    Before: export COMPILER_PATH=tools/gcc_2.7.2/linux '&&' tools/gcc_2.7.2/linux/gcc ...
#    After:
#      export COMPILER_PATH=tools/gcc_2.7.2/linux
#      tools/gcc_2.7.2/linux/gcc ...
```

### Running

```bash
# Random mode (multi-threaded, recommended):
python3 /home/dan/Documents/code/decomp/tools/decomp-permuter/permuter.py \
    nonmatchings/<func> -j4

# Let it run for a few minutes. Watch the score — if it drops to 0, you have a match.
# Ctrl+C to stop. Best candidates are saved automatically.

# Check results:
ls nonmatchings/<func>/output/

# Clean up when done:
rm -rf nonmatchings/<func>
```

### PERM macros (manual mode)

Use these in the C source to guide the search. The permuter tests all combinations systematically.

| Macro | Purpose | Example |
|-------|---------|---------|
| `PERM_GENERAL(a, b, ...)` | Try each alternative | `PERM_GENERAL(val + 1, val += 1, ++val)` |
| `PERM_RANDOMIZE(code)` | Enable random permutations in a region | Wrap a block of code to let the randomizer try variations |
| `PERM_LINESWAP(lines)` | Try all orderings of statements | `PERM_LINESWAP(a = 1; b = 2; c = 3;)` |
| `PERM_INT(lo, hi)` | Try integer values in range | `PERM_INT(0, 3)` for small constants |
| `PERM_IGNORE(code)` | Skip non-standard C during parsing | For GCC extensions the parser chokes on |
| `PERM_FORCE_SAMELINE(code)` | Join statements onto one line | Can affect codegen in some compilers |

**Combining modes**: By default, if ANY PERM macro is present, random mode is disabled. Use `PERM_RANDOMIZE(...)` to re-enable randomization within specific blocks while also testing manual alternatives elsewhere.

### Practical tips

- **Start manual, then go random.** Use `PERM_GENERAL` for the specific things you suspect differ (expression order, types, if-vs-goto). Only use full random mode as a last resort.
- **Use PERM_GENERAL for common variations**:
  ```c
  // Try signed vs unsigned comparison
  if (PERM_GENERAL((u32)arg2 > 0x8000U, arg2 > 0x8000, arg2 > (s32)0x8000)) {

  // Try different expression forms
  val = PERM_GENERAL(*arg0 + 1, *arg0, (*arg0));
  PERM_GENERAL(val++, val += 1, val = val + 1);

  // Try if-return vs goto
  PERM_GENERAL(
      if (old == 0xA) { *arg0 = val; return val; },
      if (old == 0xA) goto store
  );
  ```
- **Use PERM_LINESWAP for variable declaration/assignment ordering**:
  ```c
  PERM_LINESWAP(
      old = D_801E58A4;
      D_801E58A4 = 0xD;
      D_801E58B4 = old;
  )
  ```
- **Interpret results carefully.** The permuter often finds "nonsensical" code that matches by accident (e.g., adding unused temporaries that shift register allocation). Use the result as a hint about *which part* of the code needs changing, then write clean C that achieves the same effect.
- **Score plateaus**: If the score doesn't improve after ~500 iterations of random mode, the remaining diffs are likely structural (wrong control flow, missing variable, wrong type) not just ordering. Go back to manual analysis.

### Limitations

- Can't fix fundamental control flow differences (wrong branch type, missing loop)
- Can't fix stack frame padding (0x28 vs 0x30) — that's a compiler flag issue
- Random mode produces ugly code — always clean up matches into readable C
- Epilogue ordering is assembler-controlled (`-g2` flag), not fixable via permuter

## Compiler reference (for deep debugging)

When stuck on register allocation or instruction selection, consult the GCC 2.7.2 source code directly. Key files are in `docs/gcc-2.7.2/`:

| File | What it controls |
|------|-----------------|
| `local-alloc.c` | Register allocation within basic blocks — how pseudos map to hardware regs |
| `global.c` | Cross-function register allocation — assigns $s0-$s7 based on variable "weight" |
| `regclass.c` | Computes register class preferences and costs |
| `reorg.c` | Delay slot filling — controls `beql`/`bnel` emission and delay slot scheduling |
| `config/mips/mips.h` | MIPS target macros including `REG_ALLOC_ORDER` — the order GCC considers registers |
| `config/mips/mips.md` | MIPS instruction patterns — what C patterns produce which instructions |
| `config/mips/mips.c` | MIPS backend — register usage overrides, ABI handling |
| `flow.c` | Data flow analysis — liveness, which determines register pressure |
| `combine.c` | Instruction combining — merges operations into single instructions |
| `loop.c` | Loop optimization — loop-invariant hoisting, strength reduction |

Also available: `docs/mips-abi-reference.md` — MIPS O32 calling convention register usage.

### How to use these for debugging

1. **Register allocation mystery**: Check `REG_ALLOC_ORDER` in `mips.h` — this defines the order GCC tries to assign hardware registers. Then check `global.c` for how variable "weight" (frequency × loop depth) determines priority.

2. **Why is branch-likely emitted (or not)?**: Check `reorg.c` — the delay slot filler decides whether to use `beql`/`bnel` based on whether the delay slot can be filled with a useful instruction from the taken path.

3. **Why does one expression produce a different instruction than another?**: Check `mips.md` for the instruction patterns. Each pattern has a C expression template and constraints.

4. **Loop optimization differences**: Check `loop.c` for how constants are hoisted out of loops (e.g., why `0x8000` ends up in `$s6`).
