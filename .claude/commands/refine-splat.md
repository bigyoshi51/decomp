You are working on an N64 decompilation project. Your goal is to refine the splat YAML config and build system to get a byte-matching ROM build.

## Context

The project uses splat (splat64) to split an N64 ROM into segments (code, data, assets). The build system uses IDO (via ido-static-recomp), asm-processor, and mips-linux-gnu binutils.

The decomp project lives under the `projects/` directory. Find it by looking for a splat YAML config.

## Your workflow

1. **Assess current state**: Run `make RUN_CC_CHECK=0` and compare the built ROM against the base ROM byte-by-byte per segment.

2. **Fix issues in this priority order**:

### Section alignment (most common blocker)
- Set `ld_align_section_vram_end: False` and `ld_align_segment_vram_end: False` in splat YAML. The default `ALIGN(., 16)` between sections inserts padding that doesn't exist in the original ROM.
- Set `subalign: null` to remove `SUBALIGN(16)` from linker script section headers.

### Entry point analysis
Extract the memory layout from the entry point's BSS clear loop (typically at ROM 0x1000):
- `lui/addiu $sp` = stack pointer
- `lui/addiu $t0` = BSS start address
- `lui/addiu $t1` = BSS end address
- `jal` target = main() address
This tells you the total loaded size and BSS range.

### Segment boundaries
- Use `follows_vram` for contiguous segments, but **verify the chain produces correct vram addresses**. If a segment's compiled size differs from the ROM size (due to data/rodata sections), the chain breaks. Use explicit `vram:` instead.
- If a segment's text+data+rodata doesn't fill the ROM space between segments, there's a gap. Add a `data` subsegment or check if the segment needs explicit vram.

### Entry segment trick
If the entry segment has code followed by non-aligned data (e.g., code at 0x1000, data at 0x103C), use a single `asm` subsegment type instead of `hasm` + `data`. This puts everything in `.text` and avoids the assembler padding `.data` to 16-byte alignment.

### dlabel → glabel
Splat emits `dlabel` for data it finds in code regions. These are typically jump tables or data interleaved with code. Change `dlabel` to `glabel` (and `enddlabel` to `endlabel`) so asm-processor includes them in `.text`. Do NOT extern them out — they must stay in `.text` to maintain correct section sizes.

### Rodata handling
Do NOT create a separate `.rodata` subsegment unless you're sure the boundary is correct. Let splat's `migrate_rodata_to_functions` embed rodata into per-function asm files, which asm-processor handles automatically.

### Undefined symbols
Extract from linker errors. Named symbols like `main` need manual address assignment. Use the entry point's `jal` target for `main`.

3. **After re-splitting**: Remember splat doesn't overwrite existing .c source files. Delete `src/` before re-splitting if segment layout changed.

## Build/compare script

```python
# Full rebuild cycle
# 1. Fix entry BSS refs (game_BSS_START/END)
# 2. Fix dlabel -> glabel in nonmatchings
# 3. make RUN_CC_CHECK=0
# 4. Add undefined symbols from linker errors
# 5. Compare per-segment
```

## Key facts

- `RUN_CC_CHECK=0` skips host GCC syntax checking (needed until headers are complete)
- asm-processor requires EUC-JP encoding — no unicode in C source comments
- `.L` prefixed symbols are local jump table targets from switch statements
- Addresses starting with `0x84...` or `0x88...` are likely overlays
- mips-linux-gnu-as always sets section alignment to 2**4 (16 bytes) internally — this cannot be overridden. Work around it by keeping misaligned data in `.text` sections.
- The `section_order` for N64 ROMs should be `[".text", ".rodata", ".data", ".bss"]`

## Function boundary discovery

After getting a matching build, improve function splitting in large code segments:

1. **Scan ROM for function prologues**: `addiu $sp, $sp, -N` (opcode `0x27BDXXXX` with bit 15 set)
2. **Validate each prologue**: Only count it as a real function start if the previous instruction is `jr $ra` (a return) or a nop (inter-function padding). Prologues in `jal` delay slots are false positives.
3. **Add validated functions to `symbol_addrs.txt`**:
   ```
   func_XXXXXXXX = 0xXXXXXXXX; // type:func
   ```
4. **Re-split**: Delete `src/`, `asm/`, `assets/`, `build/` and run `splat split`. Splat uses symbol_addrs to find function boundaries.
5. **Restore decompiled code**: Re-splitting regenerates source files. Restore decompiled functions from git: `git show HEAD:src/file.c > src/file.c`
6. **Fix post-split issues**:
   - Entry BSS refs (`main_BSS_START` -> `game_BSS_START`)
   - dlabel -> glabel in nonmatchings
   - Undefined symbols from linker errors
   - Data at code/data boundary may get misinterpreted as instructions — replace with `.word` directives

**Quality check after re-split**:
```python
# Count clean vs merged vs fragment functions
for f in nonmatchings.iterdir():
    prologues = count addiu $sp, $sp, -N
    if prologues > 1: merged
    elif prologues == 1 and has jr $ra: clean
    else: fragment/leaf
```

## N64 hardware register reference

Common memory-mapped addresses found in N64 game code:

| Address | Name | Purpose |
|---------|------|---------|
| `0xA4600000` | PI_DRAM_ADDR | RDRAM address for PI DMA |
| `0xA4600004` | PI_CART_ADDR | Cartridge address for PI DMA |
| `0xA4600008` | PI_RD_LEN | Cart->RDRAM DMA length (write triggers) |
| `0xA460000C` | PI_WR_LEN | RDRAM->Cart DMA length (write triggers) |
| `0xA4600010` | PI_STATUS | PI status (bit 0: DMA busy, bit 1: I/O busy) |
| `0xB0000000-0xBFBFFFFF` | Cartridge ROM | KSEG1 uncached access to cart |
| `0xB1FFFFxx` | RAMROM debug | Development hardware debug registers |

The standard PI DMA wait pattern is: `while (*(volatile u32*)0xA4600010 & 3) {}` — wait for DMA not busy.

Cache operations (`cache` instruction) flush/invalidate I-cache (16KB, 32B lines) and D-cache (8KB, 16B lines) for DMA coherency.

Headers defining these: `PR/rcp.h` (RCP registers), `PR/R4300.h` (cache/CPU), from [n64decomp/libreultra](https://github.com/n64decomp/libreultra).

## Per-file compiler flag detection

Different source files in the same ROM may have been compiled with different flags. To detect:

1. **Check epilogue pattern** to determine `-g` flag:
   - `addiu $sp; jr $ra; nop` = compiled with `-g2` (assembler doesn't reorder)
   - `jr $ra; addiu $sp` (filled delay slot) = compiled without `-g`
2. **Check for frame pointer** (`$fp`/`$s8`) usage in prologue = `-O0`
3. **Scan the segment** to count epilogue patterns and determine the dominant flag

For Glover: D910 is ~100% `-g2`, 18020 is ~80% `-g2` with ~160 exceptions needing no `-g`.

## Goal state

`md5sum build/<target>.z64` equals `md5sum baserom.z64`.
