#!/bin/bash
# Print decompilation progress by comparing built ROM against base ROM per-function.
# Always correct — no stale expected objects.
# Usage: ./scripts/progress.sh [project_dir]

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR" || { echo "Error: cannot cd to $PROJECT_DIR"; exit 1; }

# Build if needed
if [ ! -f build/glover.z64 ]; then
    make RUN_CC_CHECK=0 -j4 > /dev/null 2>&1
fi

python3 << 'PYEOF'
import struct
from pathlib import Path

rom = open("baserom.z64", "rb").read()
built = open("build/glover.z64", "rb").read()

segments = {
    "D910":  (0xD910,  0x8010C910, "src/D910.c"),
    "18020": (0x18020, 0x80118020, "src/18020.c"),
}

total_funcs = 0
matched_funcs = 0
total_code = 0
matched_code = 0
segment_stats = {}

for seg_name, (rom_base, vram_base, src_path) in segments.items():
    seg_total = 0
    seg_matched = 0
    seg_code_total = 0
    seg_code_matched = 0
    
    src_text = Path(src_path).read_text() if Path(src_path).exists() else ""
    
    for f in sorted(Path(f"asm/nonmatchings/{seg_name}").iterdir()):
        if not f.name.endswith(".s"):
            continue
        
        text = f.read_text()
        instrs = [l for l in text.splitlines() if "/*" in l and "*/" in l]
        if not instrs:
            continue
        
        func_name = f.stem
        func_size = len(instrs) * 4
        
        # Get ROM offset from function name
        try:
            vram = int(func_name.split("_")[1], 16)
        except (IndexError, ValueError):
            # Try D_ prefix
            try:
                vram = int(func_name.split("_")[1], 16)
            except:
                continue
        
        rom_off = rom_base + (vram - vram_base)
        if rom_off < 0 or rom_off + func_size > len(rom):
            continue
        
        seg_total += 1
        seg_code_total += func_size
        
        # Check if function is decompiled (has a C body, not just INCLUDE_ASM or forward decl)
        is_include_asm = f'INCLUDE_ASM("asm/nonmatchings/{seg_name}", {func_name})' in src_text
        # Also check it has an actual function body (name followed by { on same or next line)
        import re
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
        # INCLUDE_ASM functions are not "matched" for progress purposes
    
    segment_stats[seg_name] = (seg_matched, seg_total, seg_code_matched, seg_code_total)
    total_funcs += seg_total
    matched_funcs += seg_matched
    total_code += seg_code_total
    matched_code += seg_code_matched

name = "Glover (USA)"
print(f"{name} Decompilation Progress")
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
