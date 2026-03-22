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
   - **Wrong stack frame size**: Try different variable declarations, reorder locals
   - **Wrong instruction for constant**: `-2` vs `~1` vs `0xFFFFFFFE` can produce different instructions
   - **Optimization level**: Check if this file needs `-O0`, `-O1`, or `-O3` instead of `-O2` (add per-file override in Makefile)

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

## Compiler details

- **Compiler**: KMC GCC 2.7.2 (`tools/gcc_2.7.2/linux/gcc`) with KMC assembler (GAS 2.6)
- **Default flags**: `-G0 -mips3 -mgp32 -mfp32 -Wa,--vr4300mul-off -O2 -g2`
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
- Some functions have stack frame size differences (e.g., -0x28 vs -0x30). This is NOT from STACK_BOUNDARY (which is 64 bits / 8 bytes in both builds). The original compiler sometimes allocates extra stack space for local variables that our GCC optimizes away. Workarounds: add a `volatile` local to force extra allocation (but this changes register allocation), or accept the mismatch. This blocks ~30 D910 / ~450 game functions.
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
