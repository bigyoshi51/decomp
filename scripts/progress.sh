#!/bin/bash
# Print decompilation progress by comparing built ROM against base ROM per-function.
# Project-agnostic — reads segment info from the splat YAML config.
# Usage: ./scripts/progress.sh [project_dir]

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR" || { echo "Error: cannot cd to $PROJECT_DIR"; exit 1; }

# Find the splat YAML (the one with a 'segments:' key, not decomp.yaml)
YAML=$(grep -l '^segments:' *.yaml 2>/dev/null | head -1)
if [ -z "$YAML" ]; then
    echo "Error: no splat YAML found in $PROJECT_DIR"
    exit 1
fi

# Extract basename for ROM path
BASENAME=$(python3 -c "
import yaml, sys
cfg = yaml.safe_load(open('$YAML'))
print(cfg.get('options', {}).get('basename', ''))
")

if [ -z "$BASENAME" ]; then
    echo "Error: no basename found in $YAML"
    exit 1
fi

# Build if needed
BUILT_ROM="build/${BASENAME}.z64"
if [ ! -f "$BUILT_ROM" ]; then
    # Try root-level ROM too (some projects put it there)
    if [ -f "${BASENAME}.z64" ]; then
        BUILT_ROM="${BASENAME}.z64"
    else
        make RUN_CC_CHECK=0 -j4 > /dev/null 2>&1
        # Check both locations after build
        if [ -f "build/${BASENAME}.z64" ]; then
            BUILT_ROM="build/${BASENAME}.z64"
        elif [ -f "${BASENAME}.z64" ]; then
            BUILT_ROM="${BASENAME}.z64"
        else
            echo "Error: could not find or build ROM"
            exit 1
        fi
    fi
fi

python3 - "$YAML" "$BUILT_ROM" << 'PYEOF'
import re
import sys
import yaml
from pathlib import Path

yaml_path = sys.argv[1]
built_rom_path = sys.argv[2]

cfg = yaml.safe_load(open(yaml_path))
project_name = cfg.get("name", yaml_path)
opts = cfg.get("options", {})
asm_path = opts.get("asm_path", "asm")

rom = open("baserom.z64", "rb").read()
built = open(built_rom_path, "rb").read()

# Extract code segments with vram from the YAML
segments = {}
for seg in cfg.get("segments", []):
    if isinstance(seg, dict) and seg.get("type") == "code":
        seg_name = seg.get("name")
        rom_start = seg.get("start")
        vram = seg.get("vram")
        if rom_start is None or vram is None:
            continue
        # Check for subsegments to find the actual asm directory names
        subsegments = seg.get("subsegments", [])
        for sub in subsegments:
            if isinstance(sub, list) and len(sub) >= 2:
                sub_type = sub[1]
                if sub_type not in ("c", "asm"):
                    continue
                # 3-element: [offset, type, name] — name is explicit
                # 2-element: [offset, type] — splat derives name from hex offset
                if len(sub) >= 3:
                    dir_name = sub[2]
                else:
                    dir_name = format(sub[0], 'X')
                segments[dir_name] = (rom_start, vram, f"src/{dir_name}.c")
        if not subsegments:
            segments[seg_name] = (rom_start, vram, f"src/{seg_name}.c")

if not segments:
    print(f"{project_name} Decompilation Progress")
    print("=" * 40)
    print("No code segments found in YAML config.")
    sys.exit(0)

total_funcs = 0
matched_funcs = 0
total_code = 0
matched_code = 0
segment_stats = {}

for seg_name, (rom_base, vram_base, src_path) in segments.items():
    nonmatch_dir = Path(f"{asm_path}/nonmatchings/{seg_name}")
    if not nonmatch_dir.exists():
        continue

    seg_total = 0
    seg_matched = 0
    seg_code_total = 0
    seg_code_matched = 0

    src_text = Path(src_path).read_text() if Path(src_path).exists() else ""

    for f in sorted(nonmatch_dir.iterdir()):
        if not f.name.endswith(".s"):
            continue

        text = f.read_text()
        instrs = [l for l in text.splitlines() if "/*" in l and "*/" in l]
        if not instrs:
            continue

        func_name = f.stem
        func_size = len(instrs) * 4

        # Get ROM offset from function name (func_80XXXXXX style)
        try:
            vram = int(func_name.split("_")[1], 16)
        except (IndexError, ValueError):
            continue

        rom_off = rom_base + (vram - vram_base)
        if rom_off < 0 or rom_off + func_size > len(rom):
            continue

        seg_total += 1
        seg_code_total += func_size

        # Check if function is decompiled (has a C body, not just INCLUDE_ASM)
        is_include_asm = f'INCLUDE_ASM("{asm_path}/nonmatchings/{seg_name}", {func_name})' in src_text
        has_body = bool(re.search(rf'{func_name}\s*\([^)]*\)\s*\{{', src_text))

        if not is_include_asm and has_body:
            # Decompiled — check if bytes match
            match = True
            for i in range(0, func_size, 4):
                if rom_off + i + 4 > len(rom) or rom_off + i + 4 > len(built):
                    match = False
                    break
                if rom[rom_off + i:rom_off + i + 4] != built[rom_off + i:rom_off + i + 4]:
                    match = False
                    break
            if match:
                seg_matched += 1
                seg_code_matched += func_size

    segment_stats[seg_name] = (seg_matched, seg_total, seg_code_matched, seg_code_total)
    total_funcs += seg_total
    matched_funcs += seg_matched
    total_code += seg_code_total
    matched_code += seg_code_matched

print(f"{project_name} Decompilation Progress")
print("=" * 40)
code_pct = matched_code / total_code * 100 if total_code else 0
func_pct = matched_funcs / total_funcs * 100 if total_funcs else 0
print(f"Code:      {matched_code:>8} / {total_code:>8} bytes ({code_pct:.2f}%)")
print(f"Functions: {matched_funcs:>8} / {total_funcs:>8}       ({func_pct:.2f}%)")
print()
for seg_name, (m, t, cm, ct) in segment_stats.items():
    pct = cm / ct * 100 if ct else 0
    print(f"  src/{seg_name:<16} {m:>4}/{t:<5} functions  ({pct:.2f}% code)")
PYEOF
