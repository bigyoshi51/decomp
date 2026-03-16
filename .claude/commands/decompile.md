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
   - **Register allocation differs**: Try `register` keyword, reorder statements, use temp variables
   - **Wrong instruction for constant**: `-2` vs `~1` vs `0xFFFFFFFE` can produce different instructions
   - **Optimization level**: Check if this file needs `-O0`, `-O1`, or `-O3` instead of `-O2` (add per-file override in Makefile)

7. **When matched**: Verify the full ROM still matches (only the known 1-byte alabel diff should remain), then report success.

## Compiler details

- **Compiler**: KMC GCC 2.7.2 (`tools/gcc_2.7.2/linux/gcc`)
- **Default flags**: `-G0 -mips3 -mgp32 -mfp32 -Wa,--vr4300mul-off -O2 -g2`
- **Per-file overrides**: Some files use `-O0` or `-O3`. If a function won't match at `-O2`, try other levels.

## Important notes

- Do NOT use unicode/emoji in C source — the assembler uses EUC-JP encoding
- Empty functions (`void f(void) {}`) should stay as `INCLUDE_ASM` — GCC omits the delay slot nop
- Forward declarations for called functions go right before the decompiled function
- The existing 1-byte diff at ROM 0x0C4B2C is a known forward-reference issue, not a regression
