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

6. **Iterate if not matching**: Common issues and fixes:
   - **Wrong stack frame size**: Try different variable declarations, reorder locals
   - **Missing delay slot fill**: GCC fills delay slots aggressively — make sure the C logic order matches
   - **Register allocation differs**: GCC 2.7.2 assigns $s registers based on variable "weight" (usage frequency), not declaration order. Try: reorder variable declarations, modify arg in-place (`arg0 &= -4`) instead of new variable, change types (s32 vs u32), use `-O1` or `-O3`. The `register` keyword with `asm()` constraint does NOT work in GCC 2.7.2.
   - **Wrong instruction for constant**: `-2` vs `~1` vs `0xFFFFFFFE` can produce different instructions
   - **Optimization level**: Check if this file needs `-O0`, `-O1`, or `-O3` instead of `-O2` (add per-file override in Makefile)

7. **When matched**: Verify the full ROM still matches (only the known 1-byte alabel diff should remain), then log the episode and report success.

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
- **Test standalone first**: compile the function in an isolated .c file with GCC to verify codegen matches before inserting into the main source. This isolates boundary issues from codegen issues.
- Don't give up after 2 attempts — try at least 5-6 variations of variable ordering, types, and expression structure before moving on
- Some functions have stack frame size differences (e.g., -0x28 vs -0x30). This can indicate a different optimization level for that file, or a `-g` flag difference. Try `-O0`, `-O1`, `-O3`, or removing `-g2`.
- **Arg passthrough**: m2c often misses when `$a0` passes through to a callee unchanged. If the callee loads into `$a1` instead of `$a0`, the function likely has an extra first parameter that passes through. Check: does the asm save `$a1`/`$a2` but not `$a0`?
- **Epilogue pattern determines -g flag**: Check the original ROM's epilogue:
  - `addiu $sp; jr $ra; nop` = compiled with `-g2` (default, most functions)
  - `jr $ra; addiu $sp` (delay slot filled) = compiled WITHOUT `-g` (add per-file Makefile override)
  - `-O0` functions use frame pointer (`$fp`/`$s8`) and have different epilogues entirely
- **D910.c is a debug/RAMROM module**: The `0xB1FFFFxx` addresses are development hardware registers for host debugger communication. `0xA4600010` is PI_STATUS_REG (DMA readiness). These can be used as literal addresses or defined as macros for readability.
- **Forward declarations with `()` (empty parens)**: In C89, `void func()` means unspecified args (accepts any). Use this when the same function is called with different arg counts from different callers (passthrough pattern).

## Using decomp-permuter

When manual iteration fails (especially for register allocation), use decomp-permuter to brute-force search for matching C:

```bash
# From the project directory:
# 1. Make sure the function is written as C (not INCLUDE_ASM) in the source
# 2. Import the function for permutation:
python3 /home/dan/Documents/code/decomp/tools/decomp-permuter/import.py src/<file>.c asm/nonmatchings/<segment>/<func>.s RUN_CC_CHECK=0

# 3. Run the permuter (uses multiple threads):
python3 /home/dan/Documents/code/decomp/tools/decomp-permuter/permuter.py nonmatchings/<func> -j4

# 4. If it finds a match, the output is in nonmatchings/<func>/output/
# 5. Clean up: rm -rf nonmatchings/<func>
```

The Makefile skips CC_CHECK and strip when `PERMUTER=1` is set.

You can also use PERM macros in the C code to guide the search:
- `PERM_GENERAL(a, b)` — try both `a` and `b`
- `PERM_RANDOMIZE(code)` — allow random permutations within a region

**Permuter setup gotcha**: The import.py generates a compile.sh with `export COMPILER_PATH=... '&&' gcc ...` which breaks. Fix compile.sh to split the export and gcc command onto separate lines.

**Permuter limitations**: Random permutations can't fix fundamental GCC 2.7.2 register allocation choices. If the base score doesn't improve after ~500 iterations, the mismatch is likely a compiler limitation, not a C source issue. Known hard patterns:
- `$s1`/`$s2` register swap (GCC assigns by variable weight — try dummy volatile vars, scope blocks, declaration reordering)
- Stack frame padding differences (e.g., -0x28 vs -0x30) — may indicate different `-g` or `-O` flag for that file
- Epilogue ordering is NOT a GCC issue — it's controlled by the `-g2` assembler flag (see Compiler details above). If the original has filled delay slots, remove `-g2` for that file.
