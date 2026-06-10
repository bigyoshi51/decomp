# N64 Forensics

> N64-specific knowledge: RSP ucode, splat config, ROM layout, game-specific.

_10 entries. Auto-generated from per-memo notes; content may be rough on first pass — light editing welcome._

## Index

- [bootup_uso FP literal pool is splat-folded into func_0000098C — 3 mis-attributed f32/f64 consts block func_0000E270/D900/E2D0](#bootup-uso-fp-literal-pool-folded-into-func-0000098C) — _splat disassembled the bootup_uso FP constant region (vram 0x990-0x9A8) AS code because the USO segment has no literal-pool symbol; `func_0000098C + {0x4,0xC,0x14}` are really f64/f32/f64 constants. Fix = splat-config literal-pool break-out + re-extract (deferred, multi-file)._

- [1080's RSP ucode blob (assets/game_libs_ucode.bin) is NOT F3DEX2/F3DZEX — no upstream public reference matches](#feedback-1080-rsp-ucode-not-f3dex2) — Spiked 2026-05-04.
- [game_libs absolute-address data refs use `extern T *gl_ref_XXXXXXXX` + undefined_syms](#feedback-game-libs-gl-ref-data) — _For `lui $rN, %hi(SYM); lw $rN, %lo(SYM)($rN)` pairs in game_libs (USO) that load a pointer from a fixed absolute address, declare `extern T *gl_ref_ADDR;` in game_libs.c and add `gl_ref_ADDR = 0xADDR;` to…
- [game_libs JAL targets are largely placeholders; use gl_func_00000000 for target=0, extern stubs for non-zero non-boundary targets](#feedback-game-libs-jal-targets) — _In game_libs (relocatable USO at VRAM=0), JAL targets in the ROM are runtime-patched placeholders, not real call targets.
- [1080 game_libs small-function residue is exhausted-into-caps: the bare candidates left are cross-fn-merge / caller-set-reg / jump-table-undersized / 0x8-stolen-prologue-splat-gap families — recognize-and-skip](#feedback-1080-game-libs-small-fn-cap-families)
- [GFX display-list data vs RSP microcode forensic — top-byte distribution is necessary but NOT sufficient; substring-match against public IMEM bins is the real check](#feedback-gfx-dl-data-vs-rsp-ucode-forensic-check) — _GFX-opcode top-byte counting at 8-byte alignment can give FALSE NEGATIVES on mixed blobs (CPU code + RSP IMEM concatenated together). 1080's `game_libs_text2` (originally renamed to `_dl_data` based on this heuristic)…
- [HW address literal vs symbol encoding](#feedback-hw-addr-encoding) — _Both forms produce identical ROM bytes via asm-processor — don't chase objdiff's per-.o "diff" when comparing against an INCLUDE_ASM baseline_
- [N64 RSP ucode data-section layout — id-string at fixed offset within 0x800 block, used as fingerprint anchor](#feedback-n64-ucode-data-section-layout-id-offset-signature) — _Stock Nintendo F3DEX 1.x gfx ucodes pack their banner ID string at offset 0x2B0 within a 0x800-byte DMEM data section; aspMain audio ucodes put it near the end (~0x7F0).
- [N64 ucode IMEM + DMEM can live in different ROM segments — search both before declaring a blob "non-ucode"](#feedback-n64-ucode-imem-dmem-split-across-segments) — _1080 stores gfx ucode IMEM (5 KB each, F3DEX 1.x family) in `game_libs` segment ROM 0xDFA43C+, but the paired DMEM data tables (0x800 each) in `bootup_uso_pre` ROM 0xDB7140+.
- [n64sym is unreliable](#feedback-n64sym) — n64sym has very high false positive rate — validate ALL names against real function prologues before using
- [gui_uso has inline CPU-side RDP display-list builders (texture-load Gfx fragments) via a GfxCtx idiom — recognize by `0xFD10/0xF510/0xE600/0xF400/0xE700/0xF200/0x700` constant lui's + no calls/branches](#feedback-gui-uso-inline-rdp-dl-builder) — _A no-call/no-branch function emitting paired words via `g=(ctx*)a0->0xC; i=g->idx; g->idx=i+1; slot=(int*)g->buf + i*2; slot[0]=w0; slot[1]=w1;` (a0->0xC reloaded TWICE per packet) is a hand-built RDP DL fragment, not opaque data. Top-byte constants decode as G_SETTIMG(0xFD)/G_SETTILE(0xF5)/G_RDPLOADSYNC(0xE6)/G_LOADTILE(0xF4)/G_RDPPIPESYNC(0xE7)/G_SETTILESIZE(0xF2). Verified gui_uso_func_0000413C 2026-05-17: 7-packet texture-load sequence; args = texW/texH/fmt. The GfxCtx double-reload idiom ×N + cross-packet constant CSE drives a regalloc cascade that no first-pass C reproduces (1% first attempt) — multi-run sub-80 target; decode-comment the packet formulas for forensic value._
- [1080 game_libs contains IDO-compiled libultra ports — recognize __osViSwapContext by the VI register block (0xA4400000..34) write fan-out](#feedback-game-libs-libultra-ports-vi-fingerprint) — _A game_libs fn that fans out stores to the absolute VI register block (`*(s32*)0xA4400000`..`0xA4400034`) preceded by a VI_CURRENT(0xA4400010)&1 field-parity read IS libultra's `__osViSwapContext`. Copy the structure from references/libreultra/src/io/viswapcontext.c. Caps at ~52% because __osViNext/__osViCurr are distinct globals that reloc-collapse to &D_00000000. Verified gl_func_00070C44 2026-06-03._
- [Splat-bundled "function" with 100+ jr-ra-byte patterns is opaque data — but its TYPE (RSP ucode vs GFX DL data vs other) needs forensic check](#feedback-rsp-microcode-mistaken-for-code) — _When a bundled "function" has anomalous size (50+ KB) with high `grep -c 03E00008` count, it's NOT CPU code — that part of the original claim still holds. (See 2026-05-18 ADDENDUM in that section: the SMALL sub-16 KB "tiny real fn + misID-data tail" variant — realjr/`grep 03E00008` is inflated by the data tail and is NOT a bundle signal unless inter-return words are valid o32. ADDENDUM 18b: no-frame-leaf bundles read as a FALSE single function — use jr-spacing not prologue count. ADDENDUM 18c: `grep 03E00008` UNDER-counts — register-indirect `jr $rN` jump-table dispatch is invisible to it; use `grep -nE '0[0-3][0-9A-F]00008'` on dispatch-heavy code.)_


---

<a id="feedback-game-libs-libultra-ports-vi-fingerprint"></a>
## 1080 game_libs contains IDO-compiled libultra ports — VI register block fingerprint

_2026-06-03. The `gl_func_*` cluster around 0x70B04–0x71000 is the 1080 game_libs port of libultra's VI manager (IDO-compiled, so bytes differ from GCC libreultra, but structure is identical). Recognize and copy the structure from `references/libreultra/`:_

- **`__osViSwapContext`** (verified `gl_func_00070C44`, ~215 insns): fans out stores to the **absolute VI register block** `*(s32*)0xA4400000` (CONTROL) through `0xA4400034` (Y_SCALE), preceded by a `*(s32*)0xA4400010 & 1` (VI_CURRENT field parity) read. Structure: `vc=__osViNext; vm=vc->modep;` compute origin via `osVirtualToPhysical(vc->framep)` (= `gl_func_00062F64`) + `vm->fldRegs[field].origin`, apply state fixups (XSCALE_UPDATED `&2`, YSCALE_UPDATED `&4` with the `y.factor*nomValue` float→u32 saturating convert, BLACK `&0x20`, REPEATLINE `&0x40`, FADE `&0x80`), write all VI regs, then `__osViNext=__osViCurr; __osViCurr=vc; *__osViNext=*__osViCurr` (0x30-byte struct copy). vc struct map: `unk0=state, unk4=framep, unk8=modep, unkC=control, unk20=x.scale, unk24=y.factor(f32), unk28=y.offset, unk2C=y.scale`; `fldRegs[]` stride 0x14 from `vm+0x28` = {origin, yScale, vStart, vBurst, vIntr}; comRegs in vm: `unk8=width, unkC=burst, unk10=vSync, unk14=hSync, unk18=leap, unk1C=hStart, unk20=xScale`.
- **CAP**: `__osViNext` and `__osViCurr` are distinct globals that **reloc-collapse to `&D_00000000`** here (no reloc section in the expected .o to recover names), so the swap tail can't reproduce the two distinct addresses → ~52% ceiling. The body (VI register fan-out + scale math) is otherwise faithful. Siblings: `gl_func_00070B04` (VI init, 0xA4400000/0xA4400010 vblank spin-wait) landed prior.

<a id="feedback-1080-game-libs-small-fn-cap-families"></a>
## 1080 game_libs small-function residue is exhausted-into-caps (recognize-and-skip)

_2026-05-23. After landing the clean small leaves, a size-sorted sweep of the remaining BARE game_libs functions (sizes 0x8–0x40) found they are ALL one of four cap/boundary families. Recognize by shape in seconds; don't re-decode each:_

- **0x8 stolen-prologue fragments with un-disassembled successors.** Two-insn `lui rX, 0; lw/lh/lhu/lwc1/mtc1 rX, OFF(rX)` (a USO global / FP-const load) with **no `jr`**. These are the prologue of the next function, but splat left a GAP after them (the successor at +8 is NOT in any `.s` file — e.g. `00001818`→gap→`00002540`, `00008508`→gap→`000086A0`). Can't merge (no successor to merge into) → needs a **refine-splat / re-extract pass** to disassemble the gap regions, NOT a decomp tick. Examples: `00001818` (1.0f→$f0), `00008508`, `0001FBCC`, `00020A20`, ~28 more at 0x8.
- **Cross-function tail-merge (success path `b`/`bc1fl` past declared end into the next function).** e.g. `game_libs_func_0001FDF4` (bump allocator: align a1 up to 16, bounds-check `a0[0]+a0[2] < a0[1]+sz`, on success bump `a0[1]` and `b 0x40` INTO `0001FE34` which does `v0=v1; a0[3]++; jr`). The shared continuation is a separate symbol with its own `jr ra` → unmatchable from standalone C (can't `goto` into another function; inlining a copy ≠ the branch bytes). Same family as `57194`→`571E4`.
- **Caller-set-reg finalizers.** The continuation symbols themselves (e.g. `0001FE34` starting `move v0, v1` with v1 uninitialized; `00023BC0` = `jr ra; lw v0, OFF(v0)`) take a value in `$v0`/`$v1`/`$t6` that IDO C can't express as a parameter (per the caller-set-int-reg cap).
- **Jump-table dispatchers splat under-sized.** e.g. `timproc_uso_b5_func_000087F4` (`lw t6,0x3C8(a0); addiu -1; sltiu <8; beqz default-past-end; sll 2; lui 0; lw 0x1F4(at); jr t7`). The declared size (0x40) cuts off before the case bodies; the table is reloc'd. Needs boundary fix + table resolve, not a quick match.

**Takeaway:** when source-3 (small-unstarted) rolls and the candidate is bare game_libs ≤0x40, classify it against these four shapes first. None are quick matches. The genuine remaining game_libs %-work is (a) a refine-splat pass on the 0x8-fragment gaps, (b) big-function first-pass wraps (`5721C` FPU, `578B4` 2423-insn), or (c) the permuter on the few structurally-exact reloc-free leaves (e.g. `27504`).

## 1080 kernel segment is NON-USO (real addresses, m2c works) but cap-heavy — mine the real-logic functions only

_2026-05-28. Unlike the raw-word USO segments, the kernel (`src/kernel/*.c`, `func_8000XXXX` at real RAM addrs) has PROPER mnemonic disasm — `m2c` produces clean C and libreultra reference applies. BUT a survey of its 67 bare `INCLUDE_ASM` functions shows it's cap-heavy:_

- **CP0 / TLB runtime** (the majority of small ones): `mtc0`/`mfc0 $12` (Status), `mtc0 $5/$10` (TLB), `tlbwi` — MIPS3 kernel ops not emittable from C (`func_80002DB0`, `func_800062D0`, `func_800099F0`, `func_80002DE0`…). Permanent INCLUDE_ASM cap.
- **Handwritten libultra** with non-C-reachable instructions: `func_80002CD0` = `_bzero` (uses `swl` for the unaligned head; the `.s` is even comment-tagged "Handwritten function - libultra _bzero"). Cap (cf. `reference_libreultra`).
- **Splat fragments** (m2c "Cannot find branch target .L… / Read from unset register"): `func_800031D0/31E0`, `func_80003E54` (reads unset `$t9/$at`), `func_80003FF0/3E0C`. Need boundary fixes, not decode.
- **Real-logic functions** (the only matchable vein): `func_800000B0` (bump allocator — register-renumber near-miss, partial-cracked to 15 diffs via the var-reuse lever), `func_80000D2C` (75-insn table-lookup + list-search, multi-tick), `func_80002250`/`func_80003C24` (~67 insns). These are near-misses (regalloc caps) or large multi-tick decodes.

**Takeaway:** the kernel is readable (m2c) but NOT a quick-match vein — filter out CP0/TLB/handwritten/fragment first; only the real-logic functions are workable, and those are regalloc near-misses or multi-tick. Use `decomp-search` against libreultra for the os*/__os* ones (most are handwritten → stay INCLUDE_ASM).

## 1080 game.uso spine decode status (2026-05-28) — remaining work is multi-tick decode + caps, not tick-safe

_The game.uso "spine" (top-10 biggest functions, per `project_1080_game_uso_map`) is where the call-graph-DFS priority points, but a byte-diff status sweep shows none are tick-safe quick wins — they are large multi-tick decodes whose 100% is regalloc/branch-likely-cap-blocked. Current fuzzy + the binding residual:_

- `game_uso_func_00007424` (1.7KB) — **DONE** (100%, plain C; was the "mostly self-contained algorithm").
- `game_uso_func_000044F4` (4.6KB, entry) — **70.5%**. Frame fixed (0xE8); residual is the missing-`$s2` / args-homed-to-caller-slots / per-iter `s2`-marshalling — whole-function allocno divergence (see `IDO_CODEGEN#feedback-ido-game-uso-entity-ptr-a2-cap`). Cap.
- `game_uso_func_00009B88` (1.4KB) — **55%**. First divergence is a documented branch-likely cap: target emits `addiu v1,sp,0x190; bnezl v1,+6` with the body's a2-reload in the delay-LIKELY slot; the `out=&local; if(out){...}` C produces plain `beqz` (IDO knows &local is non-null). Reorg-pass-driven, not C-reachable; cascades. Plus ~75 insns of further 3D-geometry not yet decoded.
- `game_uso_func_00001DDC` (1.5KB) — **39%**, 122 insns short, divergent from insn 0 (frame 424 vs 384). Substantially-incomplete decode (big rewrite needed).
- `game_uso_func_0000C48C` 8%, `_00008CD8` 3.5%, `_00000B3C` 3.4%, `_00007C1C` 1.5%, `_0000D9CC` 0.27% — **stub wraps** (essentially undecoded; each a 2.8–4.3KB first-pass-decode project).
- `0x5924` in the map is **not a real symbol** (no `.o`/`.s` entry — stale map row).

**Takeaway:** when source-5 (spine) rolls, expect a multi-tick decode, not a 60s match. The count-moving exact matches in this segment are the per-function `-O0`/Yay0 file-splits (REPLACE_FUNC_BODY donor splice, `MATCHING_WORKFLOW#feedback-replace-func-body-o0-donor`) and sustained spine RE — both focused-session work. Tick-safe game_uso matches (trapped promotions, decl-order/dead-spill cracks) were drained by 2026-05-28.

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

**Unrecoverable variant (2026-05-17, game_libs_func_00052674):** the
gl_ref_ recipe needs the absolute address. Some game_libs init
functions are pure `lui rX,0; sw _,off(rX)` runs where the targets are
USO 0-placeholders with **no reloc info in the `.s` AND none in
`expected/.o`** (`objdump -r expected/...o` shows nothing in range).
Diagnostic that it's unrecoverable: multiple **redundant-looking
identical stores** (e.g. `sw zero,0(at)` 3-4× each with its own
`lui at,0`). Clean C never emits redundant identical stores, so these
must be *distinct* USO-runtime-patched data exports whose addresses
exist only in the original loaded image — not in any build artifact.
You cannot assign correct `gl_ref_` addresses by inspection. Keep
INCLUDE_ASM, decode-comment the structure + OR-mask constants
(forensic value), do NOT grind. Only landable if the original ROM's
resolved symbol table is reconstructed (out of scope for CPU-progress
work).

---

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
- **CAVEAT (2026-06-04, func_80009850 = PI raw read, 10 HW-reg accesses): don't switch literal→symbol form chasing the reloc — the symbol form can REGRESS fuzzy%.** Even though `expected/*.o` has the symbol-form encoding, declaring `extern volatile s32 D_A46000xx` and using it directly scored LOWER (45% literal → 36% symbol-direct → 40% symbol-via-`&D`). Cause: IDO may pick gp-relative addressing for the bare global (`lw …,%gprel(D)($gp)`) or materialize the full address (`lui;addiu;lw 0()` — 3 insns) for the `&D` form, neither of which is the target's folded `lui %hi; lw %lo()`. Since both forms link to identical ROM bytes anyway, leave the literal `*(volatile*)0xADDR` form and treat the depressed objdiff% as a reloc-form artifact (re-snapshot `expected` to see the true match, once you trust the linked output). The fuzzy% understates a HW-register function's real correctness by ~1 mismatch per access.

---

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

---

<a id="feedback-rsp-microcode-mistaken-for-code"></a>
## Splat-bundled "function" with 100+ jr-ra-byte patterns is opaque data — but its TYPE (RSP ucode vs GFX DL data vs other) needs forensic check

_When a bundled "function" has anomalous size (50+ KB) with high `grep -c 03E00008` count, it's NOT CPU code — that part of the original claim still holds. The original memo asserted it was RSP microcode; on 2026-05-04 forensic check (see feedback_gfx_dl_data_vs_rsp_ucode_forensic_check.md) showed 1080's specific case is actually GFX display-list data, not RSP microcode. Both are opaque blobs with `jr ra`-byte coincidences, but they need different handling. Always check via opcode-distribution + ucode-ID-string presence before naming the segment._

> **CORRECTION 2026-05-04:** This memo's original conclusion ("it's RSP microcode") was WRONG for 1080's specific blob. Forensic re-check found 234 GFX display-list opcodes (gsSPVertex / gsSP1Triangle / gsSP2Triangles / gsDPTileSync) and zero ucode ID strings — it's display-list data, not microcode. The actual RSP microcodes in 1080 live elsewhere (in `bootup_uso_pre`, ROM 0xDB3FF0+; see GitHub issue #6). The general rule below is still correct (opaque, not CPU text), but the type-attribution needs the forensic check in `feedback_gfx_dl_data_vs_rsp_ucode_forensic_check.md`.

> **ADDENDUM 2026-05-18 — the SMALL "tiny real fn + misID-data tail" variant (sub-16 KB; the size trigger misses it):** the detection checklist below keys on size ≥ 16 KB, but the same hazard occurs in *small* symbols. `gl_func_00031DD8` in `game_libs` is declared only 0xF9C (≈4 KB) yet is **not** one function: the named symbol is a genuine 6-instruction USO-callback trampoline (`addiu sp,-0x18; sw ra; jal 0; nop; lw ra; addiu sp; jr ra`, ends at +0x18), immediately followed by `.word 0` padding (split into a sibling `_pad.s`) and ~990 words of non-o32 data/ucode. Key consequences for the bundle-detection heuristic used in the `/decompile` structural vein:
> - **`grep -c 03E00008` (realjr) is INFLATED by the data tail** — `0x03E00008` occurs coincidentally inside misidentified data/ucode, so a high realjr here is NOT evidence of a multi-function bundle and the count is meaningless. Before trusting realjr>1 as "bundle", confirm the words *between* the returns are valid IDO o32 (a real interior `27BDFF..` prologue, normal load/store/branch opcodes). If they aren't, it's a tiny-fn + data-tail, not an N-fn bundle.
> - **Opcode fingerprints seen here (extend the checklist's list):** `0x0D******` (opcode 0x0D, jalx-form), `0x40**5800` / `0x400*****` (opcode 0x10/COP0 mfc0/mtc0-form), `0x20******` (opcode 0x08 addi-immediate, RSP-shaped), `0x1C80****` (opcode 0x07 branch-likely-style). Any of these in a "function" body ⇒ not IDO CPU text.
> - **Handling in the loop:** decode only the tiny named function, and write a `//`-only STRUCTURAL/BOUNDARY note flagging the tail as a deferred USO boundary re-split + data/ucode reclassification (needs the spimdisasm-USO migration to cut the real boundary and re-tag the tail as `.word` data). Do NOT run split/merge tooling, do NOT C-decode the tail, no episode. Leave any trailing `_pad.s` GLOBAL_ASM line untouched.

> **ADDENDUM 2026-05-18b — the "ONE prologue ⇒ one function" check ALSO fails the other way: no-frame leaf bundles read as a FALSE single function.** The disambiguation rule above ("confirm a real interior `27BDFF..` prologue between the returns; if none, it's not an N-fn bundle") is necessary but the absence of an interior prologue does NOT prove single-function. `gl_func_00034240` (`game_libs`, 0x218) has realjr=7 but exactly ONE `27BDFF` prologue (at the top). It is nonetheless a genuine **multi-function bundle**: a real frame-allocating leading function followed by ~6 tiny **LEAF accessor functions that do not allocate a stack frame** (pure load-and-return — no `addiu $sp`, hence no prologue for `grep 27BDFF` to find). The reliable discriminator is the **`jr`-spacing pattern**, not the prologue count:
> - **Dense, repeated, small inter-`jr` gaps clustered in the tail** (e.g. `03E00008` at +0x0, +0xC, +0xC, +0xC, +0x10 — runs of ~3-word spacing) ⇒ a stack of tiny no-frame leaves ⇒ TRUE multi-fn bundle (decode only the named leader, flag the rest as a deferred USO re-split).
> - **Sparse, irregular, large inter-`jr` gaps** with normal CPU code (loads/stores/branches) between them ⇒ one function with multiple `return` points (decode the whole thing).
> So the full bundle test is: (a) opcodes between returns are valid o32 (else data/ucode tail — addendum a); AND (b) `jr`-spacing is sparse/irregular, not a tight repeating run (else no-frame-leaf bundle). Prologue count alone decides nothing.

> **ADDENDUM 2026-05-18c — `grep -c 03E00008` (realjr) UNDER-counts: register-indirect `jr $rN` (jump-table dispatch) is invisible to it and can be misread as a short/early function boundary.** `grep 03E00008` matches only `jr $ra` (rs=31). A jump-table dispatch emits `jr $rN` for some other N — e.g. `0x01E00008` = `jr $t7`, `0x02000008` = `jr $s0`, etc. (same `…00008` low half, different rs field in bits 25-21). In `gl_func_00040304` (`game_libs`, 0x338) a `01E00008` appears at +0x34, only ~13 words in, immediately after a `sltiu`/`beqz` range-check and an `lw $t7, 0xNNNN($at)` table load — this is the classic IDO switch idiom `idx = op - BASE; if (idx >= N) default; jr table[idx];`, NOT a function return. Consequences for the structural-vein heuristic:
> - realjr=1 (the `grep` count) is correct *for `jr $ra`* but the function still contains an internal `jr $rN`. Do not treat the first `…00008` you eyeball as the boundary — only `03E00008` ends a function; `jr $rN` (N≠31) is an internal computed-goto.
> - Recognise the jump-table prologue: `addiu $r, $op, -BASE` then `sltiu $at, $r, COUNT` then `beqz $at, default` then `sll $r,$r,2` + `lui/addu` + `lw $rT, OFF($at)` + `jr $rT`. The table lives at the `lw` offset (often a `&D_0+0xNNNN` USO-relocated data region — symbolize later).
> - Detection one-liner: `grep -nE '0[0-3][0-9A-F]00008' <f>.s` shows ALL `jr`s; any non-`03E00008` hit inside the declared size is an internal register-jr (switch/tail-call-via-reg), not a boundary. Use this, not bare `grep 03E00008`, when sanity-checking boundaries on dispatch-heavy code.

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

---

## .s file `nonmatching` parser only accepts SINGLE-LINE block comments before the directive

_When adding a doc-comment to an `asm/nonmatchings/<seg>/...func_X.s` file, place a single-line `/* ... */` comment immediately before the `nonmatching FUNC, SIZE` line. Multi-line comments (with the closing `*/` on a separate line) cause the assembler/post-processor to error with `.text block without an initial glabel`._

**Symptom (verified 2026-05-07 on `func_80002CD0`):**

```
Error: .text block without an initial glabel
within asm/nonmatchings/kernel/func_80002CD0.s, at line "/* Handwritten function - libultra _bzero (libreultra src/libc/bzero.s"
```

The error fires because the parser consumes only the first line of the comment as preamble metadata, then sees the next line (`* structural match: ...`) as a non-glabel statement after the empty line that should have started a function.

**Fix:** collapse the comment to a single line:
```asm
/* Handwritten function - libultra _bzero (libreultra bzero.s structural match) */
nonmatching func_80002CD0, 0x9C
```

Don't rely on `*/` line wrapping — the parser is line-oriented. If you have detail that doesn't fit on one line, put the full description in the matching `src/<file>.c` wrap-comment instead and keep the `.s`-side comment minimal.

**Bonus:** `.s` files reject unicode characters (em-dash `—`, smart quotes, etc.) the same way C source does (assembler pipeline uses EUC-JP encoding). Stick to ASCII.

---

<a id="feedback-gui-uso-inline-rdp-dl-builder"></a>
## gui_uso has inline CPU-side RDP display-list builders via a GfxCtx idiom

A `gui_uso` (or any rendering-segment) function that is **no-call,
no-branch**, ends in a single `jr ra`, and is a long run of
arithmetic + paired `sw` stores with `lui $at, 0xFD10 / 0xF510 /
0xE600 / 0xF400 / 0xE700 / 0xF200 / 0x700` constants is NOT opaque
data and NOT a generic leaf — it is a **hand-built RDP display-list
fragment** (the C equivalent of `gDPLoadTextureBlock`-style macro
expansion).

**Recognize the per-packet idiom** (repeats N times):

```
v0 = a0->0xC          ; GfxCtx*  (lw v0,12(a0))
v1 = v0->4            ; write index (Gfx units)
v0->4 = v1 + 1
t  = a0->0xC          ; a0->0xC RELOADED (second lw, distinct reg)
b  = t->0             ; Gfx *buf
slot = b + v1*8       ; 8-byte (2-word) command slot
slot[0] = w0 ; slot[1] = w1
```

So `a0->0xC` points to `struct { Gfx *buf @0x0; int idx @0x4; }`.
Each packet writes one 64-bit RDP command. Top-byte → opcode:
`0xFD`=G_SETTIMG, `0xF5`=G_SETTILE, `0xE6`=G_RDPLOADSYNC,
`0xF4`=G_LOADTILE, `0xE7`=G_RDPPIPESYNC, `0xF2`=G_SETTILESIZE,
`0x07`/`0x00` low-half continuation words. A
SETTIMG→SETTILE→LOADSYNC→LOADTILE→PIPESYNC→SETTILE→SETTILESIZE run is
the canonical texture-load block; args are typically
`texW / texH / fmt+palette`.

**Decomp note:** the `a0->0xC` double-reload per packet (×N) plus
cross-packet CSE of packed constants (e.g. a SETTILE word reused by a
later packet) drives an IDO register-allocation cascade that a
faithful first-pass C transcription does not reproduce (verified
`gui_uso_func_0000413C` 2026-05-17: structurally exact intent, 1%
byte match first attempt). Treat as a **multi-run sub-80 target** —
on the first pass, decode-comment every packet's `(w0,w1)` bit-pack
formula (high forensic value: it documents the exact GBI sequence and
the GfxCtx struct) and keep INCLUDE_ASM. Do not log an episode.

---

<a id="bootup-uso-fp-literal-pool-folded-into-func-0000098C"></a>
## bootup_uso FP literal pool is splat-folded into func_0000098C

_The bootup_uso USO segment has no rodata/literal-pool symbol, so splat
disassembled the FP constant region (vram 0x990–0x9A8) AS code, folding
it into the nearest preceding code symbol `func_0000098C` (real code,
0x4C @ 0x98C). Any `lui %hi(func_0000098C + N); l{w,d}c1 %lo(func_0000098C + N)`
reference is actually an FP constant load, not a read into a function body._

**The 3 mis-attributed constants** (enumerate with
`grep -rho 'func_0000098C + 0x[0-9A-Fa-f]\+' asm/nonmatchings/bootup_uso/`):

| Symbol expr            | Load  | Type | vram   | Used by                       |
|------------------------|-------|------|--------|-------------------------------|
| `func_0000098C + 0x4`  | ldc1  | f64  | 0x990  | func_0000D900, func_0000E2D0  |
| `func_0000098C + 0xC`  | lwc1  | f32  | 0x998  | func_0000E270                 |
| `func_0000098C + 0x14` | ldc1  | f64  | 0x9A0  | func_0000D900                 |

**Confirmation it's data, not code:** func_0000D900 builds the double 0.5
inline right next to one of these loads (`lui $at, 0x3FE00000` →
0x3FE0000000000000 = 0.5), i.e. it's mixing immediate-built doubles with
pool-loaded doubles — an FP-math fingerprint, not control flow.

**Why a typed-extern does NOT fix it:** the bytes at 0x990–0x9A8 are
disassembled as instructions inside `func_0000098C`'s `nonmatching` block,
so there is no symbol to retype. The real fix is a splat-config pass that
declares the bootup_uso literal pool (`.rodata`/`.late_rodata`) and emits
`D_0000098C..D_000009A8` (or breaks func_0000098C's tail), then re-extract.
After that the three callers get proper f32/f64 consts and can byte-match.

**NOT a single-symbol fold (added 2026-05-17):** the same bug recurs at
`func_00000044 + 0xC` (an f32 literal folded into func_00000044, the
f32-reader @ vram 0x44; referenced by func_000003F8 lwc1 @ 0x518/0x534).
So the literal pool is scattered and folded into *multiple* nearest-
preceding code symbols, not one. The fix must enumerate ALL
`grep -rho '+ 0x[0-9A-Fa-f]\+' | sort -u` literal sites across
`func_<any> + N` lwc1/ldc1 refs in bootup_uso and symbolize each — a
broad splat-config/late_rodata pass, reinforcing the deferred rating.

**Not all folds are read-only FP literals (added 2026-05-17):** some
folded sites are *writable globals*. func_00006808 does a read-modify-
write `*(int*)(func_00000000 + 0x4) |= 0x20000` (and a paired exit
mask), and func_00006808 also reads `func_00000188 + 0x3C` as an int
table; func_0000057C is hit at both `+0x34` (func_000063B4) and `+0x38`.
So the fix is not uniformly ".rodata const" — the symbolization pass
must classify each folded site as (a) `.rodata` f32/f64 literal,
(b) mutable `.data`/`.bss` global (needs real storage + a writable
symbol), or (c) a folded table — getting the section/qualifier wrong
will compile but mismatch or corrupt state. Enumerate AND type each
site before re-extracting.

**The f64 pool is a CONTIGUOUS strided table, not scattered singletons
(added 2026-05-17):** func_0000B75C reads `func_000008B4`,
`func_000008D4`, `func_000008F4` — three 0x20-apart symbols — each at
`+0x4 / +0xC / +0x14 / +0x1C` (4 f64 per symbol). That's one packed
`double[]` rodata array that splat chopped into successive 0x20-byte
"function" symbols. So the right fix for the read-only-literal subset
is a SINGLE `D_<base>` double array spanning the run (size = last
folded offset − base), not N per-offset symbols; then the lui/%lo refs
resolve as `D_base[i]`. Confirm the run's extent by listing every
`func_000008?? + N` ref and checking the addresses are contiguous at
8-byte stride before re-extracting.

**splat already symbolizes the pool START — the fix is to suppress the
spurious code symbol, not invent the data symbol (added 2026-05-17):**
func_0000D900 uses BOTH `D_00000988` (a CORRECTLY-emitted f64 rodata
symbol at 0x988) AND `func_0000098C + 0x4` in the same function. So the
pool genuinely starts at 0x988, splat got `D_00000988` right (8 bytes
→ 0x988–0x98F), then emitted a bogus *code* symbol `func_0000098C` at
0x98C that swallows 0x990+ as instructions. The corrective action is
therefore narrower than "add a D_ array from scratch": delete/disable
the spurious `func_0000098C` (and the func_000008B4/D4/F4 etc. bogus
code symbols) in the splat config so the existing rodata region
(anchored by the real `D_0000098?` symbols) extends over the run.
Check the splat yaml/symbol_addrs for an erroneous `func_` entry at
each fold base before hand-authoring data symbols.

**The fold class is NOT bootup_uso-only (added 2026-05-17):** the same
"f64 const folded behind a spurious code symbol" pattern occurs in
game_uso too — e.g. `game_uso_func_0000E1FC` reads `D_00000E68 + 0x208`
as an `ldc1` f64 threshold (D_00000E68 is a USO static-table symbol,
+0x208 lands past it in the literal pool). So the deferred
symbolization pass is per-USO: every relocatable USO segment
(bootup_uso, game_uso, timproc_uso_b5, …) needs its own
enumerate-folded-sites + suppress-spurious-`func_`-symbols + re-extract
pass. Budget the focused session accordingly (it's N segments, not 1).

**Some fold-targets are GENUINELY-COMPLETE functions — do NOT delete them
(added 2026-05-25):** the "suppress the spurious code symbol" fix above
assumes the `func_` at the fold base is bogus (data misdisassembled as
code). That is NOT universal. `func_0001016C` (bootup_uso) loads
`func_00000C10 + {0x0, 0x4, 0x8}` via lwc1 as 3 f32 consts — but
`func_00000C10` is a *real, complete* 0x90-byte function (clean
prologue→jal-loop→epilogue, verified). The reloc points at offset **+0**
(the function's very first word), not past its tail, so this is NOT the
pool-trails-code shape; it looks like a per-section module-offset
collision (a `.rodata` pool at module-offset 0xC10 resolved against the
`.text` symbol at the same numeric offset 0xC10 — USO sections carry
independent module offsets). For this sub-class the corrective action is
the OPPOSITE of the func_0000098C recipe: KEEP the `.text` func_ symbol,
and add/route the reloc to a separate `.rodata` pool symbol. Mechanism
not yet confirmed against the USO reloc table — verify which section the
reloc's symIdx actually targets before acting (offset +0 at a valid
function prologue is the tell that "delete the spurious symbol" is wrong).
**BREAKTHROUGH 2026-05-25 — these pool loads are MATCHABLE NOW, no
symbolization / re-extract needed. func_0001016C LANDED (56/56 byte+reloc
exact, count 1555→1556).** The whole "deferred splat-config pass" framing
above was wrong for MATCHING (it's only needed for semantic cleanliness).
The target's reloc IS against the splat-assigned symbol (here
`func_00000C10`); referencing that symbol directly in C reproduces the
exact `lui $at,%hi(sym+N); lwc1 %lo(sym+N)($at)` bytes + the exact
R_MIPS_HI16/LO16 reloc against `sym` — verified by `objdump -dr` of build
vs expected/.o (NOT the name-blind report). This is the SAME principle as
placeholder calls referencing `func_00000000`: use the symbol splat gave
the reloc, not an invented one. **C shape:** declare the fold-target as a
typed global and use DIRECT FIELD/struct access (which folds the +offset
into `%lo(sym+N)($at)`); a `(char*)&sym + N` cast or `sym_arr[i]`
indexing does NOT fold at -O0 (materializes the base in a reg first):
```c
extern struct { float f0, f1, f2; } func_00000C10;   /* the fold-target */
q[0] = func_00000C10.f0;  /* -> lwc1 %lo(func_00000C10+0)($at) */
q[1] = func_00000C10.f1;  /* -> lwc1 %lo(func_00000C10+4)($at) */
```
Declaring the .text function symbol as a float struct is type-punning but
harmless (the linker is type-agnostic; the reloc resolves to the same
module address the target uses). For f64 pools use `double` fields; for
mixed/`+0x4` strided pools (the func_0000098C / func_000008?? families)
size the struct to the exact offsets.

**CAVEAT — the fold needs the struct DECLARED, which collides if the
fold-target is a function defined in the SAME .c (2026-05-25):** the
struct-field fold ONLY works when you can write `extern struct{...} sym;`.
If `sym` is a real function defined in the current TU (e.g. func_0000098C
is defined at bootup_uso.c:264), you CANNOT also declare it a struct
(type clash), and the pointer-cast fallback `*(float*)((char*)&sym+N)`
does NOT fold even at -O2 (it materializes `&sym` into a $t reg, +4 insns,
wrong shape — verified on func_0000E270). func_0001016C worked because its
target func_00000C10 is NOT defined in o0_100F0.c. So the 0x990-pool trio
(func_0000E270/D900/E2D0, all in bootup_uso.c WITH func_0000098C) need a
**file-split** first — move them to a new .c where func_0000098C is just
`extern struct{...}` — before the fold applies. func_00010C8C lives in
tail3a.c (func_00000C10 NOT defined there → no clash) so its pool load is
fold-able in place, but it's separately -g3-capped. The float-3rd-arg
passing (target `mfc1 $a2,$f0`, one move not a K&R double-promote pair)
is fixable WITHOUT a split via a fn-ptr cast:
`((void(*)(void*,void*,float))func_00000000)(a,b,ratio)`. Net: the
technique is real and landed one match; the rest are file-split-gated, not
deferred-symbolization-gated.

**Status:** multi-file re-extraction = high blast radius (and 1080 has the
known preexisting tenshoe.z64 0x550 ROM-tail mismatch, so a full-ROM diff
won't be clean — verify per-function via linked ELF/objdiff). DEFERRED to a
focused non-/loop session; do not attempt under a 60s tick. Concrete
recipe captured here so the future session starts from the answer, not the
question.

**Origin:** 2026-05-17, 1080 bootup_uso, while triaging the func_0000E270
NM wrap (size-1 vein exhausted; this was the highest-value real %-mover lead).

## game_libs hardcoded RUNTIME DATA addresses (data analog of the jal thunks) (2026-06-10)

Besides build-time-patched jals (gl_ref_NNNNN fixed-address call symbols,
e.g. 0x87BA4 = USO fn + reloc base 0x1466C), game_libs also embeds
hardcoded runtime DATA addresses as plain lui/addiu immediates with NO
relocs — e.g. gl_func_00074EFC builds its message queue/records/thread/
stack at absolute 0x44080/0x45230/0x45248/0x45260/0x45278 (bootup-region
block). These look like small absolute constants in the disasm (lui
a0,0x4; addiu a0,21040). To match such functions, define fixed-address
data symbols (proposed naming: gl_dref_00045230 = 0x00045230; in
undefined_syms_auto.txt) and reference them as extern objects — same
mechanism as gl_ref jal thunks. Functions mixing these with reloc'd
globals (zeroed lui/lw pairs) need BOTH symbol kinds.

Addendum (2026-06-10, gl_func_00074EFC): the lui-pair SECOND instruction
discriminates the source construct -- `addiu` = symbol+%lo reloc (use a
gl_dref extern), `ori` = literal integer constant cast to pointer. If the
target shows lui X/addiu X, a `(char *)0x45230`-style literal in C is
WRONG (emits ori) -- reference an extern symbol and set its address in
undefined_syms_auto.txt instead. Also: hardcoded thread-entry addresses
decode like jal thunks (0x896E8 - 0x1466C = USO 0x7507C), identifying
callee functions for free.
