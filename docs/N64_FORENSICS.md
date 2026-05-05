# N64 Forensics

> N64-specific knowledge: RSP ucode, splat config, ROM layout, game-specific.

_9 entries. Auto-generated from per-memo notes; content may be rough on first pass — light editing welcome._

## Index

- [1080's RSP ucode blob (assets/game_libs_ucode.bin) is NOT F3DEX2/F3DZEX — no upstream public reference matches](#feedback-1080-rsp-ucode-not-f3dex2) — Spiked 2026-05-04. Built all 20 F3DEX2/F3DZEX variants in Mr-Wiseguy/f3dex2 and substring-searched their code+data sections against the 56 K
- [game_libs absolute-address data refs use `extern T *gl_ref_XXXXXXXX` + undefined_syms](#feedback-game-libs-gl-ref-data) — For `lui $rN, %hi(SYM); lw $rN, %lo(SYM)($rN)` pairs in game_libs (USO) that load a pointer from a fixed absolute address, declare `extern T
- [game_libs JAL targets are largely placeholders; use gl_func_00000000 for target=0, extern stubs for non-zero non-boundary targets](#feedback-game-libs-jal-targets) — In game_libs (relocatable USO at VRAM=0), JAL targets in the ROM are runtime-patched placeholders, not real call targets. For JAL target=0 (
- [GFX display-list data vs RSP microcode forensic — top-byte distribution is necessary but NOT sufficient; substring-match against public IMEM bins is the real check](#feedback-gfx-dl-data-vs-rsp-ucode-forensic-check) — GFX-opcode top-byte counting at 8-byte alignment can give FALSE NEGATIVES on mixed blobs (CPU code + RSP IMEM concatenated together). 1080's
- [HW address literal vs symbol encoding](#feedback-hw-addr-encoding) — Both forms produce identical ROM bytes via asm-processor — don't chase objdiff's per-.o "diff" when comparing against an INCLUDE_ASM baselin
- [N64 RSP ucode data-section layout — id-string at fixed offset within 0x800 block, used as fingerprint anchor](#feedback-n64-ucode-data-section-layout-id-offset-signature) — Stock Nintendo F3DEX 1.x gfx ucodes pack their banner ID string at offset 0x2B0 within a 0x800-byte DMEM data section; aspMain audio ucodes 
- [N64 ucode IMEM + DMEM can live in different ROM segments — search both before declaring a blob "non-ucode"](#feedback-n64-ucode-imem-dmem-split-across-segments) — 1080 stores gfx ucode IMEM (5 KB each, F3DEX 1.x family) in `game_libs` segment ROM 0xDFA43C+, but the paired DMEM data tables (0x800 each) 
- [n64sym is unreliable](#feedback-n64sym) — n64sym has very high false positive rate — validate ALL names against real function prologues before using
- [Splat-bundled "function" with 100+ jr-ra-byte patterns is opaque data — but its TYPE (RSP ucode vs GFX DL data vs other) needs forensic check](#feedback-rsp-microcode-mistaken-for-code) — When a bundled "function" has anomalous size (50+ KB) with high `grep -c 03E00008` count, it's NOT CPU code — that part of the original clai

---

<a id="feedback-1080-rsp-ucode-not-f3dex2"></a>
## 1080's RSP ucode blob (assets/game_libs_ucode.bin) is NOT F3DEX2/F3DZEX — no upstream public reference matches

_Spiked 2026-05-04. Built all 20 F3DEX2/F3DZEX variants in Mr-Wiseguy/f3dex2 and substring-searched their code+data sections against the 56 KB blob. Zero matches. Blob has no F3DEX2 ID string ("RSP Gfx ucode F3DEX..."). Most likely libgdl (Giles Goddard) custom RSP ucode with no public reference. Hand-decomping is out of scope for a CPU-progress-driven workflow; keep the bin-wrap._

**Spike (2026-05-04, issue #4):**
- Cloned Mr-Wiseguy/f3dex2, built armips, ran `make ok` to assemble all 20 variants.
- Substring-searched each variant's `.code` (~5 KB) and `.data` (~1 KB) against `assets/game_libs_ucode.bin` (56856 bytes / 0xDE18).
- Result: **0 matches**. None of F3DEX2_2.04 / 2.04H / 2.05 / 2.06 / 2.07 / 2.08 / 2.08PL / NoN_* / F3DZEX_*_2.06H/2.08I/2.08J have any byte sequence inside the 1080 blob.

**Forensics:**
- `strings -a` on the blob returns no readable ASCII. F3DEX2 always has the version-banner string `RSP Gfx ucode F3DEX       fifo X.YY  Yoshitaka Yasumoto 1998 Nintendo.` somewhere in its data section. None present → not F3DEX2-family.
- Blob starts with `27bd ffd8 afbf 0014 afa4 0028 0c00 0000` (RSP SU/MIPS-1 prologue: `addiu sp,sp,-0x28; sw ra,0x14(sp); sw a0,0x28(sp); jal 0`).
- Densely populated with 0x4Axxxxxx and 0x4Bxxxxxx (RSP vector ops) and 0xC9xxxxxx (LSV) bytes throughout — confirms RSP microcode, not raw CPU code.
- 56 KB total — too large for a single F3DEX2 (~6 KB). Likely contains multiple ucode payloads + tables / static data.

**Most likely origin:**
1080 was developed by Nintendo EAD Kyoto using Giles Goddard's libgdl engine. libgdl shipped its own custom RSP graphics ucode rather than using Nintendo's F3DEX line. There is no public reference assembly for libgdl's ucode.

**Implication for the project:**
- The bin-wrap (`game_libs_ucode` in `tenshoe.yaml`, MIN/MAX `0xDF3CD0..0xE01AE8`) is correct — keep it.
- Decomping 14+ KB of custom RSP code without a public reference is a multi-week dedicated effort, not a single spike, and doesn't move the CPU-progress headline number. Skip unless it becomes specifically valuable for some other reason (e.g., a graphics-pipeline understanding becomes load-bearing for CPU work).
- Issue #4 (https://github.com/bigyoshi51/1080-decomp/issues/4) should be closed with the negative-result note.

**How to apply:**
- Don't re-run F3DEX2 fingerprinting on this blob. The result is conclusive.
- If a future revision of Mr-Wiseguy/f3dex2 (or a sibling repo) adds libgdl variants or custom-Nintendo variants, re-spike then.
- A separate but cheaper task: identify any AUDIO ucode in 1080 (typical position differs from gfx) and check if it matches stock Nintendo aspMain/aspMainNoVS variants. The current bin-wrap covers gfx; audio might be elsewhere in the ROM.

---

<a id="feedback-game-libs-gl-ref-data"></a>
## game_libs absolute-address data refs use `extern T *gl_ref_XXXXXXXX` + undefined_syms

_For `lui $rN, %hi(SYM); lw $rN, %lo(SYM)($rN)` pairs in game_libs (USO) that load a pointer from a fixed absolute address, declare `extern T *gl_ref_ADDR;` in game_libs.c and add `gl_ref_ADDR = 0xADDR;` to `undefined_syms_auto.txt`. Use a NAMED local intermediate (not inline) to get `$v0` allocation matching the target._

**Rule:** When the target asm has:
```
lui $v0, %hi(SYM)
lw  $v0, %lo(SYM)($v0)       # load pointer from SYM
sw  $val, OFF($v0)            # store to [ptr + OFF]
```

...and SYM is a placeholder absolute address (e.g. 0x138, 0x2C0, etc — low addresses typical of USO `gl_ref_`):

1. Add the symbol to `undefined_syms_auto.txt`:
   ```
   gl_ref_00000138 = 0x00000138;
   ```

2. Declare the extern at file scope with pointer type matching what's stored at SYM:
   ```c
   extern int *gl_ref_00000138;   /* use the type pointed-TO by SYM */
   ```

3. **Use a named local for the load** — NOT inline — to trigger `$v0` allocation:
   ```c
   int *p;
   gl_func_00000000(...);
   p = gl_ref_00000138;
   p[OFF/4] = 0;
   ```

**Why named local (not inline):**

Inline form `gl_ref_00000138[OFF/4] = 0;` produces `lui $t6; lw $t6, %lo(SYM)($t6); sw zero, OFF($t6)` — IDO picks a `$t-register` for the anonymous intermediate. Target wants `$v0`.

Naming the intermediate as `int *p;` and assigning it `p = gl_ref_00000138;` before the use promotes it to `$v0`. (See `feedback_ido_v0_reuse_via_locals.md` for the general rule; this is the specific game_libs application.)

**Why NOT just use a different declared type:**

- `extern int *gl_ref_X` (pointer-to-int) matches the `lw` correctly.
- `extern int gl_ref_X` (int) would produce a different asm (ld or similar).
- `extern int gl_ref_X[]` (array) depends on indexing style — usually still works but can alter reloc target name.

**Real example — gl_func_00006DC8 (2026-04-19):**

Target asm:
```
addiu sp,sp,-24
sw    ra,20(sp)
addiu a1, zero, 0x1E0
jal   gl_func_00000000
or    a2, zero, zero           ; delay
lui   v0, %hi(gl_ref_00000138)
lw    v0, %lo(gl_ref_00000138)(v0)
sw    zero, 0xB4(v0)
lw    ra, 20(sp)
addiu sp, sp, 24
jr    ra
nop
```

Matching C:
```c
extern int gl_func_00000000();
extern int *gl_ref_00000138;

void gl_func_00006DC8(int a0) {
    int *p;
    gl_func_00000000(a0, 0x1E0, 0);
    p = gl_ref_00000138;
    p[45] = 0;   /* 45*4 = 0xB4 */
}
```

100 % match.

**Gotcha:** the objdump of the UNLINKED .o shows `lw $v0, 0($v0)` with offset 0 — that's the reloc placeholder, not wrong. After linking, objdump shows the real `lw $v0, 0x138($v0)`. Don't panic at the unlinked view; diff the LINKED ELF (`build/tenshoe.elf`) or trust `objdiff-cli report` which applies relocs.

**How to apply:**

- Any `lui $rN, 0x0000; lw $rN, 0xXXXX($rN)` pair in game_libs → infer `gl_ref_0000XXXX` absolute symbol.
- Low-address symbols (< 0x10000) are DATA placeholders, like `gl_func_00000000` is the CODE placeholder.
- Name the intermediate local if target uses `$v0`; inline if target uses `$tN`.

**Related:** `feedback_game_libs_jal_targets.md` covers the JAL-side (`jal` to non-zero placeholder → `gl_ref_ADDR` as extern function stub). This memory covers the DATA-side (lui/lw pair → `gl_ref_ADDR` as extern pointer variable).

**Origin:** 2026-04-19 game_libs gl_func_00006DC8. Inline form got 90 % (right offsets, wrong register). Named local got 100 %.

---

<a id="feedback-game-libs-jal-targets"></a>
## game_libs JAL targets are largely placeholders; use gl_func_00000000 for target=0, extern stubs for non-zero non-boundary targets

_In game_libs (relocatable USO at VRAM=0), JAL targets in the ROM are runtime-patched placeholders, not real call targets. For JAL target=0 (82 %) call `gl_func_00000000` in C — it links at address 0 and re-encodes as 0x0C000000, matching bytes. For non-zero targets that land mid-function, add an absolute-address extern symbol via undefined_syms_auto.txt._

**Rule:** When decompiling a `gl_func_XXXXXXXX` in game_libs and it has a `jal` instruction, look at the encoded target in the ROM:

- **Target = 0x00000000** (the common case — 82 % of JALs): write `extern int gl_func_00000000();` and call `gl_func_00000000()`. The linker resolves `gl_func_00000000` to address 0 (it's the first real function in game_libs at VRAM=0), so the JAL re-encodes as `0x0C000000` — byte-identical to the ROM placeholder. The call is semantically fake (the runtime patches it to something else) but the bytes match.

- **Target = non-zero, aligned with an existing gl_func_XXXXXXXX start**: call that function directly. Example: `jal 0x3a880` → if `gl_func_0003A880` exists, call it.

- **Target = non-zero, lands mid-function**: this is a runtime-patched reference that doesn't correspond to any real function start in our static disassembly. Create an absolute-address extern symbol in `undefined_syms_auto.txt`:
  ```
  gl_ref_0003A880 = 0x0003A880;
  ```
  Then call `gl_ref_0003A880()` in C. Linker encodes JAL target = 0x3A880 >> 2 = 0xEA20 → instruction = 0x0C00EA20 (matches ROM).

**Why:** USO overlays store pre-relocation placeholder values in JAL target fields. At runtime, the loader walks the reloc tables and rewrites these to real addresses. For our static matching build, we only need the JAL opcodes to encode the same 26-bit target as the ROM — we don't actually need the call to go anywhere sensible. The naming is semantically misleading but pragmatically essential.

**Gotcha discovered 2026-04-18:** decompiling `gl_func_000261F4` failed because I assumed `jal 0x3a880` pointed to function `gl_func_0003A880`. That function doesn't exist — the address 0x3A880 is in the middle of `gl_func_0003A58C` (size 0x420). Adding `gl_ref_0003A880 = 0x0003A880` to `undefined_syms_auto.txt` fixed it.

**How to apply:**

1. Decode the JAL target from the bytecode: `target = ((word & 0x03FFFFFF) << 2)`.
2. If `target == 0`: call `gl_func_00000000`.
3. If `target` matches a known `gl_func_XXXXXXXX` start: call that.
4. Otherwise: add `gl_ref_{target:08X} = 0x{target:08X};` to `undefined_syms_auto.txt` and call `gl_ref_XXXXXXXX`.

**Origin:** 2026-04-18 game_libs decomp batch, first function `gl_func_00027160` (JAL target=0 pure delegator, 8 insts).

---

<a id="feedback-gfx-dl-data-vs-rsp-ucode-forensic-check"></a>
## GFX display-list data vs RSP microcode forensic — top-byte distribution is necessary but NOT sufficient; substring-match against public IMEM bins is the real check

_GFX-opcode top-byte counting at 8-byte alignment can give FALSE NEGATIVES on mixed blobs (CPU code + RSP IMEM concatenated together). 1080's `game_libs_text2` (originally renamed to `_dl_data` based on this heuristic) was actually 26 KB CPU code + 25 KB RSP F3DEX 1.23 IMEM — sm64's `lib/PR/f3dex/{F3DEX_NoN,F3DEX,F3DLX_Rej}.bin` byte-match exactly inside the "DL data" region. Top-byte heuristic alone said "DL data"; ground truth is "stock SDK IMEM." Always cross-check by substring-searching against public Nintendo SDK ucode bins before trusting opcode-counting._

**The bug:** RSP "microcode," GFX "display-list data," and CPU code can ALL coexist in a single embedded blob. Top-byte opcode counting at 8-byte boundaries (the heuristic this memo originally promoted) gives a misleading answer when the blob is heterogeneous — it returns whichever class dominates by sample count, missing the smaller-but-meaningful regions. **Verified false negative**: 1080's `game_libs_text2` (formerly `game_libs_dl_data`) showed only 3.4% GFX-opcode top-bytes — well below the "DL data" threshold — yet contains three sm64-byte-identical F3DEX 1.23 IMEMs (15 KB total) plus 26 KB of MIPS CPU code. The opcode count was diluted by the dominant CPU-code region, not "low" because the blob had no RSP IMEM. Issue #6 path-C investigation 2026-05-05 corrected this.

**Forensic check (when no ucode ID strings are present):**

```python
# Known GFX display-list opcodes (top byte of 8-byte commands)
GFX_OPS = {0x01, 0x05, 0x06, 0x07, 0xDA, 0xDB, 0xDE, 0xDF, 0xE6, 0xE8,
           0xF5, 0xFC, 0xFD, 0xFE, 0xD9}
# Known RSP microcode patterns (per-instruction, 4-byte aligned)
# - 0x4Axxxxxx / 0x4Bxxxxxx: COP2 vector ops (vmadm/vmadn/vmadl etc)
# - 0xC9xxxxxx: LSV/LDV/LRV/LPV/LUV vector loads
# - 0x40xxxxxx: CP0 control register ops (mtc0/mfc0)

# Count GFX opcodes (8-byte aligned, top byte)
gfx_hits = sum(1 for i in range(0, len(blob), 8) if blob[i] in GFX_OPS)
# Count RSP-distinctive opcodes (4-byte aligned, top byte)
rsp_hits = sum(1 for i in range(0, len(blob), 4) if blob[i] in {0x4A, 0x4B, 0xC9})

print(f"GFX-cmd words / total 8-byte words: {gfx_hits} / {len(blob)//8}")
print(f"RSP-vec words / total 4-byte words: {rsp_hits} / {len(blob)//4}")
```

**Decision rule (rough thresholds):**
- ≥2% of 8-byte words have GFX-opcode top bytes → display-list data.
- ≥1% of 4-byte words are 0x4A/0x4B/0xC9 → RSP microcode.
- Both can be true if it's mixed (e.g., the actual 1080 blob has 234 GFX cmds AND scattered RSP-style bytes in the vertex-data portion). The presence of NO ucode ID strings (`RSP Gfx ucode...`, `RSP SW Version...`, `RSP Audio...`) tips toward DL data.

**Cross-check via word alignment:**
- GFX display lists are 8-byte aligned (each command is exactly 64 bits).
- RSP microcode is 4-byte aligned.
- A blob with strong 8-byte-aligned regularity is almost certainly DL data.

**Action when DL data is identified:**
- Splat segment should be named `<seg>_dl_data` or similar, not `<seg>_ucode`.
- Don't try to decompile from public ucode references (Mr-Wiseguy/f3dex2, libdragon) — those produce RSP microcode bytes, not DL data.
- Keep as bin; DL data is intrinsically tied to the rest of game_libs (the C code passes pointers into it during display-list submission).

**Action when RSP microcode is identified:**
- Look for ID strings to determine variant. Stock Nintendo SDK ucodes (F3DEX, F3DEX2, F3DZEX, aspMain) all carry banner strings.
- If F3DEX2 family → fingerprint via Mr-Wiseguy/f3dex2 (20 variants pre-built).
- If F3DEX 1.x family or aspMain → no easy public fingerprint as of 2026-05-04; see issue tracking for 1080.

**Don't trust ID-byte heuristics alone.** A blob with `0x4Axxxxxx` words could also be vertex coordinate data (16-bit signed ints with top bit set look like 0x4A-prefix when interpreted as 32-bit). The clustering and alignment matters more than any single byte.

**Mandatory pre-classification step (added 2026-05-05):** before naming a blob `<seg>_dl_data` or `<seg>_ucode`, substring-search it against `n64decomp/sm64`'s `lib/PR/f3dex/*.bin` (and `f3dex2/*.bin` for newer SDK):

```python
for ref in glob('/path/to/sm64/lib/PR/f3dex/*.bin'):
    sm64_imem = open(ref,'rb').read()
    if sm64_imem in target_blob:
        print(f"  ★ {ref} byte-exact match in target")
```

If ANY sm64 IMEM bin appears as a complete byte substring → blob is at least partly RSP IMEM, regardless of what the opcode-count heuristic says. Don't rename to `_dl_data` without doing this check first.

**Also**: 1080-style projects can split IMEM and DMEM across DIFFERENT segments. 1080 keeps gfx ucode IMEM in `game_libs` segment, but the paired DMEM data tables in `bootup_uso_pre`. Both segments need substring checks; finding ucode in one doesn't preclude finding it in the other.

---

<a id="feedback-hw-addr-encoding"></a>
## HW address literal vs symbol encoding

_Both forms produce identical ROM bytes via asm-processor — don't chase objdiff's per-.o "diff" when comparing against an INCLUDE_ASM baseline_

C code can write a hardware register address as either a literal cast or a `extern volatile` symbol — **both produce identical final ROM bytes** after linking, but their `.o`-level encodings differ.

**Literal form** (`(*(volatile u32*)0xA4600010)`): IDO emits `lui $tN, 0xA460; lw ..., 0x10($tN)` with the literal already in the immediate field. No relocation entry.

**Symbol form** (`extern volatile u32 D_A4600010;` + `D_A4600010`): IDO emits `lui $tN, 0; lw ..., 0($tN)` with `R_MIPS_HI16` / `R_MIPS_LO16` relocations against `D_A4600010`. The linker patches in 0xA460/0x10.

**Why:** When the original ROM was disassembled, splat resolved `lui 0xA460` to `%hi(D_A4600010)` for readability. The `.s` file uses the symbol form; asm-processor assembles it leaving relocations. So `expected/*.o` (snapshotted while the function was INCLUDE_ASM) has the symbol-form encoding even though the original ROM bytes were literal.

**How to apply:**
- If your decompiled C uses literals and objdiff shows a `.o`-level diff against an INCLUDE_ASM-derived baseline, **verify the actual final ROM bytes via Python before assuming the function doesn't match** — the diff is likely just relocation form.
- After confirming ROM bytes match, `make expected RUN_CC_CHECK=0` to re-snapshot the baseline so objdiff agrees. Only do this once you're confident the linked output matches the original baserom; re-snapshotting from a wrong build silently overwrites the baseline.
- Either C form is fine to commit. Match the surrounding file's convention — kernel_011 uses literals; libultra projects often use symbols defined in `include/regs.h`.

---

<a id="feedback-n64-ucode-data-section-layout-id-offset-signature"></a>
## N64 RSP ucode data-section layout — id-string at fixed offset within 0x800 block, used as fingerprint anchor

_Stock Nintendo F3DEX 1.x gfx ucodes pack their banner ID string at offset 0x2B0 within a 0x800-byte DMEM data section; aspMain audio ucodes put it near the end (~0x7F0). When fingerprinting an opaque ucode-rich blob, this position is the discriminator AND the alignment anchor for substring-matching against public references like sm64's `lib/PR/f3dex/*_data.bin`._

When carving an opaque blob suspected to contain RSP ucodes (1080 issue #6
work, 2026-05-05), banner-string offsets within the data section are
diagnostic AND give you the exact alignment for byte-substring fingerprinting.

**Why:** Nintendo SDK F3DEX 1.x ships data sections of exactly `0x800` bytes
with the banner string `RSP Gfx ucode F3DEX...` at byte offset `0x2B0` from
the data section start. aspMain audio ucode data sections also `0x800` but
the banner sits near the end (offset `~0x7F0`). 1080 uses both classes;
both patterns hold across all 11 ucode payloads.

**How to apply:**
1. Locate banner ID strings in the blob (`grep -aob 'RSP Gfx ucode\|RSP SW
   Version'`).
2. Compute candidate data-section start = `id_offset - 0x2B0` for gfx,
   `id_offset - 0x7F0` for audio.
3. Extract that `0x800` window and substring-match against
   `n64decomp/sm64`'s `lib/PR/f3dex/*_data.bin` (prebuilt 2 KB DMEM bins
   present, banner inside).
4. If match: ucode positively identified as that exact F3DEX 1.x variant
   (down to data-table revision).

**What sm64 ships in `lib/PR/f3dex/`** (F3DEX 1.x family, 1.23):
- F3DEX, F3DEX_NoN, F3DLX, F3DLX_NoN, F3DLX_Rej, L3DEX (each as `_data.bin`
  + IMEM `.bin`)
- Does NOT ship: F3DLP_Rej (1080 has it; no public ref found)

**Important caveat:** **DATA matches but IMEM (code) usually doesn't.**
Both 1080 and sm64 ship "F3DEX 1.23" per banner, but the IMEM 5168-B `.bin`s
DO NOT byte-match (verified via 64-B sliding-window). Build-environment drift
or 1.23 IMEM-only revisions explain it. **Use data-section matches for
identification, not for full ucode reconstruction.**

**aspMain (audio) public refs are scarce.** Only sm64 has it as armips
source (`sm64/rsp/audio.s`), not a prebuilt bin. oot/mm/papermario/BK
extract from baserom. libdragon uses different audio stack (rsp_mixer/opus).
Byte-fingerprinting aspMain requires building sm64's audio.s with armips
first. Banner identifies SDK version (`2.0H 02-12-97` / `2.0D 04-01-96`)
without code match.

**One more diagnostic:** within a single decomp blob with multiple aspMain
banner copies (1080 has 5x 2.0H variants), md5 each `0x800` data section.
Different md5s prove they're distinct DMEM CONFIGS sharing one IMEM (the
layout in 1080: 5x 2.0H aspMain data sections at 0xDB3800-0xDB6000 are
contiguous and md5-distinct, so they're per-track/per-config DMEM init,
not duplicate ucode payloads).

---

<a id="feedback-n64-ucode-imem-dmem-split-across-segments"></a>
## N64 ucode IMEM + DMEM can live in different ROM segments — search both before declaring a blob "non-ucode"

_1080 stores gfx ucode IMEM (5 KB each, F3DEX 1.x family) in `game_libs` segment ROM 0xDFA43C+, but the paired DMEM data tables (0x800 each) in `bootup_uso_pre` ROM 0xDB7140+. The two segments are 290 KB apart in ROM. Searching only one and finding "no IMEM" does NOT mean "no ucode" — the runtime DMA's IMEM and DMEM from separate sources at G_LOAD_UCODE time. Always grep all candidate segments for ucode banner strings + substring-match sm64 stock bins across the whole ROM._

**The structure (verified 1080, 2026-05-05):**

```
0xDB7140  bootup_uso_pre  F3DEX_NoN DMEM data (0x800 — sm64 F3DEX_NoN_data.bin byte-exact)
0xDB7940  bootup_uso_pre  F3DEX     DMEM data (0x800 — sm64 F3DEX_data.bin byte-exact)
0xDB8940  bootup_uso_pre  F3DLP_Rej DMEM data (0x800 — no public ref)
0xDB9140  bootup_uso_pre  F3DLX_Rej DMEM data (0x800 — sm64 F3DLX_Rej_data.bin byte-exact)
...
0xDFA43C  game_libs       F3DEX_NoN IMEM      (5168 — sm64 F3DEX_NoN.bin byte-exact)
0xDFB86C  game_libs       F3DEX     IMEM      (5168 — sm64 F3DEX.bin byte-exact)
0xDFCC9C  game_libs       F3DLP_Rej IMEM      (5168 — inferred, no public ref)
0xDFF2DC  game_libs       F3DLX_Rej IMEM      (5072 — sm64 F3DLX_Rej.bin byte-exact)
```

The IMEM+DMEM pairs are loaded together via `G_LOAD_UCODE` at runtime, but stored in different ROM segments at build time. This is reasonable: the linker can't guarantee IMEM and DMEM end up adjacent (sizes don't fit common page boundaries), so they're packed into whichever segment had room.

**Why this matters:**
- A heuristic like "this 56 KB game_libs blob has 3.4% GFX opcodes → it's display-list data" gave a false negative on 1080. The blob is 26 KB CPU code + 15 KB confirmed RSP IMEM + smaller unknowns. Top-byte counting on the whole blob hides the IMEM portion.
- Naming a blob `<seg>_dl_data` based on this kind of forensic without a substring check against public ucode references can lead to wholesale missed ucode identifications.

**How to apply (ucode forensic pass for any new project):**

1. **Grep for banner strings across entire ROM** (`RSP Gfx ucode`, `RSP SW Version`, `RSP Audio`, etc.). Note positions; banners live in DMEM.
2. **For each banner found, also substring-search the WHOLE ROM** (not just nearby segments) for sm64's prebuilt IMEM bins (`n64decomp/sm64 lib/PR/f3dex/*.bin` for F3DEX 1.x; `lib/PR/f3dex2/*.bin` for F3DEX2 family). IMEM may be 100s of KB away from the matching banner-DMEM.
3. **If any sm64 bin matches**: ucode is positively identified. Carve sub-bins for both the IMEM region (in whatever segment) AND DMEM region (likely a different segment), name them after the variant.
4. **Don't trust opcode-count heuristics** to decide DL data vs ucode. They under-detect on mixed-content blobs. See companion memo `feedback_gfx_dl_data_vs_rsp_ucode_forensic_check.md` for the corrected discriminator chain.

**Heuristic for "where is the IMEM?"** When you find a DMEM banner-string at ROM X and want its paired IMEM:
- First, scan the 0x10 KB immediately preceding X (typical layout has IMEM right before DMEM).
- If absent → search the entire ROM, focusing on regions with high (>80%) byte density and same-family neighbors. F3DEX-family IMEMs are typically packed contiguously (each ~5 KB).
- F3DEX 1.x variants are byte-similar (~10% identical bytes between siblings): use this for low-confidence positional inference of variants without public refs.

---

<a id="feedback-n64sym"></a>
## n64sym is unreliable

_n64sym has very high false positive rate — validate ALL names against real function prologues before using_

Never trust n64sym output blindly. On 1080 Snowboarding, only 2 out of 231 function name matches were correct. The other 229 were false positives that placed labels MID-FUNCTION, breaking splat's function boundary detection and making the disassembly impossible to decompile.

**Why:** n64sym matches short instruction sequences against known library signatures. GCC-compiled code produces coincidental matches against IDO-compiled library patterns, especially for rmon functions.

**How to apply:** After running n64sym, validate every result:
1. Check that the matched address is at a real function prologue (`addiu $sp, $sp, -N`)
2. Verify the prologue is preceded by `jr $ra`, `nop`, or another epilogue
3. Remove any n64sym names that don't land on validated prologues
4. Only then add to symbol_addrs.txt

---

<a id="feedback-rsp-microcode-mistaken-for-code"></a>
## Splat-bundled "function" with 100+ jr-ra-byte patterns is opaque data — but its TYPE (RSP ucode vs GFX DL data vs other) needs forensic check

_When a bundled "function" has anomalous size (50+ KB) with high `grep -c 03E00008` count, it's NOT CPU code — that part of the original claim still holds. The original memo asserted it was RSP microcode; on 2026-05-04 forensic check (see feedback_gfx_dl_data_vs_rsp_ucode_forensic_check.md) showed 1080's specific case is actually GFX display-list data, not RSP microcode. Both are opaque blobs with `jr ra`-byte coincidences, but they need different handling. Always check via opcode-distribution + ucode-ID-string presence before naming the segment._

> **CORRECTION 2026-05-04:** This memo's original conclusion ("it's RSP microcode") was WRONG for 1080's specific blob. Forensic re-check found 234 GFX display-list opcodes (gsSPVertex / gsSP1Triangle / gsSP2Triangles / gsDPTileSync) and zero ucode ID strings — it's display-list data, not microcode. The actual RSP microcodes in 1080 live elsewhere (in `bootup_uso_pre`, ROM 0xDB3FF0+; see GitHub issue #6). The general rule below is still correct (opaque, not CPU text), but the type-attribution needs the forensic check in `feedback_gfx_dl_data_vs_rsp_ucode_forensic_check.md`.

**Trigger:** `gl_func_0000EBF8` in game_libs was declared 0xDE18 (56 KB) with `grep -c 03E00008 = 114`. Running `split-fragments.py` recursively produced 114 "functions."

**Red flag when inspecting the splits:**

Most splits had bodies like:
```
jr $ra           ; 0x03E00008
.word 0x40921800 ; mtc0 $s2, $3 (EntryLo1) — CP0, no valid C source
```
or
```
.word 0x400B3000 ; mfc0 $t3, $6 (Wired register)
bnel $t3, zero, -2
nop
jr $ra
.word 0x00008820 ; addu $s1, $zero, $zero
```

Mid-sized splits were sequences of:
```
.word 0xC9081800  ; LSV $v0[0], 0x00($t0)  — RSP vector load
.word 0x4A126DC5  ; RSP vector op
.word 0x80070DE2  ; RSP store
```

None of these are CPU instructions emitted by IDO. They're RSP (Reality Signal Processor) microcode. `jr ra` byte pattern `0x03E00008` appears coincidentally inside the microcode binary.

**Why game_libs has this:** game_libs is a shared library USO. It packages RSP microcode blobs (for graphics pipelines, audio ucode, etc.) alongside actual CPU code. Splat saw the microcode blob as one giant `.text` section because its YAML config didn't mark the range as data.

**Detection checklist (apply when a splat "function" has these signs):**

1. Declared size >= 16 KB in a single symbol
2. `grep -c 03E00008 <func>.s` returns >= 20
3. Opcodes inside the asm include RSP-specific prefixes:
   - `0x4A/0x4B` (RSP SU ops: VMADH, VMUDH, etc.)
   - `0xC9/0xCA` (RSP vector loads)
   - `0xE8/0xEA` (RSP vector stores)
   - `0x2XXXXXXX` where XXXXXXXX looks microcode-shaped
4. CP0 ops visible (`mtc0 $sN, $M` / `mfc0`) in "functions" that aren't exception handlers

**What to do:**

1. **Do NOT run split-fragments** on the big bundle. It creates noise.
2. **Revert any splits** that came from such a bundle.
3. **Mark the range as data** in the splat YAML: change `code` to `data` or `rodata` for the `vrom` offset covering the microcode.
4. Re-run splat (remembering the `feedback_splat_rerun_gotchas.md` clobbers).
5. The range should disassemble as `.word` directives in a `.data.c.o` or equivalent, and the decomp.dev progress for it is 0 (as data is tracked separately from code).

**Suspicious ranges in 1080 Snowboarding:**

- `gl_func_0000EBF8` @ 0xEBF8–0x1CA10 in game_libs = 56 KB (confirmed RSP microcode 2026-04-20)
- Check other 10+ KB "functions" in game_libs for the same pattern (gl_func_00004244 at 10KB, gl_func_000578B4 at 10KB — audit before splitting).

**Origin:** 2026-04-20, agent-a. Split gl_func_0000EBF8 into 114 "functions" then reverted after discovering the bodies were RSP microcode (VLV/mtc0/mfc0 ops). Commit `187c31e` reverts `be2729d`.

---

