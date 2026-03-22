You are working on an N64 decompilation project. Your goal is to refine the splat YAML config and build system to get a byte-matching ROM build with correct function boundaries.

## Context

The project uses splat (splat64) to split an N64 ROM into segments (code, data, assets). The build system uses KMC GCC 2.7.2 (or IDO via ido-static-recomp), asm-processor, and mips-linux-gnu binutils.

The decomp project lives under the `projects/` directory. Find it by looking for a splat YAML config.

## Critical lesson: the correct order of operations

Based on the [splat General Workflow](https://github.com/ethteck/splat/wiki/General-Workflow) and the [HM64 decomp](https://github.com/harvestwhisperer/hm64-decomp) (100% complete reference project):

**You MUST get the splat config right BEFORE decompiling functions.** The order is:

1. **Define segment boundaries** (code, rodata, data, bss) with explicit ROM offsets
2. **Pair rodata to text segments** — match `.rodata` subsegments to their corresponding `c` subsegments by name. Do this BEFORE converting to C.
3. **Define function boundaries** in `symbol_addrs.txt` using validated prologue scanning
4. **Re-split** and verify byte-matching build
5. **Only then** start decompiling C functions

If you skip step 2 (rodata pairing), adding new function symbols later will break the build because `migrate_rodata_to_functions` reshuffles rodata based on which functions reference it.

## Splat config structure

A mature decomp project (like HM64) has **explicit subsegment boundaries** for every section:

```yaml
- name: game
  type: code
  start: 0x18020
  vram: 0x80118020
  subsegments:
    - [0x18020, c, 18020]          # .text (C code)
    - [0xC4B30, .rodata, 18020]    # .rodata (read-only data)
    - [0xD51D0, .data, 18020]      # .data (initialized data)
    - {start: 0xDA9D0, type: .bss, vram: 0x801DA9D0, name: 18020}
```

**Do NOT rely on splat auto-detecting these boundaries.** Determine them manually:
- `.rodata` start: scan for the first non-code data after the last function
- `.data` start: scan for mutable data (often after rodata, aligned to 0x10)
- `.bss` start: not in ROM; use entry point analysis or linker map

## symbol_addrs.txt and rodata coupling

**WARNING**: `symbol_addrs.txt` and the splat config are tightly coupled. Changing the function list changes how splat assigns rodata to functions, which changes the build output.

To safely add new function symbols:
1. First define explicit `.rodata` subsegment boundaries in the YAML (locks rodata layout)
2. Then add function symbols freely — they won't affect rodata placement

If you don't have explicit rodata boundaries, adding even one function to `symbol_addrs.txt` can break a matching build.

## Function boundary discovery

**Use spimdisasm CLI** (already installed, used by splat internally) to detect functions:

```bash
python3 -m spimdisasm singleFileDisasm baserom.z64 /tmp/output \
  --start 0x18020 --end 0xD51D0 --vram 0x80118020 \
  --function-info /tmp/funcinfo.csv \
  --symbol-addrs symbol_addrs.txt
```

This produces a CSV with address, name, size, and call graph for every detected function. It uses `jal` target analysis + control flow tracking, finding both prologue-based and leaf functions.

**CRITICAL: Add `size:` annotations** to every entry in `symbol_addrs.txt`:
```
func_80139D94 = 0x80139D94; // type:func size:0x1EC
```
Without sizes, spimdisasm treats `jal` targets within a function as separate function boundaries, creating fragments. With sizes, it correctly treats them as `alabel` (alternative entry points) within the parent function.

**CRITICAL: Clean re-split when changing symbol_addrs.txt:**
Splat does NOT overwrite existing C source files or delete stale asm files. After updating symbol_addrs.txt:
```bash
rm -rf asm/nonmatchings/<segment>/
rm -f src/<segment>.c
python3 -m splat split config.yaml
git checkout -- include/macro.inc  # splat overwrites this
# Restore undefined_funcs_auto.txt / undefined_syms_auto.txt from git if needed
```
Without clean deletion, stale files cause duplicate symbol errors.

**Quality check after splitting**:
```python
# For each asm file, check if it's a real function or a fragment
first_instr = ...  # first instruction in the file
has_prologue = "addiu" in first and "$sp" in first and "-0x" in first
has_jr_ra = any("jr $ra" in line for line in instrs)
if has_prologue: "real function"
elif has_jr_ra: "leaf function (valid)"
else: "fragment — bad boundary"
```

Additional tools:
- **n64sym** (`shygoo/n64sym`): identifies libultra/SDK functions by signature matching. Use `n64sym baserom.z64 -s -f splat` to generate named entries.
- **Prologue scan**: simple `0x27BDXXXX` scan as a sanity check, but spimdisasm is more thorough.

## Section alignment fixes

- Set `ld_align_section_vram_end: False` and `ld_align_segment_vram_end: False` in splat YAML. The default `ALIGN(., 16)` between sections inserts padding that doesn't exist in the original ROM.
- Set `subalign: null` to remove `SUBALIGN(16)` from linker script section headers.

## Entry point analysis

Extract the memory layout from the entry point's BSS clear loop (typically at ROM 0x1000):
- `lui/addiu $sp` = stack pointer
- `lui/addiu $t0` = BSS start address
- `lui/addiu $t1` = BSS end address
- `jal` target = main() address
This tells you the total loaded size and BSS range.

## dlabel handling

Splat emits `dlabel` for data it finds in code regions (jump tables, embedded data). These must stay in `.text` to maintain correct section sizes. Our `macro.inc` defines `dlabel` as a data-typed label. Do NOT blindly convert all `dlabel` to `glabel` — only convert labels that are actual code entry points. Data labels (`D_XXXXXXXX`) should remain as `dlabel`.

## Rodata handling

The recommended approach (from splat General Workflow):

1. **Initially**: disable `migrate_rodata_to_functions`
2. **Pair rodata to text**: splat provides hints about which rodata segments reference which functions
3. **After pairing**: enable `migrate_rodata_to_functions` to embed rodata into per-function asm files
4. **During decompilation**: transition from `.rodata.s` includes to pulling compiled `.rodata` from the C file

## Post-split fixups

After re-splitting:
1. Splat overwrites `include/macro.inc` — restore from git
2. Splat regenerates `src/*.c` — restore decompiled functions from git
3. Fix undefined symbols from linker errors
4. Data at code/data boundaries may be misidentified as instructions — replace with `.word` directives
5. Some functions may reference `.L` labels in other files — add to `undefined_syms_auto.txt`

## Per-file compiler flag detection

Different source files in the same ROM may have been compiled with different flags:

1. **Check epilogue pattern** to determine `-g` flag:
   - `addiu $sp; jr $ra; nop` = compiled with `-g2` (assembler doesn't reorder)
   - `jr $ra; addiu $sp` (filled delay slot) = compiled without `-g`
2. **Check for frame pointer** (`$fp`/`$s8`) usage in prologue = `-O0`
3. **Scan the segment** to count epilogue patterns

For Glover: D910 is ~100% `-g2`, 18020 is ~80% `-g2` with ~160 exceptions needing no `-g`.

## Key facts

- `RUN_CC_CHECK=0` skips host GCC syntax checking (needed until headers are complete)
- asm-processor requires EUC-JP encoding — no unicode in C source comments
- `.L` prefixed symbols are local jump table targets from switch statements
- Addresses starting with `0x84...` or `0x88...` are likely overlays
- mips-linux-gnu-as always sets section alignment to 2**4 (16 bytes) internally — this cannot be overridden. Work around it by keeping misaligned data in `.text` sections.
- The `section_order` for N64 ROMs should be `[".text", ".rodata", ".data", ".bss"]`
- Toolchain: KMC GCC 2.7.2 + KMC GAS 2.6 pre-built binaries are in the `toolchain` release on the Glover repo. The decompals/mips-gcc-2.7.2 release only has gcc/cc1, NOT the assembler.

## N64 hardware register reference

| Address | Name | Purpose |
|---------|------|---------|
| `0xA4600000` | PI_DRAM_ADDR | RDRAM address for PI DMA |
| `0xA4600004` | PI_CART_ADDR | Cartridge address for PI DMA |
| `0xA4600008` | PI_RD_LEN | Cart->RDRAM DMA length (write triggers) |
| `0xA460000C` | PI_WR_LEN | RDRAM->Cart DMA length (write triggers) |
| `0xA4600010` | PI_STATUS | PI status (bit 0: DMA busy, bit 1: I/O busy) |
| `0xB0000000-0xBFBFFFFF` | Cartridge ROM | KSEG1 uncached access to cart |
| `0xB1FFFFxx` | RAMROM debug | Development hardware debug registers |

## Reference projects

- [HM64 decomp](https://github.com/harvestwhisperer/hm64-decomp) — 100% complete, mature splat config (161KB YAML, explicit subsegments)
- [SSSV decomp](https://github.com/mkst/sssv) — good jump table / rodata handling examples
- [Splat wiki](https://github.com/ethteck/splat/wiki) — official docs

## Goal state

1. `md5sum build/<target>.z64` equals `md5sum baserom.z64` (or ≤1 byte diff for known issues)
2. 0% fragment rate in function boundary audit
3. Explicit `.rodata`, `.data`, `.bss` subsegment boundaries in splat YAML
4. Adding new functions to `symbol_addrs.txt` does NOT break the build
