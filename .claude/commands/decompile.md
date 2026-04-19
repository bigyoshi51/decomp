Decompile a function in the N64 decomp project. The user may provide a function name as an argument, or you should pick the next best candidate.

## Finding the project

The decomp project lives under `projects/`. Find the splat YAML config and the `src/` directory.

## Picking a function

If no function is specified, pick a good candidate:
- Run `uv run decomp discover --sort-by size` to list unmatched functions
- Prefer small functions (8-20 instructions) that are self-contained (have `jr $ra`, no external `.L` jumps)
- Avoid functions that are all `.word` directives (data misidentified as code)
- Avoid functions that branch/jump outside their own boundaries

## Decompilation workflow

1. **Read the assembly**: Read the function's `.s` file from `asm/nonmatchings/`

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

7. **When matched**: Verify the full ROM still matches, then log the episode, commit, and report success.

8. **Log the episode**: After every successful match, log it for the training dataset:
   ```python
   import sys
   sys.path.insert(0, "/home/dan/Documents/code/decomp")
   from pathlib import Path
   from decomp.episode import log_success

   log_success("func_XXXXXXXX", Path("asm/nonmatchings/<segment>/func_XXXXXXXX.s"),
               '<the matching C code>', output_dir=Path("episodes"))
   ```
   This captures (asm, m2c_output, final_c) triples for future RL/fine-tuning. Always do this — every matched function is training data.

9. **Commit**: After logging the episode, commit the changes immediately:
   ```bash
   git add src/<file>.c episodes/
   git commit -m "Decompile <func_name> (<brief description>, <N> instructions)"
   ```
   Commit after EACH matched function — don't batch. This keeps the history clean and makes it easy to bisect regressions.

9b. **Update the project README on milestones**: Each 1080 / Glover / etc. project has a per-segment progress table in its README. It does NOT need updating after every decompile — only when something in the "Status" section is meaningfully stale. Trigger a README refresh when:

   - **A new segment is set up** (e.g. first time adding `bootup_uso` or `game_libs` to the build). Add its row to the table; note any new decomp pattern.
   - **A segment crosses a round-number milestone** (25 %, 50 %, 75 %, 100 % of that segment's functions or code). 11.4 % → 11.5 % is noise; 24 % → 25 % is worth updating.
   - **A tracked number drifts by ≥2 percentage points** from what's in the README (for any segment or the overall total). Projects with a `scripts/refresh-report.sh` print a staleness warning when this happens.
   - **The "not tracked" list changes** — e.g., we start tracking a USO overlay that was previously opaque.

   How: compare `report.json` against the table in the project's `README.md`. If an update is warranted, edit the README inline and land it with the triggering commit or as a standalone `Update README progress stats` commit. Keep the table concise — it's a project README, not a changelog.

10. **NON_MATCHING functions — preserve partial C, don't delete it**: if a function is decompiled but has cosmetic diffs (scheduler interleaving, temp register choice, ≥80 % match) that don't affect function size or logic, **do NOT revert to a bare `INCLUDE_ASM` line**. Instead, wrap the decompiled C in `#ifdef NON_MATCHING ... #else INCLUDE_ASM(...); #endif`. This preserves the C for reference, keeps the default build at 0 ROM diffs (INCLUDE_ASM path), and lets future agents or `decomp-permuter` pick up from the partial.

   **Template:**
   ```c
   #ifdef NON_MATCHING
   /* <one-line diff summary, e.g. "sw ra scheduling differs">
    * Bytes match except for [describe the diff]. */
   void gl_func_XXXXXXXX(...) {
       /* decompiled body */
   }
   #else
   INCLUDE_ASM("asm/nonmatchings/game_libs/game_libs", gl_func_XXXXXXXX);
   #endif
   ```

   **Do NOT log an episode** for a NON_MATCHING function. Episodes are the training dataset for exact matches only (asm → C triples where the C compiles to the exact bytes). A NON_MATCHING function's C would train on incorrect output. Commit the NON_MATCHING wrap as `Wrap gl_func_XXXXXXXX as NON_MATCHING (<reason>)` without a corresponding `.json` in `episodes/`.

   **Threshold:** wrap at ≥80 % match. Below that the body is likely structurally wrong and not useful reference — prefer to keep INCLUDE_ASM until you understand the function better. Exact byte-matching is the final standard — "close" is not matching, but "close" is still useful context vs "gone".

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

## Important notes

- Do NOT use unicode/emoji in C source — the assembler uses EUC-JP encoding
- Empty functions (`void f(void) {}`) should stay as `INCLUDE_ASM` — GCC omits the delay slot nop
- Forward declarations for called functions go right before the decompiled function
- The existing 1-byte diff at ROM 0x0C4B2C is a known forward-reference issue, not a regression
- When assigning `0xFF` to a `s8` variable, GCC sign-extends to `-1` (`0xFFFFFFFF`). Use `u8` type instead.
- The INCLUDE_ASM macro must use `.set noreorder` / `.set reorder` boundaries to prevent cross-function delay slot optimization. This is already done in common.h.
- Many functions in 18020.c are actually function fragments (epilogues, mid-function entries) due to imprecise splat splitting. Signs: no proper prologue, `lw $ra` as first instruction, unset register errors from m2c. Don't try to decompile these.
- **Always test one function at a time with clean builds (`rm -rf build/`)**. Batching multiple decompiled functions can cause cascading failures where one mismatch shifts everything after it.
- **Test standalone first**: compile the function in an isolated .c file with GCC to verify codegen matches before inserting into the main source. This isolates boundary issues from codegen issues. **Count instructions correctly**: `objdump -d` shows `...` for alignment nop padding — don't count that as an instruction. The actual code size is in the `nonmatching` header (e.g., `0xD4` = 0xD4/4 = 53 instructions).
- **DO NOT GIVE UP EASILY.** Try at least 8-10 structurally different C variations before moving on. func_8010FC10 took 6 different C structures before matching — the winning approach used `goto` labels and split load+increment. Always test standalone first (compile to .s and compare) — this is much faster than full ROM builds. When stuck, try: goto-based control flow, split expressions, swap if/else arms, inline vs separate variables, different types (s32/u32), wrapping vs flat if chains.
- Some functions have stack frame size differences (e.g., -0x28 vs -0x30). Use `char pad[4]` to add 8 bytes of padding without generating instructions. Do NOT use `volatile` — it changes register allocation. The `char pad[4]` trick works because GCC allocates stack space for all declared locals even if unused.
- **Cross-function .L labels**: When decompiling a function whose `.L` labels are referenced by other INCLUDE_ASM functions, add the labels to `undefined_syms_auto.txt` with absolute addresses (e.g., `.L80118088 = 0x80118088;`). This has already been done for 555 labels in the game segment — check `undefined_syms_auto.txt` before assuming a function is blocked by this.
- **ObjectNode struct**: `include/structs.h` defines `ObjectNode` for the D_8026A148 / D_8028F350 linked list objects. Use `node->displayList`, `node->type`, `node->posX`, etc. for typed access. Declare list heads as `extern ObjectNode D_8026A148;`.
- **Arg passthrough**: m2c often misses when `$a0` passes through to a callee unchanged. If the callee loads into `$a1` instead of `$a0`, the function likely has an extra first parameter that passes through. Check: does the asm save `$a1`/`$a2` but not `$a0`?
- **Epilogue pattern determines -g flag**: Check the original ROM's epilogue:
  - `addiu $sp; jr $ra; nop` = compiled with `-g2` (default, most functions)
  - `jr $ra; addiu $sp` (delay slot filled) = compiled WITHOUT `-g` (add per-file Makefile override)
  - `-O0` functions use frame pointer (`$fp`/`$s8`) and have different epilogues entirely
- **D910.c is a debug/RAMROM module**: The `0xB1FFFFxx` addresses are development hardware registers for host debugger communication. `0xA4600010` is PI_STATUS_REG (DMA readiness). These can be used as literal addresses or defined as macros for readability.
- **Forward declarations with `()` (empty parens)**: In C89, `void func()` means unspecified args (accepts any). Use this when the same function is called with different arg counts from different callers (passthrough pattern).
- **INCLUDE_ASM boundary effects**: Functions that match byte-perfectly when compiled standalone may have prologue scheduling differences when embedded between INCLUDE_ASM blocks. The `-g2` assembler's `.set reorder`/`.set noreorder` transitions across boundaries affect instruction ordering. **Strategy**: decompile adjacent functions together to eliminate boundaries. As more functions are decompiled, boundary effects decrease.
- **Compiler validated**: Our decompals/mips-gcc-2.7.2 reconstruction produces byte-identical output to the original KMC CC1.OUT. All matching issues are source code or assembler boundary problems, never compiler differences. Original KMC tools saved at `tools/kmc-gcc-original/` for verification via Wine.

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
