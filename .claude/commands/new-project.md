Set up a new N64 decompilation project. The user provides the game name (and optionally the ROM path).

## Arguments

The user should provide the game name, e.g. `1080 Snowboarding (USA)`. If they also provide a ROM path, copy/symlink it into the project.

## Steps

### 1. Create project directory

Create `projects/<Game Name>/` with this structure:

```
projects/<Game Name>/
├── decomp.yaml          # Agent config
├── baserom.z64          # ROM (user provides)
├── checksum.md5         # MD5 of baserom.z64
├── include/             # C headers
│   └── include_asm.h    # INCLUDE_ASM macro
├── src/                 # Decompiled C source
├── asm/                 # Splat-generated assembly
│   └── nonmatchings/   # Per-function asm files
├── assets/              # Extracted assets
├── episodes/            # Decompilation episode logs
├── symbol_addrs.txt     # Function/data symbol addresses
└── Makefile             # Build system (generated later)
```

### 2. Generate decomp.yaml

```yaml
# decomp agent configuration
project_root: /home/dan/Documents/code/decomp/projects/<Game Name>
base_rom: baserom.z64

# Agent settings
max_attempts: 30
model: claude-opus-4-6

# Project structure
asm_dir: asm/nonmatchings
src_dir: src
include_dir: include
```

### 3. Generate checksum.md5

If the ROM is present:
```bash
md5sum baserom.z64 > checksum.md5
```

### 4. Initialize git repo

```bash
cd "projects/<Game Name>"
git init
```

Create a `.gitignore`:
```
baserom.z64
build/
tools/
*.o
*.d
```

### 5. ROM analysis

If the ROM is present, perform initial analysis:

1. **Identify the compiler** — scan for IDO vs GCC signatures:
   - IDO: look for `_gp_disp` relocations, SGI-style function prologues
   - GCC: look for `.gnu.attributes`, GCC-style frame setup
   - Check for compiler version strings embedded in the ROM

2. **Extract entry point info** — read the ROM header:
   - Entry point address (offset 0x08)
   - Game title (offset 0x20, 20 bytes)
   - Game code (offset 0x3B, 4 bytes)
   - ROM size

3. **Analyze the boot code** at ROM offset 0x1000:
   - Stack pointer (`lui/addiu $sp`)
   - BSS start/end addresses
   - Main function address

4. **Run n64sym** if available:
   ```bash
   n64sym baserom.z64 -s -f splat
   ```
   This identifies libultra/SDK functions.

5. **Scan for function prologues** to estimate code size and function count:
   - Count `addiu $sp, $sp, -N` instructions (opcode 0x27BDXXXX with bit 15 set)
   - Report estimated function count and code range

### 6. Create initial splat config

Based on ROM analysis, create `<game_code>.yaml` (the splat config):

```yaml
name: <Game Name>
sha1: <sha1 of baserom.z64>
options:
  basename: <game_code>
  target_path: baserom.z64
  base_path: .
  platform: n64
  compiler: <IDO|GCC>

  # Section alignment (avoid phantom padding)
  ld_align_section_vram_end: False
  ld_align_segment_vram_end: False
  subalign: null

  section_order: [".text", ".rodata", ".data", ".bss"]

  auto_all_sections: [".text", ".data", ".rodata", ".bss"]
  symbol_addrs_path: symbol_addrs.txt

  asm_path: asm
  src_path: src
  build_path: build
  asset_path: assets

segments:
  - [0x0, bin, header]
  - [0x40, bin, boot]
  - [0x1000, asm, entry]
  # ... further segments to be determined by ROM analysis
```

### 7. Report findings

Print a summary:
- Game title and code
- ROM size
- Detected compiler
- Entry point and BSS range
- Estimated function count
- Known library functions (from n64sym)
- Next steps (run splat, refine config, get matching build)

## Notes

- The `projects/` directory is gitignored from the parent decomp repo — each project has its own git repo
- ROMs must NOT be committed (they're copyrighted)
- Use the `/refine-splat` skill after initial setup to iterate on the splat config
- Use the `/setup-objdiff` skill to configure objdiff for function-level diffing
- Reference projects: [HM64](https://github.com/harvestwhisperer/hm64-decomp), [SSSV](https://github.com/mkst/sssv)
