# Ido Codegen

> **Note (2026-05-23):** any entry below that recommends INSN_PATCH /
> NON_MATCHING_INSN_PATCH / PROLOGUE_STEALS / instruction-appending SUFFIX_BYTES
> as the fix is **OBSOLETE** — that post-cc instruction-patching was removed as
> match-faking. The IDO codegen *facts* (what C shape emits what asm) are still
> valid and useful; just stop at "here's the C shape that produces it." If no C
> shape matches, the function stays NON_MATCHING. See
> `memory/feedback_no_instruction_forcing_matches_policy.md`.

> IDO 7.1 codegen quirks: how the compiler emits specific patterns, and what C-source shapes do or don't match a given asm.

_121 entries. Auto-generated from per-memo notes; content may be rough on first pass — light editing welcome._

## Quick reference by sub-topic

### branch likely / bnel

- [Isolated-compile vs full-TU IDO -O2 codegen can DIVERGE for the same function — verify decodes against the full `make` build, never an isolated cc](#feedback-isolated-vs-full-tu-o2-divergence) — _A function body can compile to the exact target shape (12 insns, plain beq/bne, nop delays) when cc'd IN ISOLATION with the exact project flags, yet the full-TU `make` build of the same source (asm-processor phase-1 output verified identical) produces a different, worse shape (17 insns, beql/bnel, loop rotation) at the SAME -O2. IDO's optimizer is TU-context-dependent. Implication: a "proven-correct in isolation" decode can still be sub-80 in the real build — that's NOT a logic error, don't re-derive; it's permuter / TU-robust-form territory. Always measure against the build .o. Verified 2026-05-16 game_libs_func_0003D9E4._
- [Same-base multi-deref: intervening `jal` forces natural reload (exact-able) vs no-call → IDO CSEs base (reload-CSE cap)](#feedback-intervening-call-forces-reload-vs-cse-cap) — _Triage which small fresh/split funcs to push to byte-exact: a `jal` between two same-base derefs forces the reload that matches the target (verified timproc_uso_b3_func_00001184 byte-exact land); no call → IDO CSEs, N-short reload-CSE cap (120C/11D4/EE84/DDC0 family), no C form defeats it. Exact-able case must be unconditional C, not #else INCLUDE_ASM (tautology)._
- [Branch-likely opcode cheat sheet — decode raw `.word` correctly before drafting C control flow](#feedback-mips-branch-likely-opcode-cheatsheet) — Top 6 bits of the instruction (`(word >> 26) & 0x3F`): `0x14` = `beql`, `0x15` = `bnel`, `0x16` = `blezl`, `0x17` = `bgtzl`. In the high byte, that's `0x50–0x53` = `beql` (rs varies the low 2 bits), `0x54–0x57` = `bnel`, `0x58–0x5B` = `blezl`, `0x5C–0x5F` = `bgtzl`. So `5320000B` IS `beql $t9, $zero, +0xB` — branch on EQUAL, not `bnezl`. Misreading silently inverts the C if-condition direction; the body compiles fine but byte-matches drop dramatically.
- [IDO emits the if-body's first store TWICE around a beql — once in delay slot (annulled on taken) + once at fall-through](#feedback-ido-beql-speculative-store-double-emit) — _For `if (cond) { dst = val; ... }` IDO -O2 emits `beql cond_reg, $0, end; sw val, dst_off(dst_reg)` in the delay slot AND ALSO `sw val, dst_off(dst_reg)` at the fall-through.
- [Asm `blez/blezl` vs `bne/beql` distinguishes `> 0` (signed) from `!= 0` (eq) source](#feedback-ido-blez-vs-bne-signed-compare) — When target asm uses `blez $rs, X` or `blezl $rs, X` for a conditional, the C source MUST be `if (val > 0)` (signed comparison), NOT `if (val != 0)`.
- [IDO `bnel` with value-in-delay-likely comes from C with the EQUAL case in the `if` arm](#feedback-ido-bnel-arm-swap) — When the target asm has `bnel $a, $b, .exit; or v0, zero, zero` (branch-likely with "set 0" in delay-likely) and the other path sets v0=1 via `b + addiu v0, zero, 1`, write the C with the `==` case inside the `if`, not…
- [bnel-likely with shared store-in-delay = `if (!cond) helper(); shared_store;`](#feedback-ido-bnel-shared-store-after-helper) — When asm shows `bnel ptr,zero,+N; sw <val>,off(reg) [delay-likely]; jal helper; ...; sw <val>,off(reg)` (same store on both paths), the C source is `if (cond == 0) helper(); store;` — the store happens both as…
- [IDO bnel tail-merging routes the false-path epilogue through the true-path's register-restore tail (cosmetic, ~99 % cap)](#feedback-ido-bnel-tail-merge-register-restore) — When the function body is `if (cond) { several jal calls }` and the true path ends with reload-args-then-jal patterns like `lw a0,0x18(sp); jal; lw a1,0x1C(sp)`, IDO sets the bnel branch target to the MIDDLE of those…
- [For float-predicate functions with conditional body, prefer positive-arm form to avoid branch-likely](#feedback-ido-branch-likely-arm-choice) — `if (!cond) return 0; body; return 1;` triggers IDO to emit `bc1tl`/`bnezl` (branch-likely).
- [Used incoming arg ALSO dead-spilled to its outgoing-shadow (`sw aN,off(sp)` in the jal delay) — CRACK with `int *p = &aN; ...(*p)`](#feedback-ido-used-arg-dead-home) — _A function that passes param `aN` to its first call can have a dead `sw aN,off(sp)` (to aN's shadow slot) in that jal's delay slot; plain -O2 C puts a `nop` → 1 insn short (~94-96%). **CRACK: take the parameter's address** — `int *p = &aN; ... use *p` forces the home. (permuter-found 2026-05-24, gl_func_0006A5B0 96→100.) `(void)aN;` is DCE'd when aN is used (unused-args only); `-g` adds a frame. Use do-while (not while) for if+spin-loops. RE-GRIND any single-`sw aN`-residual NM-wrap with `&param` (incl. the prologue-less variant game_libs_func_0002BA08)._
- [Circular-list do-while walk emits BOTH branch-likelies naturally (conditional-skip `bnel` + loop-back `bnezl`) — don't fear bnel here, write the obvious do-while](#feedback-ido-circular-list-do-while-natural-bnel) — _A circular-list iteration `node=head; if(node){ do { if(key==node->K) call(self,node); node=node->NEXT; if(node==head) node=0; } while(node!=0); }` compiles BYTE-EXACT including the two target branch-likelies: the `if(key==node->K) call(...)` skip becomes `bnel key,t,skip` (the `node=node->NEXT` advance fills the annulled delay), and the `while(node!=0)` loop becomes `bnezl node,loop` (the next iter's first load fills the delay). No coaxing — the obvious do-while IS the match. Loop state (self/key/node) lands in s0-s2 across the call. Verified 2026-05-24 gl_func_00060ED0 (29/29 first try) and gl_func_0005B568 (sibling, single bnel-free variant). Counter to the usual "bnel is hard" instinct._
- [IDO -O2 emits branch-likely for empty-body do-while loops; move call into the body to get plain branch + nop delay](#feedback-ido-empty-body-do-while-emits-branch-likely) — _`do { } while (func() & MASK)` (empty body, call in condition) compiles to beqzl/bnezl (branch-likely) with the call's lui hoisted into the annulled delay slot.
- [Counter-loop tail with reloaded loop-header pointer: IDO prefers `bnezl` + delay-slot-hoist of next-iter `lw` over target's `bne` + addiu-in-delay — counter-loop "addiu wins the delay" variant is unreachable from C when a hoistable load exists](#feedback-ido-counter-loop-vs-load-hoist-tail) — _Target `do { items=v0->[K]; i++; ...; v0=a0->[J]; n=v0->[L]; off+=0xC; } while ((u32)i < n)` emits `sltu/bne/addiu-in-delay`. The "obvious" do-while form (verified across 6 variants: vanilla, goto+label, for-loop, broader-scope, narrower-scope, separate-decl) emits `sltu/bnezl/lw-in-delay` — IDO chooses the hoistable next-iter loop-header `lw $X, off($vN)` as more valuable than the increment for delay-slot fill (latency hiding). The choice is cost-model driven and not flippable by C restructuring — distinct from `feedback-ido-circular-list-do-while-natural-bnel` (which is for list-walk-emit; this is counter-emit on a reloaded-base). Standalone-cc caps at ~71% on this shape. Path forward = permuter. Verified 2026-05-27 game_libs_func_0003C7A4 (28-insn loop body)._
- [Annulled `bnel`/`beql` needs test-reg ≠ delay-load-base-reg — the enabler is IDO double-reloading a spilled pointer param into two regs; single reload (test==base) forces plain `bne`](#feedback-ido-branch-likely-needs-distinct-test-and-delay-base-regs) — _When target has `lw t8,off(sp); lw t9,off(sp); bnel t8,zero,L; lw t1,0(t9)` (same spilled param reloaded into TWO regs — t8 tests, t9 is the delay-slot load base), GCC reorg can annul-fill only because the branch-test reg ≠ the delay load's base reg. C that reloads the param once (test and deref share one reg) makes reorg emit a plain `bne` + no annul → exactly 1 insn short. The double-reload is an IDO regalloc/reorg artifact, NOT reachable by C restructuring (verified ineffective: EQUAL-in-if arm-swap, pointer-local CSE). Path forward is permuter or force-SAME-LEN-then-INSN_PATCH the bne→bnel. Verified 2026-05-16 gl_func_0003D7F8._
- [Multi-case literal-dispatch bnel chain (sparse `if (c == X) c = Y` ladder) needs "modify-c-in-place + single masked return" + separate `int v` for the compare source](#feedback-ido-bnel-dispatch-modify-c-mask-return) — _`int v; c &= 0xFF; v = c; if (v == X1) c = Y1; else if (v == X2) c = Y2; ...; return c & 0xFF;` produces the bnel-chain pattern with `bne+move v0,a0` first compare and per-case `addiu a0; jr ra; andi v0,a0,0xFF` hit-handlers (matches USO entry-glyph dispatchers). Per-case `return CONST` form emits a shorter 4-insn-per-case chain without the `or v0,a0,$0` default-save. Cap ~95 % via the chain-source-register picker (a0 alias vs target's v0)._
- [IDO -O2 sparse-case switch (case 0 + case 1) compiles to 3-arm beql dispatch with delay-slot pre-loads — unreachable from C if-else; switch is also rejected (.rodata jumptable)](#feedback-ido-sparse-switch-beql-preload-unreachable) — _When target asm shows `addiu $at,zero,1; beql v0,zero,caseA; <lw delay>; beql v0,$at,caseB; <lw delay>; b end; <lw ra delay>` (3-arm beql dispatch with each delay slot pre-loading the case body's first lw), this is a…
- [bc1fl with target=epilogue and `lw ra,X(sp)` in delay slot is a CONDITIONAL-CALL marker, not a clamp — the if-block guards a `jal` between here and the epilogue](#feedback-ido-bc1fl-skips-jal-to-epilogue) — _Diagnostic for misreading IDO -O2 trailing FP conditionals: when target's last bc1fl jumps to the epilogue with `lw ra,X(sp)` in the delay slot, it's NOT a clamp/store guard; it's `if (!cond) jal()` where the jal sits between the bc1fl and the epilogue. Decode the C as `if (cond_complement) func();`._

### FPU / float specifics

- [FP read-modify-write: use compound `dst *= src` NOT expanded `dst = dst * src` — the expanded form swaps the operand load order ($f-reg diffs)](#feedback-ido-fp-compound-assign-load-order) — _For `dst OP= src` on floats (matrix/vector scale etc.), the compound assignment loads `dst` into the low $f-reg FIRST (matching IDO's target order); the expanded `dst = dst * src` loads `src` first → every `lwc1` base swaps (arg0↔arg1) and the whole function shows ~half its insns as $f-reg/load-order diffs even though it's byte-count-exact. Verified 2026-05-24 game_libs_func_0005E8B0 (9× mul.s matrix scale): expanded = 18 diffs, `*=` = byte-exact. Cracks the FP-interplay load-order residual for the RMW subclass._

- [IDO -O2 folds `/const` float-divide to `*reciprocal` (mul.s) — but a NAMED-LOCAL divisor flips it back to `div.s`; also -mips2 schedules across mtc1 load-delays](#feedback-ido-div-2-mul-fold-and-mtc1-load-delay-nops) — _`x / 1024.0f` (literal) compiles to `lui 0x3A80; mul.s` (reciprocal); `float d=1024.0f; x/d` compiles to `lui 0x4480; div.s` (target form). Verified gl_func_0005B764 2026-05-24 — supersedes the old "no lever" claim. (1) `expr / 2.0f` compiles to `mul.s ..., 0.5f` instead of `div.s ..., 2.0f`._
- [IDO -O2 emits double return into $f0+$f1 pair, not $f0+$f2 — kills "force $f2 via double-trick" theory](#feedback-ido-double-return-uses-f0-f1-not-f2) — For `double f(void){return 0;}`, IDO -O2 emits `mtc1 zero,$f1; mtc1 zero,$f0; jr ra; nop` — upper-half lands in $f1 (o32 paired-register convention), NOT $f2.
- [Function reads $f0 at entry without setting it — caller-context "implicit zero" pattern](#feedback-ido-f0-implicit-zero-at-entry) — Some IDO -O2 functions store $f0 (float return reg, NOT a standard arg) to memory at the start of the body.
- [IDO -O2 always folds `return 0.0f` paths through $f0 directly — `mtc1 $0, $f2; mov.s $f0, $f2` unreachable from C](#feedback-ido-f2-intermediate-unreproducible) — Target 4-insn leaves that return 0.0f via an intermediate ($fN != $f0) like `mtc1 $0,$f2; nop; jr $ra; mov.s $f0,$f2` cannot be reproduced from any tested IDO-O2 C body — literal, local var, volatile local (→stack…
- [IDO's fabs idiom leaves an unreachable `mov.s` at the merge point — branch-likely artifact unmatchable from C](#feedback-ido-fabs-dead-mov) — _IDO emits fabs as `bc1fl fall_taken; mov.s fDst, fSrc (taken=positive); b merge; neg.s fDst, fSrc (delay-always=negative); mov.s fDst, fSrc (fallthrough, unreachable); merge:`.
- [Commutative FP op operand order (`mul.s`/`add.s` fs vs ft) IS flippable via an assignment-expression: `coord * (tmp = scale)` forces `scale` as fs](#feedback-ido-fp-commutative-operand-order-assignment-lever) — _For `A * B` IDO -O2 does NOT reliably emit source-left as fs; after a fresh coord load it uses coord-as-fs even for `scale * coord`. Force the scale as fs via `coord * (tmp = scale)` (assignment-expr pins it into a reg at the op); on a neg, `coord * (tmp = -x)` also lands the target's result reg. Cracked the documented `game_uso_func_00003FAC` "genuine cap" (99.245% → byte-exact, 5 diffs closed). Found via permuter `X*(var=Y)` mutation, then minimized. Supersedes the "final-add operand order can't flip" cap — try this before NM-wrapping any pure-operand-order FP near-miss; re-grind game_uso_func_000000A0. **2026-05-29: GENERALIZES to integer commutative ops (`or`/`and`/`xor`/`addu`)** — `value | (t = const)` forces the const as `rs` where source-swap and named-local both fail; cracked timproc_uso_b{3_00002700,1_000024F4} (8 `or` diffs each, CSE keeps the single lui). **ALSO GENERALIZES to DOUBLE precision** — `(double)D + (t = (double)f)` with `double t` pins the cvt.d.s result distinct from the ldc1 load, fixing `$f4↔$f6` cross-allocation on `add.d`. Cracked `game_libs_func_000086A0` (documented "FP allocator choice, not C-reachable" cap → byte-exact). **ALSO cracks `call() * cast` patterns** — `(cast) * (t = call())` pins the call return as `fs`. Cracked `gl_func_00052104`/`gl_func_000520B8` (both documented "permuter-resistant" caps → byte-exact). The lever is broadly effective; treat documented "operand-canonicalization" / "FP allocator choice" / "permuter-resistant" FP-operand-order caps as RE-CHECK candidates, not permanent._
- [IDO -O2 final-add operand order in FPU reductions (`add.s fd, fs, ft`) follows source evaluation; can't easily flip without changing load order](#feedback-ido-fpu-reduction-operand-order) — _For dot products and chained FPU adds like `a[0]*b[0] + a[1]*b[1] + ... + a[n]*b[n]`, IDO emits the final reduction `add.s fd, fs, ft` with `fs` = running-sum register and `ft` = last-product register.
- [IDO-unrolled loop residual trip-counter representation (count-groups vs count-elements) is NOT C-controllable](#feedback-ido-unroll-trip-counter-representation) — _When IDO auto-unrolls a simple `for(i=0;i<N;i++)` body by K, the body emits byte-identical but the residual pure trip-counter may count elements (`0,K,2K..<N`, `+K`) or groups (`0..N/K`, `+1`). If target chose the other representation it's a 2-insn cap (the bound + the increment immediates); element-loop, manual grouped-unroll `i<N/K`+ptr, and `i*K+k` indexing ALL emit IDO's same scaled counter. Verified-fail `game_libs_func_0005BDC0` (16-elem 1/x loop, 4x-unrolled)._
- [Inline a cached load-deref local into the loop body to drop its stack slot and shrink the frame (sibling of inline-everything for GPR-renumber)](#feedback-ido-inline-cached-local-for-frame-shrink) — _When a near-miss has a too-large frame by an aligned slot's worth (+8 typical) AND a cached `T x = *load_chain(...)` local used only inside a single loop, inlining the load chain at each loop use removes the local's slot. Frame shrinks; spill offsets for OTHER live values align down to the target. Different from inline-everything (which targets GPR-renumber by forcing fresh-temp reloads); this one targets frame-size. Verified `titproc_uso_func_00000418` 6→2 diffs (frame 40→32, spill 28→24) by inlining `unsigned short mask = **(unsigned short**)(...)` from a local into the loop body's `if` condition._
- [Block-scope a re-assigned cached local to drop its `$s` save and shrink the frame (sibling of inline-cached-local)](#feedback-ido-block-scope-cached-local-for-frame-shrink) — _A cached local re-assigned mid-function (e.g. `int *root = ...; ...; root = ...;` for the same expression between two segments) gets promoted to a callee-saved `$s` register because IDO sees one long-lived variable. The save+restore costs +8 frame bytes vs target. Wrap each segment in `{ int *root = ...; ... }` so each scope's `root` is a fresh local — IDO uses a temp ($3-class) instead of $s, the save/restore disappear, and the frame shrinks by 8. Verified `h2hproc_uso_func_00000E04` 38→37 diffs (frame -56 → -48 matching target; insn count fixed)._
- [K&R-declared extern can't be called with float args under IDO (no way to get direct jal)](#feedback-ido-knr-float-call) — _In game_libs (1080), `gl_func_00000000` is declared as `extern int gl_func_00000000();` (K&R / no prototype).
- [Target asm with `mfc1 $aN, $f12` (float-bits-to-int-reg) is hard to reproduce from IDO C](#feedback-ido-mfc1-from-c) — When the target has a single `mfc1 aN, $f12` instruction converting a float arg's bits to an int register for passing as arg, IDO's C compiler emits a stack round-trip (swc1 + lw) instead — at least 14 C variants tried…
- [A SINGLE named float local in tight FPU code globally restructures IDO's entire FPU schedule — not just the immediate computation](#feedback-ido-named-float-local-globally-shifts-fpu-schedule) — _In tightly-scheduled FPU code (dot products, vector reductions), introducing ANY named `float` local — even just to name an intermediate sum — shifts IDO's FPU register allocation and instruction order across the WHOLE…
- [IDO -O2 needs named float locals to load-batch all loads before stores; inlined float derefs interleave load/store](#feedback-ido-named-float-locals-enable-load-batching) — When asm shows `lwc1 f14; lwc1 f12; lwc1 f2; lwc1 f0; swc1 f14; swc1 f12; swc1 f2; swc1 f0` (4 loads then 4 stores), the C source MUST have 4 named float locals.
- [Inline a re-used base expression (don't name it) to force a fresh reload per access; a named local CSEs to one load](#feedback-ido-inline-base-forces-reload-per-access) — _When the target reloads the same base each time it's used inside a loop (e.g. two `lw base,0(a0)` per iteration before two different accesses through it), do NOT cache it in a named local — IDO will CSE that to a single load (N insns short). Write the base expression inline at each use site: `*(T*)((char*)a0[0] + off)` repeated, not `b = (char*)a0[0]; ... b+off ... b+off+4`. The inline form reloads the base for each access, matching. (Inverse of the named-float-locals load-batching rule.) Verified 2026-05-23 game_libs_func_00060CB8 (per-entry array reset: named base → 18/20, inline a0[0] twice → 20/20 byte-exact)._
- [Force a SECOND zero FP reg (defeat the 0.0f CSE): store INT `0` through a `float*` variable](#feedback-ido-int-zero-through-float-ptr-forces-second-zero-reg) — _When the target materializes two zero FP regs (e.g. `mtc1 zero,$f0` for most float stores + `mtc1 zero,$f4` for one hoisted into a `jr` delay slot), plain `0.0f` everywhere CSEs to ONE reg (1 insn short), and `float z=0.0f` CSEs too. For the store needing the distinct reg, assign through a `float*` variable and store INT `0` (not `0.0f`): `float *p = ...; *p = 0;` — the int-0→float conversion doesn't CSE with the `0.0f` constant, forcing the 2nd `mtc1`. Cracked timproc_uso_b5_func_00003890 (7/8 → byte-exact, permuter-found). Disproved its "0.0f CSE not C-controllable" cap._
- [Float-const register choice ($f0 vs $f2) follows C SOURCE order of the constants' first use, not asm store order — reorder to flip](#feedback-ido-float-const-reg-by-source-order) — _A multi-const float-init (e.g. identity matrix: 1.0f on the diagonal, 0.0f elsewhere) where the target puts one constant in $f0 and the other in $f2. IDO assigns $f0 to whichever constant's stores appear FIRST in C source, then reorders the actual stores during scheduling. So if the target has 1.0f in $f0 but stores 0.0f first in asm, write the 1.0f stores first in C — IDO still emits the 0.0f stores first but keeps 1.0f in $f0. Flips the "float-register-swap (f0 vs f2)" cap. Verified 2026-05-23 game_libs_func_0005E83C (3x4 identity init, 14/16 → byte-exact)._
- [Float→narrow-int store: cast through `(int)` for `trunc.w.s`, NEVER directly to `(char)`/`(short)` (which pulls the soft-float-to-int range-check helper)](#feedback-ido-float-to-int-cast-via-int-not-char) — _For `byte = (T)(f * k)` where T is char/short, `(char)(float)` or `(short)(float)` emits a giant inlined float→int conversion routine (range checks + helper, ~100 insns). The target is just `mul.s; trunc.w.s; mfc1; sb`. Write `(int)(f*k)` and assign to the narrow lvalue — the (int) maps directly to `trunc.w.s`, the store narrows. Verified 2026-05-23 game_libs_func_00047AD8 (Vec3→3 bytes ×127.0f): (char) cast → 111 insns, (int) cast → 20-insn byte-exact._
- [O32 passes floats in $aN when preceded by a non-float arg — use `mtc1 aN, fM` reconstruction](#feedback-ido-o32-float-in-int-reg) — _When a function signature is `(int_like, float, ...)`, MIPS O32 passes the float in $a1 (the int register), not $f14. **TRAP (verified 2026-05-27 gl_func_0005E664)**: do NOT write the body with `int a1_bits` arg + `float scale = *(float*)&a1_bits;` — taking address of an int arg forces a stack home spill + `lwc1` reload per iteration, regressing 45-insn target to 62 insns. The correct form is `void f(T *p, float scale, ...)` — IDO emits the natural `mtc1 a1, $f12` at entry, $f12 persists across the body. Sig-type-fix lever = byte-exact match on this family._
- [o32 mixed-mode ABI — when first arg is int, a float second-arg passes in $a1 (int reg) not $f14, triggering `mtc1 $a1, $f12` at function entry](#feedback-ido-o32-mixed-mode-float-in-a1) — _o32 reserves $f12/$f14 for floats only when ALL leading args are floats.
- [IDO target `swc1 $f0, N(sp)` x4 at entry WITHOUT preceding `mtc1 $0, $f0` — $f0 inherited from caller](#feedback-ido-swc1-f0-without-mtc1) — Some functions store $f0 to multiple stack slots at entry (e.g. `swc1 $f0, 0x34..0x40(sp)` for a 4-float out-buffer) without any `mtc1 $0, $f0` to initialize $f0 first.

### argument / save register

- [Register-allocation-renumber caps: the matching toolkit (IDO color order, GVN/dedup, live-range split, permuter PERM_ passes, and the `-zdbug` dump — blocked by an `ecvt` stub)](#feedback-ido-regalloc-renumber-matching-techniques) — _When logic + instruction COUNT match but a value lands in the wrong register (cascading: const in `$a2` vs `$v1`, ptr in `$a3` vs `$t7`, FP `$f4` vs `$f18`). NOT operand-order. IDO colors in fixed order `$v0,$v1,$a0..$a3,$t0..` by first-USE/expression-list position + Chow–Hennessy priority. Levers: reorder first-use (not decls); duplicate/CSE-fold a subexpr to shift the cascade; split live ranges around calls (`a=b; a+=c`); drive permuter `perm_pad_var_decl`/`perm_refer_to_var`/`perm_duplicate_assignment` MANUALLY via PERM_ macros (random mode floors). SYSTEMATIC DIAGNOSTIC: `cc -Wo,-zdbug:6` dumps IDO's UCODE expr-list + regalloc coloring to a file **`uoptlist`** in the CWD (NOT stdout) — **UNLOCKED 2026-05-29** by implementing `wrapper_ecvt`/`wrapper_fcvt` in tools/ido-static-recomp/libc_impl.c (was an `assert(0)` stub that crashed the dump; codegen-verified-safe). The `N: N assigned (unconstrained) R` lines show candidate→register order. Researched from OoT/sm64/mm IDO guides + permuter, 2026-05-29._
- [**Pass an adjacent int pair AS A STRUCT BY VALUE to reproduce outgoing-arg home-stores (`sw a1,4(sp); sw a2,8(sp)`) — DISPROVES the "precall-arg-spill cap"**](#feedback-ido-struct-by-value-homes-arg-pair) — _When the target stores outgoing register args to their home slots right around a `jal` — `lw a1,0(p); sw a1,4(sp); lw a2,4(p); jal; sw a2,8(sp)` — and your C `f(x, p[0], p[1], k)` does NOT emit the `sw a1,4(sp)/sw a2,8(sp)` stores, the fix is to pass the adjacent pair as a 2-int STRUCT BY VALUE: `typedef struct {int a,b;} Pair2; f(x, *(Pair2*)p, k);`. IDO places the struct's two ints in a1,a2 AND homes them to the caller's outgoing-arg slots (sp+4, sp+8), exactly matching the target. Verified empirically: K&R/`(int,...)`/`(int,int,...)`/`(int,int,int,...)`/`(int,int,int,int)` prototypes and register/pointer/global-addr arg sources ALL fail to home the args; only struct-by-value does it. The old `feedback_ido_precall_arg_spill_unreachable` "cap" was WRONG. Verified 2026-05-28 on game_uso_func_00011168: 61.2% → 93.92% (instruction count 46→60 to match target; residual ~6% is an unrelated $v0/$v1 &D-base renumber). Recheck every NM wrap labeled "precall-arg-spill"/"vararg-spill cap" (game_uso_func_0000A374/0000FF48/0000FFB8/00010BAC/0000D5F8, etc.) — many pass adjacent int pairs and should now match or near-match._
- [**Declare a byte arg as `unsigned char` to reproduce BOTH its `sw aN` home AND its `andi 0xFF` zero-extend — but the eager extension flips s-reg order vs a later int arg**](#feedback-ido-unsigned-char-param-homes-and-extends) — _When the target both homes an incoming int-register arg (`sw a2,64(sp)`) AND zero-extends it once before use (`andi sX,a2,0xff`, hoisted out of a loop), the arg is an `unsigned char` parameter. Declaring it `int` + masking `a2 & 0xFF` gets the andi but NO home (the home only appears with the char type). The `unsigned char` declaration produces the home + the eager prologue zero-extend together — the cleanest way to match a dead-arg-home that coexists with a byte mask. CAVEAT (verified 2026-05-29 gl_func_0000A7B4): the char extension is EAGER at the prologue, so the extended pseudos are born before a sibling `int` arg's loop-invariant copy and grab the LOWER $s-regs — leaving the int arg (e.g. a1) in a higher $s than the target wants. So char-arg homing and "int-arg-first allocno order" are mutually exclusive; a function needing both lands as a clean cyclic $s-reg renumber (size + control flow + homes all exact). NM-wrap that residual._
- [IDO target's 3-save reg pattern (copy to free reg + stack spill + stack reload) for arg preservation isn't reachable from natural C](#feedback-ido-3save-vs-2save-arg-preserve) — _When target asm preserves an arg ($a0) across a jal via THREE moves — `or $aN_free, $a0, $zero` (copy to a free arg-reg) + `sw $aN_free, off(sp)` (spill the copy) + `lw $aN_free, off(sp)` (reload after call) — IDO -O2…
- [IDO bnel + delay-likely-move + fall-through alloc = "out = ptr ? ptr : alloc(N)" ternary](#feedback-ido-alloc-or-passthrough-ternary) — USO functions emit a 4-insn `bnel ptr,$0,+6 / move v1,ptr [delay-likely] / jal alloc / addiu a0,$0,N` pattern for the conditional-alloc ternary.
- [Pre-assign default + conditional-overwrite for data-mux ternary: `p = a0; if (cond) p = buf;`](#feedback-ido-preassign-conditional-overwrite-ternary) — _When target asm shows a register being loaded from caller-spill in a `beq cond, $0, .skip; lw r, OFF(sp)` delay-slot fill, then ONLY OVERWRITTEN on fall-through via `addiu r, sp, BUF_OFF`, the matching C idiom is `p = a0; if (cond) p = buf;` — pre-assign the default, conditional-overwrite. NOT a ternary `p = cond ? buf : a0;` (which IDO emits differently with separate branch around the assignment) and NOT an explicit if/else (which doesn't schedule the default-load into the delay slot). Verified 2026-05-15 on `gl_func_0005FFD0`: 33.7% → 73.5% (+39.8pp) via this rewrite._
- [Reuse the PARAMETER as the object (not a fresh local) → IDO arg-saves to the caller slot (small frame) instead of an in-frame spill slot (+8 frame)](#feedback-ido-reuse-param-as-object-caller-slot-spill) — _In an alloc-or-given constructor `obj = a0 ? a0 : alloc(N)` whose object must survive ≥1 jal, a fresh `int obj;` local spills to an IN-FRAME slot (frame grows +8, all spill offsets shift). Assigning back into the PARAMETER instead (`if (a0==0){ a0=alloc(N); … } … use a0 … return a0;`) makes IDO spill via the ARG-SAVE-to-caller-slot convention (`sw a0, framesize(sp)`), keeping the minimal frame and matching the target's spill offsets. Erased the final 6 frame-size diffs on gl_func_00041524 (→ byte-exact 32/32, pure C). Try this whenever the only residual is `addiu sp,-N` / spill-offset off by a constant and the object is param-derived._
- [Drop the extra "working register" param — IDO routes the spill to the SOURCE param's home slot, not the working register's home slot](#feedback-ido-drop-working-reg-param-spill-follows-source-pseudo) — _When `obj = a0 ? a0 : alloc(N)`-shaped code is written with TWO params (`f(int a0, int a1)` + `a1 = a0;` to force the working pseudo into $a1), IDO -O2 spills $a1 across the second jal to **a1's own home slot 0x1C**. The same logic written with ONE param (`f(int a0)` + `a0 = alloc(N);` reusing the param) compiles to the SAME registers (working pseudo still in $a1 via the `or a1,a0,$0` copy) but the spill lands at **a0's home 0x18** — because IDO tracks the spill against the SOURCE pseudo (the param-named `a0`), not against the working register $a1. This is finer-grained than [arg-reuse-keeps-small-frame](#feedback-ido-reuse-param-as-object-caller-slot-spill): even with the same -0x18 frame and the same working register, the offset of the single spill flips by 4 bytes depending on which param the working pseudo descends from. Keep the goto-to-shared-epilogue (`goto L_end;` not `return 0;`) — `return 0;` adds 2 insns of `or v0,$0,$0` + jump to epilogue. Counter-trap: a fresh-local 1-arg form (`int r = a0;`) does NOT crack the spill — it bumps the frame to -0x20 with the working pseudo in $v1 (different registers entirely). The full lever is: 1-arg + reuse the param + goto-to-epilogue. Byte-exact gl_func_00037FAC 2026-05-27 (24 insns, prior 99.92%); generalizes to gl_func_00066514 (same shape, working in $a2 → spill flips 0x20 → 0x18)._
- [Goto-loop + reuse-param-as-counter for count-limited list walks — defeats isolated-vs-full-TU IDO divergence](#feedback-ido-goto-loop-reuse-param-counter) — _For count-limited linked-list walks (`int *node = list[off]; for (i=0; i!=key; i++) { node = node->next; if (!node) break; } return node;`), the natural `int i = 0; while/for` form picks $v0 for the counter and produces 17 insns in full-TU build (3.75% fuzzy) due to branch-likely loop rotation — even though isolated standalone-cc emit is 12-insn near-target. **Lever**: convert the function param to take the list-base as plain `int a0`, dereference into local `v1` FIRST, then reassign `a0 = 0` and use it as the counter via goto-loop: `int *v1 = *(int**)(a0+0x34); a0 = 0; if (v1==0) goto end; loop: if (a0==a1) goto end; v1 = (int*)v1[off/4]; a0++; if (v1 != 0) goto loop; end: return v1;`. Two effects combine: (1) reusing `a0` as the counter (not `int i`) forces IDO to allocate the counter to $a0 (recycling the dead param register) instead of $v0; (2) the goto-end form prevents IDO from emitting the branch-likely loop rotation (`bnel`+delay-likely-load) AND from optimizing `a0 == a1` into `beqz a1` (since a0's value-flow is opaque through the labels). Byte-exact game_libs_func_0003D9E4 2026-05-27 (12 insns, prior documented "isolated-vs-full-TU divergence" cap). Generalizes for any count-limited walk where the dead param can be recycled as the loop counter._
- [Array-index addressing (`int** a0; a0[a1 + K]`) packs stack spills tighter than char*-pointer-arith (`a0 + a1*4`) — fixes frame-size/spill-slot-offset residuals](#feedback-ido-array-index-vs-charptr-spill-packing) — _When the only diff is frame size / spill-slot offsets off by a constant (e.g. -0x28 with a 4-byte gap vs target -0x20), and the base is a param indexed by another param: express the access as typed array indexing (`int** a0; obj = a0[a1 + 0x14]`, 0x14 = byteoff/4) rather than char* arithmetic (`(char*)a0 + a1*4` then `[0x50/4]`). The array-index form makes IDO pack the pointer spills with no gap. Byte-exact gl_func_0002A50C 2026-05-24._
- [Copy adjacent fields as a STRUCT, not separate field-copies, to flip a $t-register-renumber residual](#feedback-ido-struct-copy-vs-field-copy-treg-order) — _When two (or more) adjacent words are copied `dst.f0=src.f0; dst.f1=src.f1;` and the only diff is the loads/stores using swapped $t regs (t6/t7 vs t7/t6), replace the separate copies with a single struct-typed copy (`*(Pair*)(dst)=*(Pair*)(src)`). The struct copy emits lw/lw/sw/sw in a fixed order that often matches the target's. Byte-exact game_uso_func_0000D438 2026-05-24 (was a banned INSN_PATCH)._
- [Pull `a0->field` into a named local when the same call overwrites $a0 with a new address](#feedback-ido-arg-deref-before-a0-overwrite) — For calls like `func(&SYM, *(int*)(a0 + N), 0)` where $a0 is about to be reassigned to &SYM, inlining the `*(int*)(a0+N)` deref makes IDO spill a0 early and reload via a fresh temp ($t6).
- [Function that never sets or spills a0 is forwarding caller's a0 to a callee](#feedback-ido-arg-passthrough) — If asm body shows a0 is never touched (no `sw a0, N(sp)`, no `or a0, ..., zero`, no `addiu a0, ..., N`) but a jal still uses it, the C takes a0 as a parameter and passes it through unchanged
- [IDO picks $a1 (not $a3) to save an arg across a jal — can't reliably flip from C](#feedback-ido-arg-save-reg-pick) — _When a function spills its incoming `a0` to survive a `jal`, IDO -O2 consistently allocates $a1 as the holding register: `or a1, a0, zero; sw a1, N(sp); ...jal...; lw a1, N(sp)`.
- [Pre-call `or aN, aM, zero` (move) plus a stack spill is 3rd-arg marshalling, not a defensive register-save](#feedback-ido-precall-move-is-arg-marshal) — When asm shows `or aN, aM, zero; sw aN, off(sp); addiu aM, aM, K; jal; sw aP, off(sp) [delay]` before a call where `aN > aM` (e.g. `or a2, a0` then `addiu a0, a0, 0x10`), the `or` is materialising a 3rd argument register, not preserving aM across the jal. Decoded C should be `f(aM+K, aP, aM)` (3 args), not `f(aM+K, aP)` (2 args). Mistaking it for a save makes you wrap NM at ~80% with no available C lever; the fix is just adding the missing argument.
- [IDO schedules arg-save `or sN, aN, zero` into bne delay slot when an immediate `if (aN == 0)` test follows the prologue](#feedback-ido-arg-save-to-sreg-in-bne-delay) — When function body starts with `if (a0 == 0)` after prologue, IDO -O2 schedules `or s0, a0, zero` (the s-reg copy of a0) into the bne delay slot rather than into the inter-spill gap.
- [IDO -O2 hoists `move sN, aM` above adjacent jal when no data dependency; source order `jal; p = a0;` doesn't keep them in source order](#feedback-ido-hoists-save-reg-init-above-jal) — When you write `func(...); p = a0;` in C, IDO -O2 schedules the `move sN, aM` (the p=a0 emit) BEFORE the jal because there's no data dep.
- [Inlining intermediates into a fn-ptr call expression drops IDO's defensive arg-register spill](#feedback-ido-inline-fnptr-call-drops-arg-spill) — _When IDO -O2 spills caller-arg regs ($a1) defensively before an indirect call, factoring out the named local intermediates and inlining the deref chain INTO the call expression keeps the arg dead at the spill point —…
- [IDO emits extra `andi`/`sll+sra` for narrow (char/short) function parameters](#feedback-ido-narrow-arg-promotion) — Declaring a function arg as `char` or `short` makes IDO insert byte/halfword promotion at the prologue that breaks matching.
- [IDO does not CSE repeated immediate args at -O2](#feedback-ido-no-cse-arg-immediates) — Passing the same literal constant (e.g. 1) to multiple stack-arg slots and a register-arg in one call materializes a fresh `addiu rN, zero, K` per slot — no shared register
- [IDO pre-call outgoing-arg spills (`sw aN, N(sp)` before jal for args loaded from globals) are not C-reproducible for K&R callees](#feedback-ido-precall-arg-spill-unreachable) — _Some IDO-compiled functions emit extra `sw $a1, 4(sp); sw $a2, 8(sp)` stores IMMEDIATELY before a jal, saving the OUTGOING arg values (just loaded from global memory) into the caller's arg-save slots.
- [IDO -O2 empty `void f(int a0) {}` produces exactly `jr ra; sw a0, 0(sp)` — save-arg sentinels ARE matchable from C](#feedback-ido-save-arg-sentinel-empty-body) — _The 2-insn "save-arg-to-caller-shadow-space" sentinel (`jr ra; sw a0, 0(sp)`) — previously documented as non-C-expressible — IS matchable from IDO -O2 with the trivial C body `void f(int a0) { }`.
- [Fix IDO unused-a0 spill by passing a0 through to the jal callee](#feedback-ido-unused-arg-fix-pass-to-callee) — When a function has signature `void f(int a0, int *a1)` where a0 appears unused in the body but is a real (required) parameter to preserve a1's register assignment, IDO spills a0 to the caller's arg-save slot (extra `sw…
- [IDO -O2 won't put `addiu aN, aN, K` into a jal-delay slot when a store via the SAME base precedes the call](#feedback-ido-no-addiu-into-jal-delay-when-store-via-base-precedes) — _For `*a0_offset_K = v; func(&a0[L], ...)`, IDO emits the `addiu a0,a0,L*4` as a standalone insn before the jal — it can't sink into the delay slot because the preceding store-via-a0 is a true dependency on the original $a0. Creates a fixed +1-insn delta vs targets that DO have the addiu in the delay slot. No clean C lever; structural cap. Verified 2026-05-16 on gl_func_0003E904 (built 26 vs target 25)._
- [Inline `aN[OFFSET]` at each use to force IDO to emit the same `lw` twice — matches target's redundant-reload shape](#feedback-ido-inline-arg-deref-defeats-cse-emit-multiple-lw) — _When built is N insns short and the missing insns are duplicate `lw aN, K(aN)` for the same struct field, refactor the C to inline the deref at each use instead of caching into a local. IDO's CSE doesn't fold separate-statement field-deref loads. Verified 2026-05-16 on gl_func_00046B64: caching `int *p = a0[0x240/4]` produced 23 insns (target 24); inlining `(int*)a0[0x240/4]` at all 3 use sites gave 24 insns matching target's count._
- [`float four = 4.0f;` named local pins the FP constant to one $fN across multiple uses](#feedback-ido-named-float-const-pins-fp-reg-across-body) — _For FP literals used 2+ times in a function body, declare `float NAME = LITERAL;` as a named local — IDO -O2 pins one $f-reg and reuses, vs re-materializing `lui at, IMM; mtc1 at, $fN` per use. Different from the `register int N = 1;` constant-fold trap because FP literals need lui+mtc1 setup. Verified 2026-05-16 on game_libs_func_000086A0 (parallel) and gl_func_0000871C (this tick) — both 4.0f-pinning under `float four = 4.0f;`._
- [IDO spills unused `int a0` param to caller-slot sp+frame when function contains a jal](#feedback-ido-unused-arg-save) — _If the target asm has `sw a0, frame_size(sp)` at entry (into caller's arg-save slot) but you see no use of a0 later, declaring `void f(int a0) { ...jal... }` with an unused a0 parameter reproduces it — IDO -O2 does NOT…
- [Force caller-slot spill of a USED arg via `volatile T *p = &argN;`](#feedback-ido-arg-addr-via-volatile-ptr-forces-caller-spill) — _When target has a leading `sw aN, frame+offsetN(sp)` (caller's aN slot) for an arg that IS used in the body — i.e., the unused-arg-save pattern doesn't apply — declare `volatile T *p = &argN;` to take the arg's address through a volatile-qualified pointer. IDO -O2 must materialize argN to its caller-slot since the address escapes (volatile prevents address-DCE). Verified 2026-05-08 on `gl_func_0003EA98` (82.89% → 100%)._
- [Pre-load arg field into named local to force field-load BEFORE `&D` materialization clobbers the arg-register](#feedback-ido-preload-field-into-local-forces-load-before-clobber) — _When target reads `lw aN, K(a0)` BEFORE `lui a0, %hi(D_X)` (load via original arg-pointer, then clobber it), the inline `func(&D, arg->field)` form emits clobber-then-reload-via-spill (+1 insn). Fix: `int val = arg->field; func(&D, val);` — named local creates a sequence point that forces field-load first. 2026-05-10: unlocked gl_func_00054668 (75.62% → byte-exact)._
- [Place `volatile int local = arg;` INSIDE the if-non-zero block to flip early-exit from `bnel-likely+delay-load` to `beqz+nop`](#feedback-ido-volatile-local-scoped-to-if-block-flips-early-exit-shape) — _Declaring a volatile-spilled local at function top emits the spill BEFORE the early-exit branch, letting IDO's scheduler hoist the first-iter loop-load into the branch's likely-delay slot (mismatching target's `beqz+nop` pattern). Scoping the volatile decl INSIDE the if-non-zero block pushes the spill AFTER the branch, removing IDO's hoist opportunity. Verified 2026-05-08 on `gl_func_0003EA98` — same-tick fix as the volatile-pointer caller-slot trick._

### scheduling / delay slot

- [IDO folds prologue sw ra into early-return beq's delay slot](#feedback-ido-early-return-ra-delay-slot) — When `if (a0 == 0) return;` is the first statement, IDO moves the prologue `sw ra` into the beq's delay slot — write the C naturally and the scheduler handles it
- [**Remove an "obvious idiomatic local" and recompute inline** — IDO CSE's it AND schedules the spill into the jal delay slot at a HIGHER in-frame offset](#feedback-ido-remove-local-recompute-inline-for-jal-delay-spill) — _When a function spills a small computed value (`char *newA0 = a0 + 0xA0`) across a `jal`, the natural `T name = expr;` local makes IDO -O2 spill `name` to the LOWEST in-frame slot (sp+0x18 in a 0x20 frame), BEFORE the jal. Target has the spill in the jal's DELAY SLOT at sp+0x1C. **Lever: delete the local; recompute the expression inline at every use.** IDO CSE collapses the recompute back to one value AND schedules its spill into the delay slot at the higher slot (0x1C, not 0x18). 9-variant grind (alias, &a0-home, register, volatile, decl-order swap, int pad, static pad, K&R, etc.) all failed before this; removing the local was the simplest possible change. Verified byte-exact 2026-05-27 on `gl_func_0004E180` + `gl_func_0002FA90` (16 + 32 insns respectively). Generalizes for any near-miss whose ONLY residual is "in-frame spill at lower slot than target wants" — try the no-local lever before declaring an allocator cap. **FAILURE MODE (verified 2026-05-28 on func_00007C74 + game_uso_func_00000724): only works when the value has essentially ONE consuming use across the jal so CSE collapses the recompute to a single spill. When the local has MANY uses — e.g. a loop-condition read + after-loop reads, or 4 derefs bracketing a call — inlining makes IDO emit a fresh reload at each use site and REGRESSES (func_00007C74 6→19 diffs, game_uso_func_00000724 ~5→18 diffs). Check the local's use-count first; if it's used >1-2 times across calls, skip this lever.**_
- [**Volatile-pad sandwich** to pin an &-taken local to a specific in-frame slot — declare volatile pads ABOVE and BELOW; NO `(void)pad;` cast](#feedback-ido-volatile-pad-sandwich-for-and-taken-local) — _When the residual is `&local` placed at slot X but target wants slot X±4, and the existing C uses `int local; volatile int pad[N];`, switch to a SANDWICH layout: `volatile int pad_upper; int local; volatile int pad_lo_a, pad_lo_b;` — IDO -O2's first-declared-highest stack placement puts pad_upper at the highest slot, then local one slot down (matching the target's slot), then the lower pads fill the remaining frame. **Critical: do NOT cast `(void)pad;`** — the cast emits extra `lw zero, N(sp)` discard reads at epilogue (one per pad). The volatile DECLARATION alone reserves the slot without emitting any read/write — it's a layout hint only. Don't use array-typed pads (`volatile int pad[3]`) either — IDO aligns arrays to 8 bytes which can over-pad and yield the wrong slot. Verified byte-exact 2026-05-27 on `gl_func_00041768` (25 insns, vtable dispatch + `int local; …; func(…, &local);`). Generalizes for any near-miss whose only residual is "in-frame slot off by 4 bytes from target AND local has `&local` somewhere"._
- [**Pad-SPLIT (not pad-size) positions a MULTI-local block at fixed offsets while holding frame size; re-check "INSN_PATCH-only" cap notes — they can be false**](#feedback-ido-pad-split-multi-local-block) — _Extends the volatile-pad sandwich to TWO adjacent locals. When the target places a block of locals (e.g. `buf@sp+0x28` AND `sp_arg@sp+0x34`, sp_arg ABOVE buf) but your emit puts the whole block N bytes too high, the fix is to SPLIT the dead-space pad into top+bottom halves of the SAME total size — `volatile int pad_top[2]; int sp_arg; float buf[3]; volatile int pad_bot[2];` — NOT to grow/shrink a single pad. First-declared = highest offset, so pad_top occupies the top dead space (pushing the block down) and pad_bot fills the bottom, keeping total locals constant → frame size unchanged (-0x40) while the block lands at the target offsets. Adding pad without removing the equal amount elsewhere just GROWS the frame (8-diff regression). Array-typed volatile pads with `(void)pad;` cast are FINE here (the cast decays to a pointer discard, emits NO `lw` — unlike a scalar `volatile int pad`). Verified byte-exact 2026-05-28 on `gl_func_00039A9C` (28 insns) — whose prior comment claimed a "99.8% INSN_PATCH-only cap, pad-size tuning is a C-level dead-end". It was a FALSE dead-end: the author only tried pad SIZE, never the top/bottom SPLIT. **Lesson: a stale "INSN_PATCH-only" / "C-level dead-end" note is worth one re-test via declaration-order + pad-split before trusting it** — especially since INSN_PATCH is now banned, so those notes predate the requirement to find a real C form. Also: the function's two `jal` words were R_MIPS_26 relocs to absolute-defined symbols — objdiff is reloc-aware and already scored them matched; the raw-byte `jal 0` "diff" was never real._
- [**`volatile int pad` declared FIRST cracks the "8-byte frame-alignment cap" on near-misses whose residual is `&`-taken locals (BYTE-EXACT — the family cap is FALSE)**](#feedback-ido-volatile-pad-first-frame-align) — _**LANDED 2026-05-29 `gl_func_00041F90` byte-exact, 60/60.** The recurring "frame -0xN0 vs -0x(N0+8), &local + spill offsets all +4, genuine frame-alignment cap" note (E6E8 finalizer family etc.) is a FALSE dead-end for the subclass whose mis-positioned slots are `&`-taken NAMED locals (`addiu aN,sp,K` in the diff). Fix: add an unused `volatile int pad;` as the **FIRST** local (IDO first-declared-highest gives it the top slot), which grows the frame +8 (zero extra insns — volatile-unused emits no load/store) AND shifts the &locals +4, landing every offset. **pad-FIRST lands it; pad-LAST overshoots the named block +8 (joins their region); a `volatile double`/`int[2]` 8-aligns and also overshoots.** Use a single scalar `volatile int` first. Try this on ANY frame-size-only near-miss whose diffs are `addiu aN,sp,K` (&local) off by a constant before trusting a "frame-alignment cap" note — they predate this lever. **BOUNDARY:** when the mis-positioned slot is a COMPILER-generated spill (`sw aN,X(sp);lw aN,X(sp)` re-materialization) NOT an &local — as in `gl_func_0000E6E8` (a1-spill at 0x24 vs target 0x2C) — no named pad reaches it (named locals sit ABOVE compiler spills); use the [decl-permutation brute-force](#feedback-ido-interleave-decl-spill-slot-alignment) on a named version of the spilled value instead._
- [**`&local` forces a dead home-spill WITHOUT a reload; `volatile` forces the spill WITH a reload (1 insn longer)**](#feedback-ido-and-local-dead-spill-no-reload) — _When the target spills a computed value to a stack slot (`sw t6, X(sp)`) as a DEAD store but then uses the same register copy directly afterward (`addiu a1, t6, 0x30` — no reload from the slot), the C must produce the spill while keeping the register live. `volatile T t = expr;` emits the spill but ALSO re-reads it on next use (`lw a1, X(sp)`) → 1 insn too many. **Lever: `T t = expr; T *p = &t; … use t; (void)p;`** — taking the local's address forces IDO to home `t` to its stack slot (the dead spill) but it keeps the register copy live for subsequent uses (no reload, because nothing writes through `p`). This is the COMPUTED-LOCAL generalization of the `&param` crack at [used-arg-dead-home](#feedback-ido-used-arg-dead-home). Verified byte-exact 2026-05-28 on `gl_func_0003604C` (10 insns: `int t=a0[5]; int *p=&t; f(a0,t+0x30); (void)p;`), which cracked a documented "non-volatile dead spill" cap whose recorded variants (plain local / volatile / register+pad) had all missed the address-taken form._
- [TU-CONTEXT-SENSITIVE scheduling: a standalone-byte-exact function can mis-schedule IN-TREE (reverse of the standalone-false-cap trap)](#feedback-ido-tu-context-sensitive-scheduling) — _Same C, same cc, same flags, but the full translation unit schedules a tiny leaf differently than the isolated standalone compile. `game_uso_func_0000C3E8` (`return *(int*)&D`): standalone -O2 = target byte-exact (dead a0 homed in jr-delay as a free filler); in the full game_uso.c TU the home/load swap (home before jr, load in delay). NOT lower-opt, NOT a C-form issue, NOT permuter-crackable — the TU perturbs the list scheduler's delay-slot pick. When standalone matches but in-tree doesn't, suspect this; it's a genuine cap (2026-05-24)._
- [IDO `-g3` disables delay-slot filling while keeping -O2 optimization — unfilled-`sw; jr; nop` IS matchable](#feedback-ido-g3-disables-delay-slot-fill) — _Compiling with `-O2 -g3` produces unfilled-delay-slot epilogues (`sw; jr ra; nop` instead of `sw; jr ra; sw(delay)`).
- [IDO -g does NOT suppress delay-slot fill (unlike KMC GCC -g2) — don't borrow the Glover technique](#feedback-ido-g-flag-does-not-suppress-delay-slot-fill) — _KMC GCC -g2 disables delay-slot reordering (per project_compiler_findings.md).
- [IDO -O1 target `lw $sN, spill(sp)` in jal delay slot — can't force via explicit C assignment](#feedback-ido-o1-delay-slot-s-reload) — rmon-style -O1 funcs spill arg `a0` to caller slot, then fill the first jal's delay slot with `lw $s0, SPILL(sp)` to promote msg into a callee-saved reg for later use.
- [Swap source order of two stores to let IDO's scheduler fill a jal delay slot with the SECOND-listed store](#feedback-ido-swap-stores-for-jal-delay-fill) — _When target asm has `sw $tA, OFFSET_X(a0); jal func; sw $tB, OFFSET_Y(a0)` (two consecutive stores with the second in the delay slot), write the C with the OTHER order: put the X-offset store SECOND in source.
- [IDO -O1: `register u32 v = expr & MASK; func(..., v);` produces andi-pre-jal pattern](#feedback-ido-o1-andi-pre-jal-via-register-u32-mask) — _When target has `andi tN,X,MASK; jal; or argReg,tN,zero` (3-insn mask-pre-jal vs natural delay-slot fold), use `register u32 v = expr & MASK; func(..., v);` block-local. The `& MASK` on the initializer (not the use) commits IDO to emitting the and pre-jal._
- [Lift unconditional loop-counter init OUT of the if-body to claim the branch's delay slot](#lift-unconditional-loop-counter-init-out-of-the-if-body-to-claim-the-branchs-delay-slot--leaves-the-result-init-before-the-branch) — _When target has `or v1, a0, 0` (result=sum) BEFORE `beq len, 0` and `or v0, 0, 0` (i=0) IN the delay slot, but built emits `result=sum` in delay slot, lift `unsigned int i = 0;` OUT of the if-body. Both inits become unconditional and IDO picks i=0 for the slot. Generalizes the cap-class previously labeled "no C-level lever"._
- [When the target is 1 insn LARGER than IDO's natural emit — preemptive `or v0, v1, 0` + NOP-delay branch is unreachable from C](#feedback-ido-target-larger-preemptive-set-nop-delay) — _Diagnostic for the inverse-of-bloat cap: when built `.o` is SHORTER than target by exactly 1 insn (a preemptive `or v0, v1, 0` BEFORE a sltu/bnez that the natural emit folds INTO the branch's delay slot), suspect this scheduling cap. IDO never picks the longer "preemptive + nop" form. Tested early-exit, goto-out, and early-set-clear variants all produce the same shorter natural emit. NM-wrap. Verified 2026-05-08 on kernel/func_800000B0 (91.15% fuzzy)._
- [Leaf load-hoist-above-aliasing-store: don't cache the first deref in a named local](#feedback-ido-leaf-load-hoist-no-named-temp) — _When a no-frame leaf's target hoists `lw t6, off(aN)` ABOVE a preceding `sw aM, 0(a0)` (aliasing store) AND uses transient `$t6/$t7` for two un-CSE'd derefs of the same `aN[k]`, write the load-bearing statement FIRST in source with NO named temp. A named `int t = aN[k];` both mis-allocates the value ($v0 instead of $t6) and CSEs the second deref to one load. Verified byte-exact 2026-05-18 on `game_libs_func_000664D4` (7-insn doubly-linked-list splice)._
- [A no-dependency constant store (`field = 0`) gets hoisted into an earlier load-delay gap — write it LAST in source order to pin it at the end](#feedback-ido-zero-store-write-last-to-prevent-hoist) — _When a function copies several loaded fields into the object AND also writes a constant (e.g. `obj->K = 0`), IDO's scheduler hoists the zero-store (no value dependency) up to fill a load-delay gap, landing it earlier than the target. Writing the constant store as the LAST statement keeps it after the dependent loads, matching the target's late placement (typically just before the jr-delay store). Verified byte-exact 2026-05-22 on `timproc_uso_b5_func_0000A928` (3 global-table field copies + one `a0->0x3C=0`): zero-store written 3rd → emitted at pos 8 (hoisted); written last → pos 11 (matches)._
- [jr-epilogue double-store: delay-pick + emit-order + temp-reg# all couple to source order, so some target combos are unreachable (cap)](#feedback-ido-jr-epilogue-double-store-coupling-cap) — _A 5-insn `compute;compute;sw;jr;sw` leaf with two independent stores of differently-computed values: the delay-slot store (always the FIRST source store), the emit order, and the temp-reg numbering (first-computed value → lower temp) are all locked to source order. If the target's delay store uses the second-computed value while the first-computed value lands in the lower temp, no source order produces both — NM-wrap/defer. jr analogue of the jal swap-stores recipe, but the jr case couples reg# too so the swap that fixes the delay store breaks the reg. Verified 2026-05-23 game_libs_func_000478D8._
- [Commutative compare (beq/bne) operand order: don't cast the parameter — casting flips which operand becomes rs](#feedback-ido-beq-operand-order-param-cast) — _`while(p!=a0)`/`if(p!=a0)` against a param: no cast → loaded value p ($v0) is rs (`beq $v0,$a0`); casting the param (`p!=(int*)a0`, or `int**a0`+cast) makes the param rs (`beq $a0,$v0`) — reversed bytes. Source operand order (a0!=p vs p!=a0) does NOT change it; only the cast does. Declare the param at the type that avoids the cast to match a target whose freshly-loaded value is rs. Verified byte-exact 2026-05-23 game_libs_func_0005B73C._
- [getc-style post-increment: deref `**a0` (not a named pointer local) keeps the pointer in $a1 and forces lbu-before-addiu](#feedback-ido-getc-deref-form-keeps-a1) — _For `c = *(*pp)++` (read byte, post-increment caller's pointer), write `unsigned char v = **a0; *a0 = *a0 + 1; return v;`. The double-deref keeps the loaded pointer in $a1 and emits `lbu` before the `addiu`/`sw`-in-delay. A named `p = *a0; v = *p; *a0 = p+1;` mis-allocates to $v1 and reorders to increment-first/lbu-in-delay. Verified byte-exact 2026-05-23 game_libs_func_0002A9A4._
- [Reference `*a2` twice in the C source when target loads it twice across a jal — IDO scheduler picks the second load to fill the jal delay slot](#feedback-ido-double-deref-fills-jal-delay-slot) — _When target asm loads a pointer dereference (`lw t6, 0(a2)`) early, then loads it AGAIN (`lw t8, 0(a2)`) right before a jal whose delay slot is `sw t8, OFFSET(sp)` (store of the second-loaded value), the C body must reference `*a2` twice. Write two assignments (e.g. `b60_1 = *a2; ...; b70 = *a2;`) rather than caching the value in one local — IDO's scheduler picks the second source-level read to fill the delay slot. Caching `int t = *a2;` and writing `b60_1 = t; b70 = t;` produces a single-load form with an unfilled delay slot. Verified pattern 2026-05-15 on `gl_func_0003F2B8` — duplicate-deref produces the expected scheduler emit, though that function caps at 83.4% NM due to the separate unused-arg-spill family (sw a0, 0xB8(sp) + sw a2, 0x68(sp))._

### $s register allocation

- [Append+overflow: hold `n = count+1` in a named temp; do NOT reload the just-stored counter for the bound test](#feedback-ido-append-overflow-count-temp) — _The recurring record-append shape `n=self->K+1; self->K=n; if(!((u)n<cap)) cb_assert(); return self->K-1;` byte-matches only when the incremented value lives in ONE temp reused by the `sltu` AND the `sw`. Writing `self->K=self->K+1; if(!((u)self->K<cap))…` reloads `self->K` for the test, which IDO allocates to `$v1`/`$t7` instead of the target's `$v0` (count+1 from the bump) → ~7 regalloc diffs at the tail. Same-count, pure-C lever (no post-cc). The 4 field stores still use uncached `*(short*)(self[K2/4]+self[K/4]*8+OFF)` derefs (idx reloaded per store). Verified 2026-05-19 byte-exact on `gl_func_000503A4`; applies to the game_libs record-append family (gl_func_00044CE8 etc.)._
- [At IDO -O0, count target's `sw sN, ...` saves to set the EXACT number of `register T x;` declarations](#feedback-ido-o0-register-count-matches-target-s-saves-exactly) — _At -O0, IDO promotes register-typed locals to s0/s1/s2/... in declaration order.
- [IDO -O2 global s-register allocator is NOT driven by local declaration order](#feedback-ido-sreg-order-not-decl-driven) — _`feedback_ido_local_ordering.md` covers STACK OFFSETS (first-declared → highest sp offset).
- [Reuse ONE C variable for two non-overlapping values to force IDO to share a register (inverse of the alias-splits-regs lever)](#feedback-ido-reuse-var-forces-shared-reg) — _When the target reuses a single register (often `$v0`) for two values whose live ranges don't overlap — e.g. a scratch `mask = align-1` early, then the returned pointer late — but your C uses two separate locals (so IDO assigns two different registers, e.g. mask→`$v1`, ret→`$v0`), MERGE them into one C variable reused for both (`u32 v; v = align-1; …use v…; v = D_heap; …; return v;`). IDO then allocates one register for the merged variable, matching the target's reuse. The inverse of `feedback-ido-arg-alias-doubles-s-reg` (there, splitting into an alias forced TWO regs; here, merging forces ONE). Partial-cracked `func_800000B0` mask (18→15 diffs, mask now `$v0`) 2026-05-28; doesn't fix a PERVASIVE temp-renumber, only the specific shared-reg pair. NOTE: don't over-apply — adding a `ret`-var on top REGRESSED it (extra moves). Try only when the diff is exactly "target reuses regX for two things, mine uses two regs"._
- [Drop the `int *s2 = a0;` alias when `a0` is deeply used across calls — alias forces IDO to allocate TWO distinct $s regs](#feedback-ido-arg-alias-doubles-s-reg-when-used-across-calls) — _When `a0` is referenced both as the loop-base AND passed unchanged as an arg to inner calls, an explicit `int *s2 = a0;` alias makes IDO allocate $s2 for the alias AND $s3 for the original `a0` ($s3 = a0 spill, retained for the post-call passthrough). Drop the alias and use `a0` directly throughout — IDO collapses to a single $s register, saving 3 spill insns. Counters the older "alias is DCE'd at -O2" claim from `feedback-ido-3save-vs-2save-arg-preserve` (different live-range shape). Verified 2026-05-08 on `gl_func_00068524` (88.72% → 100% with this + entry-test type fix)._
- [Identical C body in different .c files can emit DIFFERENT frame sizes — file-context affects IDO's spill-slot allocator](#feedback-ido-file-context-affects-frame-size) — _Three siblings (eddproc_uso_func_000003BC, arcproc_uso_func_00002334, mgrproc_uso_func_00003358) share IDENTICAL C body (same volatile-ptr-to-arg lever, same control flow, same cross-call shape). eddproc matches at 100 % with frame 0x28; arcproc and mgrproc both land at ~89 % with frame 0x20. Only difference is which .c file the function lives in. The 8-byte frame discrepancy can't be closed with C-level levers — OPT_FLAGS are nominally identical, and the volatile-ptr lever is already applied. Suspect file-level state (other functions' codegen perturbing IDO's allocator pseudo-numbering or live-range analysis). When you see this pattern, NM-wrap and document; don't grind. Verified 2026-05-08 across three functions. (BUT FIRST try the declaration-order-permutation lever below — that crack post-dates this entry.)_
- [Frame-size / spill-slot-offset 8-byte near-miss CRACKED by INTERLEAVING int and pointer local declarations — brute-force all decl permutations](#feedback-ido-interleave-decl-spill-slot-alignment) — _A non-leaf orchestrator whose ONLY diffs are an 8-byte-too-big frame (mine 0x30 vs target 0x28) plus the shifted home/spill/reload offsets that follow from it. Root cause: IDO assigns int spill-slot offsets in local-declaration order, and the alignment/packing depends on how int decls are INTERLEAVED with pointer decls. Grouped decls (`int *v0; int *p0; int *p1; int n0,n1;`) packed the int spills 4-aligned/adjacent (n1@0x1C, n0@0x20) and grew the frame; the target uses 8-aligned slots with gaps (n1@0x18, n0@0x20, frame 0x28). LEVER: brute-force every permutation of the local declarations through standalone IDO (each `cc -c` ~0.1s; objdump + word-diff vs the target `.s`) — `int *v0; int n0; int *p0; int n1; int *p1;` (interleaved) byte-matched. 120 perms = a few seconds. Verified 2026-05-28 mgrproc_uso_func_00001AD0 (34 insns, 9 diffs → 0, landed). DIRECTLY COUNTERS the "don't grind 8-byte frame discrepancies, NM-wrap" advice above for the pure-spill-slot-offset subclass (regalloc-only, NOT file-context). Always run the perm brute-force before NM-wrapping a frame-size-only near-miss. Builds on [feedback-ido-sreg-order-not-decl-driven](#feedback-ido-sreg-order-not-decl-driven)'s note that STACK OFFSETS (unlike $s-reg choice) ARE declaration-order-driven._
- [SYSTEMATIC game_uso cap: target keeps the entity ptr in caller-saved $a2 (register early, spill/reload only around calls); IDO C can't reproduce it](#feedback-ido-game-uso-entity-ptr-a2-cap) — _Across game_uso spine/helper functions that take an entity/struct pointer used many times across calls, the target keeps that pointer in caller-saved **$a2** — `move a2,a0` at entry, used register-resident early, spilled to its home slot and reloaded only around the calls that clobber it, saving NO extra $s register. IDO C produces one of two non-matching shapes instead: (a) normal `a0` use → promotes to a callee-saved **$s** (extra $s save, bigger frame); (b) the `int* volatile p=arg` knob → reloads on EVERY use (over-corrects, regresses). Neither matches "register-early, reload-after-call-only". No C knob pins a many-use value to a caller-saved reg with selective spill. Confirmed across game_uso_func_000044F4 ($s2 variant), _00001DDC (volatile knob got +0.88pp partial but a0 still mis-located), _000043D8 (no-call: a1→$s0 vs target $a3), _0000B750 (a0+a1→$s0/$s1 vs target a1→$s0 only; knob regressed 71→67%). This caps the PROLOGUE and cascades, so these functions plateau well below 100% regardless of body correctness. Don't grind the prologue with $s/volatile/register tricks — it's a whole-function allocno-weight divergence; needs the permuter (impractical on 300+ insn fns) or the original cc. NM-wrap and move on._
- [Model an adjacent-stack-slot pair (cur/next cursor) as `T *arr[2]` to force STACK-residency — defeats s-reg promotion of loop-carried pointers](#feedback-ido-stack-slot-pair-as-array) — _When the target keeps a loop-carried pair of pointers in two ADJACENT stack slots (e.g. `sw cur,0x18(sp)` / `sw next,0x1C(sp)`, reloaded each iteration) instead of promoting them to `$s` regs, declare them as a 2-element ARRAY (`int *cursor[2];`, cur=cursor[0], next=cursor[1]). Arrays are never register-promoted, so IDO keeps them sp-resident and reloads per use — matching the target's no-s-reg loop. Plain `T *cur, *next;` locals get promoted to s0/s1 (extra saves, bigger frame). COMBINE with: (a) SEPARATE vars for the loop's entry-test (`v1`) vs the bottom continue-test (`v0`) — reusing one var makes it loop-carried → promoted; (b) `&self` (or `&param`) to keep a cross-call param stack-homed+reloaded rather than s-reg-promoted. Took `gl_func_00041EDC` (cb-scope list-walk + vtable dispatch) 58% → 80.2% (2026-05-28). Residual: the last loop-continue temp still promotes to s0 (target uses zero s-regs) — the C can't force a total no-s-reg allocation. Recognition: target loop body starts with `lw rX,N(sp); lw rY,M(sp)` for the cursor pair + saves only `ra`. Sibling family: gl_func_0003E2B0 / 00040640 / 00040974._
- [Indexed double-deref accessor (`return base[idx*4+K]->[J]`) — SOLVED via addu operand-order lever (was mislabeled a cap)](#feedback-ido-indexed-double-deref-allt-cap) — _Tiny leaf chaining 2-3 indexed pointer loads. NOT a cap: fully inline (no named locals) AND write the scaled index FIRST in each addu (`idx*4 + base`, not `base + idx*4`) — for a LOADED base the C-second operand becomes the addu rs, emitting the target's all-$t order. Cracked the whole family 2026-05-23 byte-exact (timproc_uso_b5 8C1C/8AD4/8A38/8A64/8A90), no INSN_PATCH. Residual cap only when the base is the PARAMETER (a0+idx*4 with int-cast forces index-first; try pointer-arith param-first first)._

### constant fold / immediate / CSE

- [IDO -O2 constant-folds the load-address even when the base is a register-declared local](#feedback-ido-constant-address-load-fold-inevitable) — _For `arg = *(int*)((char*)base + N)` where base = `&D_constant`, IDO emits a fresh `lui+lw` rather than `lw arg, N($base_reg)` even with `register` keyword.
- [Force shared base register across multiple loads from `&D + N` via deferred assign + named locals](#feedback-ido-shared-base-via-deferred-assign-and-named-locals) — _Counter to the above for TWO+ loads consumed by a single call: `register T *t; ... t = &D + N; v1 = t[0]; v2 = t[1]; f(..., v1, v2, ...)` produces shared-base form (lui+addiu once, 2 lw with offset), vs the natural `f(..., t[0], t[1], ...)` which inlines 2 separate luis._
- [Force N-fold reload of `*(SYM+N)` via `volatile T **` + N intermediate locals (no CSE)](#feedback-ido-volatile-pp-forces-n-fold-pointer-reload) — _When target asm has `lui v1; addiu v1, 0; lw t?, OFF(v1)` repeated N times — i.e., the symbol address materialized once and N separate lw reloads from the same offset — natural C `base = *(...)` collapses to one load via IDO CSE. Use `volatile char **base_pp = ...; b1 = *base_pp; ... b2 = *base_pp; ...` with N separate intermediate locals to force N volatile reads._
- [Local-variable naming-swap (`a3 = *(int**)a2` after `a2 = a3`) does NOT defeat IDO local-CSE — both encode the SAME emit register](#feedback-ido-local-var-naming-swap-cse-locked) — _When two locals hold the same value (e.g. just after `a2 = a3`), changing the C source from `a3 = *(int**)a3` to `a3 = *(int**)a2` does NOT change which register IDO uses in the emitted `lw` instruction. IDO -O2's value-numbering CSE sees the assignment chain and picks the canonical source register (usually the right-hand side of the assignment). Verified 2026-05-14 on gl_func_0006AF0C — the local-CSE is locked through the recent assignment, no naming-only lever defeats it. Use INSN_PATCH for the affected insns, or accept the register-name cap. Distinct from `feedback-ido-cse-bust-via-distinct-externs` (which is about EXTERN-symbol CSE on `lui` materialization, not local-variable value-numbering CSE)._
- [Defeat IDO -O2 cross-USO-placeholder CSE by declaring two DISTINCT externs both aliased to the same address](#feedback-ido-cse-bust-via-distinct-externs) — _When target uses TWO separate `lui` instructions for `&D_00000000` accesses (one per scratch register), declare each access via a distinct C extern. Add aliases for both → same `0x0` in `undefined_syms_auto.txt`. Linker collapses, CSE doesn't. Verified on `gl_func_0002D710` (1/15 → 14/15)._
- [IDO -O2 globally CSE's `&D_00000000` (and other large-extern bases) into a single $sN, breaking per-iter lui reloads in unrolled-loop matches](#feedback-ido-global-cse-extern-base-caps-unrolled-loops) — _When a function references the same large-extern symbol (`&D_00000000`, `&func_00000000`, etc.) at MANY sites, IDO -O2 caches the high half (lui+addiu) into a single saved register ($s3 typical) and reuses it across…
- [IDO load-CSE swap to flip $v0/$v1 regalloc](#feedback-ido-load-cse-swap-v0-v1) — Decl-order trick that flips IDO's $v0/$v1 assignment for a chained pointer-deref pair via CSE
- [Inlining `(*a0)` 3+ times instead of caching `p = *a0` flips IDO from $tN to $v1 for the int** spill-load](#feedback-ido-inline-deref-vs-cache-flips-vN-tN) — _When target keeps a `int**` arg in $v1 across post-call uses (multiple `lw tN, 0(v1)` reloads), explicit caching `p = *a0;` lets IDO pick a $t-reg instead. Inlining `(*a0)` at every use forces 3 separate reloads which IDO assigns via $v1._
- [Type-different unique externs (`int X` + `char Y`, both at addr 0) break IDO CSE between sibling lui+addiu in the same call](#feedback-ido-type-split-unique-extern-breaks-cse) — _When `func(p, *(int*)&D_X, &D_Y)` should emit TWO separate `lui+addiu` (target shape) but built emits ONE shared lui via CSE, declaring the externs with DIFFERENT types (one `int`, one `char`) prevents IDO from CSE-folding even when both link-resolve to address 0._
- [Break `&X` ↔ `*(int*)&X = 0` CSE by expressing the second use as pointer-arithmetic from a NEAR symbol](#feedback-ido-cse-bust-via-near-symbol-pointer-arith) — _When target emits `*(int*)&X = 0` (naked store, single `lui at; sw 0(at)`) but separately needs `end = &X` for a pointer bound, IDO CSEs the address load → wrong shape (`lui v?; addiu v?; sw 0(v?)`, 3 insns). Use `end = &Y + N` where `Y + N` resolves to the same final address as `&X`. Pointer arithmetic on a near symbol post-links to the same VRAM but is syntactically distinct → no CSE. Verified 2026-05-13 on `func_80001184` (kernel zero-init): 72.10% → 81.58% (+9.48pp) by writing `end = D_80012D3C + 8` instead of `end = &D_80012D5C` (both resolve to 0x80012D5C)._
- [Replace literal `0.0f * 0.0f` with `local[N] * local[N]` (where local[N] holds 0.0f) to force IDO to emit the redundant mul/add insn pair](#feedback-ido-zero-term-via-memory-load-not-literal) — _When target asm has an explicit middle 0-term in a sum (e.g. `sqrlen = a*a + 0 + c*c` with a literal mul.s on the zero), C `0.0f * 0.0f` gets constant-folded out of the expression by IDO -O2. Reference a memory-stored 0.0f local (`local_xz[1]`) instead — the lwc1 + mul.s + add.s chain emits as expected. Verified 2026-05-08 on game_uso_func_00001DDC (+0.73pp from this single line change)._
- [IDO -O2 auto-unrolls simple count-bounded pointer-chase loops 4x; also constant-folds `/ const` to `* recip`](#feedback-ido-o2-loop-unroll-and-constfold) — A bare `for (i=0; i<n; i++) p = p->next;` loop at IDO -O2 compiles to a Duff's-device-style 4x unrolled body with a remainder prologue.
- [IDO `register T x = const;` does NOT prevent constant-folding through reads of x](#feedback-ido-register-keyword-doesnt-block-constant-fold) — Declaring `register int one = 1;` in IDO -O2 does NOT pin `one` to a $s-register for all reads.
- [Split `x | 0x06000001` into `x |= 0x06000000; x |= 1;` to match `lui+or+ori` sequence](#feedback-ido-split-or-constant) — When the target asm has `lui at, HI; or a0, a0, at; ori a0, a0, LO` (three insts), don't combine the constant in C.
- [IDO -O2 folds `&extern == 0` to FALSE — defeats null-check arms in C bodies that mirror cross-USO unbound-symbol asm](#feedback-ido-extern-addr-non-null-fold-defeats-runtime-null-check) — When target asm checks `if (v1 == 0) alloc(...); else *v1 = 0;` and v1 originates from a stolen-prologue `lui v0, 0; addiu v1, v0, 0` (i.e. `v1 = &D_00000000` after relocation), the natural C `int *v1 = (int*)&D_00000000; if (v1 == 0) { ... }` doesn't match — IDO -O2 sees `&D_00000000` as compile-time non-null, folds the null-check branch, and elides the entire alloc arm (e.g. 14 target insns → 7 emitted). Cross-USO unbound symbols CAN be 0 at runtime, but IDO has no way to know. Lever to defeat the fold: load v1 via a `volatile T *` indirection from a separate `int *D_globalptr` global so the value isn't a compile-time symbol. Verified 2026-05-08 on `gl_func_0005165C` (kept as NM wrap — the lever fix wasn't tried).
- [Pass magic-numeric arg via `&gl_ref_<addr>` symbol — IDO emits `lui+addiu` only for symbol refs, not raw int literals (which emit `lui+ori`)](#feedback-ido-magic-arg-via-symbol-not-literal) — When target asm has `lui aN, HI; addiu aN, aN, LO` materializing some magic constant 0xNNNNNNNN passed as a call arg, the C source must use `&gl_ref_0xNNNNNNNN` (a declared linker-symbol reference) — passing the raw int 0xNNNNNNNN emits `lui+ori` instead. Add `gl_ref_0xNNNNNNNN = 0x0NNNNNNN;` to `undefined_syms_auto.txt`. Linker fills in the resolved bytes; build/.o has unresolved R_MIPS_HI16/LO16 relocs which look like `lui 0; addiu 0` to naive objdump-of-.o compare BUT byte-match expected/.o once linked. Verified 2026-05-08 on `gl_func_000682F8` (3-arg call with magic 0x2B3B8 base — exact at link time).
- [Don't `volatile int target = K; *p = target;` to defeat const-load hoist — catastrophic regression (~50pp) from cascading $s-reg reshuffle](#feedback-ido-volatile-const-bind-catastrophic-regression) — _When IDO hoists a constant load above a body branch where target keeps it inside, wrapping the assignment as `volatile int target = K; *p = target;` adds 3+ insns AND shifts $s-reg allocation across every variable whose live range crosses the volatile, dropping fuzzy ~50pp (90.86% → 35.63% verified 2026-05-08 on h2hproc_uso_func_00001204). Use INSN_PATCH or statement reorder instead._
- [Replacing literal `1024` with `(x<<10)/x` DOES emit the sll+div+mflo sequence at IDO -O2 (memory-load operand defeats SR), but added locals can shift register allocation enough to net-zero fuzzy%](#feedback-ido-div-substitution-necessary-but-regalloc-shifts)
- [Inline `&D_X + N` everywhere (not via a `base` local) — lets IDO use $at-fused `lui at; sw 0(at)` stores instead of 2-insn $v1 materialization](#feedback-ido-inline-symbol-arith-vs-base-local) — _For multiple stores like `*(int*)(base + 0xN) = 0` where `base = &D_X`, declaring `base` as a local forces IDO -O2 to materialize the symbol in $v1 (`lui v1; addiu v1, v1, 0; sw $0, 0xN(v1)` — 3 insns per store). Inlining `(char*)&D_X + 0xN` at every site lets IDO use the $at-fused store pattern (`lui at, %hi(D_X+0xN); sw $0, %lo(D_X+0xN)(at)` — 2 insns per store). On `gl_func_00021EA8`, this single refactor moved fuzzy 68% → 87% (+18.7pp) on a 38-insn function with 5 `*(int*)(base + offset) = 0` stores. Counter-intuitive vs the usual "factor common subexpressions" rule — for constant-address stores specifically, IDO's optimizer prefers the inlined form because $at is reservable per-instruction whereas $v1 must be materialized once._ — _When target asm has `sll tN, sM, 10; div 0, tN, sM; mflo sP; bnez sM, +2; nop; break 7` (a self-canceling `(x<<10)/x = 1024` sequence with div-by-zero trap), replacing the literal `1024` in the C body with the equivalent `(x<<10)/x` expression IS recognized — IDO -O2 doesn't strength-reduce when the operand comes from a memory load (no compile-time visibility). However, declaring the result as a new local (or substituting inline) introduces extra register pressure: frame size can grow (e.g., 0x58→0x60), and $s-reg assignments shift across the function. The div pattern alone is "necessary-but-not-sufficient" — to land net-positive fuzzy%, the divided value must also be assigned the same $s-reg slot as the target. Verified 2026-05-07 on `gui_func_00000B58` (substitution emitted matching div, fuzzy unchanged at 36.12% due to $s0/$s1/$s4/$s5 reshuffling)._

### loop / unroll

- [Auto-unrolled loop counter is BY-N element-stride (cmp total), never a BY-1 trip counter (cmp total/N) — CAP if target uses a trip counter](#feedback-ido-unroll-element-vs-trip-counter) — _When IDO -O2 auto-unrolls a count-bounded loop ×N, the loop variable becomes a by-N ELEMENT counter (e.g. `i+=4; i!=16`); a literal N-trip loop (`i<4`) FULLY unrolls (no loop) instead. So the target's "by-1 trip counter on an N-unrolled body" form (`addiu cnt,1; bne cnt,N` + pointer+=N*sz) is NOT C-reachable — verified game_libs_func_0005BDC0 (16-elem reciprocal, ×4) across 4 forms (indexed-i<16 / for-×4 / do-while-×4 / countdown-pointer) + 200s permuter (floored at the 2 counter-constant bytes). Genuine cap; leave NM ~99.9%. The only diff is `li cnt,total`/`addiu cnt,N` vs target's `li cnt,N`/`addiu cnt,1` — was previously INSN_PATCH-faked (banned). **2026-05-27 partial-crack note**: explicit `goto-loop` form + named pointer locals (`float *psrc=src, *pdst=dst; int i=0; loop: ... pdst+=4; psrc+=4; i++; if (i!=4) goto loop;`) DOES produce the target's structural 24-insn rolled body — but with a 3-insn permutation residual in the init-block ordering (target: `addiu a0,$0,4; or v0,$0,$0; or v1,a1,$0`; built: same 3 insns in different order `or v0,$0,$0; or v1,a1,$0; addiu a0,$0,4`). The IDO scheduler is robust against C-level decl-order, `register` keyword, `volatile`-fence, and ptr-derived limit tricks; the permutation is allocator-internal. The objdiff mnemonic fuzzy_match for the partial-crack form is WORSE (~91%) than the element-counter form (~99.9%) because the 3 diffs span major opcodes vs the original's 2 immediate-value diffs — keep the element-counter form unless feeding to permuter (the partial-crack form is structurally permuter-bait but still floored at the 3-insn permutation)._
- [IDO -O2 if-guarded do-while defers register-only assignment past jal](#feedback-ido-if-guarded-do-while-defers-reg-move) — When a `p = a0;`-style register-only move is hoisted by IDO ahead of an unrelated jal (no data dep), wrapping the loop as `if (count > 0) { p = a0; do { ... } while (i < count); }` forces the move AFTER the count load…
- [IDO `while(1){}` always emits unreachable jr-ra epilogue + 2 alignment nops — caps short infinite-loop stubs](#feedback-ido-infinite-loop-unreachable-epilogue) — For functions whose target is a tight infinite-loop stub (`b .; nop; …nops; jr ra; nop`), IDO emits jr $ra at offset 0x20 with seven nops between (size 0x28).
- [IDO -O2 2x-unrolls a known-small-trip loop; a target with a non-unrolled body + `li`-constant bound is likely an un-suppressible-from-C cap](#feedback-ido-unrolls-known-small-trip-loop) — _When the target loop has ONE body + `addiu iv; bne iv,tN` (tN=`li` constant) but C-emit is ~2x the insns with two body copies per pass, IDO computed the static trip count and unrolled 2x. for-loop AND do-while both unroll (trip count known either way). If the target was compiled NON-unrolled despite `li`-constant bounds, no C-level lever reliably suppresses it (runtime/opaque bound would defeat trip analysis but contradicts the baked `li`); treat as a loop-unroll cap. Diagnose via `build/non_matching/.../X.c.o` disasm: count body copies. Seen 2026-05-18 on game_libs_func_00054144 (76 vs 51)._
- [IDO -O2 auto-unrolls do-while pointer-walks with subu/andi alignment guard regardless of bounds origin](#feedback-ido-pointer-walk-loop-unroll-guard-unflippable) — _For a do-while loop walking through memory clearing fields (`do { ptr += 4; ptr[-4]=ptr[-3]=ptr[-2]=ptr[-1]=0; } while (ptr != end);`), IDO -O2 emits TWO loops + a `subu/andi 0x3F` alignment guard.
- [IDO rewrites pointer-comparison sentinels as `s1 != magic - slot` in unrolled-loop bodies — recognize the pattern](#feedback-ido-sentinel-rewrite-in-unrolled-loops) — _When IDO encounters `if (s1 + slot != (char*)MAGIC)` inside an unrolled loop and MAGIC doesn't fit a 16-bit immediate, it rewrites the test as `if (s1 != (char*)(MAGIC - slot))` and emits `addiu $at, $zero, sentinel;…
- [Decoding `a0 * K` multiplication sequences from `sll/subu/addu` chains: walk left-to-right, each `sll<<N` is `*2^N`, each `addu/subu r,r,aM` is `±aM`. Read the chain to recover K — don't trust the C-source comment, the asm has the truth](#feedback-ido-decoding-multiply-via-shift-add-chain) — _When target asm has 5 chained `sll/addu/subu` insns at function entry computing `a0 * K` for an array stride or struct offset, walk the chain step-by-step to recover K. A miscoded `K` in the C source produces shift-counts that LOOK similar to target's but encode a different multiplier — and you can spend ticks chasing register-cascade caps that aren't the real issue. Verified 2026-05-14 on gl_func_0002D130: doc comment said "0x320-byte stride" (wrong), asm chain `sll<<2;subu;sll<<2;subu;sll<<5` decodes to `a0 * 11 * 32 = 0x160` (right). Single-character C constant fix yielded +3.36pp._
- [Reuse an arg as a later loop iterator only AFTER a separate null-test temp to get `lw v0` + delay-slot `$s0 = v0`](#feedback-ido-reuse-arg-after-null-test-for-sreg-iterator) — _When target first preserves `a0` in `$s0`, later loads `node = s0->next` into `$v0`, tests it, and copies `$v0` into `$s0` in the branch delay slot, write `node = *(arg0+off); if (node != 0) { arg0 = node; do { ...; arg0 = arg0->next; } while (arg0 != 0); }`. The separate temp creates the `lw v0`/test; reusing `arg0` only inside the if lets `$s0` become the iterator. Verified 2026-05-16 on `func_000086C0`: 84.94% → 99.70%, then exact with inline `$t9` callback._
- [Don't cast a K&R extern function pointer inline (`((int(*)(int))gl_func_X)(...)`) to fix arg-reg allocation — REGRESSES even when the cast is semantically correct. IDO treats the casted form as variadic-style and forces extra spills](#feedback-ido-typed-cast-of-kr-extern-regresses) — _Negative finding 2026-05-14: when target asm has `or a1, a0, zero` (self preserved in $a1) but built has `or a2, a0, zero` (self in $a2), the natural fix-attempt is to add an inline typed cast like `((int(*)(int))gl_func_00000000)(arg)` to declare a 1-arg signature for THIS call (so $a1 is free for self preservation). Verified on timproc_uso_b1_func_00001130: this REGRESSES 86.17% → 70.33%. IDO emits extra arg-spill scaffolding for the typed-cast form even though it's a valid C-level shape. Don't try this lever on K&R `extern int gl_func_X();` calls; the K&R ABI is what's already best-emit. Distinct from `feedback-ido-magic-arg-via-symbol-not-literal` (which fixes a different issue: lui+addiu vs lui+ori for the constant arg). For the arg-reg-preservation cap, accept the cap or use INSN_PATCH._
- [`$s0` priority is FIRST-ASSIGNMENT order, not declaration order — initialize the wanted-in-$s0 local first in the function body](#feedback-ido-sreg-priority-first-assignment-not-decl-order) — _When two locals compete for $s0, IDO -O2 picks the one assigned FIRST in the body, NOT the one declared first. Declaration order alone does NOT flip the allocation. Verified 2026-05-14 on gl_func_0004ED0C: declaring `int i;` before `int *iter` and assigning `i = 0;` before `iter = self;` flipped $s0 from iter to i (matching target) — but JUST swapping declaration order produced no change. The for-loop init `for (i = 0; ...)` runs AFTER any earlier assignments, so the assignment order matters. +1.6pp final-mile fix._
- [Drop redundant `if (count <= 0) return;` before a for-loop with the same `i < count` test — IDO emits both `blezl` (early-return) AND `blez` (loop-start), doubling the test code](#feedback-ido-drop-redundant-early-return-before-for-loop) — _When target asm has a single `blez tN, .end` before the loop body and your wrap has both `if (count <= 0) return;` AND `for (i = 0; i < count; ...)`, IDO -O2 emits BOTH branch checks (the early-return as `blezl` likely, the loop-start as plain `blez`). The for-loop's initial test already handles count <= 0, so the explicit early-return is redundant. Removing it collapses to a single blez. Verified 2026-05-14 on gl_func_0004ED0C: 88.57% → 96.07% (+7.5pp) just from dropping the redundant check + the inline-method-ptr-for-$t9 fix._
- [Diagnostic: `bne vN, zero, .L1` + `or aM, vN, zero` in DS means the result is preserved as the next call's arg-aM (NOT dead code) — re-read the C body, the else-branch call takes one more arg than you think](#feedback-ido-bne-ds-preserves-result-for-next-arg) — _Regular (non-likely) bne's DS executes regardless. When target has `bne vN, $zero, .L1` followed by `or aM, vN, $zero` in the DS, IDO is preserving the v0 (call result) into a different arg-reg for the next call on the taken path. The C should pass the call result as the corresponding ARG to the next call. The wrap was missing this arg, capping fuzzy ~12% short. Verified 2026-05-14 on `gl_func_00021EA8`: 87.5% → 100% by changing `func(table, arg)` to `func(table, r, arg)` (`r` = the named call result, `arg` was the original input)._
- [Short-of-int extraction emits the WRONG halfword address: `(short)int_at_OFF` emits `lh OFF+2` (low half, big-endian), `*(short*)((char*)p + OFF)` emits `lh OFF` (direct halfword at byte offset). Same trap for `(unsigned short)*int_ptr` → `lhu +2` vs `*p & 0xFFFF` → `lw + andi 0xFFFF`](#feedback-ido-short-of-int-vs-direct-short-load) — _When target asm has `lh rT, OFFSET(rS)` reading a halfword at byte offset OFFSET inside a struct of ints, the natural C `(short)struct[OFFSET/4]` does NOT match. IDO -O2 emits `lh rT, OFFSET+2(rS)` for the int-cast form (low half of the 32-bit word, MIPS big-endian). To get the direct halfword load, use `*(short*)((char*)struct + OFFSET)`. Same trap for `(unsigned short)*int_ptr` (emits `lhu OFF+2(p)`) vs `*int_ptr & 0xFFFF` (emits `lw 0(p); andi rT, rT, 0xFFFF`). Verified 2026-05-14 on gl_func_00038C04: both forms fixed null fuzzy → 95.92%._
- [`x & ~K` emits `andi rT,rS,0xFFFF-K` (sign-extended-complement form); `x & EXPLICIT_MASK` emits `andi rT,rS,EXPLICIT_MASK` (literal form)](#feedback-ido-andi-mask-bytewidth-depends-on-c-form) — _For an 8-bit char store like `*p = *p & ~2;` vs `*p = *p & 0xFD;`, both produce functionally-identical results (clear bit 1 of the low 8 bits) but IDO encodes the andi with a DIFFERENT 16-bit immediate: `~2` → `andi 0xFFFD` (0x31cffffd byte), `0xFD` → `andi 0x00FD` (0x31cf00fd byte). Match the target's literal — `andi 0xFFFD` means source used `~K`; `andi 0x00FD` means explicit mask. Verified 2026-05-14 on gl_func_0002D064. Same one-bit-different-byte issue as `ori vs addiu` for symbol-vs-literal constants._
- [`volatile int low_pad[N];` declared BEFORE a `float buf[M]` grows the frame by 4N bytes AND pushes buf to a higher stack offset](#feedback-ido-volatile-int-array-low-pad-grows-frame-and-pushes-buf-up) — _When buf is offset 4N bytes too low vs target, a leading `volatile int low_pad[N]; low_pad[i]=0;` grows the frame by 4N AND pushes buf up by 4N (volatile-scalars-before-array layout rule). Verified 2026-05-14 on gl_func_00039A9C: 2-element low_pad moved buf sp+0x24 → sp+0x28. Cost: N visible `sw zero` insns; net regression unless paired with INSN_PATCH to elide them._
- [Reproduce a target's DEAD store (store X to addr, then overwrite with Y, no intervening read) via a TARGETED volatile cast on just that one store](#feedback-ido-targeted-volatile-keeps-dead-store) — _When the target writes a field twice with no read between (e.g. `sw t3,0x40(a0)` then `andi t5,t3,0xF; sw t5,0x40(a0)` — first store dead), clean C `p[i]=t; p[i]=t&0xF;` lets IDO -O2 dead-store-eliminate the first (1 insn short, shifts branch offsets). Cast ONLY that store's lvalue: `((volatile T*)p)[i] = t; p[i] = t & 0xF;` — the volatile store can't be DCE'd, so both emit. Whole-pointer `volatile T *p` OVER-applies (forces every access to a fresh load — 22 diffs on gl_func_00031784); the targeted single-store cast is surgical. Verified 2026-05-23 on game_libs_func_00031784 (ring-buffer index `=t; =t&0xF`): 26→27 insns, then 5 residual register-renumber insns INSN_PATCHed → byte-exact + episode._
- [Write-only `volatile int dummy = aN;` keeps an 8-byte frame allocated WITHOUT the dead-load artifact of `(void)dummy;`](#feedback-ido-write-only-volatile-keeps-frame-without-deadload) — _When `volatile int dummy;` is the only lever to keep IDO -O2 from collapsing a small stack frame, the default `(void)dummy;` use-site emits a trailing `lw zero, OFF(sp)` dead-load. Swap it for `dummy = aN;` (volatile-WRITE, no read): slot stays anchored, no trailing load emitted. Verified 2026-05-14 on `gl_func_0006AF0C` (79.28% → 86.78%, 16→14 insns)._
- [`volatile s32 sp4;` forces IDO to keep a loop counter on the stack with per-iteration `lw/addiu/sw` instead of register-promoting it](#feedback-ido-volatile-loop-counter-for-stack-iter) — When target asm shows a loop body that reloads the counter from `N(sp)` each iteration (`lw rA, N(sp); ... addiu rB, rA, 1; sw rB, N(sp)`), the C source's loop counter must be `volatile` to prevent IDO from promoting it…
- [IDO -O2 strength-reduces `array[idx]` in nested inner loops into cached-pointer-post-increment — not flippable from standard C](#feedback-ido-o2-loop-array-strength-reduction) — When the inner loop reads `array[idx]` and increments idx every iter, IDO -O2 caches `s_reg = array + idx` and post-increments it. If target has the NON-strength-reduced form (per-iter `addu base, idx`), no C variant defeats it. Verified 2026-05-06 on gl_func_00055B44.
- [When the TARGET has two IVs (counter + strength-reduced pointer), write ONE counter IV and index the array — don't declare an explicit pointer](#feedback-ido-want-two-iv-use-single-counter-index) — Productive inverse of the above: index `(char*)src + i` so `i` is the sole source IV (test + address) → wins `$s0`, and GCC manufactures the data pointer into `$s1`. Fixes both the `$s0↔$s1` swap AND the residual preheader schedule diff in one move. Verified 2026-05-24 on gl_func_0005C784 (98.8%→exact).
- [**When the target has a trip counter + a SEPARATE advancing pointer (both real $s-regs), write TWO explicit IVs and init the COUNTER first; comma-`for` cracks the prologue schedule**](#feedback-ido-two-explicit-ivs-counter-first) — _The complement of the single-counter-index recipe above. When the target loop genuinely keeps BOTH a trip counter AND a separate advancing pointer in distinct $s-regs — outer `addiu cnt,1; bne cnt,LIMIT` + `addiu ptr,STRIDE` in the delay slot (the pointer is NOT re-derived from the counter each iteration) — DON'T index (`a1[row*4+col]`) and don't compute `p = a1 + row*4` (IDO strength-reduces both to a single by-stride counter). Write two explicit IVs: `counter` (trip) and `ptr` (advancing). Two levers make it byte-exact: (1) **init the counter before the pointer** (`for (i=0, q=base; ...)`, not `q=base; for(i=0;...)`) so the counter's pseudo is born first and wins the LOWER $s-reg — the documented "p+=4 only swaps roles" failure was caused by initing the pointer first; (2) use the **comma-init `for` form** `for (i=0, q=base; i!=N; i++, q++)` — this reorders the prologue so the loop-invariant address `addiu`s schedule before the var-init moves, cracking the last scheduler-tie diffs. Nests cleanly (inner: byte counter `col 0..16,+4` + `p++`; outer: `row 0..4,+1` + `rowp += 4floats`). Verified 2026-05-29 on gl_func_0005C6C4 (4x4 matrix printer): a documented induction-var cap, 99.96% → 100%. NOTE: distinct from the auto-unroll by-N-vs-by-1 cap ([feedback-ido-unroll-element-vs-trip-counter](#feedback-ido-unroll-element-vs-trip-counter), e.g. 0005BDC0) — that's a SINGLE fully-unrolled loop where the counter IS strength-reduced; this recipe is for NON-unrolled loops whose target already has two separate IV regs. Try this before NM-wrapping any "induction-var cap" whose target shows counter+separate-pointer (NOT an unrolled body)._
- [GCC 2.7.2 evaluates binary-operator operands RIGHT-to-LEFT — swap commutative operands to control which pointer IV wins the lower temp register](#feedback-ido-rtl-operand-eval-pointer-reg) — In `dst[i] = a[i] + b[i]`, GCC evaluates `b[i]` first, so b's strength-reduced pointer IV is created first and gets the lower temp ($v1), a gets $a3. If the target has a→$v1/b→$a3, swap to `b[i] + a[i]` (commutative: same value, same `add.s` bytes) to flip it. Verified 2026-05-24 on gl_func_0005E030 (register swap fixed). NOT applicable to non-commutative ops (sub/div) where operand order is semantically fixed.
- [For args-preserved-as-locals byte-copy loops, decrement the ARG directly (`count--`) — not the local copy (`cp--`)](#feedback-ido-decrement-arg-not-local-for-counter-loop) — When target preserves an arg as the loop counter (one move at entry, then `addiu argReg,argReg,-1` per iter) AND a local mirror, write the loop with `count--` (decrement the arg-named param) and use the local only as the loop-bound capture (`rem = count`). `cp--; rem = cp` regresses 22→29 diff lines on the same function; `count--; rem = count` tightens to 10 diff lines. Verified 2026-05-06 on func_80000598.
- [Bitfield setter `*a0 = (*a0 & ~M) | (V << N);` emits ONE sw; target's two-sw shape needs split into two statements](#feedback-ido-bitfield-setter-two-statement-split-for-redundant-sw) — _When target asm has TWO `sw rX, 0(a0)` writes (cleared-mask intermediate + final OR'd value) for a bitfield setter, the natural single-expression form `*a0 = (*a0 & ~M) | (V << N);` emits only ONE `sw`. Split into `*a0 = *a0 & ~M; *a0 = *a0 | (V << N);` — IDO honors the two sequence points and emits the intermediate store. Verified 2026-05-17 on game_libs_func_0000A884/A8B4/A938/A96C (4 bitfield setters)._
- [Leaf with `beqz $tN, +K` branching past function end into next function's `jr ra` body — tail-fallthrough caps INCLUDE_ASM-only](#feedback-ido-leaf-beqz-fallthrough-into-next-func) — _Pattern: an 8-insn getter where the false-condition branch lands past the function's own `jr ra` insn, falling through into the immediately-following empty function's `jr ra; nop`. The fall-through provides the return for the false case; the true case uses the function's own jr ra. Cannot be reproduced from C alone — IDO has no way to emit a function that intentionally relies on linker layout placing a specific neighbor after it. Identified 2026-05-17 on game_libs_func_0000A8D8 (where next function game_libs_func_0000A8F8 is empty `void f(void){}`)._
- [IDO -O2 unrolls const-bound (32-iter) const-body byte-fill loops 4x with pointer-stepping — defeats indexed-loop targets](#feedback-ido-o2-unrolls-const-bound-fill-loop-4x) — _When target asm has a single-body indexed byte-fill loop (`lw t6, a0_home(sp); lw t8, i_local(sp); lbu t7, K(t6); addu t9, sp, t8; sb t7, BUF_OFF(t9); ... addiu t1, t0, 1; slti $1, t1, 32; bne $1, $0, loop; sw t1, i_local(sp)`) and your C is `for (i=0; i<32; i++) buf[i] = src[K];`, IDO -O2 unrolls 4x with pointer-stepping (4 `lbu/sb` pairs per iter advancing through `addiu v0, v0, 4`), capping at ~28%. `for` vs `do-while` produce identical unrolled emit. **Recipe (verified 28% → 75% on gl_func_00072550)**: combine three knobs — (1) `volatile int i = 0` defeats the unroll (28→50%); (2) `volatile int ret = 0; ret = call_result; return ret;` round-trips return via stack like target (50→60%); (3) `int* volatile a0 = arg;` forces a0 to home-slot reload each access instead of $s0 promote (60→75%). The remaining gap is IDO precomputing `&buf[0]` outside the loop vs target's per-iter `addu sp+i` — no known C-source defeat for that one._ **Applicability boundary on knob (3) (2026-05-28): `int* volatile p = arg` reloads the pointer on EVERY use. It helps ONLY when the target also reloads on every use (verified +0.88pp on game_uso_func_00001DDC). It REGRESSES when the target keeps the value in a register early and spills/reloads only around calls (game_uso_func_0000B750 71.26→67.53%, game_uso_func_000043D8 similar). Check first: count the target's reloads of the value — if fewer than the C use-count (register-resident across some uses), the volatile knob over-corrects. No C knob expresses "register early, reload-after-call-only".**
- [goto-loop + register-keyword-on-src + char-cast-end DEFEATS IDO's full-unroll on small-trip-count pointer loops](#feedback-ido-goto-register-char-cast-defeats-unroll) — _For small constant-trip-count pointer loops (e.g. 4-iter 4x4 matrix transpose), IDO -O2's natural `do-while` / `while` / `for` emits a FULLY-UNROLLED giant (4-iter × 4-load body = 16 lwc1+16 swc1, dead-rolled-loop-body emitted too). The combination `goto label; ... if (cond) goto label;` + `register T *src; src = src_arg;` (explicit save) + `char *end = (char*)dst + N;` (char-cast end pointer) produces the target's exact rolled loop instead. Lever decomposition: (1) `goto` form prevents IDO from emitting both rolled-AND-unrolled bodies (do-while emits both, peeled-loop entry); (2) `register` keyword on src forces a save-to-$v1 (`or v1, a0, zero`) freeing $a0 for end-pointer-as-sentinel reuse — matches IDO's "reuse incoming arg reg for stop sentinel" pattern; (3) char-cast end (vs `float*`) prevents pointer-stride analysis from inferring small trip-count. With single `volatile int pad;` for the 8-byte frame adjustment, **goes from 80.95% cap → 89.5% byte-for-byte except 1-insn dst-base-hoist** (the residual `addiu a1, sp, 0x28` to share dst across {p init, jal arg} — cost-model IDO-internal, not C-flippable). Verified 2026-05-27 on `gl_func_0005E138` (4x4 matrix transpose + dispatch). New crack lever for the "IDO unrolls my small loop" family — supersedes 'leave inline-form-only' advice in the 2026-05-15 cap doc. **Also verified the goto-lever rolls a NESTED outer/inner do-while** (2026-05-27 game_libs_func_00042374: 43→25 insns, 1-insn target). Residual diffs in nested case = const-fold + bne-vs-bnel — both cost-model permuter-class; `volatile int a1_init` defeats the fold but trips the catastrophic-regression trap (see #feedback-ido-volatile-const-bind-catastrophic-regression)._

### char / int / signed / narrow

- [For multi-condition state checks, single boolean-return expression beats if-return chain by 70+ pp](#feedback-ido-boolean-return-xor-sltiu-chain) — When target uses `xor; sltiu; bne` chains for `(c1 || c2 || c3)` style checks (computing each condition as a 0/1 value, branching on non-zero to a shared exit), use `return c1 || c2 || c3;` in C — NOT `if (c1) return 1;…
- [IDO treats plain `char` as UNSIGNED by default — use `signed char` for `lb` opcodes](#feedback-ido-char-default-unsigned) — _Casting `(char)int_val` at IDO -O2 emits `lbu` (zero-extend), not `lb` (sign-extend).
- [Named `unsigned char c = *p;` forces $v0; inline `*p` in the comparison keeps the load in $t6](#feedback-ido-named-char-v0-vs-t6) — When the target has `lbu $t6, 0($sN)` for a char loaded from memory and compared immediately, declaring it as a local (`unsigned char c = *p`) forces IDO to allocate $v0 for the load instead.
- [IDO -O2 picks bgez vs srl+beqz for sign-test based on C form — `(unsigned)x>>31` forces 2-insn srl+beqz](#feedback-ido-sign-test-form-choice) — For `if (x < 0) {...}`, IDO -O2 emits the 1-insn `bgez x, .Lend` form (branch if non-negative, skipping the body).
- [Test arbitrary bit-N (N != 31) by `((unsigned)x << (31-N)) >> 31` — emits `sll + bgezl/bltzl`](#feedback-ido-bit-N-test-via-sll-bgezl) — _When target uses `sll t, x, K; bltzl/bgezl t, ...` to test bit N (where K = 31-N), the natural `andi+bnez` form won't match. Write `((unsigned)x << K) >> 31` to force the SLL+sign-branch form. Verified 2026-05-14 on h2hproc_uso_func_000015F0 bit-16 test (94.31% first try)._
- [1080 game_libs 67xxx libc-string family (strlen/strcat/strncpy/strstr) uses a two-pointer-lag + branch-likely idiom that clean C doesn't reproduce — recognize-and-NM-wrap](#feedback-1080-67xxx-string-lag-idiom) — _The ROM form per iteration is `move vL, cursor; lbu c, 0(vL); addiu cursor,1; bnezl c, loop` (a lag pointer vL copied from the live cursor each iter, char read via vL, plus branch-likely loop). Clean C (`while(*s++)`, `while(*d)d++`, separate-statement) emits a single-cursor `lbu c,0(cursor); addiu cursor,1` with plain branches — structurally off by the lag-copy + bnezl. Confirmed 2026-05-23 on 67FA4(strlen)/67C1C(strcat)/67C98(strncpy): all reloc-free, all NM-wrapped (recognized libc, byte-match deferred). Likely a compiler-version/idiom gap; a future focused pass could try `*p++`-with-saved-prev or permuter. NEGATIVE forms tried on 67FA4 strlen (2026-05-23, neither reproduces the `move vL,cursor; lbu 0(vL)` pointer-copy lag): (1) `while(*s++) n++;` → single-cursor `lbu 0(a0); addiu a0,1`; (2) `if(*s){do{s++;n++;}while(*s);}` → offset-fold `lbu 1(a0); addiu a0,1`. Both are 13/13 off (same opcodes, structure differs). So don't retry those two; the lag-copy likely needs a different idiom or compiler version. More family members confirmed: 67B04/67B40 (strcmp-variants, return 1 on mismatch), 67E28 (hash, but caller-set v0/v1 — separate cap)._
- [Unrolled `multu`/`mflo` loops won't byte-match — this build omits the r4300 multiply-hazard nops the ROM has](#feedback-r4300-mult-hazard-nops-missing) — _A loop like `for(i=1;i<n;i++) x*=10;` makes IDO unroll-by-4 with a `(n-1)&3` remainder loop (reproducible exactly) BUT the ROM separates each `mflo` from the next `multu` with 2 hazard nops (r4300 mult-after-mflo erratum); this build (`-Wab,-r4300_mul`) emits the multu/mflo back-to-back (no nops), so the unrolled body is N nops short. The remainder loop matches (addiu+branch already separate multu/mflo). Not a per-fn C fix — detect (back-to-back multu/mflo in an unrolled loop) and NM-wrap. game_libs_func_000611E4 (pow10), 2026-05-23._
- [Forcing `addiu base,N; sw 0(base)` for a struct RMW: REASSIGN the base pointer (a field-pointer folds to `sw N(base)`)](#feedback-rmw-reassign-base-ptr-forces-addiu-sw0) — _Target writes a field via an advanced pointer (`lw N(base); addiu base,N; sw 0(base)`); natural `p->fieldN |= x` folds to `sw N(p)` (1 insn short). Fix: `int t=*(T*)((char*)v+N); v=(T*)((char*)v+N); *v=t|x;` — reassigning the BASE forces addiu+sw-0. Refines the field-pointer-folds cap. gl_func_0000E368 95.2%→98.45% (2026-05-28)._
- [Byte-RMW clear-mask: write the exact 16-bit `andi`-fitting form (`& 0xFF7F`), NOT `& ~0x80` — the negative form mis-emits `li -129` + register-`and`, evicting a reg and cascading the whole allocation](#feedback-ido-andi-fitting-mask-vs-negative) — _For `*(u8*)p &= ~0x80`, `~0x80` = 0xFFFFFF7F doesn't fit `andi`'s 16-bit immediate, so IDO materializes `li at,-129; and rd,rs,at` (2 insns + a consumed register), which shifts every subsequent `$t` assignment. Writing the equivalent `& 0xFF7F` (the low-16 mask, identical for a byte value) emits a single `andi rd,rs,0xFF7F` AND keeps the register allocation aligned. On game_libs_func_0001CF68 this single change dropped 15→14 diffs and, more importantly, removed the register cascade root. General rule: for any `x & MASK` where MASK has the high bits set (negative-looking), use the 16-bit-truncated positive literal that `andi` accepts._
- [Reuse the parameter register as a loop counter: declare the param `int` and reassign it (→ `move aN,zero`), instead of a fresh local (→ `move v0,zero`)](#feedback-ido-reuse-param-reg-as-counter) — _When the target reuses a parameter's register as a loop counter after the param's last use (e.g. `lw v1,0x34(a0); move a0,zero` — a0 becomes the counter), a fresh `int i = 0` local lands in `$v0`/another temp instead. Fix: declare the param as `int` (not the pointer type) and reassign it: `int f(int a0, int a1){ int v1 = *(int*)(a0+0x34); a0 = 0; ... a0++ ...}`. IDO then reuses the param register for the counter = exact. Also: a `do { if (i==a1) break; ...; i++; } while (v1 != 0);` body-top break gives `beq i,a1 / bnez v1` (matching), where `while (i != a1) {...; if(v1==0)break;}` gives `beqz a1 / bnel` (off). Verified 2026-05-23 on game_libs_func_0003E0C0 (clean 12/12 episode, reloc-free linked-list walk)._
- [`bgez v0; sra t, v0, 1; addiu at, v0, 1; sra t, at, 1` is IDO's signed `/2` lowering](#feedback-ido-signed-divide-2-idiom) — Signed-integer division by 2 in IDO doesn't become a single `sra`.
- [`bgez x, +4 (DELAY: andi t, x, M-1); beq t, $0, +2; nop; addiu t, t, -M` is IDO's signed `x % POW2` lowering](#feedback-ido-signed-modulo-pow2-idiom) — _Signed remainder by a power-of-2 mask M (e.g. M=8 → mask=7) emits a fast-path / slow-path sequence: delay-slot ALWAYS computes `t = x & (M-1)`; if x>=0 jump straight to use (low bits ARE the remainder, 0..M-1); if x<0 AND those low bits are nonzero, subtract M to get a negative remainder (-(M-1)..-1). Write as `x % M` (signed int) in C. Spotted 2026-05-18 on gl_func_00009EBC's `(a2 % 8) << 3` grid-index computation._

### inline / register keyword

- [Inline nested pointer deref uses $v0; named local forces $t-reg](#feedback-ido-inline-deref-v0) — When target asm uses `lw $v0, off(a0); lw $tN, 0x10($v0)` for a two-step pointer deref, keep the expression inline as `*(int*)(*(int*)(a0 + off) + 0x10)` — a named local `int *t = ...; t[...]` makes IDO pick a $t-reg…
- [IDO inline expression keeps $t6/$t7 registers, named local moves to $at/$v1](#feedback-ido-inline-keeps-t-regs) — For pointer-arithmetic functions like `return a0 + idx*N + K`, fully inline single-expression form keeps temps in $t6/$t7 registers (matching target's natural pick); naming a local for the offset shifts temps to $at/$v1.
- [Mix named-local and inlined access in the SAME function to get per-use-site reg allocation (named → $v, inline → $t)](#feedback-ido-mix-named-and-inline-per-usesite) — When a function has the same expression (e.g. `(int*)a0[OFF/4]`) used both in pre-call argument setup AND in post-call follow-up stores, the natural choice (one named local) caps below 100% because IDO reuses the…
- [Named intermediate `char *t = base + OFFSET` forces IDO to split `lw/sw` addressing into `lw + addiu + sw(N)` even when the offset fits in 16 bits](#feedback-ido-named-base-forces-addiu-split) — When target has `lw t, 0x30(a0); addiu t, t, 0x758; swc1 fN, 0x10(t)` but inline-deref C generates `lw t, 0x30(a0); swc1 fN, 0x768(t)` (merged offset), use a named local `char *t = ... + 0x758;` followed by `*(float*)(t…
- [reusing one named local across sequential alloc-then-populate blocks regresses IDO match](#feedback-ido-named-local-reuse-across-alloc-blocks) — When a function has multiple `out = alloc(N); if (out!=0) write(out, ...)` blocks back-to-back, sharing one named `out` local across them confuses IDO's dataflow tracking and tanks the match.
- [IDO cfe does not accept `register T var asm("$N")` (GCC extension)](#feedback-ido-no-gcc-register-asm) — The `register T var asm("$register")` trick for forcing a specific MIPS register — which IS supported by KMC GCC 2.7.2 (Glover) — is NOT supported by IDO 7.1's cfe.
- [IDO -O0 — `++j < N` keeps j in register across back-edge slt; `j++; while(...)` spills+reloads](#feedback-ido-o0-pre-increment-keeps-register) — _For do-while loops at IDO -O0, `do {...} while (++j < N)` keeps the incremented j in $t8 across the loop-end `slt at, j, N` test.
- [IDO -O0 respects `register` for $s0 and inline-callable exprs avoid stack spills](#feedback-ido-o0-register-and-inline) — At -O0, IDO normally assigns every local to a stack slot and reloads on every use.
- [IDO -O0 with two `register` locals — declaration order flips which gets $a2 vs $a3 (later-declared gets HIGHER-numbered $a-reg)](#feedback-ido-o0-register-decl-order-flips-a-alloc) — When matching an -O0 function that uses two `register` locals filling the unused $a-slots (e.g., $a2 and $a3 when only a0/a1 are real args), the order you DECLARE them controls which gets which slot.
- [IDO -O0 reserves a 4-byte backup stack slot for EACH `register`-typed local — adds frame overhead beyond what target needs](#feedback-ido-o0-register-locals-reserve-backup-stack-slots) — _At -O0, IDO honors `register T *p` hints to save callee-save s-regs (s0/s1/s2/s3) — but ALSO reserves a 4-byte backup stack slot per register-typed local.
- [IDO register keyword for $s0 allocation](#feedback-ido-register) — IDO respects 'register' as a strong hint — required to match libultra interrupt-bracket functions
- [IDO `register` keyword promotes to $s-class but doesn't pin the $s-number](#feedback-ido-register-promotes-class-not-number) — _Adding `register T x;` on locals forces IDO to allocate them to callee-saved $s-regs instead of caller-saved $t/spills.
- [IDO spill+reload register pair — partially flippable via volatile-spill-shaping](#feedback-ido-spill-reload-register-pair-locked) — _Initial belief: spill+reload pair across a jal is jointly locked (89.5% cap).
- [IDO $t-register swap unreachable — first-seen pseudo gets lowest $t number, can't be flipped from C](#feedback-ido-t-register-swap-unreachable) — When target has `$t7` for the FIRST paired-load and `$t6` for the SECOND (i.e. registers in DECREASING order), IDO at -O2 will always pick the opposite — first-seen → $t6, second-seen → $t7.

### optimization level (-O0/-O1/-O2/-O3)

- [0x14 stub `sw a0,0(sp); b +1; nop; jr ra; nop` = `void f(int a0) {}` compiled at -O0](#feedback-ido-o0-empty-stub) — The IDO -O0 output for `void f(int a0) {}` is exactly 5 instructions — no prologue/epilogue, a0 spilled to caller's arg slot, a redundant forward-1 branch.
- [IDO -O0 swap == operands to control which side loads FIRST](#feedback-ido-o0-eq-operand-swap-for-load-order) — _For an `if (LHS == RHS)` comparison in IDO -O0 mode, the side on the RIGHT of `==` is evaluated FIRST.
- [IDO -O0 field-load order isn't controlled by C expression order](#feedback-ido-o0-load-order-not-expression-driven) — _At -O0, reading two fields from the same base pointer (`p[1]` and `p[2]`) inside a single boolean expression emits loads in the OPPOSITE order from what the C says — and flipping the expression doesn't flip the emitted…
- [IDO -O0 `lui tA; lw tA, %lo(D)(tA)` reuse is the default; forcing fresh-temp `lw tB` is unreliable](#feedback-ido-o0-lui-lw-reuse) — _When the target asm reads a D_* global at -O0 with `lui tA; lw tB, %lo(D)(tA)` (fresh register for dest), plain `if (D == C)` produces the reuse form `lw tA, %lo(D)(tA)`.
- [IDO -O0 gives target-prefix bytes for unfilled-delay-slot leaves, but adds dead trailing jr-nop — not trimmable from C](#feedback-ido-o0-prefix-match-dead-epilogue) — _For 3-insn leaf setters (`sw X, off(a0); jr ra; nop`) that IDO -O2 compacts into 2 insns (`jr ra; sw X, off(a0)`) — the classic `feedback_ido_unfilled_store_return.md` cap — -O0 DOES emit the 3 target insns as a…
- [IDO -O2 `sw ra; lui a0` order for 1-arg 1-call void wrappers is unflippable from C](#feedback-ido-o2-tiny-wrapper-unflippable) — _Simple `void f(void) { func(&SYM); }` wrappers at IDO -O2 always emit `addiu sp; sw ra; lui a0; jal; addiu a0(delay)`.
- [Value-returning -O0 functions emit an extra return-branch this toolchain can't fold — likely a systematic cap](#feedback-ido-o0-value-return-extra-branch) — _A value-returning -O0 function ends with TWO branches (return's `b epilogue` + the body's `b +1` marker); many 1080 targets have only one. Void -O0 funcs match fine; value-returning ones are +1 insn. Suspected IDO patch-level divergence._
- [Float function-return used in an expression is preserved in callee-saved $f20 — target uses $f0 directly (toolchain cap)](#feedback-ido-float-call-result-preserved-in-f20) — _This IDO build moves a float call-return to callee-saved $f20 (+save/restore) before the next FP operand; targets keep it in $f0. Not C-fixable. Caps float-returning-call expressions (mgrproc_uso_func_000005D0)._
- [-O0: a dead reassignment of a `register` var reproduces a stray `lui sN; addiu sN` symbol-materialize](#feedback-ido-o0-dead-reassign-forces-s-reg-materialize) — _Reproduce a target's dead `&D` address-materialize into a callee-saved reg via `register int v; ...; v = (int)&D;` (no DCE at -O0). Reuse the same register var to keep it in s0. Took mgrproc_uso_func_00000504 byte-exact._
- [IDO -O3 produces byte-identical output to -O2 for single-file compiles — file-split with OPT_FLAGS=-O3 only adds value for inter-module (IPO) builds, which the per-.c.o pipeline doesn't use](#feedback-ido-o3-equals-o2-for-single-file-compile) — _When a function is stuck at -O2 codegen and you're considering file-split-with-OPT_FLAGS to try -O3, don't bother — IDO's -O3 differs from -O2 only in inter-module optimization (requires `cc -O3 -j ...`).
- [-O0-cluster split mid-file requires a paired -O2 layout shim, not just the -O0 file](#feedback-o0-cluster-split-with-layout-shim) — _When a -O0 cluster sits MID-file (not at start or end), splitting it out needs THREE files: predecessor (truncated), the -O0 cluster file, AND a successor "layout shim" (-O2 INCLUDE_ASMs only) holding everything…
- [New -O0 .c file split needs FOUR config touches; objdiff.json is the easy-to-miss one](#feedback-o0-file-split-objdiff-json-step) — _When carving an -O0 function out of its parent .c into a dedicated `<seg>_o0_<offset>.c` file, you need (1) Makefile per-file `OPT_FLAGS := -O0` and `TRUNCATE_TEXT`, (2) tenshoe.ld entry, (3) source split itself, AND…
- [Loop reloads ALL locals from sp every iteration = -O0 codegen signal](#feedback-ido-o0-loop-stack-reload-signal) — _When a function's loop body starts with `lw tA, X(sp); lw tB, Y(sp); lw tC, Z(sp)` for variables that have no `volatile` or address-taken reason, it's almost certainly -O0 compiled. -O2 keeps loop-carried values in registers (only ra + callee-saves spill). Detection signal: before writing C, check if the loop body's first 3 insns are `lw` from sp-relative offsets matching the function's own prologue spills — if yes, abandon -O2 attempts and either (a) file-split to per-function OPT_FLAGS=-O0, or (b) accept INCLUDE_ASM. Verified 2026-05-14 on gl_func_00071864 (16-bit byte-sum checksum, 23 insns): straightforward -O2 C body produced 5.4% match because target reloads p/accum/i from sp every iteration._
- [-O0 variant of the int-reader accessor template — 19 insns / 0x4C bytes vs the standard -O2 template's 16 insns / 0x40 bytes](#feedback-o0-int-reader-template-variant) — _When scanning USO accessor templates, also check 0x4C-byte / 19-instruction variants — these are -O0 compiles of the SAME body.
- [Stack-residency does NOT imply -O0 — `residency + FILLED delay slots` is an -O1 build with original register-pressure spill, NOT reproducible by the project cc](#feedback-ido-stack-residency-plus-filled-slots-is-o1-not-o0) — _Refines `#feedback-ido-o0-loop-stack-reload-signal`: loop-reloads-all-locals is necessary but NOT sufficient for -O0. -O0 ALSO leaves delay slots UNFILLED (b;nop / jr;nop). If the target reloads locals from sp every use AND has its delay slots FILLED (≈0-1 nops), it is NOT -O0 — it is an -O1 object whose original register pressure spilled those locals while the assembler still filled slots. The project cc can't emit that combo: -g1/-g2 force residency but leave slots unfilled; plain -O1/-O2 fill slots but register-allocate the locals away. Permuter can't help (can't add assembler-level slot filling); a `volatile` base adds a reload the target lacks. Genuine cap. Verified 2026-05-25 on gl_func_00070194/000718C0/0003D914 (previously mis-tagged "-O0 carve candidates")._
- [-O0 stack-offset +8 shift between mine and target — declaration reorder + extra padding locals all grow the frame instead of shifting layout (gl_func_00008A40, 4-diff stays 4)](#feedback-ido-o0-local-offset-shift-not-c-reachable) — _When -O0 codegen produces a 4-diff residual where target's struct locals are at sp+8 higher offset than mine but frame size is identical: declaration reorder, type swaps (Tri3i → long long pad), or adding pad locals all GROW the frame (extra 8 diffs from prologue/epilogue) without shifting tmp/raw's offsets the desired +8. The -O0 allocator's bottom-padding-vs-top-padding choice between saved-regs and locals isn't driven by C-source structure. Verified 2026-05-27 on gl_func_00008A40 (4 stack-offset diffs at 0x24/0x38/0x3c/0x5c): swap raw↔tmp decl order, add 12-byte pad_low first, add long long pad_align first — all worsened to 8 diffs. Cap class: -O0 stack-layout non-determinism similar to register-rename cap. Don't grind -O0 4-diff stack-offset residuals; wrap NM with stack-layout-cap label._
- [-O0 RETURN-VALUE functions get a DEAD second `b epilogue; nop` after the return's branch — our ido-static-recomp cc emits it, the original 1080 toolchain didn't; not C-fixable (TOOLCHAIN-BINARY GAP, blocks all -O0 return fns)](#feedback-ido-o0-return-value-dead-double-b) — _A frame-having -O0 function ending in `return X;` compiles to `lw v0,off(sp); b epi; nop; b epi; nop; <epilogue>` — TWO unconditional branches to the epilogue (the return's, then a dead/unreachable closing-brace one). The 1080 target has only ONE. Proven a toolchain-binary codegen gap, NOT a C-structure issue: the trivial `int f(int*a0){int x=a0[0];g();return x;}` reproduces the double-b. Full matrix (IDO 7.1 AND 5.3): -O0/-O0-g/g1/g2/g3 and -O1-g/-O1-g2 all give b=2 with full -O0 reloads; -O1-g3/-O2/-O2-g3 give b=0 (over-optimized, registers cached, breaks the -O0 reload structure). NO setting yields the target's "b=1 + full reloads". VOID -O0 functions are unaffected (no return → the single closing-brace b is LIVE and matches — that's why void -O0 fns DO land, e.g. gl_func_000093DC). Blocks ALL -O0 return-value fns project-wide (func_00011B5C, arcproc_uso_func_0000012C, gl_func_000092F4, etc.). Removing the dead b post-cc would be match-faking (BANNED). Only real fix = the exact original 1080 IDO cc binary that elides it (focused acquisition, not a tick). Verified 2026-05-25._

### indirect / function pointer

- [Inline function-pointer call → IDO uses `jalr $t9`; naming as local → `$a1` or other](#feedback-ido-indirect-call-t9) — _For indirect calls via a struct member (`(*struct->callback)(args)`), keep the function-pointer EXPRESSION inline inside the call.
- [`volatile T buf[N]` forces IDO to emit `addiu tA, sp, off; lw tB, 0(tA)` (pointer-indirect load) instead of `lw tB, off(sp)` (direct sp-relative)](#feedback-ido-volatile-buf-pointer-indirect) — When the target asm uses `addiu tA, sp, off; lw tB, 0(tA)` (materialize stack address into a temp register, then load via the temp) instead of the standard direct `lw tB, off(sp)`, declaring the local buffer as…

### other

- [Asm epilogue with no `move v0, ...` before `jr ra` indicates void return — match the C signature](#feedback-ido-epilogue-no-move-v0-implies-void-return) — _When the target's epilogue is `lw ra, X(sp); addiu sp, sp, +N; jr ra; nop` with NO `move v0, ...` (or `or v0, ..., zero`) immediately before `jr ra`, the function returns `void`. C bodies declared as `T *fn(...)` with `return X;` will emit a spurious `move v0, X` that doesn't appear in target. Fix: declare as `void fn(...)`, drop the `return X;`. Verified 2026-05-07 on `game_uso_func_00001DDC`: 19.64% → 19.90% just from the signature change._
- [`(char*)&D_00000000 + 0xK` constant-folds field offsets into per-access absolute `lui;lw` — use a distinct relocated symbol for a held base register](#feedback-ido-generic-reloc-base-folds-vs-distinct-symbol) — _When the target keeps a single reloc base in a reg/stack and uses base+offset for many fields of one object, the generic `(char*)&D_00000000 + 0xK` makes IDO -O2 fold each `obj+fieldoff` into a separate ABSOLUTE `lui;lw` (no held base; shorter, wrong frame). A distinct `extern T D_000K;` + `&D_000K` keeps the symbol address in one reg (its own HI/LO reloc; offsets stay immediates). The distinct symbol must be in the segment symbol table (undefined_syms_auto.txt / splat) or it's a link error. Seen 2026-05-18 on `gl_func_0006A304` (USO pointer-fixup driver, NM-wrapped pending symbol plumbing)._
- [IDO `addu` operand order depends on whether expression is split into a named local](#feedback-ido-addu-operand-order) — For `v1 = A + B` in C, IDO picks `addu $rd, $rs, $rt` with `$rs = first-computed operand` and `$rt = second-computed operand`.
- [IDO doesn't share `lui $at` across stores to adjacent externs — struct retype DOESN'T fix it at -O1](#feedback-ido-adjacent-extern-shared-at) — _IDO -O1 (and possibly -O2) emits a fresh `lui $at` before EACH store to an external symbol, even when the symbols are adjacent bytes AND are declared as fields of a single struct.
- [Two adjacent-offset global stores — split into per-store extern symbols to force `lui $at` per store](#feedback-ido-adjacent-store-extern-split) — _When target emits `lui $at, HI; sw X, 0($at); lui $at, HI; sw Y, 4($at)` (two independent `lui $at` per store, no cached base pointer), writing the obvious C `*(int*)&SYM = X; *((int*)&SYM + 1) = Y;` makes IDO cache…
- [IDO C compiler treats `__asm__("nop")` as a FUNCTION CALL, not inline-asm](#feedback-ido-asm-intrinsic-treated-as-function-call) — _IDO 7.1 does NOT support GCC's `__asm__("...")` inline-asm syntax.
- [IDO target's "base-adjust trick" (addiu base, base, +N then use smaller offsets) isn't reachable from natural C](#feedback-ido-base-adjust-for-clustered-offsets) — When target asm does `addiu $v1, $v1, +0x2C` once and then accesses fields at offsets 0xC, 0x0, 0x10, etc. (= original 0x38, 0x2C, 0x3C of the struct), it's an IDO-O2 base-adjust optimization for accessing a CLUSTER of…
- [IDO stack placement — use `int buf[2]` not `int buf` to force 8-byte alignment](#feedback-ido-buf-array-alignment) — When a stack buffer ends up 4 bytes higher than target, try declaring it as `T buf[2]` instead of `T buf`; IDO aligns arrays to 8 bytes, simple scalars to 4.
- [IDO 7.1 cfe rejects specific non-C-syntax chars EVEN IN COMMENTS — concrete blocklist](#feedback-ido-cfe-strict-ascii-gotchas) — _The general rule "no unicode in C source" is well known, but IDO 7.1's cfe is stricter than standard C — it rejects specific characters even inside `/* ... */` comment blocks.
- [For 16-case sparse dispatchers in segments without .rodata, `if (a1 == N) goto cN;` chain beats both switch (jumptable) and if-else-if chain](#feedback-ido-dispatch-goto-chain-beats-switch-and-ifelse) — _When the target asm is a chain of sequential `li at, K; beq a1, at, body_K` (compares grouped at top, case bodies after), straight `if-else-if` produces 49 % match (interleaves bodies) and `switch` produces 69 %…
- [IDO -O2 `void f(void) {}` produces exactly `jr ra; nop` — empty functions ARE matchable](#feedback-ido-empty-void-matchable) — _The CLAUDE.md general note ("Empty functions should stay as INCLUDE_ASM — the compiler typically omits the delay slot nop") is WRONG for IDO 7.1 at -O2.
- [Tiny branch-predicate funcs with forced `addiu sp, -8/+8` frame + explicit `b` to epilogue — unreachable from IDO -O0/-O1/-O2](#feedback-ido-forced-frame-tiny-predicate) — Some 7-9-insn predicate functions (e.g. `return (a & MASK) != 0;`) have a target shape with a forced stack frame (`addiu sp, -8` prologue / `addiu sp, +8` in jr delay slot) AND an explicit `b` to the epilogue-merge…
- [Use `goto end` for early-return from alloc-check; plain `return` emits extra branch. **Three variants: UNIFIED-epilogue (`goto end; ... end: return a0;`), SPLIT-epilogue (`goto end_zero; ... return DERIVED; end_zero: return 0;`), and FALL-THROUGH-WITH-NULL-GUARD (`if (X != 0) { partial body }` instead of `if (X == 0) return 0;` when target's beq lands MID-BODY, not at full end). Verified 2026-05-14: split form on gl_func_00021E08 (68.65% → 100%), fall-through form on titproc_uso_func_00001B10 (51.93% → 73.40%) AND sibling titproc_uso_func_00001D7C (59.36% → 84.20%)](#feedback-ido-goto-epilogue) — _IDO compiles `return a0` from inside a nested if into `b + lw ra` redundancy, not a direct `beqz/bnez` to the epilogue.
- [INVERTED-COND + `goto success` recipe for targets with SEPARATE fail/success epilogues + explicit `b success` mid-function](#feedback-ido-inverted-goto-success-separate-epis) — _The opposite-direction sibling of `goto end`. When target asm has `bnez (fail) + b success` with the fail epi (`jr ra; move v0, zero`) INLINE between the bnez and the success epi, the natural `if (overflow) return 0; ... return cur;` form lets IDO merge both paths into a `beqzl + load-hoist` tail (one shared epi, ~73%). Inverting and goto'ing forces the target shape: `if (!overflow) { a0[1] = newcur; goto success; } return 0; success: a0[3]++; return cur;` emits `bnez ... + b success + inline-fail-jr + success-epi-block` (+16pp lift on game_libs_func_0001FDF4: 73.09% → 89.23%). Sister to feedback-ido-goto-epilogue but for two-epi-distinct shapes. Last-1-insn cap remains: bnez delay fills with `nop` instead of target's `move v1, a2` save-cur-for-return (live-range split unreachable from C, permuter-class)._
- [IDO implicit decl conflicts with later explicit extern](#feedback-ido-implicit-decl-extern-conflict) — K&R-implicit `int func()` from a call BEFORE the explicit `extern void func()` declaration causes IDO cfe to error "Incompatible function return type"
- [IDO places locals first-declared-highest; add leading pad local to shift scratch slot down](#feedback-ido-local-ordering) — If your local `scratch` ends up at sp+0x1C but the target wants sp+0x18, declare an extra `int pad` BEFORE scratch.
- [`or v0, v1, zero` after jal = wrapper returning low word of callee's 64-bit return](#feedback-ido-long-long-v1-move) — In 1080 USO wrappers, the target `or v0, v1, zero` right before `jr ra` means the callee returns a `long long` and the wrapper returns only the low 32 bits.
- [Consuming a 64-bit CALL return: extract hi/lo with a UNION, not `(int)(r>>32)`](#feedback-ido-consume-64bit-call-return-union) — _When a callee returns 64-bit (v0=hi,v1=lo) and you need both words, `(int)(r>>32)` emits a CALL to a shift helper (bloat; objdiff-None). A `union{long long ll; struct{int hi,lo;} w;}` stores v0:v1 and reads the words, matching the target's stack roundtrip. Do 64-bit arithmetic with manual int hi/lo (subu/sltu/subu). Verified gl_func_000743C4 → 55% 2026-05-28._
- [IDO doesn't accept bare `__asm__("")` as a scheduling barrier](#feedback-ido-no-asm-barrier) — _The GCC trick of `__asm__("")` to force an instruction ordering barrier is NOT supported by IDO 7.1.
- [`&BASE + 0xOFFSET` vs `extern SYM_AT_OFFSET` produces different .o byte patterns even when addresses are equal](#feedback-ido-offset-in-instruction-vs-reloc) — _When target asm has `lw $reg, 0xNNN($at)` (offset baked into the instruction), write `*(int*)((char*)&BASE + 0xNNN)` in C — this emits `lw $reg, 0xNNN(...)` matching the target.
- [IDO can't fold `&SYM + 0xCONST + runtime` into 3-insn lui/addiu/addu — always factors constant onto runtime side (4 insns)](#feedback-ido-symbol-offset-runtime-cannot-fold) — Pure-address-computation analog of the load-offset-vs-reloc rule: IDO emits 4 insns (lui-D / addiu-CONST-on-runtime / addiu-D-lo / addu) where expected has 3 (lui-D-with-CONST / addiu-D-lo-with-CONST / addu). Workaround: per-offset extern + undefined_syms entry + INSN_PATCH for the linked-imm word.
- [Force IDO to materialize `&D` in `$v1` (lui+addiu pair) by combining named-local-for-first-deref with inline-second-deref of same offset](#feedback-ido-v1-base-materialization-via-second-inline-deref) — When target reloads `lw $aN, OFF($v1)` after a store via `lw $v0, OFF($v1); sw _, _($v0)`, name the first deref as a local (locks $v0) and INLINE the second deref inside the call arg expression (triggers base sharing in $v1).
- [Standard accessor templates at -O0 produce 3 extra insns (`b +1; nop` dead tail jump) vs the -O2 form](#feedback-ido-o0-accessor-template-extra-b1-nop-tail) — Asm with the Quad4/Vec3/int-reader shape PLUS a dead `b +1; nop` between the last copy-store and the epilogue → function lives in an -O0 file. Same C body matches at both opt levels; the dead tail jump is a natural -O0 scheduling artifact.
- [Parameter type signedness shifts allocno priority — `int` vs `unsigned int` changes downstream register-name chain](#feedback-ido-arg-type-signedness-shifts-allocno-order) — Same C body, same insn count, same shift opcode — but `int a1` vs `unsigned int a1` flips the surrounding register names by one position. The cast-to-unsigned inside the shift expression is enough for srl; the signature type independently controls allocno ordering. Try both when register names are 1 off.
- [IDO -O2 multi-arg setters — put register-only stores LAST in source order to keep stack-arg lw/sw pairs adjacent](#feedback-ido-reg-only-store-ordering) — For 6+arg setters where stack args (sp+0x10, sp+0x14) go to struct fields, IDO's scheduler hoists cheap register-only stores (`sw aN, N(a0)`) into load-use gaps.
- [IDO picks $v0 (not $v1) when a literal flows to the return register — unflippable](#feedback-ido-return-flowing-v0-unflippable) — _When asm has `addiu $v1, $zero, N` preloaded into a branch delay slot + `or $v0, $v1, $zero` at shared return block, IDO cannot reproduce this from C.
- [For IDO functions whose asm sets BOTH v0 and v1 as outputs, signature is s64 — return `((s64)hi << 32) | (u32)lo`](#feedback-ido-s64-pack-return-via-lo-hi) — _When asm shows distinct values flowing into both v0 (return-low) and v1 (return-high) at the function epilogue (e.g. `or v0, ret_lo, zero; or v1, ret_hi, zero; jr ra`), the function signature is `long long`/s64 (o32…
- [IDO -O2 leaf with `addiu sp,-8` but no stack use is unreachable from standard C](#feedback-ido-sp-frame-without-stack-use) — When target has a leaf function with stack frame adjust (`addiu sp, sp, -8` / `addiu sp, sp, +8`) but NO sw/lw using the frame, no standard C idiom produces this at IDO -O2.
- [kernel/func_80008030 (SP_STATUS & 3 check) not reproducible from C at -O1 or -O2](#feedback-ido-sp-status-check-unreachable) — _Simple `if ((SP_STATUS & 3) == 0) ret |= 1;` function (0x24 = 9 insns, no stack frame, ret in $v0 with `or v0,zero,zero` + `ori v0,v0,1`) is not reachable from IDO C. -O1 spills ret to stack (adds 4 insns); -O2 routes…
- [IDO -O2 picks the lowest-available spill slot when the frame has unused space; can't force a higher slot without bloating the frame](#feedback-ido-spill-slot-picks-low-offset) — When IDO -O2 needs to spill a $aN/$tN register across a jal, it picks the LOWEST available slot above the ra-save (e.g. if ra=sp+0x14, it picks sp+0x18).
- [Split `char pad[N]` into pad-before-buf + pad-after-locals to fine-tune array offset within a fixed frame size](#feedback-ido-split-pad-for-buf-offset) — When you need a buf at a specific stack offset (e.g., target wants `swc1 $f0, 0x34(sp)` with frame 0x48 but your single `pad[N]` only puts buf at 0x28 or 0x38), split the pad into TWO declarations bracketing your…
- [IDO -O2 schedules "store non-delay" before "addu feeding delay-slot store" — unreachable from C](#feedback-ido-sw-before-addu-unreachable) — IDO -O2's list scheduler picks `sw $reg, N(a0)` before `addu $t1, a0, $t0` when both are ready and the addu's output is needed for the jr delay slot store.
- [IDO `switch` statements emit a `.rodata` jump table — breaks 1080's linker (rodata discarded)](#feedback-ido-switch-rodata-jumptable) — Writing a C `switch` at IDO -O2 with 3+ cases produces a jump table in `.rodata` and a `lui+addu+lw+jr` dispatch.
- [bootup_uso void setters use unfilled delay slot (sw; jr; nop) — not matchable from C](#feedback-ido-unfilled-store-return) — _Some bootup_uso tiny void setters produce `sw; jr $ra; nop` instead of `jr $ra; sw` (delay slot).
- [Splat synthetic stubs — INCLUDE_ASM + file-scope `extern int f()` (K&R, int return)](#feedback-ido-unspecified-args) — _For stubs like bootup_uso's func_00000000 that callers use with varying arg counts and sometimes want a return value: INCLUDE_ASM the body, and file-scope declare `extern int f();`.
- [IDO $v0 vs $t-regs — named locals get $v0, inlined expressions get $t6/$t7/$t8](#feedback-ido-v0-reuse-via-locals) — IDO assigns $v0 to named locals (esp. short-lived ones) and $t-regs to intermediate expression temps.
- [Init pointer/end locals AFTER the call so they don't live across it — IDO uses caller-save regs instead of spilling to stack](#feedback-ido-init-locals-after-call-avoids-spill) — _When loop pointers/end-markers are only used POST-call, declaring them uninitialized at top + initializing AFTER the call keeps them in caller-save $t/$v regs with no stack slot. Putting `int *src = buf; gl_func(...); ...` (init BEFORE call) forces IDO to spill src to stack across the call. Verified 2026-05-13 on game_uso_func_0000C12C: 0 % → 81.27 % from init-after-call alone._
- [Brace-block scope for short-lived named locals keeps stack frame at natural size](#feedback-ido-brace-block-scope-saves-stack-frame-bytes) — When you introduce named locals to flip IDO's reg pick, declaring at function scope grows the frame by 8 bytes; wrapping in `{ }` keeps the frame natural while preserving the reg-pick win. Verified +0.21pp on mgrproc_uso_func_00001AD0.
- [`void f(int a0, ...)` with empty body spills all 4 arg regs to caller slots](#feedback-ido-varargs-empty-body) — When target asm is `addiu sp, -8; sw a0, 8(sp); sw a1, 12(sp); sw a2, 16(sp); sw a3, 20(sp); jr ra; addiu sp, 8` — 4 consecutive spills of a0..a3 to caller's arg area, no jal, no other body — the original C was a…
- [Typed-varargs extern (`int f(int,int,...)`) does NOT force IDO -O2 caller-side stack-arg spills (sw a1,4(sp); sw a2,8(sp))](#feedback-ido-varargs-extern-doesnt-force-caller-spill) — _When target asm shows defensive `sw a1,4(sp); sw a2,8(sp)` spills around a jal but mine doesn't, the natural fix-attempt is to declare a unique-aliased extern with explicit varargs sig.
- [Use `void` return when target doesn't restore $v0 — int return forces IDO to spill v0 across calls](#feedback-ido-void-return-avoids-v0-spill) — When the asm doesn't have an explicit final `or v0, ...` epilogue insn AND v0 is consumed by an intermediate call (e.g. as $a2 arg in delay slot), the C should be `void` return, not `int`.
- [Use `volatile T *arg` to prevent IDO from fusing two `sb`/`sw` stores to the same address](#feedback-ido-volatile-preserve-redundant-io) — When the target asm has two distinct stores to the same address (e.g. `sb $t9, 0(a0); sb $t0, 0(a0)` where the second value is derived from the first), plain C emits ONE store because IDO fuses `*a0 = val; *a0 = val |…
- [`volatile int saved_arg = aN;` forces IDO to spill aN to a LOCAL stack slot instead of the caller's outgoing-arg slot](#feedback-ido-volatile-unused-local-forces-local-slot-spill) — _When target has `sw $aN, 0x24(sp)` (local-slot offset) but your IDO build emits `sw $aN, 0xBC(sp)` (caller's outgoing-arg slot at sp+frame_size+slot), the difference is whether IDO treats the saved arg as "live local"…
- [`(void)a; (void)b; (void)c;` after the call forces IDO to spill ALL incoming args to caller's outgoing-arg-shadow](#feedback-ido-void-cast-arg-spill) — _Multi-arg forwarder pattern: `f(a, b, c) { callee(&D); (void)a; (void)b; (void)c; }` emits `sw $a0,0x18(sp); sw $a1,0x1c(sp); sw $a2,0x20(sp)` (varargs-prologue-style) instead of register-shifting args. Sister technique to `volatile int saved` but for many args._ **2026-05-27 INTERLOCK NOTE**: switching FROM `volatile int aN_sp = aN;` (which allocates a 4-byte local at sp+0xLOW) TO `(void)&aN;` (which only spills to caller's shadow at sp+0xHIGH) **shrinks frame by the freed local-slot bytes**. Compensate with `char _pad[N];` (e.g. +8 bytes) to keep frame size constant, OR you'll lose 8 bytes of frame and shift every downstream sp-relative ref by -8. Verified on game_uso_func_000044F4 (spine #1): the (void)&aN switch correctly placed args at sp+0xE8/0xEC/0xF0 but the lost volatile-local slot dropped the frame from 0xE8→0xE0, net -0.5pp match. Always pair `(void)&aN` migrations with frame-padding adjustments in a single edit.
- [Signed `%` (and `/`) on a memory-loaded divisor emits a `break 7` (÷0) AND a `break 6` (INT_MIN/−1 overflow) guard pair — C-unsuppressible](#feedback-ido-signed-mod-break-pair) — _A C `(a + b) % n` where `n` is loaded from memory compiles to `div $zero,t4,t5; mfhi tP; bnez t5,+2; nop; break 7` THEN (for the result use) `addiu at,$zero,-1; bne t5,at,+2; lui at,0x8000; bne t4,at,+2; nop; break 6`. The `break 7` is the divide-by-zero trap; the `break 6` is the signed INT_MIN/−1 overflow trap MIPS HW can't represent. Both are emitted for signed `/` and `%` whenever the divisor isn't a compile-time-known nonzero constant — there is NO C form that suppresses them (they're part of IDO's signed-div lowering, not optimizer-removable). A ring-buffer index `idx=(first+count)%max` (inlined osSendMesg shape) therefore caps <100 from plain C unless `max` is a literal. Verified 2026-05-17 func_800044CC (libultra PI-event callback). Use `unsigned` operands to drop to `divu` + only `break 7` (no overflow guard), or post-cc INSN_PATCH if the target really uses signed div._
- [Trailing `lw v0,saved(sp)` reload (Δ+1 vs target) = `return saved_var` where the target returns the last call's result — change to `return last_call(...)`](#feedback-ido-return-saved-var-trailing-reload) — _A wrapper `r = cb(1); cb(...); cb(...); cb(r); return r;` spills `r` to stack (passed to the last call), then `return r` adds a trailing `lw v0,saved(sp)` reload → Δ+1 / ~95% vs a target that has no v0 reload before the epilogue. The target returns the LAST call's value (v0 already live), so write `return cb(r);` (or `return last_call(...)`) to drop the reload. Quick diagnostic: align built vs target; if the ONLY real diff is one extra `lw v0,K(sp)` right before `addiu sp` / `jr ra`, it's this. Verified 2026-05-23 gl_func_00034C7C (94.7→100). Likely the same shape for several of the Δ+1 count-mismatch near-misses._
- [Split a `<<16` shift into `(x<<15)<<1` to renumber the temps IDO allocates for a multi-field word-pack](#feedback-ido-split-shift-temp-renumber) — _A 2-word GBI command packer `a0[0]=((a1&0xFF)<<16)|CMD|(arg4&0xFFFF); a0[1]=(a2<<16)|(a3&0xFFFF);` compiles with the second word's temps numbered one lower than the target (t2/t3/t4 vs t3/t4/t5) — a register-renumber residual that doesn't byte-match. Writing the shift as `(a2<<15)<<1` (two shift insns folded back to one `sll ,16` by the optimizer, but the extra RTL node bumps the temp numbering) makes IDO allocate t3/t4/t5 → byte-exact. Permuter-discovered; matched 3 siblings (game_libs_func_0001D624/D770/D7A4). Try it when the ONLY diff is a uniform +1/−1 `$t` renumber on a shift-heavy expression and plain forms won't budge._


---

<a id="feedback-ido-split-shift-temp-renumber"></a>
## Promoted loop-invariants get saved registers in UCODE-ENCOUNTER ORDER — reorder C references to flip a base↔constant $s-reg swap

_When two loop-invariant values (e.g. a base pointer and a multiplier constant) both get promoted to saved registers, and the build has them in SWAPPED registers vs the target (base=$s5/mult=$s4 instead of base=$s4/mult=$s5), it's an encounter-order tiebreak. IDO's uopt assigns the lower saved reg to whichever loop-invariant is **referenced first in the UCODE op stream**. In `s1 = base + buf[i]*24`, the multiply (`umpy buf[i],24`) is evaluated before the add (`uadd product,base`), so `24` is encountered first and grabs `$s4`. Splitting into `s1 = base; s1 += buf[i]*24;` references `base` first → `base=$s4`, `24=$s5`._

**Confirmed via the regalloc dump** (`cc -Wo,-zdbug:6` → `./uoptlist`, see project_1080_regalloc_dump memo). Reading the dump: the `N: N assigned (constrained) R` lines map UCODE-candidate→register; promoted loop-invariant constants are the candidates CREATED during reg-alloc-prep (index higher than the UCODE-listed vars), assigned in creation order, and `R` maps `14..21 = $s0..$s7`. So the contested-register winner is the earlier-created (earlier-encountered) candidate — reorder the C so the value you want in the lower reg is referenced first. Cracked arcproc_uso_func_00002884's base/24 swap 2026-05-30 (9→5 diffs; residual 5 were a separate ugen-backend instruction-scheduling order, not coloring). General: a base↔const or ptr↔ptr saved-reg swap with otherwise-correct code is usually this — reorder references, don't blind-permute.

**Works via CONTROL-FLOW restructure too, not just expression reordering — and it cracks the documented "s1/s2 swap / permuter-class" caps.** The "value referenced first gets the lower $s" rule applies to the order values are first touched across the whole function, including in a LOOP GUARD. gl_func_0000E230 was a documented 98.45% "pure s1/s2 register-swap, neither C-shape lever flips it, permuter-class" cap (a0=ptr vs offset=counter swapped). The target compiles from a `blez` guard that reads `a0->0x48` and sets `offset=0` in the delay slot — i.e. a0 is referenced (in the guard) BEFORE offset is initialized. The old C was a plain `while (i < a0->0x48) { ...; offset += ..; }` with `offset = 0;` ABOVE the loop → offset touched before a0 → offset grabbed $s1. Rewriting as `if (a0->0x48 > 0) { offset = 0; do { ... } while (i < a0->0x48); }` (a guard that references a0 first, offset init inside) flipped a0→$s1/offset→$s2 → BYTE-EXACT (2026-05-30). **So many of the "permuter-class $s-reg-swap" near-misses ARE crackable: identify which value the target touches first (often in the loop guard / an early field read) and restructure the C control flow so that value is referenced before the others.** Don't trust old "permuter-class / neither-lever-flips-it" comments — they predate this technique.

## Index-form `buf[i]` vs pointer-form `*p++` changes saved-reg pressure for a loop over a stack array

_When iterating a stack-local array inside a loop, the C access form decides whether IDO burns a saved register on the array base. Pointer-form (`p = arr; ... *p; p++;` reset each outer iteration) makes IDO hoist the array base address into a **saved register** (computed once, `move` to the working ptr each reset) — a whole extra `$s` reg. Index-form (`arr[i]; i++;`) lets IDO recompute the base cheaply each outer iteration via `addiu sN, sp, OFF` (the array is at a fixed sp offset), using ONE FEWER saved reg. If a near-miss has exactly one extra saved reg (target uses s0-s7, build uses s0-s8) and the function loops over a stack buffer, switch pointer-form → index-form. Verified 2026-05-29 on arcproc_uso_func_00002884 (9→8 saved regs, 62-diff → 9-diff). Caveat: this only changes the base-holding; an explicit `char *base = &D+0xN` loop-invariant pointer is still correctly hoisted to its own `$s` reg (that's wanted) — see the loop-invariant-CSE note. The remaining diffs after the fix are usually allocno-order register swaps between the surviving loop-invariants._

## Split a `<<16` into `(x<<15)<<1` to renumber the temps IDO allocates for a multi-field word-pack

Symptom: a function that packs several bit-fields into a 32-bit word (GBI-style
display-list command builders are the canonical case) compiles to the right
instructions in the right order, but every `$t` register in one of the words is
numbered one off from the target — e.g. built uses `t2/t3/t4` where the target
uses `t3/t4/t5`. Plain C variations (reorder, extra locals, `(x & 0xFFFF) << 16`
vs `x << 16`) don't move the numbering; it's a uniform register-renumber
residual, not a logic diff.

```c
// 2-word command packer. word0 already matches; word1's temps are off by 1.
void packer(int *a0, int a1, int a2, int a3, int arg4) {
    a0[0] = (((a1 & 0xFF) << 16) | 0x0E000000) | (arg4 & 0xFFFF);
    a0[1] = (a2 << 16) | (a3 & 0xFFFF);          // built: t2/t3/t4
    a0[1] = ((a2 << 15) << 1) | (a3 & 0xFFFF);   // FIX:   t3/t4/t5  -> byte-exact
}
```

The optimizer folds `(a2 << 15) << 1` back to a single `sll ,16` (same final
instruction), but the extra shift node in the RTL bumps IDO's pseudo-register
numbering for that sub-expression, shifting the whole word's temp allocation up
by one to match the target.

This was permuter-discovered (the kind of "nonsensical but it works" result the
permuter is good at), then confirmed reusable across the whole family: it
byte-matched **nine** sibling packers in game_libs — `game_libs_func_0001D594`
(cmd 0x0C), `_0001D5E0` (0x08), `_0001D624`, `_0001D694` (0x12), `_0001D770`
(0x0E), `_0001D7A4` (0x19) with `a0[1]=((a3<<15)<<1)|(a4&0xFFFF)`; plus the
3-arg sub-shape `_0001D670` (0x11), `_0001D720` (0x16), `_0001D7F8` (0x03) with
`a0[1]=((a1<<15)<<1)|(a2&0xFFFF)` — each a 2-word GBI command builder for a
different command byte (`a0[0]=...|CMD|...`; the `<<16` word always needs the
split-shift to renumber its temps). Permuter found it on the first one; the rest
were a mechanical hand-application of the lever (one edit each, no permuter). When
you hit a word-pack whose only residual is a uniform `$t` renumber on a shift-heavy
expression, try splitting the shift before reaching for the permuter. Verified
2026-05-24.

---

<a id="feedback-ido-3save-vs-2save-arg-preserve"></a>
## A caller-saved value spilled-and-reloaded AROUND a jal is often a genuine ARG to that call — pass it (don't grind reg-alloc)

_Before treating a "post-jal reload goes to the wrong register ($t7 vs $a1)" near-miss as a reg-alloc cap, check whether the spilled/reloaded value is actually an **argument** to the call. If the asm holds a value in $aN through the call (spills it in the jal delay slot, reloads it after) and that value was the incoming param, the call almost certainly TAKES it as an arg — and the prior C just under-counted the call's arguments. Passing it as the genuine arg makes IDO keep it live in $aN across the call, so the reload lands in $aN (matching) with zero spill-shaping tricks._

**Symptom (2026-05-29, `h2hproc_uso_func_000008EC` + sibling `00000944`, capped 89.5–94% for weeks):**
```
move  a2,a0            ; save orig a0
sw    a1,0x6B8(a0)
lw    a0,0x6A8(a0)     ; a0 = first call arg
sw    a2,0x18(sp)      ; spill orig-a0
jal   <call1>
sw    a1,0x1c(sp)      ; DELAY: spill a1 (still the incoming param!)
lw    a1,0x1c(sp)      ; reload a1  <-- target reloads to $a1
lw    a2,0x18(sp)
bnez  a1, ...          ; a1 used after the call
```
The reload to `$a1` (not `$t7`) is the tell: `a1` is live across the call because it's `call1`'s **2nd argument**. Prior C wrote `call1(*(a0+0x6A8))` (1 arg) → `a1` wasn't an arg → IDO reloaded the still-live param into `$t7`. Fix: `call1(*(a0+0x6A8), a1)`. Result: 89.5% → **100% byte-exact**, no `volatile`/dead-spill shaping (the long history of volatile-spill grinding in the file's comment was chasing the wrong cause).

**Vein breadth (2026-05-29 sweep — DON'T re-run):** automating the raw signature (a caller-saved `$aN` spilled in a jal delay slot + reloaded) across game_libs + game_uso + kernel returned **167 hits** — far too noisy to be a vein, because *any* value live across a call matches it. Of the small wrapped ones, only `gl_func_000525F0` was even a near-miss (3 diffs) and that's a genuine `$v0`/`$v1` regalloc-renumber cap, NOT an arg-count bug. **8EC/944 was a rare true case, not a broad vein.** The discriminator that the raw signature CANNOT capture: the spilled reg must be a *call argument* (set up before the jal, consumed by the callee) AND the C must currently pass fewer args than the asm sets up. Live-across object/temp preservation (the overwhelming majority) looks identical at the spill but is not the lever. So: apply this opportunistically when you're already staring at a small near-miss whose lone diff is a wrong-register post-jal reload — don't sweep for it.

**General rule:** a documented "reg-alloc reload cap" with a spill/reload bracketing a single call deserves an argument-count recheck first. The arg count is recoverable from the asm: any caller-saved reg ($a0–$a3) that holds a value AT the jal (set up before it, not clobbered) is being passed as that positional arg, even if a later decoder dropped it. Contrast with [[#ido-targets-3-save-reg-pattern-copy-to-free-reg--stack-spill--stack-reload-for-arg-preservation-isnt-reachable-from-natural-c]] (336) and the `$a1`-not-`$a3` save-pick entry (913): those are genuine caps where the saved value is NOT an arg; this lever applies only when it IS.

## IDO target's 3-save reg pattern (copy to free reg + stack spill + stack reload) for arg preservation isn't reachable from natural C

_When target asm preserves an arg ($a0) across a jal via THREE moves — `or $aN_free, $a0, $zero` (copy to a free arg-reg) + `sw $aN_free, off(sp)` (spill the copy) + `lw $aN_free, off(sp)` (reload after call) — IDO -O2 won't generate that from natural C. IDO picks the simpler 2-save (spill $a0 directly + reload). The "extra save into a free arg-reg" gives target a different reg layout for downstream code (e.g. index goes to $v1 instead of $v0) that 2-save can't reach. Skip these or NM-wrap._

**Symptom (2026-05-02, gl_func_0004E384):**

Target asm:
```
0x319_C: bne $t7, $zero, +0x13   # skip if flag bit set
0x31990: or  $a2, $a0, $zero      # delay: COPY a0 to a2
0x31994: lw  $v1, 0xC(a0)         # use a0 directly here
...
0x319AC: jal gl_func_00000000     # call clobbers a0..a3
0x319B0: sw  $a2, 24(sp)           # delay: SPILL a2 (the saved copy)
0x319B4: lw  $a2, 24(sp)           # RELOAD a2 from stack
0x319B8: lw  $v1, 0xC(a2)          # reuse a2 as base for downstream loads
```

That's 3 moves to preserve a0: `or` + `sw` + `lw`. After the call, downstream code reads from $a2 (the saved copy) rather than $a0.

IDO's natural 2-save:
```
0x...:  jal gl_func_00000000
0x...:  sw $a0, 24(sp)             # delay: SPILL a0 directly
0x...:  lw $a0, 24(sp)             # RELOAD a0
0x...:  lw $v0, 0xC(a0)            # downstream uses a0
```

Just `sw` + `lw`. Index lands in $v0 (since $a0 still holds the array). Target uses $v1 because $a2 holds the array post-call.

**Why IDO won't generate the 3-save pattern from C:**

The 3-save's "copy to a free arg reg" is unmotivated for IDO — it's strictly worse than the 2-save (one extra `or`). IDO's allocator picks the cheapest preservation strategy. Adding a `int *p = a0;` C-level alias is dead-code-eliminated by IDO at -O2, so it doesn't force the extra `or`.

**How to apply:**

When you see the 3-save pattern in target (`or $a2, $a0, $zero` BEFORE a jal, `sw $a2, off(sp)` in the jal's delay slot, `lw $a2, off(sp)` immediately after, downstream loads using $a2 not $a0), and your IDO build uses 2-save with $v0 as the post-call base, **don't grind register-rename knobs**. The 2 patterns aren't reachable from each other. NM-wrap with the decoded body and a note.

**Possibly recoverable cases:**

If the function has additional uses of $a0/the array AFTER the jal, IDO might find motivation to use a different reg. But for this specific pattern (single-use after jal), no known knob flips it.

**Generalizes:** Other arg-preservation cases where target uses copy-to-reg + spill-reload trio. Same logic — IDO picks the shortest path.

---

---

<a id="feedback-ido-addu-operand-order"></a>
## IDO `addu` operand order depends on whether expression is split into a named local

_For `v1 = A + B` in C, IDO picks `addu $rd, $rs, $rt` with `$rs = first-computed operand` and `$rt = second-computed operand`. Inlining both computations swaps them from what you might expect; pulling ONE into a named local reverses the byte-level operand order. At the machine-code level `addu v1, a, b` and `addu v1, b, a` have DIFFERENT bytes even though the result is identical._

**Rule:** When the target has a specific `addu` byte encoding like `004E1821` (= `addu $v1, $v0, $t6`) and your build gets `01C21821` (= `addu $v1, $t6, $v0`), split one of the operands into a named local to flip the order.

**Inline (produces `addu $v1, $t6, $v0` — $t6 first):**
```c
int *p = (int*)(r + a1 * 16);
```
IDO schedules `sll $t6, $a1, 4` before the add completes, so `$t6` ends up as the first source — encoded `01C21821`.

**Split (produces `addu $v1, $v0, $t6` — $v0 first):**
```c
int offset = a1 << 4;              /* named local */
int *p = (int*)(r + offset);
```
Naming `offset` changes the scheduling: `$v0` (the call result `r`) is held as first source, `$t6` (offset) as second — encoded `004E1821`.

**Why it matters:** commutative ops like `addu`, `or`, `and`, `xor` produce different BYTES depending on rs/rt order. objdiff treats these as different and docks the match. If you're stuck at 99 % with a single differing `addu`/`or`/… opcode, try splitting one operand into a named local (or inlining a named one).

**How to apply:**

- Check the target's 32-bit encoding of the commutative op. Decode `rs` (bits 25–21) and `rt` (bits 20–16). Compare with your build.
- If swapped: name one operand as a local and see.
- If still swapped: name the OTHER operand instead. Empirically, whichever operand is "computed first" in the C source becomes `$rs`.

**Scope limit (2026-05-27, game_libs_func_0005B5D8 negative):** the named-local lever fixes the SPECIFIC `addu` operand pair ($rs/$rt swap) but does NOT propagate to broader register-cascade renumbers in the surrounding lw/sll/and/sw chain. If the residual diff covers multiple insns (lw, sll, and, sw) all with renumbered operands — not just the addu — then renaming one operand to a named-local leaves the cascade unchanged. Recognize: the lever works for the "stuck at 99% with ONE addu/or/etc differing" case, not the "5+ insns all use the wrong registers" case. The latter is allocno-priority-driven and permuter-class.

**Anti-lever for tiny leaves (2026-05-27, game_libs_func_000274C0 negative):** for very short leaf functions (≤8 insns, no stack frame), named-locals SHIFT register allocation from $t-class to $v-class, not just to lower-$t. Inline `*a0 = ((a1[4]<<4) & 0x10) | (*a0 & ~0x10);` allocates loads to $t8/$t6/etc. Split into `int src = a1[4]; int dst = *a0;` pushes both loads to $v0/$v1. Neither matches target's $t5/$t8 (low-$t) selection. The named-locals lever is a useful nudge for moderately-sized functions but in tiny leaves it doesn't bridge from "high $t" to "low $t" — it leaps over to $v-class instead. Recognize: if the target uses low-$t ($t4/$t5/$t6) in a tiny leaf, named-locals will overshoot. Permuter only.

**Related:** `feedback_ido_v0_reuse_via_locals.md` and `feedback_ido_inline_deref_v0.md` cover the broader "inline vs named local" axis for register allocation. This memory is the narrow case for commutative-op operand ordering in the encoding itself.

**Origin:** 2026-04-19 game_libs gl_func_00023B08. Inline `r + a1 * 16` → 99.33 % (only `addu` operand order off). Split `int offset = a1 << 4; r + offset` → 100 %.

## Two independent register-inits at entry: C source order controls which IDO emits first

_When a function opens with two independent setup assignments to saved/temp regs
(e.g. a loop counter `i = 0` and a base pointer `entry = a0 + 0x18`), IDO emits
them in the order they appear in the C source. If your build has them swapped vs
the target (`addiu s1,a0,0x18` then `move s0,zero` where the target wants
`move s0,zero` first), reorder the C so the target's-first init appears first._

**Common trap:** a `for (i = 0; i < N; i++)` loop puts `i = 0` in the for-init,
which the compiler sequences AFTER any earlier declaration-initializer. So
`int i; char *entry = base; for (i = 0; ...)` emits `entry`-init first. To emit
`i`-init first, initialize `i` at its declaration and empty the for-init:
```c
int i = 0;                 /* i-init now precedes entry-init in source */
char *entry = base;
for (; i < N; i++) { ... }
```
**Verified** 2026-05-25 game_libs gl_func_0000A4D0: 92.86 % (entry/i pair-swap) →
byte-exact after moving `i = 0` to its declaration. Replaced a banned 2-insn
INSN_PATCH. Same family as the `addu` operand-order and float-const-order levers
above — all "C source order controls IDO scheduling of independent ops."

**Addendum (2026-04-19, bootup_uso/func_00002774):** Array-indexing form `((T*)base)[i + offset]` gives `addu rd, base, idx` (BASE first), while the arithmetic form `*(T*)(base + i*sizeof(T) + offset*sizeof(T))` gives `addu rd, idx, base` (OFFSET first). Same semantic access, different operand order at the byte level.

**Addendum (2026-05-08, game_libs_func_00031580):** Indexing-form `base + i*N + offset` repeated at every loop body store (vs advancing-pointer `p += N; *(p-N+offset)`) RAISES i's ref count above base's ref count. When i and base compete for $v0/$v1, the higher-ref-count variable wins $v0. So switching to the indexed form flips i→$v0, base→$v1 (matching loops where target asm has `or v0, zero, zero` for the counter init and `lui v1, ...` for the base). Net effect on game_libs_func_00031580: 83.52% → 88.23% (regalloc gap closed; remainder is reloc-pre-resolution alias scoring artifact, byte-exact post-link).

```c
/* WRONG: addu t9, t8, a0  (offset-first) */
*(int*)(a0 + a1 * 4 + 0x30)

/* RIGHT: addu t9, a0, t8  (base-first) */
((int*)a0)[a1 + 12]
```

Prefer the array form when the target has base-first operand order.

---

---

<a id="feedback-ido-adjacent-extern-shared-at"></a>
## IDO doesn't share `lui $at` across stores to adjacent externs — struct retype DOESN'T fix it at -O1

_IDO -O1 (and possibly -O2) emits a fresh `lui $at` before EACH store to an external symbol, even when the symbols are adjacent bytes AND are declared as fields of a single struct. Target code that shares `$at` across adjacent %lo pairs (`sb t0, %lo(X)(at); sb t1, %lo(X+1)(at)`) comes from some other compiler mood I haven't characterized. Struct retype did NOT trigger coalescing in my 2026-04-20 experiment on kernel/func_80004E50._

**Observation:** If IDO's built asm has an extra `lui $at` before every adjacent-symbol store where target shares `$at`, neither of these fixes I tried works at -O1:

1. Keep each byte as a separate `extern u8 D_X;` — each store gets its own `lui $at`. 
2. Retype the adjacent bytes as fields of a `typedef struct {...} SysState; extern SysState S;` and access via `S.field = val` — STILL emits a fresh `lui $at` per store.

Both produce correct bytes (the linker resolves each relocation independently) but neither coalesces the lui's.

**Target pattern (shared `$at`):**
```
lui   at, %hi(D_800195D6)
sb    t0, %lo(D_800195D6)(at)
sb    t1, %lo(D_800195D7)(at)   ; shares at across 2 stores
```

**What my C produces either way:**
```
lui   at, 0x0
sb    t0, 6(at)         ; struct offset, or %lo(D6)
lui   at, 0x0           ; fresh lui even with struct
sb    t1, 7(at)
```

**Things I haven't tried yet (add here when confirmed):**
- Local pointer: `u8 *p = &D_800195D0; p[6] = 6; p[7] = 2;` — using a real pointer in a `$t` reg should coalesce.
- `char *base; base = (char*)&SYM; base[+offset]` — equivalent; maybe the indirection helps.
- Compile at -O2 instead of -O1 — but the file is -O1 so that changes the whole file.

**Bottom line as of 2026-04-20:** the struct retype prescription in the PREVIOUS version of this memo was wrong. Do NOT recommend struct retype as the fix until confirmed on at least one function. Mark as NON_MATCHING and move on, or try a real `char*` base-pointer local.

**Origin:** 2026-04-20, kernel/func_80004E50. Both plain-externs and full-struct versions produced separate `lui $at` per store. The target's shared-`$at` output is still unexplained.

---

---

<a id="feedback-ido-adjacent-store-extern-split"></a>
## Two adjacent-offset global stores — split into per-store extern symbols to force `lui $at` per store

_When target emits `lui $at, HI; sw X, 0($at); lui $at, HI; sw Y, 4($at)` (two independent `lui $at` per store, no cached base pointer), writing the obvious C `*(int*)&SYM = X; *((int*)&SYM + 1) = Y;` makes IDO cache the base address in `$v1` with an addiu (4 insns but wrong shape). Fix: declare a second extern `extern int D_NNNN_4` at offset+4 in `undefined_syms_auto.txt`, then write `D_NNNN = X; D_NNNN_4 = Y;` — IDO emits independent `lui $at` per store._

**Pattern (target):**
```
lui   $at, HI(D_SYM)
sw    $v0, LO(D_SYM)($at)
lui   $at, HI(D_SYM + 4)    ; independent lui, not cached
sw    $zero, LO(D_SYM + 4)($at)
```

Two `lui $at` in a row, each for one store. `$at` is the assembler-reserved scratch register (auto-emitted by gas for `sw X, SYMBOL` macros).

**What common C writes INSTEAD (wrong shape, 93-97% match):**
```c
*(int*)&D_00000000 = v0;
*((int*)&D_00000000 + 1) = 0;     // or ((int*)&D_00000000)[1]
// → compiled: lui $v1, 0; addiu $v1, 0; sw $v0, 0($v1); sw $zero, 4($v1)
```

IDO sees `&D_00000000 + 4` as arithmetic on a cached base, pins the base in `$v1` (via lui+addiu), then reuses it. 4 insns but shape is wrong.

**Fix:** declare two separately-named externs mapped to consecutive offsets:
```c
extern int D_00000000;
extern int D_00000000_4;    // or D_00000004 if using offset-in-name convention
```
```
# undefined_syms_auto.txt
D_00000000 = 0x00000000;
D_00000000_4 = 0x00000004;    # or D_00000004
```
```c
D_00000000 = v0;
D_00000000_4 = 0;
```

IDO now treats them as independent symbols and emits:
```
lui $at, HI(D_00000000); sw $v0, LO(D_00000000)($at)
lui $at, HI(D_00000000_4); sw $zero, LO(D_00000000_4)($at)
```

Both `lui $at` are independent (same HI=0 at link time for USO placeholders, but compiler doesn't know that and can't coalesce).

**Applies when:**
- Two back-to-back stores land at consecutive 4-byte offsets of a global/extern
- Target asm has two `lui $at, HI` (not cached via a $v1 base pointer)
- Your build has `lui $v1; addiu $v1; sw A, 0($v1); sw B, 4($v1)` (4 insns, base-pointer form)

**Doesn't apply when:** stores go to stack locals, or when only one store is emitted. Not a cure for any base-pointer diff — only for per-store `lui $at` targets specifically.

**Origin:** 2026-04-20, eddproc_uso_func_0000015C. After trailing-head trim promoted it to 93.9%, the remaining 4-insn diff was exactly this pattern. Declaring `D_00000004` as a second extern + using `D_00000004 = 0;` in the C flipped to 100%.

**Related:** `feedback_uso_multi_placeholder_wrapper.md` (similar "separate extern per usage" pattern for cross-USO function-pointer calls) and `feedback_ido_v0_reuse_via_locals.md` (named locals → $v0 reuse).

---

---

<a id="feedback-ido-bnel-dispatch-modify-c-mask-return"></a>
## Multi-case literal-dispatch bnel chain — "modify-c-in-place + single masked return" with separate `v` for compare source

_USO entry-0 character dispatchers (e.g. `gui_func_00000000`) compile a sparse `if (c == X) c = Y` ladder into a 6-insn-per-case bnel chain. The structural recipe is `int v; c &= 0xFF; v = c; if (v == X1) c = Y1; else if (v == X2) c = Y2; ... return c & 0xFF;`. The single trailing mask + per-case modify-in-place form makes IDO schedule `move v0, a0` into the FIRST compare's bne delay slot (matches target's `or v0, a0, $0` default-save) and emits per-case `addiu a0, $0, Y; jr ra; andi v0, a0, 0xFF` hit-handlers. Caps at ~95% via the chain compare-source register picker._

The pattern this matches is N sequential equality compares against a
single masked-byte input, each producing a small constant lookup result,
with a default fall-through equal to the input itself. Target asm shape:

```
andi a0, a0, 0xFF
li at, X1
bne a0, at, .next            # FIRST compare: bne, NOT bnel
or v0, a0, $0                # delay (always exec): v0 = c (default-save)
addiu a0, $0, Y1             # match: a0 = result
jr ra
andi v0, a0, 0xFF            # delay: v0 = result
.next:
li at, X2
bnel a0, at, .next2          # SUBSEQUENT compares: bnel
li at, X3                    # delay-likely: pre-load NEXT compare's `at`
addiu a0, $0, Y2
jr ra
andi v0, a0, 0xFF
.next2:
li at, X3                    # head (dead when entered via bnel-taken path)
...
```

The natural `if (c == X) return Y;` ladder emits a SHORTER 4-insn-per-case
chain (`bnel; li at NEXT; jr ra; li v0, RESULT`) without the `or v0, a0, $0`
default-save and without the `andi v0, a0, 0xFF` per-hit. To unlock the
target's 6-insn-per-case form:

1. Modify `c` in place per case (don't `return CONST`):
   ```c
   if (v == 0x21) c = 0x27;
   else if (v == 0x2C) c = 0x28;
   ...
   ```
2. Single trailing masked return: `return c & 0xFF;` — this is the trigger
   for IDO to put `move v0, a0` in the FIRST compare's delay slot (saves
   `c` into v0 as the default-return register that subsequent range checks
   like `addiu a0, v0, -W` source from).
3. Compare against a SEPARATE `int v` (not against `c`) so range checks
   correctly pick v0 as the source register: `int v; v = c; if (v == X1)
   c = Y1; ...`. Without splitting v from c, range checks emit
   `addiu a0, a0, -W` instead of `addiu a0, v0, -W`.

Cap: the bnel/slti chain compares against a0 in built (vs v0 in target).
After `move v0, a0`, both regs alias since neither is modified between
compares; IDO picks a0. Range-check `addiu a0, v0, -W` byte-matches
correctly. Pure register-source picker — no semantic difference. The
remaining 4–5% is grindable via register-allocation knobs but the
structural shape is locked.

Discovered 2026-05-06 promoting `gui_func_00000000` from 4.1% (varargs
form) to 95.30% (this recipe).

---

<a id="feedback-ido-preassign-conditional-overwrite-ternary"></a>
## Pre-assign default + conditional-overwrite for data-mux ternary

_When the target asm shows a register's default value loaded from a caller-spill in a `beq cond, $0, .skip` delay slot, then ONLY OVERWRITTEN on fall-through via `addiu` or similar, the matching C idiom is the explicit pre-assign with conditional overwrite — NOT a `?:` ternary._

**Target asm shape:**
```
beq    $rv, $0, .skip
lw     $p, CALLER_SLOT(sp)     ; [delay] default value: load from caller spill
addiu  $p, sp, BUF_OFF         ; fall-through: overwrite to local buf addr
.skip: ...                     ; both paths continue with $p set
```

**Matching C:**
```c
char *p = a0;             /* default — IDO emits as lw a0_spill */
if (gl_func_X(a0, buf)) {
    p = buf;              /* conditional overwrite via addiu sp+OFF */
}
```

**Non-matching alternatives:**
- `char *p = cond ? buf : a0;` — IDO emits a branch around the assignment, not the delay-slot-fill pattern.
- Explicit `if/else`:
  ```c
  if (cond) p = buf;
  else p = a0;
  ```
  Has the same problem; doesn't schedule the default load into the delay slot.

**Why this works:** IDO's scheduler treats the pre-assign `p = a0` as a definition that "always runs," then sees the `if (cond) p = buf;` overwrite as a conditional update. When the next live use of `p` (the call) is in the fall-through path, IDO fills the conditional branch's delay slot with the default-load (since the default value MUST be set before the branch resolves whether it's needed).

**Verified 2026-05-15** on `gl_func_0005FFD0` (game_libs_post.c): 33.7% → 73.5% (+39.8pp). 22-insn 2-call ternary-pick wrapper where `p` is either `&buf` (post-call success) or `a0` (post-call fail). The pre-assign form matched the target's `lw a3, 0x80(sp) [delay] / addiu a3, sp, 0x1C` shape; both ternary and if/else variants left the delay slot unfilled and required an extra branch.

**Cap considerations:** Even with this idiom, additional gaps may remain (frame size, register-name choice, downstream branch shape). The recipe specifically targets the delay-slot fill at the conditional-overwrite branch.

---

<a id="feedback-ido-alloc-or-passthrough-ternary"></a>
## IDO bnel + delay-likely-move + fall-through alloc = "out = ptr ? ptr : alloc(N)" ternary

_USO functions emit a 4-insn `bnel ptr,$0,+6 / move v1,ptr [delay-likely] / jal alloc / addiu a0,$0,N` pattern for the conditional-alloc ternary. When ptr is a stack-local addr the alloc arm is dead; both arms converge on the same body that uses the result._

A 4-insn pattern recurring through game_uso (3+ instances in
`game_uso_func_00009B88` alone) is IDO's emit for the conditional-alloc
ternary `out = ptr ? ptr : alloc(N)`:

```
addiu vN, sp, 0xOFF      ; vN = ptr (often a stack-local Vec3 addr)
bnel  vN, zero, +6       ; if (ptr != 0) skip alloc — branch likely
or    v1, vN, zero       ; (delay-likely) v1 = ptr — only on taken branch
jal   gl_func_00000000   ; alloc(N) fall-through
addiu a0, zero, 0xN      ; (delay) a0 = N (alloc size)
beqz  v0, +<skip-body>   ; if alloc returned 0, skip the rest
or    v1, v0, zero       ; (delay) v1 = alloc-result
;; converge here:
;; ... use v1 as the output buffer ...
```

When ptr is a stack-local address (`sp+0xOFF`), the bnel is always taken
and the alloc arm is dead. The compiler can't see this and emits both
arms verbatim. The C source typically uses an actual `if (ptr != NULL)`
or a ternary or a macro that wraps the conditional alloc.

**Why:** observed 2026-05-03 in `game_uso_func_00009B88`. Three
instances back-to-back: dispatch 1 at 0x9BB8 (sp+0x190 / size=0xC),
dispatch 2 at 0x9BF4 (sp+0xDC / size=0xC), dispatch 3 at 0x9C9C (no
ternary, plain alloc(0xC)). All three converge on a `if (out != 0)`
body that populates a Vec3 in `out`.

**How to apply:**
- When you see a 5-6 byte alloc constant with a `bnel` 6 insns prior to
  a jal, decode as `out = ptr ? ptr : alloc(N)`. The `or v1, ptr, zero`
  in the bnel delay slot is the "passthrough" arm.
- The `addiu a0, zero, N` in the jal's delay slot is the alloc size — N
  is typically 0xC (Vec3) or 0x10 (Quad) for game_uso buffers.
- **Bnel-likely vs bnez (non-likely) distinction:** the bnel-likely shape
  ONLY happens when target's asm has `bnel`. If target shows plain `bnez
  ptr, +5; or vN, ptr, zero (delay)`, that's a DIFFERENT pattern — a
  regular if-else, NOT a ternary. For non-likely cases (e.g.
  `gl_func_0005FCC4`), use `if (p == 0) { p = alloc(N); if (p == 0) goto
  end; }` — the **ternary form REGRESSES** to ~50% match because IDO emits
  extra branches around it (verified 2026-05-03: ternary 51%, if-else+goto
  97%).
- Since the branch arm is always taken at runtime (stack addr is non-
  null), the alloc arm produces dead bytes that still must match. Wrap
  the C as `if (out == 0) { out = alloc(N); }` so the compiler emits the
  same dead-arm shape.

**Decision rule:**
- Target asm has `bnel ptr,zero,...` → use ternary `out = ptr ? ptr : alloc(N);`
- Target asm has `bnez ptr,zero,...` → use if-else `if (p == 0) { p = alloc(N); ... }` + `goto end` for early-exit

---

---

<a id="feedback-ido-struct-copy-vs-field-copy-treg-order"></a>
## Copy adjacent fields as a STRUCT (not separate field-copies) to flip a $t-register-renumber residual

When a function copies two (or more) **adjacent** words and the only residual is the load/store temps using swapped $t registers — e.g. you emit `lw t6,lo(a0); lw t7,hi(a0); … sw t6; sw t7` but the target has `lw t7; lw t6; … sw t7; sw t6` — replace the separate field-copies with a single **struct-typed copy**. The struct copy emits the `lw/lw/sw/sw` block in a fixed canonical order that frequently matches the target's register assignment, whereas separate `*(int*)…=*(int*)…` statements let the allocator pick the opposite order.

**Worked example (game_uso_func_0000D438, 2026-05-24 — was a banned INSN_PATCH):**
```c
/* separate copies -> loads in t6/t7 (target wants t7/t6): 2-reg diff */
*(s32*)(a0 + 0xC8) = *(s32*)(a0 + 0xC0);
*(s32*)(a0 + 0xCC) = *(s32*)(a0 + 0xC4);

/* struct copy -> lw/lw/sw/sw in target order: BYTE-EXACT */
typedef struct { int a, b; } Pair;
*(Pair*)(a0 + 0xC8) = *(Pair*)(a0 + 0xC0);
```
Note this is a tiny straight-line leaf where the permuter has no mutation surface (per `TOOLING_DECOMP.md`, ≤8-insn leaves resist) — the struct-copy form is the deterministic fix. A `double` copy (`*(double*)=*(double*)`) is NOT equivalent: it emits ldc1/sdc1 (FP path), diverging entirely. Reuse an existing `struct{int a,b;}` typedef in the file to avoid a redefinition (this codebase has `Pair2`).

**Generalizes to the varargs `&param`-pointer regalloc case** (game_uso_func_0000D5BC, 2026-05-24): a function that homes `a1,a2` via `&a1` and copies them to an adjacent dest had the `&a1` pointer stuck in `$v0` (a `volatile int *p = &a1; dst[0]=p[0]; dst[1]=p[1]` form) where the target uses `$t6`. Writing it as `*(Pair2*)(dst) = *(Pair2*)&a1` homes the args, takes `&a1` into `$t6`, and emits the lw/sw/lw/sw via the pointer in the target registers — byte-exact. So struct-copy fixes both the adjacent-field $t-swap AND the `&param`-pointer `$v0`-vs-`$t6` choice. (Verify in-tree, not just standalone — see `MATCHING_WORKFLOW.md#feedback-standalone-false-convergence-verify-in-tree`.)

**Also generalizes to the dest-pointer-reuses-call-arg-register case** (gl_func_00037DA8, 2026-05-27): a function that copies 6 ints from `*src` into a local then calls `f(&D, &local, 24)`. Target has `addiu a1, sp, 0x18; lw t7, 0(a0); sw t7, 0(a1); lw t6, 4(a0); sw t6, 4(a1); …` — i.e. it computes `&local` ONCE into `a1` (which is also call-arg-2 = `&local`) and uses `a1` as the dest pointer for the 6 stores. The "obvious" C form `int local[6]; local[i] = a0[i];` lets IDO pick sp-direct stores (`sw rN, OFF(sp)`), missing the pointer-reuse pattern (95.83% NM cap). Writing it as
```c
struct Six { int a, b, c, d, e, f; };
struct Six local;
local = *a0;
gl_func_00000000(&D_00000000, &local, 0x18);
```
makes IDO emit memcpy-style inline using an explicit dest-pointer register that the scheduler then unifies with the call-arg-2 register — byte-exact 23/23. The lever applies whenever the dest of the struct copy is also passed as an argument to the immediately-following call (and the size argument matches the struct size, so IDO recognizes the pointer-equality).

**Also generalizes to the MIRROR direction** (gl_func_00037CE0, 2026-05-27): a function that calls `f(&D, &local, N)` to POPULATE local THEN copies from local to `*a0`. The "obvious" `int buf[N]; a0[i] = buf[i];` form leaves a 4-insn gap because IDO uses caller-spilled-a3 reload pattern; the struct-assign form `struct N buf; func(&D, &buf, N); *a0 = buf;` unifies the dest pointer with the spilled-a0-reload register — byte-exact 26/26. So both DIRECTIONS of struct-copy-around-a-call benefit: src→local-then-call AND call-then-local→dst. Recognize: if the function has `int buf[N]; func(arg, buf, sizeof_N); for(i) dst[i]=buf[i];` (or the mirror), apply struct-assign.

**Also generalizes to compound levers** (gl_func_00024B94, 2026-05-27): struct-assign for an inner 4-int copy (a0+0x20 ← v0[0..0xC]) PLUS `~0x0C` form for a byte-clear mask (`*(char*)v0 &= ~0x0C` emits `andi 0xFFF3` to match target's encoding, see feedback-ido-andi-fitting-mask-vs-negative for that lever). Combined: 97.55% → 99.83% (only remaining diff is alt-entry-jal reloc encoding — post-link byte-exact). Lesson: when triage shows MIXED diff classes, peel them apart and apply layered levers; sometimes the right combination cracks even when each lever individually falls short.

**Scope limit: int→float reinterpret patterns** (2026-05-27, gl_func_0003D620 + gl_func_00037D48 negatives). When the target's shape REQUIRES a stack ping-pong (int stores into tmp + float reads from same tmp address), struct-assign skips the reinterpret. Example target asm:
```
sw t6, 0x24(sp)   ; tmp[0] = (int)p[0]
sw t7, 0x28(sp)
sw t8, 0x2C(sp)
lwc1 f4, 0x24(sp) ; reinterpret tmp[0] as float
lwc1 f6, 0x28(sp)
lwc1 f8, 0x2C(sp)
swc1 f4, 0x30(a0) ; *(float*)(a0+0x30) = tmp[0] bits
```
The "obvious" struct-assign collapse `*(struct ThreeF*)(a0+0x30) = *(struct ThreeF*)tmp` skips the int-load-then-float-store chain entirely, emitting direct int stores — regressed 26/27 → 11/27 on 0x3D620. Recognize: if the target asm has `sw` then `lwc1` of the SAME stack slot (int→float reinterpret via stack), the struct-assign lever does NOT apply. Keep the explicit `*(float*)&tmp[N]` casts.

<a id="feedback-ido-array-append-count-store-vs-array-addr-schedule-cap"></a>
## Array-append (load count / store count+1 / store array[idx]) — count-store-vs-array-addr schedule is an in-tree cap; detect-and-skip

The recurring "append to a count+entries list" idiom:
```c
int idx = obj->count;          /* lw */
obj->count = idx + 1;          /* sw count+1 */
obj->entries[idx] = val;       /* sll idx; addu base; sw val */
```
has a fixed 2-word residual: the **target computes the array address (`addu base,idx*N`) BEFORE the count store (`sw count+1`), but IDO's full-TU scheduler emits the count store first** (the `idx+1` is ready before the `idx*N` shift). No C reorder flips it: array-store-first regresses (extra diffs), count-store-first is the 2-word cap. **It also false-converges** — a standalone compile schedules the array-addr first (looks like a match) but the in-tree (full-TU) build puts the count store first; always verify in-tree.

This is a **cap class**, not a one-off — confirmed identical on `timproc_uso_b5_func_0000A95C` (0x3C/0x40), `bootup_uso func_00002088` (0x104/0x108), `func_000020AC` (0xC0/0xC4/0xC8). Recognize the shape and leave NM (~75-90%); don't burn ticks reordering or trusting a standalone zero. (Permuter is the only lever that might reach it — A95C floored, untried on the others.)

<a id="feedback-ido-array-index-vs-charptr-spill-packing"></a>
## Array-index addressing packs stack spills tighter than char*-pointer-arith (fixes frame-size / spill-offset residuals)

When a function's only residual is a **frame-size / spill-slot-offset** difference off by a constant — the target uses a smaller frame and your build leaves a gap between spill slots — and the addressed base is a parameter scaled by another parameter, the **way you write the address computation** changes IDO's spill-slot packing.

**Symptom (gl_func_0002A50C, 2026-05-24, obj-deinit helper, 2 pointers spilled across 2 jals):**
```
mine  : addiu sp,sp,-0x28 ; ... ; sw v0,0x1c(sp) ; sw a2,0x20(sp)   (gap at 0x18)
target: addiu sp,sp,-0x20 ; ... ; sw v0,0x18(sp) ; sw a2,0x1c(sp)   (packed)
```
Everything else byte-identical; only the frame size and the two spill offsets differ.

**char*-pointer-arith form (gap, frame -0x28):**
```c
int *obj_slot = (int*)((char*)a0 + a1 * 4);
int *obj = (int*)obj_slot[0x50/4];
... obj_slot[0x50/4] = 0;
```

**typed array-index form (packed, frame -0x20, BYTE-EXACT):**
```c
void f(int **a0, int a1) {          // a0 typed as int** (element size 4)
    int *obj = a0[a1 + 0x14];        // 0x14 = 0x50/4; gives a0 + a1*4 + 0x50
    ...
    a0[a1 + 0x14] = 0;
}
```
The array-index form (base typed so the element size matches, index = `param + byteoff/4`) makes IDO pack the pointer spills with no inter-slot gap, matching the target's minimal frame. Reusing the parameter in place (`#feedback-ido-reuse-param-as-object-caller-slot-spill`) did NOT fix it here — the lever was the addressing *form*, not param-reuse. **Watch the scaling:** `a0[a1*4 + K]` on an `int**` double-scales to `a1*16` (`sll 0x4`); you want `a0[a1 + K]` to get `a1*4` (`sll 0x2`). Args that need byte offsets into a `char`-typed extern (e.g. `&D_00000000 + 0x5368`) can stay as `(char*)&D_00000000 + 0x5368` — only the spilled-base access needs the typed-index form.

<a id="feedback-ido-arg-deref-before-a0-overwrite"></a>
## Pull `a0->field` into a named local when the same call overwrites $a0 with a new address

_For calls like `func(&SYM, *(int*)(a0 + N), 0)` where $a0 is about to be reassigned to &SYM, inlining the `*(int*)(a0+N)` deref makes IDO spill a0 early and reload via a fresh temp ($t6). Pulling the deref into a named local first lets IDO emit `lw a1, N(a0)` directly on the still-valid $a0, THEN spill a0 for later reloads. Shaves 2 insns and flips the prologue ordering._

**Rule:** If a function uses `a0` as a pointer base AND later calls a function that wants a different `&SYM` in $a0, AND a **middle call arg** needs to come from `*(int*)(a0 + N)`:

**WRONG (inline deref — forces t6 spill/reload via separate temp):**
```c
void f(char *a0) {
    func(&D_SYM, *(int*)(a0 + 0xC), 0);   /* IDO spills a0, reloads as t6, then lw a1,0xC(t6) */
    /* ... more uses of a0 ... */
}
```
Asm:
```
sw  a0, N(sp)       ; spill
lw  t6, N(sp)       ; reload into fresh temp
sw  ra, ...         ; ra save happens later
lui a0, %hi(SYM)    ; set up $a0 for call
addiu a0, %lo(SYM)
or  a2, zero, zero
jal func
 lw a1, 0xC(t6)     ; read via t6 in delay slot
```

**RIGHT (named local — IDO reads via $a0 before spilling):**
```c
void f(char *a0) {
    int arg = *(int*)(a0 + 0xC);          /* lw a1, 0xC(a0) immediately — $a0 still valid */
    func(&D_SYM, arg, 0);                 /* now set up $a0 = &SYM */
    /* ... more uses of a0 ... */
}
```
Asm:
```
sw  ra, ...
sw  a0, N(sp)       ; spill
lw  a1, 0xC(a0)     ; read via $a0 BEFORE it's overwritten
lui a0, %hi(SYM)
addiu a0, %lo(SYM)
jal func
 or  a2, zero, zero
```

**Key insight:** Even though the two C forms are semantically identical, IDO's instruction scheduler picks a different reg for the intermediate read. The named local form lets IDO commit the read to `$a1` (the target arg register) while `$a0` is still the original pointer — avoiding a fresh temp.

**How to apply:**

If target asm shows `lw aN, offset(a0)` EARLY in the prologue (while a0 still holds its original value), and your build emits `lw tX, offset(sp)` + `lw aN, offset(tX)` later: pull the `*(T*)(a0 + offset)` into a named local as the FIRST statement.

**Example (1080/bootup_uso/func_00008744, 24 insns):** 5-call setup wrapper with first call `func(&D1, a0->0xC, 0)`. Inline deref → wrong order + 2 extra insns. Named local `int arg = *(int*)(a0+0xC)` → exact match.

**Related:**
- `feedback_ido_inline_deref_v0.md` — inline vs named pointer deref shifts v0 vs tN allocation
- `feedback_ido_v0_reuse_via_locals.md` — similar axis for v0 reuse across expressions

**Origin:** 2026-04-19, 1080 bootup_uso/func_00008744.

---

---

<a id="feedback-ido-arg-passthrough"></a>
## Function that never sets or spills a0 is forwarding caller's a0 to a callee

_If asm body shows a0 is never touched (no `sw a0, N(sp)`, no `or a0, ..., zero`, no `addiu a0, ..., N`) but a jal still uses it, the C takes a0 as a parameter and passes it through unchanged_

**Rule:** When a non-leaf function's body NEVER modifies or spills `$a0`, but a `jal` inside the function still uses `$a0` — the caller's `a0` value passes straight through to the callee. The C signature needs `int a0` (or typed equivalent) as a parameter even though nothing visibly "uses" it in the function body.

**Why:** MIPS O32 ABI passes the first int arg in `$a0`. If the function doesn't clobber `$a0` and calls another function, the caller's original value is what the callee sees. From C, writing `f(arg0, -1, 0)` with `arg0` unmodified produces no extra instructions — IDO just leaves `$a0` alone and sets `$a1`/`$a2`.

**How to apply:**

- Count `a0` references in the body:
  - `sw a0, …($sp)` → save (not passthrough)
  - `or a0, …, $zero` / `addiu a0, a0, …` → set/modify (not passthrough)
  - NO appearance at all between prologue and jal → **passthrough**
- The C signature takes `a0` as a parameter even though it "looks" unused in the body.

**Example — `timproc_uso_b1_func_00001100`:**
```
27BDFFE8  addiu sp, -0x18
AFBF0014  sw ra, 0x14(sp)
240E0009  addiu t6, zero, 9
3C010000  lui at, 0
AC2E0040  sw t6, 0x40(at)            # gl_ref_00000040 = 9
2405FFFF  addiu a1, zero, -1
0C000000  jal 0                        # gl_func_00000000(a0 [untouched], -1, 0)
00003025  or a2, zero, zero            # [delay]
…
```
→
```c
void timproc_uso_b1_func_00001100(int a0) {
    gl_ref_00000040 = 9;
    gl_func_00000000(a0, -1, 0);
}
```

**Origin:** 2026-04-19 timproc_uso_b1/b3 passthrough wrappers. Both matched 100 %.

---

---

<a id="feedback-ido-arg-save-reg-pick"></a>
## IDO picks $a1 (not $a3) to save an arg across a jal — can't reliably flip from C

_When a function spills its incoming `a0` to survive a `jal`, IDO -O2 consistently allocates $a1 as the holding register: `or a1, a0, zero; sw a1, N(sp); ...jal...; lw a1, N(sp)`. If the target uses $a3 instead, 7+ variants (register keyword, split locals, extra args, unused args, K&R decl) all still give $a1. 98 % match, 1-byte register-field diff — wrap NON_MATCHING._

**Rule:** For a function shape `void f(char *a0) { ...; jal ...; /* uses a0 again */ }` where IDO must preserve `a0` across the call:

- **IDO -O2 always picks $a1 as the holding register** and spills it to the stack:
  ```
  or  a1, a0, zero
  sw  a1, N(sp)
  ... jal ...
  lw  a1, N(sp)
  ... (uses of a1 as a0) ...
  ```

- If the target encoding uses `$a3` (or any other reg) for this role, **you cannot reliably flip it from C**. Tried and confirmed ineffective:
  1. `register char *saved;`
  2. Split into `saved = a0` before and use `saved` instead of `a0`
  3. Extra args (2-, 3-, 4-arg function signature)
  4. Unused dummy local declarations
  5. K&R-style declaration
  6. Two-level dereferences to "occupy" earlier regs
  7. Moving the call earlier/later in the function

All produce `$a1`. 98 % match with only the register field differing.

**How to apply:**
- If you hit 98 % on a short leaf/non-leaf function, and the single diff is `or aN, a0, zero` with `aN != a1`: accept it as NON_MATCHING; don't grind further.
- Candidate for decomp-permuter; not worth manual iteration.

**Example (1080/bootup_uso/func_00001F78):** linked-list insert-head, 20 insns. Target uses `$a3` to save `a0`; 7 C variants produce `$a1`. Wrapped NON_MATCHING at 98 %.

**Related:** `feedback_ido_o2_tiny_wrapper_unflippable.md` (similar "unflippable register allocation" blocker, different pattern — sw ra vs lui a0 ordering for wrappers).

**Origin:** 2026-04-19, 1080 bootup_uso/func_00001F78.

---

---

<a id="feedback-ido-precall-move-is-arg-marshal"></a>
## Pre-call `or aN, aM, zero` (move) plus stack spill is 3rd-arg marshalling, not a defensive register-save

_When asm shows `or aN, aM, zero; sw aN, off(sp); addiu aM, aM, K; jal; sw aP, off(sp) [delay]` (where `aN > aM`, e.g. `or a2, a0`), the `or` is materialising a 3rd argument register for the call — not preserving aM across the jal. Mistaking it as a save leads to wrapping the function NM at the `~80%` cap with no C lever; the actual fix is adding the missing argument to the call._

**Why this looks like a save:**

- `or a2, a0, zero` reads identically to "copy a0 to a2 to keep a0 alive across jal."
- `sw a2, off(sp)` reinforces the read — looks like a defensive spill.
- After the jal, `lw a2, off(sp)` reload + use of `$a2` for stores feels like "restore the saved a0."
- IDO's actual 2-arg-call save pattern (`feedback-ido-arg-save-reg-pick`) DOES use `or a1, a0, zero; sw a1, off(sp)`. Same shape, just different register number.

**Why it's actually a 3rd argument:**

- `$a2` is the 3rd argument register in MIPS o32. If the call takes 3 args, `$a2` MUST be set up before the jal — the `or` is the IDO emit for "pass aM as the 3rd argument."
- `addiu a0, a0, K` between the move and the jal mutates `a0` for arg 1 (an offset version of aM). The unmutated `aM` survives in `$a2` as arg 3.
- The post-call use of `$a2` for stores is just IDO reusing the value still sitting in `$a2` (no separate reload needed by the compiler model — the spill was for the call frame, the post-call use comes from register state).

**Diagnostic test:** count the args. The call's pre-jal arg-reg setup tells you the arity:

- `addiu a0, ...` → arg 1 set
- `sw a1, off(sp) [delay]` or pre-call mov to a1 → arg 2 set
- `or a2, aM, zero` → arg 3 set (this is what's been mis-read)
- `or a3, aM, zero` → arg 4 set

If you see arg-3 setup and your decoded C call only has 2 args, your call is missing arg 3. Find it (often it's `aM` itself — the original a0 passed alongside its mutated version).

**How to apply:**

1. When you hit a documented `~80–89%` cap with notes like "extra `or aN, aM` insn" or "regalloc cap":
2. Re-count the asm's arg-reg setups (`a0`, `a1`, `a2`, `a3` plus stack args at `sp+0x10..0x1C` for arg 5+).
3. If $a2 or $a3 is set up via a `move` from another arg reg (or is `or aN, aM, zero` not justified by 2-arg semantics), the call has more args than your decode shows.
4. Add the missing argument; rebuild — usually byte-exact with no other change.

**Example (1080/game_libs/gl_func_0004E888):** 19-insn link-back-pointer wrapper, sat at NM 80.26% with documented "extra `or a2, a0` cap." Re-count showed `addiu a0, a0, 0x10` (arg 1) + `sw a1, sp+0x1C` delay (arg 2) + `or a2, a0, zero` (arg 3). C body had only 2 args; adding `arg0` as 3rd argument byte-matched immediately. Sibling `gl_func_0004E8D4(a0+4, a1, a0)` had been written 3-arg correctly — the 0004E888 decode just dropped it.

**Origin:** 2026-05-08, 1080 game_libs/gl_func_0004E888 promotion (NM 80% → exact).

---

---

<a id="feedback-ido-tu-context-sensitive-scheduling"></a>
## TU-context-sensitive scheduling — a standalone-byte-exact function can mis-schedule in-tree

_The usual trap is the reverse (`feedback_standalone_compile_false_cap_verify_in_tree`: standalone diverges, in-tree matches). This is the OTHER direction: standalone MATCHES byte-exact, but the same function in the full translation unit does not._

**`game_uso_func_0000C3E8`** — `int f(int a0){ return *(int*)&D_00000000; }`:
- **Standalone** `cc -G 0 -non_shared -Xcpluscomm -Wab,-r4300_mul -O2 -mips2 -32 -I include -I src -DNON_MATCHING` → `lui v0; lw v0,0(v0); jr ra; sw a0,0(sp)` = **the target, byte-exact**. (Note: the dead `a0` is homed in the jr delay slot automatically — IDO uses the arg-home as a free delay-slot filler when nothing else is available; no `&param`/`volatile` lever needed.)
- **In-tree** (compiled as part of the full `game_uso.c`, identical cc + flags via asm_processor) → `lui v0; sw a0,0(sp); jr ra; lw v0,0(v0)` — the home and the load are **swapped**: IDO's list scheduler fills the `lui→lw` gap with the independent home store, pushing `lw` into the delay slot.

Same compiler, same flags, same preprocessed C body — only the surrounding TU differs. This is NOT lower-opt (-O1/-g3 don't reproduce it), NOT a C-form issue (tried volatile `*p=&a0`, `*p=a0` self-store, statement reorder, volatile global load — all give the in-tree order or worse), and NOT permuter-crackable (the scheduler state is TU-wide). **Diagnostic:** when a function matches standalone but the in-tree `report.json` shows it not matching, verify the in-tree `.o` with objdump — if the only diff is delay-slot/scheduling order, it's this cap. Genuine cap; keep INCLUDE_ASM. (2026-05-24)

<a id="feedback-ido-arg-save-to-sreg-in-bne-delay"></a>
## IDO schedules arg-save `or sN, aN, zero` into bne delay slot when an immediate `if (aN == 0)` test follows the prologue

_When function body starts with `if (a0 == 0)` after prologue, IDO -O2 schedules `or s0, a0, zero` (the s-reg copy of a0) into the bne delay slot rather than into the inter-spill gap. Target may have it earlier in prologue. Unflippable._

**Pattern:** function takes `a0` as char* and immediately tests `if (a0 == 0)` to alloc-fallback. The body uses `s0` for the working pointer (so `or s0, a0, zero` happens somewhere in the prologue).

**Two valid placements IDO can choose:**

1. **Inline-prologue** (target sometimes): `sw s0; or s0,a0,zero; sw ra; sw a1; sw a2; bne a0,zero,+5; sw a3 [delay]`
2. **Bne delay slot** (IDO -O2 default in this case): `sw s0; sw ra; sw a1; sw a2; sw a3; bne a0,zero,+7; or s0,a0,zero [delay]`

**Why:** IDO's instruction scheduler picks the simplest fill for the bne delay slot. The `or s0,a0,zero` has no dependency on the spill chain, so it's a candidate. With 4+ arg spills, IDO ends up with the move as the freshest unscheduled instruction at bne emission time → fills delay slot.

**What does NOT flip it (verified on `game_uso_func_00001D30`, 2026-04-21):**
- `register char *p = a0;` — no change
- `register char *p; p = a0;` (decl/assignment split) — no change
- Various rearrangements of the `if (p == 0)` block — body always re-emerges with same prologue scheduling

**How to apply:** when the only diff in an otherwise byte-identical match is the position of `or sN,aN,zero` (target inline-prologue, ours in bne delay slot), accept the ~95-97 % match and NM-wrap. Don't grind register hints; they don't help here. Permuter might find an offset-shift via local variable reorder, but the cap is structural for IDO -O2 with this idiom.

**Related:** `feedback_ido_arg_save_reg_pick.md` — sibling case where IDO picks the WRONG arg-save reg ($a1 vs $a3); also unflippable.

---

---

<a id="feedback-ido-asm-intrinsic-treated-as-function-call"></a>
## IDO C compiler treats `__asm__("nop")` as a FUNCTION CALL, not inline-asm

_IDO 7.1 does NOT support GCC's `__asm__("...")` inline-asm syntax. Writing `__asm__("nop");` in C compiles to a cross-USO function call (`lui+addiu+jal __asm__`) plus full prologue/epilogue rewriting. NOT a nop emission. The empty-string scheduling-barrier `__asm__("")` is the only widely-used variant; even THAT may be a no-op to the optimizer rather than a literal asm directive — verify shape impact when used. Don't reach for `__asm__("nop")` as a delay-slot suppression trick._

**Rule:** Don't use `__asm__("nop");` (or any non-empty `__asm__("...")` containing instruction text) in IDO 7.1 source. The IDO C front-end does not implement GCC inline-asm; the `__asm__` token parses as an undeclared function name, so:
- The string literal `"nop"` becomes the call's argument: emits `lui+addiu` to materialize the string-literal pointer.
- `__asm__` becomes the call target: emits `jal __asm__` (which links via cross-USO placeholder to `game_uso_func_00000000` or similar in this project).
- The function wrapping it gains a full prologue (`addiu sp,sp,-N; sw ra,...`) and epilogue (`lw ra; addiu sp,sp,N; jr ra`).

**Why this matters:**
- The doc-locked `game_uso_func_00007ABC` cap is "missing nop in delay-slot position 1." Naive instinct: just `__asm__("nop");` between two C statements to occupy the slot before reorg.c fills it. Wrong — IDO doesn't pass through the directive.
- Variants seen in 1080: a 4-insn / 0x10-byte function explodes to 11+ insns / 0x40+ bytes with a spurious `jal` into a cross-USO placeholder, fuzzy 0%.

**Why this is non-obvious:**
- GCC of any vintage honors `__asm__("nop")` as literal-byte emission; this is the standard portable trick across compilers.
- The 1080 / Glover / OoT codebases use `__asm__("")` (empty body) liberally as a scheduling barrier, which has zero string-literal arg and is routed through the optimizer's no-op path. That sets the expectation that other `__asm__("...")` strings might also work — they don't.
- The build doesn't fail; it produces wrong code that link-resolves cleanly (because the `__asm__` symbol gets relocation-bound to whatever cross-USO placeholder is in scope).

**How to apply:**
- For IDO inline-asm-style needs: stick to `__asm__("")` empty-body scheduling barriers — those are validated.
- For asm-emission, use `INCLUDE_ASM`/`.s` files only, not inline directives.
- For delay-slot fill suppression: there's no C-level lever in IDO 7.1; the choice is reorg.c's. Pre-arrange code such that no fillable insn is in scope at the branch point (e.g. function entry / function exit), which forces nop. Otherwise accept the cap.

**Companion memos:**
- `feedback_byte_correct_match_via_include_asm_not_c_body.md` — wrap-via-INCLUDE_ASM is the byte-correct path when C can't reach the shape.
- `feedback_uso_entry0_trampoline_95pct_cap_class.md` — explains why post-cc recipes (PREFIX/SUFFIX/INSN_PATCH) are the structural fallback when C-emit can't reach byte-correct.

---

---

<a id="feedback-ido-base-adjust-for-clustered-offsets"></a>
## IDO target's "base-adjust trick" (addiu base, base, +N then use smaller offsets) isn't reachable from natural C

_When target asm does `addiu $v1, $v1, +0x2C` once and then accesses fields at offsets 0xC, 0x0, 0x10, etc. (= original 0x38, 0x2C, 0x3C of the struct), it's an IDO-O2 base-adjust optimization for accessing a CLUSTER of fields near offset 0x2C. Natural C uses original $v1 with full offsets like `*(int*)(p + 0x38)`. IDO -O2 won't generate the base-adjust from natural C — it picks the simpler full-offset form. NM-wrap such cases._

**Pattern (verified 2026-05-02 on `gl_func_0005FE1C`):**

Target asm:
```
0x...: addiu $v1, $v1, 0x2C        ; one-time base shift
0x...: jal gl_func
0x...: sw $v1, 0x1C(sp)             ; spill SHIFTED v1
0x...: lw $v1, 0x1C(sp)             ; reload SHIFTED v1
0x...: lw $a1, 0xC($v1)             ; = *(p + 0x38) using shifted base
0x...: addiu $t7, $a1, 1
0x...: sw $t7, 0xC($v1)             ; *(p + 0x38) = a1+1
0x...: lw $t8, 0($v1)               ; = *(p + 0x2C) using shifted base
```

The `addiu $v1, $v1, +0x2C` happens ONCE before the cluster of field accesses, letting subsequent loads use offsets 0xC, 0x0, 0x10 (small enough to fit in the 16-bit signed `lw` immediate AND visually clustered).

**Natural C** (no base-adjust):
```c
char *p = ...;
int count = *(int*)(p + 0x38);     // lw a1, 0x38(v1)
*(int*)(p + 0x38) = count + 1;     // sw t7, 0x38(v1)
return *(char**)(p + 0x2C) + ...;  // lw t8, 0x2C(v1)
```
IDO emits `lw rA, 0x38(v1)`, `sw rB, 0x38(v1)`, `lw rC, 0x2C(v1)` — three full-offset accesses on $v1, no base-adjust.

**Why IDO won't generate it:**

The base-adjust costs 1 extra `addiu` insn but doesn't shorten any individual load (offsets fit in 16-bit signed either way). IDO's allocator sees no benefit and picks the simpler form. The target asm was generated from C that EITHER had a `p2 = p + 0x2C` named local OR (more likely) this was a deeper IDO scheduling pass that we haven't reverse-engineered.

**How to apply:**

When you see this pattern in target — especially with the `sw $vN; lw $vN` spill+reload of the shifted base across a jal — recognize it as the base-adjust trick. Skip the function or NM-wrap with a note. Don't try `int *p2 = (int*)(p + 0x2C);` from C — IDO will eliminate the alias *if you only access it once*.

**2026-05-06 partial walk-back — multi-offset access through a typed intermediate IS reachable.**

Verified on `func_00007BF4` (bootup_uso): writing `short *p8 = (short*)((char*)arg + 8);` and accessing `p8[0]` (= flag), `p8[1]` (= idx), and `*(int*)((char*)p8 + 4)` (= fallback) DID make IDO emit `addiu v1, a0, 8` and reuse it for the cluster — promoting match from 69.5% to 79.8%. Three conditions seem to matter:

1. **Multiple distinct offsets through the intermediate** — single-use gets inlined.
2. **Smaller pointee type** (`short *` here) — type-mismatch with original arg `Cmd*` may stop IDO from collapsing the alias.
3. **Mixed-width loads through the intermediate** — `p8[0]`/`p8[1]` are `lh`, plus an `lw` via cast — the typed-intermediate tells IDO this is a deliberate base.

When the original `feedback_ido_base_adjust_for_clustered_offsets.md` claim was tested, both pre-conditions probably failed (single use OR same-typed alias). The base-adjust trick IS reachable; the gating is "multi-offset access through a different-typed intermediate."

**Related:** `feedback_ido_3save_vs_2save_arg_preserve.md` — similar "target uses an extra reg-shuffle that IDO won't reproduce."

---

---

<a id="feedback-mips-branch-likely-opcode-cheatsheet"></a>
## MIPS branch-likely opcode cheat sheet (decode raw `.word` before drafting C control flow)

When the splat output is raw `.word` directives instead of decoded mnemonics, decode the opcode by hand before writing C — guessing at the mnemonic by the leading hex digit silently inverts control flow.

Top 6 bits of the instruction = `(word >> 26) & 0x3F`:

| Opcode | Mnemonic | Top byte range |
|--------|----------|----------------|
| `0x14` | `beql`   | `0x50`–`0x53`  |
| `0x15` | `bnel`   | `0x54`–`0x57`  |
| `0x16` | `blezl`  | `0x58`–`0x5B`  |
| `0x17` | `bgtzl`  | `0x5C`–`0x5F`  |

(Within each row, the low 2 bits of the top byte spill into the `rs` field — `0x53` = `beql` with rs's high bit set, e.g. `$t8` or `$t9`. The mnemonic is unchanged.)

**Concrete failure:** for `mgrproc_uso_func_00001594`, raw word `5320000B` was misread as `bnezl t9` (a non-existent mnemonic — `bnezl` is the alias for `bnel rs, $zero`, opcode `0x15`, top byte `0x54-0x57`). The actual encoding is `beql $t9, $zero, +0xB` — branch ON EQUAL likely. The C body was written with the inverted condition (`if (entry != 0) early-return` instead of `if (entry == 0) early-return`); compiles fine but match dropped dramatically because all the downstream stores wound up on the wrong arm.

**Fix:** when raw `.word` lines have the leading byte in the `0x5x` range, look up the table above before assigning a mnemonic. The other regular branches with single-bit-direction confusion (`beq`/`bne`, `blez`/`bgtz`, etc.) live in opcode range `0x04`-`0x07` (top byte `0x10`-`0x1F`).

---

<a id="feedback-ido-beql-speculative-store-double-emit"></a>
## IDO emits the if-body's first store TWICE around a beql — once in delay slot (annulled on taken) + once at fall-through

_For `if (cond) { dst = val; ... }` IDO -O2 emits `beql cond_reg, $0, end; sw val, dst_off(dst_reg)` in the delay slot AND ALSO `sw val, dst_off(dst_reg)` at the fall-through. The delay-slot annulment semantics of beql cause the store to execute ONLY when the branch is NOT taken (cond != 0), so the doubled store is semantically correct — but visually surprising in the asm. Must be matched by writing the redundant store explicitly in the C body when reproducing the pattern, OR using a goto-based control flow that reuses the if-body's first statement._

**Pattern in target asm:**

```
        lw   v0, ...                ; some prior call's return value
        ...
        beql v0, $zero, .Lend       ; branch-likely on v0 == 0
         sw   v1, 0x14(a1)          ; delay slot — ANNULLED if taken
        sw   t9, 4(v1)              ; fall-through body
        sw   v1, 0x14(a1)           ; ← SAME store as delay slot, AGAIN
.Lend:
```

The `sw v1, 0x14(a1)` appears TWICE in the asm: once in the beql delay
slot, once at the fall-through path. This is NOT redundant in execution —
the delay slot is annulled when v0 == 0 (branch taken), so the store
runs only when v0 != 0 (and falls through). The fall-through copy then
runs (also only when v0 != 0). So the store actually executes ONCE per
branch-not-taken, but the asm encodes it TWICE.

**Why IDO does this:** beql with annulled-on-taken delay slot lets IDO
speculatively place the "first instruction of the if-body" in the delay
slot. The same instruction must ALSO be at the fall-through entry so
straight-line execution in the not-taken case sees the right code stream.
IDO emits both rather than restructuring control flow to share the slot.

**To match this pattern, write the redundant store in C:**

```c
if (cond_result != 0) {
    *dst = val;          /* this becomes the beql delay slot */
    other_work();
    *dst = val;          /* IDO will emit this AGAIN at fall-through */
}
```

The double-store-in-C is intentional — it represents the asm's
beql-delay-slot + fall-through pattern. Don't try to "optimize" the
duplicate away with `do { ... } while(0)` or goto — IDO loses the beql
emit.

**When it appears:** small if-bodies whose FIRST statement is a memory
store, called from a context where the branch condition has just been
loaded from a recent jal return. Especially common in constructors that
do "if (subobject != 0) { parent[idx] = subobject; ... }" patterns.

**Verified 2026-05-03 on eddproc_uso_func_000003BC** — the trailing
~10-insn region after the inner gl_func call shows this exact pattern.
The TODO-decode revealed the doubled `sw v1, 0x14(a1)` was IDO emit, not
a programmer mistake.

**Related:**
- `feedback_ido_swap_stores_for_jal_delay_fill.md` — similar but for jal
  delay slot stores (no annulment, just scheduling).
- `feedback_ido_unfilled_store_return.md` — when stores DON'T get
  promoted to delay slots.
- `feedback_ido_bnel_arm_swap.md` — bnel/beql arm-swap conventions.

---

---

<a id="feedback-ido-blez-vs-bne-signed-compare"></a>
## Asm `blez/blezl` vs `bne/beql` distinguishes `> 0` (signed) from `!= 0` (eq) source

_When target asm uses `blez $rs, X` or `blezl $rs, X` for a conditional, the C source MUST be `if (val > 0)` (signed comparison), NOT `if (val != 0)`. The `!= 0` form emits `bne $rs, $zero, X` (or `beql` for the inverted branch), which has the SAME runtime semantics for non-negative values but DIFFERENT bytes — and different semantics if the value can be negative. A fast 5-pp fix when the only diff is the branch instruction type._

**Pattern (verified 2026-05-02 on `game_uso_func_00000AEC`, 91.5 % → 97 %):**

Target asm:
```
8dcf0024  lw    $t7, 0x24($t6)
59e00003  blezl $t7, +3 (=skip)         ; if t7 <= 0 (signed) branch+likely-delay
ac850250  sw    $a1, 0x250($a0)         ; (only when t7 > 0)
```

**Wrong C** (matches "ptr is non-null" intuition):
```c
if (*(int*)((char*)p + 0x24) != 0) {
    a0->0x250 = a1;
}
```
IDO emits: `lw t7, 0x24(t6); beql t7, zero, +3` (branch-on-EQ-likely). Bytes diff vs target.

**Right C** (signed > 0):
```c
if (*(int*)((char*)p + 0x24) > 0) {
    a0->0x250 = a1;
}
```
IDO emits: `lw t7, 0x24(t6); blezl t7, +3` (branch-on-LE-zero-likely). Matches target.

**Decision matrix** for the typical `if (val ??? 0)` pattern:

| C source              | Asm emit (likely-form)  | Asm emit (regular form) |
|-----------------------|-------------------------|-------------------------|
| `if (val > 0)`        | `blezl rs, X`           | `blez rs, X`            |
| `if (val >= 0)`       | `bltzl rs, X`           | `bltz rs, X`            |
| `if (val < 0)`        | `bgezl rs, X`           | `bgez rs, X`            |
| `if (val <= 0)`       | `bgtzl rs, X`           | `bgtz rs, X`            |
| `if (val != 0)`       | `beql rs, zero, X`      | `beq rs, zero, X`       |
| `if (val == 0)`       | `bnel rs, zero, X`      | `bne rs, zero, X`       |

(IDO emits the LIKELY form when the if-body is small and the after-if can fill the delay slot. The non-likely form when the if-body is larger.)

**How to apply:** when grinding a NM wrap at 90+ % and the only diff is the branch-instruction MNEMONIC at a `if (val ??? 0)` test:
1. Look at the MIPS branch mnemonic in the target.
2. Find the row in the table.
3. Rewrite the C condition to match.

**Semantic caveat:** `> 0` and `!= 0` are NOT equivalent for negative values. If the field can be negative and the original logic was `!= 0`, using `> 0` to chase a byte match is INCORRECT semantically. Verify with caller context (what values does this field hold?). For raw byte-matching purposes the change is safe IF you trust the original target encodes the intended signed-positive check.

**Related:**
- Unsigned compare: `(u32)x > N` → `sltu`, `x > N` (signed) → `slt`
- `feedback_ido_branch_likely_arm_choice.md` — when likely-form fires
- `feedback_ido_bnel_arm_swap.md` — sibling case for arm-swap matching

**Origin:** 2026-05-02, game_uso_func_00000AEC: 91.5 → 97 % from this single fix; the remaining 3 % was pure regalloc shifted by inlining the chained deref.

---

---

<a id="feedback-ido-bnel-arm-swap"></a>
## IDO `bnel` with value-in-delay-likely comes from C with the EQUAL case in the `if` arm

_When the target asm has `bnel $a, $b, .exit; or v0, zero, zero` (branch-likely with "set 0" in delay-likely) and the other path sets v0=1 via `b + addiu v0, zero, 1`, write the C with the `==` case inside the `if`, not the `!=` case. The natural "bnel = branch-not-equal" mapping produces `beql` instead._

**Rule:** Target pattern:
```
bnel $v0, $t6, .exit
or   $v0, $zero, $zero   ; delay-likely (executed on branch-taken = !=)
b    .exit
addiu $v0, $zero, 1      ; delay of b (set when == and fall-through)
```

This returns 1 when equal, 0 when not-equal. Write the C as:

```c
/* MATCHES */
int r = foo();
if (r == a1) return 1;
return 0;
```

NOT this (produces `beql` instead of `bnel`):
```c
/* NON-MATCHING */
int r = foo();
if (r != a1) return 0;
return 1;
```

**Why this is counter-intuitive:**

You'd expect the "natural" translation of `bnel v0, t6 → return 0` to be `if (v0 != t6) return 0;`. But IDO picks `bnel` vs `beql` based on which arm is the **fall-through** (always-taken path that b + delay-sets-1 follows), not which condition you wrote. The FALL-THROUGH arm is the ONE AFTER the `if`. So putting `return 1` after the `if (==) {...}` makes IDO place the b+set-1 in the fall-through lane.

**How to apply:**

- If the target has `bnel` and you got `beql`: swap the if/else arms and invert the condition (`!=` → `==`).
- If the target has `beql` and you got `bnel`: same swap.
- Works for any "compare + set-0-or-1" flag-return pattern, not just equality. Same logic for `bgezl/bltzl`, `bnezl/beqzl`, etc.

**Related:** the general "If/else arm swapping" guidance in the /decompile skill. This memory covers the specific branch-likely flavor where both "arms" are flat `return 0` / `return 1`.

**Origin:** 2026-04-19 game_libs gl_func_0000A9F4. First attempt `r != a1 → 0; else 1` → `beql` (wrong). Swapped to `r == a1 → 1; else 0` → `bnel` (100 %).

**Caveat — DOES NOT apply to 2-stage NULL-check returning 0/1.** For:
```c
if (p == NULL) return 0;
if (p->field == 0) return 0;
return 1;
```
IDO -O2 emits eager-init `move v0,zero; beqz p; nop` even for the canonical
"== case in the if arm" form. The single-stage swap recipe above only works
when there's exactly ONE branch and the not-taken path falls through to a
`b + addiu v0,zero,1`. With TWO early-returns chained, IDO doesn't move the
return-value init into either delay-likely. The `goto end` shared-epilogue
form is also identical. Cap is permuter-class (regalloc-driven: target reuses
the return reg as the second-deref base). Verified 2026-05-17 on
arcproc_uso_func_00000F78.

---

---

<a id="feedback-ido-bnel-shared-store-after-helper"></a>
## bnel-likely with shared store-in-delay = `if (!cond) helper(); shared_store;`

_When asm shows `bnel ptr,zero,+N; sw <val>,off(reg) [delay-likely]; jal helper; ...; sw <val>,off(reg)` (same store on both paths), the C source is `if (cond == 0) helper(); store;` — the store happens both as delay-likely (when ptr!=0, skip helper) AND after helper returns (when ptr==0, helper runs)._

**Asm fingerprint:**
```
bnel  $rN, $zero, +K       ; branch if rN != 0 (skip helper)
sw    $zero, OFF($rM)      ; delay-likely: ONLY runs if branch taken (rN != 0)
jal   helper                ; fall-through: runs only if rN == 0
addiu $a0, ..., ...         ; (jal delay)
sw    $zero, OFF($rM)      ; after helper returns (rN == 0 path)
;; both paths converge here
```

Note both stores write the SAME value to the SAME address — but only ONE runs per execution path. The delay-likely's store handles the "skip helper" path; the post-jal store handles the "run helper" path.

**The C that matches:**
```c
if (*(int*)&D_GLOBAL == 0) {
    helper(&D + format_offset);
}
*(int*)((char*)a0 + 0x18) = 0;     // shared store
```

The IDO emit naturally produces the bnel-likely + shared-store-in-delay shape because:
- `if (cond) helper(); X;` reads as "X always runs; helper conditionally"
- IDO's scheduler picks `X` (cheap store) as the delay-likely-fill candidate
- bnel emits when delay-slot fill is "useful on the taken path AND independent of the test"

**How to apply:**
- See bnel + delay-likely-store + jal + post-jal-same-store pattern? Write the if-check followed by the shared store. Don't separate them into two different stores or add an else branch — the cleanest C form is `if (cond) helper(); shared_store;`.
- The store value is typically `0` or some constant that's safe to issue on either path (since both paths reach it).
- This is DISTINCT from `feedback_ido_alloc_or_passthrough_ternary.md` (bnel for alloc-or-passthrough); recognize the difference: alloc form has TWO different code paths writing the SAME variable; this form has ONE store that runs on both paths.

**Origin:** 2026-05-03, gl_func_0005FE7C (38-insn resource-load function). Hit 90.79% NM first try with the natural `if (*global == 0) helper(); a0[6] = 0;` shape. Sibling of gl_func_0005FDCC/FCC4/FD20.

---

---

<a id="feedback-ido-bnel-tail-merge-register-restore"></a>
## IDO bnel tail-merging routes the false-path epilogue through the true-path's register-restore tail (cosmetic, ~99 % cap)

_When the function body is `if (cond) { several jal calls }` and the true path ends with reload-args-then-jal patterns like `lw a0,0x18(sp); jal; lw a1,0x1C(sp)`, IDO sets the bnel branch target to the MIDDLE of those reloads (skipping the jal but keeping the reloads). Effectively the false-path "wastes" cycles reloading caller-saved args before jumping to the actual epilogue. C produces a clean target — straight to `addiu sp; jr ra`. The result is structurally correct but loses ~0.5 % match._

**The pattern:**

Target asm:
```
bnel  $v0, $at, .Ltail        ; if v0 != const, branch
 lw   $a0, 0x18(sp)           ; (delay) reload a0
jal   gl_func                 ; first call (v0==const path)
 nop
jal   gl_func                 ; second call
 lw   $a0, 0x18(sp)           ; (delay) reload
lw    $a0, 0x18(sp)           ; reload again for third call
jal   gl_func
 lw   $a1, 0x1C(sp)           ; (delay) reload — `.Ltail` lands HERE
.Ltail:
lw    $ra, 0x14(sp)
addiu $sp, $sp, 0x18
jr    $ra
 nop
```

So when `v0 != const`, control jumps to the third call's delay-slot reload of `$a1`. The reload happens (with no useful effect — `$a1` is dying) and execution proceeds into the epilogue.

**My C output:**
```
bnel  $v0, $at, .epilogue
 lw   $ra, 0x14(sp)           ; (delay) reload ra
... [v0 == const path with 3 jals] ...
.epilogue:
addiu $sp, $sp, 0x18
jr    $ra
```

Branch target lands directly at the epilogue with `lw ra` in the delay slot. Cleaner, but 1 fewer instruction in the false path.

**Why this happens:** IDO's optimizer notices that the v0==const path's epilogue starts with `lw a0` (already known to be correct value from saved slot, even though dead). Tail-merging finds the longest matching suffix between paths and shares it. The false-path branch target lands earlier in the shared tail than seems necessary.

**How to apply:**

- When you see a 99.4 %+ match where the only diff is the bnel branch target offset (target points 2-3 instructions later than yours), check whether the target lands inside a register-reload sequence. If yes, this is the IDO tail-merge pattern.
- **No reliable C fix.** Tried: replacing `if (v == k) { ... }` with `if (v != k) return; ...` (same output), goto-end pattern (same), reordering calls, splitting blocks. The optimizer makes this choice based on its own analysis.
- Wrap NON_MATCHING at 99 %+. Don't burn iterations chasing the last 0.5 %.

**Origin (2026-04-20):** `titproc_uso_func_00000FD0` — body is `if (*a1 == 21) { gl_func(); gl_func(a0); gl_func(a0,a1); }`. Reached 99.42 % with named local `int v = *a1`, but bnel target landed at `addiu sp` (epilogue) while target lands at `lw a1, 0x1C(sp)` (3 instructions earlier). All flip variants tried produced the same result.

**Combine with `feedback_ido_v0_reuse_via_locals.md`:** that memo handles the inlined-vs-local choice for the deref register ($v0 vs $t-reg). This memo handles the bnel target offset within the matched-otherwise body. Both can apply to the same function.

---

---

<a id="feedback-ido-boolean-return-xor-sltiu-chain"></a>
## For multi-condition state checks, single boolean-return expression beats if-return chain by 70+ pp

_When target uses `xor; sltiu; bne` chains for `(c1 || c2 || c3)` style checks (computing each condition as a 0/1 value, branching on non-zero to a shared exit), use `return c1 || c2 || c3;` in C — NOT `if (c1) return 1; if (c2) return 1; ...`. The if-return chain emits multiple separate `jr ra; addiu v0, zero, 1` epilogues, completely different shape (~20% match). The single-expression form emits the target's chained boolean-compute-and-branch (~94%)._

**Pattern (verified 2026-05-02 on `game_uso_func_00000674`, 20 % → 93.86 %):**

Target asm shape (44 insns checking a struct's fields):
```
lw   v0, 0x0(a0)
addiu a1, zero, 2
xor  v1, a1, v0          ; v1 = (2 ^ a0[0])
sltiu v1, v1, 1          ; v1 = (v1 == 0) ? 1 : 0  =  (a0[0] == 2)
bne  v1, zero, +N (=match_label)   ; if (a0[0] == 2) goto match
xori v1, v0, 3            ; v1 = (a0[0] ^ 3)
sltiu v1, v1, 1          ; v1 = (a0[0] == 3)
beql v1, zero, +N (=skip_a1_check) ; if (a0[0] != 3) skip
... (chain continues for each || term) ...
match_label:
or   v0, v1, zero        ; return v1
jr   ra
```

The whole function returns a single boolean (last condition's value), and IDO uses **xor + sltiu** (not `slt + bne`) to compute each `(val == const)` test, then **chains them with `bne v1, zero, exit`** to short-circuit on the first true.

**Wrong C** (matches "natural" if-return reading):
```c
int f(int *a0) {
    if ((a0[0] == 2 || a0[0] == 3) && a0[1] == 1) return 1;
    if ((a0[4] == 2 || a0[4] == 3) && a0[5] == 1) return 1;
    if (a0[8] == 1) return 1;
    if (a0[10] == 2) return 1;
    return a0[12] == 2;
}
```
Result: **20 % match.** IDO emits each `return 1` as its own `jr ra; addiu v0, zero, 1` epilogue (4 separate exit points), uses `beq` not `bne` chains, and the overall shape is a tree of if-then-else blocks, not the target's flat short-circuit chain.

**Right C** (single expression):
```c
int f(int *a0) {
    return ((a0[0] == 2 || a0[0] == 3) && a0[1] == 1)
        || ((a0[4] == 2 || a0[4] == 3) && a0[5] == 1)
        || a0[8] == 1
        || a0[10] == 2
        || a0[12] == 2;
}
```
Result: **93.86 % match.** IDO emits the target's `xor; sltiu; bne` chain with a single `or v0, v1, zero; jr ra` epilogue. Remaining 6 % is just $v0/$v1 register-naming flip (not C-controllable per `feedback_ido_v0_reuse_via_locals.md`).

**Why the gap is so large:**
The if-return form has C semantics that REQUIRE separate exit points (each `return 1` is observable), so IDO can't merge them. The single-return form has the WHOLE expression as one observable thing, freeing IDO's scheduler to fold it into a chained-test sequence.

**How to recognize when to use this:**
Look at the target asm:
- Multiple `xor + sltiu` 2-instruction sequences computing booleans → single-expression return
- Single `or v0, vN, zero` epilogue (returning a register that's the result of a boolean compute) → single-expression return
- Each branch jumps to the SAME exit point (single `jr ra`) → single-expression return

Vs:
- Multiple separate `jr ra; addiu v0, zero, CONST` epilogues → if-return chain (each return is its own basic-block tail)
- Branches go to different exit blocks → if-return chain

**How to apply:** for state-check / "match-any-of-these-conditions" functions, write the C as a single `return X || Y || Z` expression, not as a sequence of `if-return-1` blocks. Use `&&` for AND-chained conditions inside each `||` term. The single-expression form is also more idiomatic for predicate functions and easier to read.

**Related:**
- `feedback_ido_v0_reuse_via_locals.md` — explains the residual v0/v1 flip after this pattern is right
- `feedback_ido_swap_stores_for_jal_delay_fill.md` — sibling principle: source order/structure controls IDO's emission shape

---

---

<a id="feedback-ido-branch-likely-arm-choice"></a>
## For float-predicate functions with conditional body, prefer positive-arm form to avoid branch-likely

_`if (!cond) return 0; body; return 1;` triggers IDO to emit `bc1tl`/`bnezl` (branch-likely). The equivalent `if (cond) { body; return 1; } return 0;` emits plain `bc1f`/`bnez`. Same logic, different scheduling._

When the function has a float comparison gating a non-trivial body that ends with `return 1`, IDO -O2's branch selection depends on the source ARM order:

**Negative early-return form (gives branch-likely, hard to match expected non-branch-likely target):**
```c
int f(int *a0) {
    if (*(float*)((char*)a0 + 0x48) != 1.0f) {
        return 0;        // early-return on failure
    }
    if (*(int*)((char*)a0 + 0x68) == 0) {
        call(&D, 1);
    }
    return 1;
}
```
→ IDO emits `bc1tl` (branch-likely-true) and `bnezl`. Match: ~51 % vs target.

**Positive in-arm form (gives plain branch, matches):**
```c
int f(int *a0) {
    if (*(float*)((char*)a0 + 0x48) == 1.0f) {
        if (*(int*)((char*)a0 + 0x68) == 0) {
            call(&D, 1);
        }
        return 1;
    }
    return 0;
}
```
→ IDO emits plain `bc1f` and `bnez`. **100 % match.**

**Why:** IDO's scheduler decides whether to use a branch-likely variant based on what fills the delay slot. With early-return-on-failure, the body sits AFTER the branch and IDO sees an opportunity to use bc1tl with the body's first instruction in the delay slot. With positive-arm form, the body is INSIDE the if-block and IDO uses plain bc1f to skip the entire block, with `move v0, zero` (early v0=0 init) hoisted before the comparison so the fall-through can `b epilogue` cheaply.

**How to apply:**
- For predicate functions returning 0/1 with conditional side-effect body: write the positive form (`if (cond) { body; return 1; } return 0;`).
- The early-return form is generally GOOD for IDO scheduling (see `feedback_ido_early_return_ra_delay_slot.md`), but for THIS specific pattern (float compare → conditional body → return 1/0), it inverts.
- Easy test: if your build emits `bc1tl` or `bnezl` where the target has plain `bc1f`/`bnez`, try inverting the if-arm structure.

**Origin:** 2026-04-19 bootup_uso func_00013924 (`if (a0->[0x48]==1.0f) { if (a0->[0x68]==0) call(); return 1; } return 0;`). The early-return form scored 51 %; the positive form scored 100 %.

**Extension to integer 2-deref null-check predicates (verified 2026-05-06 on `timproc_uso_b3_func_00000E30`):** the same arm-choice rule applies when the cond is `if (ptr == 0)` instead of `if (!float_cmp)`. For a 2-deref null-check returning 1/0:
- **Negative early-return form** `if (v == 0) return 0; if (v->X == 0) return 0; return 1;` → IDO emits `bnezl` + duplicated body `lw`, **14 insns**.
- **Positive nested form** `if (v != 0) { if (v->X != 0) return 1; } return 0;` → IDO emits clean `beql` with `move v0,zero` in delay-likely slot, **12 insns** = exact match.

The 2-insn delta is because the negative form forces IDO to materialize the second-deref `lw` on BOTH branches of the inverted-skip, while the positive form lets IDO use beql annulled-delay to skip the second deref entirely on the null path. Same principle as the float-predicate case: target's branch-likely-with-success-fallthrough shape needs the C to express success as the inner positive arm.

**Extension to tail-call wrappers (verified 2026-05-08 on `gl_func_00067510`):** the same arm-choice rule applies when the success arm is a `return tail_call(...)` (not just `return 1`). 16-insn early-return + tail-call wrapper:
- **Negative early-return form** `if (v == 0) return 0; return call(&D, v - 1);` → IDO emits `bnez + nop + b + move v0,zero`, 15 insns, **does not match** (target is 16 insns).
- **Positive in-arm form** `if (v != 0) { return call(&D, v - 1); } return 0;` → IDO emits `beqzl + move v0,zero (delay-likely) + jal + addiu a1,v0,-1 (delay) + b + lw ra (delay) + move v0,zero (dead) + lw ra + addiu sp + jr ra`, 16 insns = exact match. Note the duplicated `lw ra` and apparently-dead second `move v0,zero` are tail-merge artifacts that the positive-arm form preserves but the negative-arm form optimizes away.

Lesson: this rule isn't limited to predicate functions returning literal 0/1 — any `early-return-zero + return-non-zero-result` pattern where the non-zero result is a function call (or any non-trivial expression) is subject to the same arm-choice flip.

**Extension to plain int if-else dispatch (verified 2026-05-06 on `timproc_uso_b1_func_00000E40`):** when target uses plain `bnez` to JUMP TO the call-arm (vs target using `beql` to SKIP-OVER it), the arm-choice direction is OPPOSITE. For dispatch shape `bnez cond, call_label; nop; b end_label; sw store(in delay); call_label: jal; or a2,$0(in delay); end_label:`:
- **Positive call-arm form** `if (cond != 0) call(); else store;` → IDO picks `beql` skip-on-zero (10 diffs).
- **Negative store-arm form** `if (cond == 0) store; else call();` → IDO picks plain `bnez` jump-to-call (0 diffs = exact match).

**Rule of thumb:** if target has plain `bnez/beq` JUMPING TO a call-arm (non-call-arm in fallthrough delay slot), write `if (cond == 0) non_call_arm; else call();`. If target has `beql/bnezl` SKIPPING a call-arm, write `if (cond != 0) call(); else non_call_arm;`. The C arm that contains the JUMP-TARGET work is opposite to the C arm that contains SKIPPED work.

**Multi-predicate `bc1fl`-to-shared-return chain (AABB/range tests) NOT reproduced by either form (2026-05-23, `game_libs_func_0003A158` point-in-AABB):** a 6-comparison float test `return (a1[0]<=a0[0] && a0[0]<=a1[3] && ...) ? 1 : 0` where the TARGET emits, for each check, `c.le.s; bc1fl SHARED_return0; lwc1 next_operand(annul delay)` — i.e. branch-likely-FALSE to ONE shared return-0 block, with the next comparison's operand load tucked in the annulled delay slot. Neither C form reproduces this: the `&&` single-if form → plain `bc1f` (38/38 same size, but bc1f not bc1fl + different load schedule); the negative-early-return form `if(!(a<=b)) return 0;`×6 → `bc1tl` with SEPARATE return-0 blocks (48 insns, bigger). The shared-return + annul-delay-load + branch-likely confluence is its own arm-choice cap — recognize the AABB/range-test family (game_libs 3A158/3A1F0/3A278/3A2FC/3A380/3A400/3A484/3A504, all reloc-free FP) and NM-wrap with the clean `&&` form; defer byte-match to a focused pass.

---

---

<a id="feedback-ido-buf-array-alignment"></a>
## IDO stack placement — use `int buf[2]` not `int buf` to force 8-byte alignment

_When a stack buffer ends up 4 bytes higher than target, try declaring it as `T buf[2]` instead of `T buf`; IDO aligns arrays to 8 bytes, simple scalars to 4._

**Rule:** If IDO places a stack buffer 4 bytes higher than the target asm expects (e.g., target `addiu $a1, $sp, 0x18` but your compile produces `addiu $a1, $sp, 0x1C`), rewrite `T buf;` as `T buf[2];` (array of 2 — access only `buf[0]`).

**Why:** IDO's -O2 stack allocator aligns array-typed locals to 8 bytes, but scalar `int`/`float` locals to just 4 bytes. When the saved-arg slot (at sp+0x20 in a 32-byte frame) and a scalar buf both want to live in the 0x18–0x20 window, IDO places the scalar at sp+0x1C (4-byte aligned, just below the arg slot), leaving sp+0x18–0x1B as padding. An array buf gets bumped to the 8-byte-aligned sp+0x18 instead, consuming sp+0x18–0x1F. Accessing `buf[0]` reads from sp+0x18 — matching the target.

The original code probably used a small struct or an array too, for the same reason. Either way, `T buf[N]` with `buf[0]` as the only access is a clean reproduction.

**How to apply:**
- Symptom: your build's `addiu` and `lw`/`lwc1` offsets to the stack buffer are +4 from the target.
- Fix: change `int buf;` → `int buf[2];` (or `float buf[2];`), change `&buf`→`buf`, change `buf` read → `buf[0]`.
- Verify via `/tmp/test.c` standalone compile before patching the real source.

**Origin:** hit 2026-04-18 on bootup_uso func_00000008/00000044 (read-4-bytes wrappers that call `func_00000000(&SYM, &buf, 4); *dst = buf;`). Scalar `int buf` produced sp+0x1C offset; `int buf[2]` matched at sp+0x18.

---

---

<a id="feedback-ido-cfe-strict-ascii-gotchas"></a>
## IDO 7.1 cfe rejects specific non-C-syntax chars EVEN IN COMMENTS — concrete blocklist

_The general rule "no unicode in C source" is well known, but IDO 7.1's cfe is stricter than standard C — it rejects specific characters even inside `/* ... */` comment blocks. Concrete blocklist verified 2026-05-05 via build errors on src/kernel/kernel_020.c._

**Rule:** When writing comments in `.c` files for the IDO build, stick to **plain ASCII without these specific characters**:

| Char | Verified-failing example | Fix |
|------|--------------------------|-----|
| `→` (em-arrow) | `(F1→F2 via no-jr-ra)` | `->` (ASCII arrow) |
| `—` (em-dash, U+2014) | `applicability window — 8-insn function` | `--` (double-dash) |
| `@` (literal at-sign) | `F4 @ 0x80AC-0x80CC: 8 insns` | `F4 at 0x80AC-0x80CC` |
| `` ` `` (backtick) AROUND non-ASCII | `(F3→F2 via \`b\`)` — backtick + arrow combo | use plain words, no backticks |
| `\*` escape (in comment text) | `*MI_INTR_MASK_REG = 0x2; /\* enable \*/` | use line-comment `// ...` instead |

**Why is this non-obvious:** standard C allows ANY character inside `/* ... */` comments. But IDO 7.1's cfe (a pre-MIPSpro compiler-frontend) does its own pre-tokenization scan that recognizes `@` as an "unknown character" and refuses to treat the rest of the line as comment text — emits "Unknown character @ ignored" + cascading "Syntax Error" lines.

**Diagnostic signal:** build errors of the shape:
```
cfe: Error: <file>, line N: Unknown character X ignored
  * ... source line ...
 -----^
cfe: Error: <file>, line N: Syntax Error
```
The `Unknown character` error tells you exactly which char is the problem. The cascading "Syntax Error" entries are downstream confusion from cfe losing comment-block tracking after the bad char.

**Common-sense workarounds:**
- Use ASCII art for arrows: `->`, `=>`, `<-`
- Use ASCII for dashes/separators: `--`, `==`
- Use "at offset 0xN" instead of "@ 0xN"
- Use C-style line comments `//` for inline pseudocode that contains `*` (avoids nested-comment-terminator issues with `\*...\*/`)
- Replace `feedback_xxx.md` with `feedback_xxx_md` if backticks cause issues — though backticks alone usually work; combos with non-ASCII break it

**Nested-comment-terminator caveat (related):** trying to escape `/* ... */` inside a `/* ... */` block by writing `/\*...\*/` doesn't help if you later accidentally `sed s/\\\*/*/` — that re-introduces the terminator. Use `//` line comments for inline pseudocode samples.

**Project-wide note:** the project README/skill says "Do NOT use unicode/emoji in C source — the assembler uses EUC-JP encoding." This memo enumerates the SPECIFIC characters seen in practice. Many src files have em-dashes (`—`) inside comments and build fine, so the rule is char-specific not blanket-unicode — `@` and arrow combos are the consistent breakers.

**Verified break + fix (2026-05-05, src/kernel/kernel_020.c):** added a 4-sub-function bundle wrap with `→`, `@`, `\*` characters; build failed with `Unknown character @ ignored` + nested-comment-terminator cascade. Fixed by ASCII-substituting all listed chars. Triggered when running `scripts/land-successful-decomp.sh` for an unrelated function (kernel_000.c.o was rebuilt, but kernel_020's NM build was clean — turned out kernel_020's NON_MATCHING-build-only path tried to compile the comment that had survived the default INCLUDE_ASM tautology path).

---

---

<a id="feedback-ido-char-default-unsigned"></a>
## IDO treats plain `char` as UNSIGNED by default — use `signed char` for `lb` opcodes

_Casting `(char)int_val` at IDO -O2 emits `lbu` (zero-extend), not `lb` (sign-extend). If the target asm has `lb`, write `(signed char)int_val`. Plain `char` locals and plain `(char)` casts behave as unsigned. Also: reading a byte from a big-endian `int` local at sp+N via `(signed char)`cast produces `lb (N+3)(sp)` — the LSB on big-endian MIPS._

**Rule:**

1. **Plain `char` is unsigned in IDO's C mode.** `(char)x` produces `lbu` (zero-extend). To get `lb` (sign-extend) in the output, use **`(signed char)x`** explicitly. Same for local variables: `char local2;` → `lbu`. `signed char local2;` → `lb`.

2. **Byte extraction from an int local on big-endian MIPS:** writing `func((signed char)int_local)` in C generates `lb (slot_addr+3)(sp)` because the LSB of a 4-byte int lives at the HIGH address on big-endian. This is how the ROM reads low-byte-of-int idioms.

**Example (1080 bootup_uso/func_0000031C):**

Target asm:
```
addiu a1, sp, 0x1C    # &local1 (int at sp+0x1C)
addiu a2, sp, 0x18    # &local2 (4-byte slot at sp+0x18)
jal ...
...
jal ...
lb   a2, 0x1B(sp)     # read LSB of local2 (byte at slot_addr+3)
```

**Wrong C** (gives lbu + wrong slot address):
```c
int local1;
char local2;                    /* char → lbu, slot addr = 0x1B (1-byte) */
func(a1, &local1, &local2, a2);
func(a0, local1, (int)local2);  /* (int) promotion uses lbu */
```
Produces: `addiu a2, sp, 0x1B` and `lbu a2, 0x1B(sp)`.

**Right C:**
```c
int local1, local2;                      /* both int → slot at sp+0x18 */
func(a1, &local1, &local2, a2);
func(a0, local1, (signed char)local2);   /* reads byte at sp+0x18+3 = 0x1B with lb */
```
Produces: `addiu a2, sp, 0x18` and `lb a2, 0x1B(sp)`.

**How to apply:**

- If target uses `lb`: the C must cast through `(signed char)` or declare the local as `signed char`, NOT plain `char`.
- If target reads a byte-offset from a stack int (e.g., `lb N+3(sp)` where `N` is the int's address): the source is `(signed char)int_local` — not a separate `char` local. The `+3` is big-endian LSB positioning.
- `lbu` is the default for plain `char`/`unsigned char`; only switch to `signed char` if you see `lb`.

**Related:** `feedback_ido_narrow_arg_promotion.md` (don't use `char`/`short` args; use `int a + (char)a` cast for byte-store patterns). This is the "read" analogue.

**Origin:** 2026-04-19, 1080 bootup_uso/func_0000031C. First attempt used `char local2`, got `lbu` + wrong stack offset; `(signed char)int_local` fixed both in one shot.

---

---

<a id="feedback-ido-constant-address-load-fold-inevitable"></a>
## IDO -O2 constant-folds the load-address even when the base is a register-declared local

_For `arg = *(int*)((char*)base + N)` where base = `&D_constant`, IDO emits a fresh `lui+lw` rather than `lw arg, N($base_reg)` even with `register` keyword. The fold is structural; no C-level workaround flips it._

When `base` is `register T *base = &D_constant;` (a stack-local pointer
to a fixed extern address), IDO -O2 emits load-from-base accesses as
fresh `lui+lw` rather than indexed-via-base:

```c
register char *base = &D_00000000;
arg = *(int*)((char*)base + 0x40);
// IDO emit: lui v1, %hi(D_00000000); lw v1, %lo(D_00000000+0x40)(v1); or arg, v1, zero
// (3 insns, fresh address materialization)
```

Even though `base` IS in an $s-reg and the indexed form would be cheaper:
```
lw arg, 0x40($base_reg)    // 1 insn — what target uses
```

IDO's constant-fold pass sees `((char*)base + 0x40)` as a compile-time
constant address (because base = &D, both fixed) and re-emits the lui
sequence at each use site.

**Why:** observed 2026-05-03 on `n64proc_uso_func_00000014`'s loop-tail
reload `arg1 = base[0x40]`. 3 variants tried — all failed:
- `register int *base = (int*)&D` + `base[0x10]` indexed — folded.
- `volatile int*` cast — defeats CSE, regresses (extra t-reg shuffle).
- `register int *baseAt40 = base + 0x40` precomputed — folded too.

**How to apply:**
- When the asm has `lw arg, OFFSET($s_reg)` with $s_reg holding a known
  extern's address, you cannot reach it from C with `&D_constant`-derived
  pointers. Don't grind on it — accept the cap.
- The only path to indexed-via-$s would be a non-constant base — e.g.
  if `base` were a function arg or came from a runtime computation.
  But for "free pointers" to fixed externs, IDO's constant fold wins.
- This affects loop-tail reloads in functions that re-read fixed
  extern memory each iteration. Common in dispatcher loops over
  global state arrays.

---

---

<a id="feedback-ido-shared-base-via-deferred-assign-and-named-locals"></a>
## To force IDO to share a single base register across multiple loads from `&D + N`, defer the pointer assignment past prior calls AND capture into named locals before the consuming call

_Counter-example to `feedback-ido-constant-address-load-fold-inevitable`. When you have TWO+ loads from the same `&D + offset` base going into a SINGLE downstream call (e.g. `f(a0, t[0], t[1], 1)`), the natural form `int *t = &D + N; ... f(a0, t[0], t[1], 1)` makes IDO inline 2 separate `lui+lw` per access. To get target's shared-base form (`lui base; addiu base, base, N; lw r1, 0(base); lw r2, 4(base)`), use `register T *t; ... t = &D + N; v1 = t[0]; v2 = t[1]; f(a0, v1, v2, ...)` — defer the assign past prior calls AND capture into named locals before the call._

**Pattern (verified 2026-05-06 on game_uso_func_00010E2C, 85.17 → 87.38%):**

Bad C (2 lui per access):
```c
int *t = (int*)((char*)&D_00000000 + 0xE40);
game_uso_func_00000000(a0, 0, 0, 1, 1, 1);
game_uso_func_00000000(a0, t[0], t[1], 1);
// emit: lui a1, 0; lui a2, 0; lw a2, 0xE44(a2); lw a1, 0xE40(a1)
```

Good C (shared base):
```c
register int *t;
int v1, v2;
game_uso_func_00000000(a0, 0, 0, 1, 1, 1);
t = (int*)((char*)&D_00000000 + 0xE40);
v1 = t[0];
v2 = t[1];
game_uso_func_00000000(a0, v1, v2, 1);
// emit: lui v0, 0; addiu v0, v0, 0; lw a1, 0xE40(v0); lw a2, 0xE44(v0)
```

**Why:** the deferred assignment + intermediate locals split the address computation into a distinct basic-block from the consuming call's arg-setup. With the inlined `f(..., t[0], t[1], ...)` form, IDO's combine pass treats each `t[N]` as an independent address-fold candidate and re-emits the lui per access. With separate-statement `v1 = t[0]; v2 = t[1]; f(..., v1, v2, ...)`, IDO must materialize the base before the loads and reuses it across both.

**Note:** doesn't promote the function on its own (still missing the varargs-style shadow spills) but tightens the structural shape, removing one diff source.

**Caveat — does NOT produce `addiu base, OFFSET; lw 0(base); lw 4(base)`:** if the target uses `lui base; addiu base, base, OFFSET; lw 0(base); lw 4(base)` (offset materialized in the addiu, not the lw), this technique still emits `addiu base, base, 0; lw OFFSET(base); lw OFFSET+4(base)` — same shared base register but offset baked into each lw. The constant-fold from `&D+N` is structural per `feedback-ido-constant-address-load-fold-inevitable`. Verified 2026-05-06 on game_uso_func_00010DC8 (sibling of 10E2C, same family-cap at 88.6%).

<a id="feedback-ido-volatile-pp-forces-n-fold-pointer-reload"></a>
## Force N-fold reload of `*(SYM+N)` via `volatile T **` + N intermediate locals (no CSE)

_When target asm has `lui v1; addiu v1, v1, 0; lw t?, OFF(v1)` repeated N times — i.e., the symbol address materialized once and N separate lw reloads from the same offset — natural C `T *base = *(...)` collapses to ONE load via IDO CSE, then 3 register-base offset accesses against `base`. To force N separate reloads of `*(SYM+N)` itself, use a volatile pointer-pointer + N intermediate locals._

**Pattern (verified 2026-05-06 on timproc_uso_b5_func_0000131C, 81.80% → 84.96%):**

**Wrong C** (one load, 3 register-base offsets):
```c
char *base = *(char**)((char*)&D_00000000 + 0x134);
*(int*)(self + 0x2C) = *(int*)(base + 0x84);
*(int*)(self + 0x30) = *(int*)(base + 0x80);
*(int*)(self + 0x34) = *(int*)(base + 0x8C);
// emit: lui v1, %hi; lw t6, %lo+0x134(v1); lw t7, 0x84(t6); ...
//       i.e., 1 base-load + 3 separate t-reg accesses via the cached pointer
```

**Good C** (3 reloads of the pointer, target shape):
```c
volatile char **base_pp = (volatile char**)((char*)&D_00000000 + 0x134);
char *b1, *b2, *b3;
b1 = (char*)*base_pp;  *(int*)(self + 0x2C) = *(int*)(b1 + 0x84);
b2 = (char*)*base_pp;  *(int*)(self + 0x30) = *(int*)(b2 + 0x80);
b3 = (char*)*base_pp;  *(int*)(self + 0x34) = *(int*)(b3 + 0x8C);
// emit: lui v1, 0; addiu v1, v1, 0; lw t6, 0x134(v1); lw t7, 0x84(t6); ...
//       lw t8, 0x134(v1); lw t9, 0x80(t8); ... lw t0, 0x134(v1); lw t1, 0x8C(t0); ...
//       i.e., 3 separate `lw t?, 0x134(v1)` reloads of the pointer at SYM+0x134
```

**Why:** `volatile T **` makes each `*base_pp` an observable read; the C standard requires the compiler emit each one separately. The N intermediate locals (b1, b2, b3) prevent the compiler from CSE-ing across statements (without them, IDO might fold across the void context).

**When NOT to use:** if the target only has ONE load of `*(SYM+N)` followed by multiple register-base offset accesses, the natural `base = *(...)` is correct — don't volatilize. This recipe is specifically for the pattern where target reloads the POINTER itself N times, not just the base register.

**Precondition: needs N≥3 reads to actually reshape emit.** Verified 2026-05-06 on game_uso_func_00010DC8 (10E2C-family member at 88.60% cap, 2 adjacent loads `lw a1, 0(t8); lw a2, 4(t8)` going into one downstream call): the volatile-pp wrap was a no-op — IDO still emitted v0-base + offsets baked into lw, same as plain `int *t`. The trick only locks the base register when there are 3+ separate `*base_pp` reads forcing the compiler to materialize the pointer-load 3+ times. With 2 adjacent reads, the compiler's combine pass collapses them regardless of volatile attribution. Don't try this recipe on 2-read functions; it's strictly for 3+. The 2-read case is structurally capped per `feedback-ido-shared-base-via-deferred-assign-and-named-locals` (no further C-level lever).

**Cousin recipe:** `feedback-ido-shared-base-via-deferred-assign-and-named-locals` does the OPPOSITE — forces a SHARED base register across N independent loads of `&D+N`, `&D+M` etc. Both recipes target IDO's CSE behavior; one suppresses it, the other induces it.

**Related:** `feedback-ido-constant-address-load-fold-inevitable` (the "natural" load-fold this is fighting against), `feedback-ido-volatile-loop-counter-for-stack-iter` (other volatile uses).

---

---

<a id="feedback-ido-dispatch-goto-chain-beats-switch-and-ifelse"></a>
## For 16-case sparse dispatchers in segments without .rodata, `if (a1 == N) goto cN;` chain beats both switch (jumptable) and if-else-if chain

_When the target asm is a chain of sequential `li at, K; beq a1, at, body_K` (compares grouped at top, case bodies after), straight `if-else-if` produces 49 % match (interleaves bodies) and `switch` produces 69 % (jumptable + .rodata that won't link). The matching form is a hand-laid `if (a1 == N) goto cN;` chain followed by `cN: body; goto end;` labels. This puts compares-first / bodies-after, matching IDO's emit for the chained-beq pattern._

**Pattern (verified 2026-05-02 on game_uso_func_0000174C, 16-case dispatch):**

Asm shape (target):
```
li    at, 3
beq   a1, at, case3
sw    zero, 0x268(a0)     ; delay slot ALSO does the default work
li    at, 4
beq   a1, at, case4
li    at, 5
beq   a1, at, case5
... 13 more comparisons, all beq ...
li    at, 18
beq   a1, at, case18
nop                        ; last delay slot
b     end
lw    ra, 0x14(sp)         ; epilogue starts in delay slot

case3: ...; b end; ...
case4: ...; b end; ...
...
end: addiu sp; jr ra
```

C source comparisons:

| Form | Match % | Why |
|------|---------|-----|
| `if (a1==3) {body3;} else if (a1==4) {body4;} else if (a1==5) {body5;} ...` | 49 % | IDO interleaves the comparisons WITH the case bodies. Each `if` emits its compare + body in source order. |
| `switch (a1) { case 3: body3; break; case 4: ...; }` | 69 % | IDO emits a `.rodata` jump table (`sltiu`, `lw t6, 0(at)`, `jr t6`). 1080's linker discards .rodata, so this also breaks the link. |
| `if (a1==3) goto c3; if (a1==4) goto c4; ...; goto end; c3: body3; goto end; c4: body4; goto end; ... end: ;` | 95 % | Matches the target's "compares first, bodies after" layout. |

**Why goto-chain works:**
- Forces "compares grouped at top" — each `if (cond) goto label;` is a single beq, no body inline.
- Forces "bodies-after" — labels are placed sequentially after the dispatch chain, in dispatch order.
- IDO's branch-likely optimization can't interleave bodies because the body code is in a separate basic block reachable only via goto.

**Last-comparison cap (~95 % typical):**
The very LAST `if (a1 == N) goto cN;` may emit `bnel` (branch-likely-not-equal) instead of plain `beq + nop`, because IDO can fold the `lw ra` epilogue load into BL's delay slot. Target uses plain `beq + nop` then `b end` with `lw ra` in `b`'s delay. Tried these without success:
- `if (a1 != N) goto end; <body>; goto end;` (inline last case): regressed to 91.86 %.
- `goto end;` vs `return;` for case bodies: same 95 %.
- Adding extra logic after the chain: regressed.
- `if (a1 == N) <body>; goto end;` (inline last case body, no label) — 2026-05-02 confirmation: also regressed to 92.56 % on game_uso_func_0000174C. **Generalization:** any structural change that puts the last case body in the dispatch chain itself (instead of past the dispatch + label) regresses by ~3 percentage points. The goto-chain's "all cases past the chain" layout is structurally rigid; the bnel cap can only be broken by permuter.
- **Reordering case bodies in source has no effect on the bnel arm choice** (verified 2026-05-02 on n64proc_uso_func_00000268). Putting `c1:` body BEFORE `c0:` body (so c1 becomes the fall-through after dispatch) does change basic-block placement but the second-dispatch branch still emits `bnel skip-to-end` not `beql jump-to-c1-body`. IDO's arm choice for branch-likely is decoupled from body source-order — driven by something else (early-return heuristic? delay-slot fill profitability scoring?). Don't waste a build cycle on body-reorder.

This cap may need permuter to break.

**How to apply:**
- For ANY function whose asm shows N consecutive `li at, K; beq a1, at, BODY` then bodies after, write the goto chain — don't try `switch` or if-else-if first.
- Use sequential labels `c3, c4, c5, ...` named by the case value for readability.
- Each body ends with `goto end;` (or `return;`); the last one optionally falls through to `end: ;`.
- The default fall-through is `goto end;` after the dispatch chain.
- Wrap NM at 95 % with the documented bnel cap; iterate via permuter later.

**Caveats:**
- The goto chain is more verbose than `switch`. Worth it for matching, not for greenfield code.
- Doesn't apply to dense switches that target jump tables (Glover and other GCC projects DO use jumptables; only IDO + .rodata-discarded segments need this).
- ~~For `switch` with small case counts (≤2), IDO emits if-else-if too — no goto chain needed.~~ **Refuted 2026-05-02 (n64proc_uso_func_00000268, 2-case v==0/v==1 dispatcher):** if-else-if form caps at 85.25%; goto-chain hits 93.57% (8.32pp jump). The pattern works even for 2-case sparse dispatch — apply it whenever target asm shows compares-grouped-at-top.
- **Doesn't apply when the default arm is a side-effecting call + return** (e.g. `gl_func(...); return 0.0f;`). Verified 2026-05-06 on `gl_func_00052144` (float-returning state dispatcher with cross-USO call in default): switch-form hits 98.13%; goto-chain regresses to 24.62% because IDO places the default-arm body BETWEEN the dispatch-chain and the case labels (in source-order), shifting all case body offsets vs target's "case bodies first, default last" layout. For float-returning dispatchers with side-effecting defaults, use plain `switch` with overlap-fall-through cases (`case A: case B: case C: return X;`) — the default falls through naturally to the post-switch code which already lands AFTER all cases.
- **`switch` ALSO wins for void state-machines with sparse non-contiguous cases + call-heavy bodies (verified 2026-05-29, mgrproc_uso_func_00001614, cases 0/1/4).** A plain `switch (state) { case 0: ...; break; case 1: ...; break; case 4: ...; break; }` compiled to the target's up-front compare-dispatch `beqz a1,case0; beq a1,1,case1; beql a1,4,case4; b end` (each case-4 arm using `beql` with a delay-slot pre-load) — NO `.rodata` jumptable, because the cases are SPARSE/few (3 non-contiguous values). The if-else-if chain capped at 82.5% (nested branches); `switch` hit 91.8% + exact insn count. **So the "switch → jumptable → won't link" warning only bites DENSE contiguous case sets; for sparse few-case dispatch, prefer `switch` first** (it gives the compares-grouped-at-top layout for free without the verbose goto chain). The goto-chain is still the tool when the asm shows a long `li at,K; beq` run (many cases) where even sparse `switch` would tableize.

**Related:**
- `feedback_ido_switch_rodata_jumptable.md` — base reference; this memo extends it with the matching idiom.
- `feedback_ido_branch_likely_arm_choice.md` — last-comparison bnel cap reasoning.
- `feedback_ido_goto_epilogue.md` — `goto end` to share epilogue (similar idiom).

---

---

<a id="feedback-ido-fp-compound-assign-load-order"></a>
## FP read-modify-write: compound `dst *= src` matches; expanded `dst = dst * src` swaps the operand load order

_For float RMW (`dst OP= src`), IDO loads the **dst** operand into the lower `$f` register FIRST. The compound assignment `dst *= src` produces that order; the expanded `dst = dst * src` loads **src** first, swapping every `lwc1` base (arg0↔arg1) and the `mul.s` operand regs — byte-count stays exact but ~half the instructions differ. Verified 2026-05-24 on `game_libs_func_0005E8B0` (per-axis matrix scale, 9× `mul.s`): expanded form = 18 diffs, `*=` form = byte-exact match. Applies to `+= -= *= /=` float RMW. The arg1 component is reloaded per operation (no caching)._

<a id="feedback-ido-div-2-mul-fold-and-mtc1-load-delay-nops"></a>
## IDO -O2 folds `/2.0f` to `*0.5f` (different opcode); -mips2 schedules across mtc1 load-delays while -mips1 emits strict nops

_Two IDO codegen rules surfaced on bootup_uso func_000102A4. (1) `expr / 2.0f` compiles to `mul.s ..., 0.5f` (lui 0x3F000000, mtc1, mul.s) instead of `div.s ..., 2.0f` (lui 0x40000000, mtc1, div.s). The fold happens regardless of source form — can't flip from C. (2) `-mips2` IDO schedules across mtc1 load-delay slots when there are independent insns to fill them; `-mips1` (and apparently the original ROM build) emits strict `nop` load-delays after every mtc1. Function emits 12+ bytes shorter at -mips2 with no source workaround._

**Rule 1 — `/2.0f` becomes `*0.5f`**:

C source `x / 2.0f` (or any constant divisor that's a power of two
representable exactly in float) compiles to:
```
lui at, 0x3f00          # 0.5f as immediate
mtc1 at, fN
mul.s f_dst, f_src, fN
```

Expected form (what the original ROM has):
```
lui at, 0x4000          # 2.0f as immediate
mtc1 at, fN
div.s f_dst, f_src, fN
```

**Why**: IDO's float optimizer recognizes power-of-2 divisors and
strength-reduces div→mul (multiply by reciprocal). Faster on MIPS R4300
because div.s is multi-cycle (~30 cycles) vs mul.s (~5 cycles).

**LEVER (verified 2026-05-24, supersedes the old "no lever" claim): a NAMED
LOCAL divisor prevents the fold and emits `div.s`.** The fold only fires when
the divisor is a compile-time LITERAL in the division expression. Pull the
constant into a named `float` variable first:
```c
float d = 1024.0f;          /* materialized as lui 0x4480; mtc1 -> $fN */
float f = (float)v / d;     /* div.s f, v, $fN  (NOT mul.s by reciprocal) */
```
IDO still materializes the constant (lui+mtc1) but no longer reciprocal-folds
the division — exactly the target's `div.s` form. `volatile float d` over-does
it (forces a stack roundtrip). Verified on gl_func_0005B764: the literal
`/1024.0f` gave `lui 0x3A80; mul.s` (reciprocal); `float d=1024.0f; v/d` gave
`lui 0x4480; div.s` (target opcodes). NOTE: a hoisted named divisor can shift
the entry register-save / prologue order (a secondary cap on some functions),
so byte-verify in-tree — but for the FP opcode itself this is the fix.
(`INSN_PATCH` is banned; do not use it for this.)
**SCOPE MATTERS (2026-05-25, gl_func_0005B848):** the named divisor must be at
FUNCTION scope. An in-LOOP `float d = 1024.0f;` (declared inside the do/while
that uses it) gets const-propagated per iteration and RE-FOLDS to `mul.s` — the
fix silently fails. Hoist the decl above the loop (as gl_func_0005B764 does).
Confirmed: in-loop decl → `lui 0x3A80; mul.s`; same decl hoisted → `lui 0x4480;
div.s` byte-exact. Two functions in the float-format-log family (0005B764 matched,
0005B848 matched this way); look for more 0005B* siblings with the same /1024.0f.

**BOTH-LITERAL → FULL POOL-FOLD variant (2026-05-29, gl_func_0000D7B8):** when
BOTH numerator and divisor are literals (e.g. `250.0f / 255.0f`, a color ratio),
IDO doesn't even emit mul.s — it fully constant-folds the quotient at compile time
and emits a precomputed `lwc1 fN, lo(at)` from the literal pool (one load per
ratio). The SAME named-local-divisor fix applies and is even more impactful here:
`float denom = 255.0f; v->a = 250.0f/denom; v->b = 235.0f/denom; ...` makes IDO
materialize denom once (lui 0x437F; mtc1 → $f0) and emit a runtime `div.s` per
ratio reusing that divisor — exactly the target's shape. Verified on gl_func_0000D7B8
(four x/255 ratios): literal form pool-loaded all four (63% reg-blind); hoisted
`float denom` restored the 4 `div.s` and the shared f0 divisor → 88%. So: a shared
literal divisor across several ratio stores is a strong signal to hoist it into one
named `float` — both to flip the opcode AND to get the single-materialize+reuse.

**EXACT-RECIPROCAL EXCEPTION (2026-05-27, func_000102A4):** the named-local lever
FAILS for divisors whose reciprocal is an EXACT power-of-2 float (2.0f→0.5f,
4.0f→0.25f, 8.0f→0.125f, etc.). IDO's optimizer recognizes the exact-reciprocal
case earlier in the pipeline (before const-propagation through locals) and folds
unconditionally. `float d = 2.0f; expr / d` STILL emits `lui 0x3F00 (=0.5f); mul.s`.
`static const float two_f = 2.0f` produces `div.s` via memory-load (`lui at, hi;
lwc1 fN, lo(at)`) but the load-form diverges from target's lui+mtc1 immediate
shape. For exact-power-of-2 divisors, the only way to match `lui 0x4000; mtc1;
div.s` is if the original C had a non-divisor expression that incidentally
emits as 2.0f at the asm level — there's no C lever from the simple `/2.0f`
form. Defer to permuter or leave NM.

**Rule 2 — mtc1 load-delay nops**:

After `mtc1 rN, fM`, the float register fM has a 1-cycle load-delay
before it can be used in a float op. On strict MIPS-I, you MUST insert
a `nop` (or unrelated insn) between mtc1 and any insn that reads fM.
On MIPS-II/III the hardware handles this with stalls, so the nop is
optional.

IDO's behavior:
- `-mips1`: emits `nop` after every mtc1 (strict adherence).
- `-mips2` / `-mips3`: schedules unrelated insns into the slot, OR
  emits no nop if the next insn is independent.

Our project compiles at `-mips2 -32`. Original 1080 ROM was apparently
compiled with `-mips1` or an equivalent setting that forced the nops —
many of its function tails have unfilled mtc1 nops while ours don't.

**Match path** for functions with mtc1 nops in expected:
- Per-file `-mips1` override in Makefile (changes other functions in
  the same file too — verify they still match).
- OR pad the C with explicit `__asm__("nop")` (but IDO's cfe rejects
  `__asm__` per `feedback_ido_no_asm_barrier.md`).
- OR document as cap and defer.

**Detection**: when target asm has `nop` immediately after `mtc1`, and
your built emit has a different insn there (typically the NEXT
operation), this is the load-delay-nop class. Function size will be
4×N bytes longer in expected.

**Concrete case** — `func_000102A4` (bootup_uso):
- Expected: 19 insns including 3 nop load-delays (after each mtc1).
- Built: 16 insns, no nops, schedules `mtc1 at,f16` and `mtc1 a1,f4`
  back-to-back with cvt/mul/sub interleaved.
- 12-byte size deficit makes the function strictly INSN_PATCH-blocked.

**Related**:
- `feedback_insn_patch_size_diff_blocked.md` — what to do when this
  hits the size-diff blocker
- `feedback_ido_no_asm_barrier.md` — why `__asm__("nop")` doesn't
  help with IDO
- `project_o1o2_split.md` — file-split mechanism for per-function
  flag overrides (extends naturally to per-file -mips1)

---

---

<a id="feedback-ido-double-return-uses-f0-f1-not-f2"></a>
## IDO -O2 emits double return into $f0+$f1 pair, not $f0+$f2 — kills "force $f2 via double-trick" theory

_For `double f(void){return 0;}`, IDO -O2 emits `mtc1 zero,$f1; mtc1 zero,$f0; jr ra; nop` — upper-half lands in $f1 (o32 paired-register convention), NOT $f2. Don't try the "declare as double-returning to force $f2 emit" trick when grinding $f2-shape caps; it produces $f1, which won't match a target that uses $f2._

**The plausible-but-wrong theory:**

For functions with a target shape involving `mtc1 zero,$f2` (e.g.
game_uso_func_00007ABC's 4-insn body `mtc1 zero,$f2; nop; jr ra;
mov.s $f0,$f2`), one might guess: "$f2 is part of the o32 double-return
ABI — declare the function as double-returning, return 0, IDO will
emit to $f2."

**Verified standalone (2026-05-04, IDO 7.1, -O2 -mips2):**

```c
double f(void) { return 0.0; }
```

emits:

```
mtc1 zero, $f1   ; upper half of double return
mtc1 zero, $f0   ; lower half of double return
jr ra
nop
```

**$f1, NOT $f2.** O32's float-pair convention for `double` uses
$f0/$f1 (consecutive evens-and-odds make a paired register on
big-endian o32), not $f0/$f2. So this trick produces a 4-insn body
of the wrong shape: insn 1 hits $f1 instead of $f2, and there's no
mov.s in the delay slot.

**How to apply:**

When the target asm shows `mtc1 zero,$f2` (or any free-standing $f2
write) for a return-zero function, **don't try the double-return
trick.** $f2 is reachable only through:
- A computation that already used $f2 as a temp and feeds into the
  return value, OR
- Cross-function tail-share where another function's epilogue at the
  same address landed there (the only known mechanism on
  game_uso_func_00007ABC).

Standalone C cannot force IDO to choose $f2 specifically for a fresh
zero-emit. Confirmed across 21+ variants in
`src/game_uso/game_uso.c` (game_uso_func_00007ABC wrap doc).

**Origin:** 2026-05-04, /decompile tick on game_uso_func_00007ABC.
Tested four fresh variants (`double`, float-arg-ignored,
int-arg-ignored, static-zero-load) standalone after 17 prior
variants. The double-return result was the most theoretically
promising but emits to $f1 not $f2.

---

---

<a id="feedback-ido-early-return-ra-delay-slot"></a>
## IDO folds prologue sw ra into early-return beq's delay slot

_When `if (a0 == 0) return;` is the first statement, IDO moves the prologue `sw ra` into the beq's delay slot — write the C naturally and the scheduler handles it_

When a function begins with an early-return null-check (or similar single-condition early-exit), IDO -O2 schedules the prologue's `sw $ra, N($sp)` INTO the delay slot of the early-return branch. Don't try to outsmart it.

Target asm:
```
addiu $sp, -0x18
beq   $a0, $zero, .Lend
sw    $ra, 0x14($sp)        ; delay slot of beq, executes regardless
... body ...
.Lend:
lw    $ra, 0x14($sp)
addiu $sp, $sp, 0x18
jr    $ra
nop
```

Source that matches:
```c
void f(void *a0, ...) {
    if (a0 == 0) return;        // or NULL
    ... body ...
}
```

**Why:** IDO knows the early-return branch can be filled with the `sw ra` because (1) it's safe — the store completes before the branch resolves regardless of branch taken/not, and (2) the early-return path eventually loads ra back, so storing it first means there's no observable difference. The ra save is "free" cleanup that happens whether you take the early return or not.

**Bonus:** When the body has its own conditional store before another branch (e.g. `*ptr = val; if (cond) call();`), IDO ALSO moves that store into the second beq's delay slot — TWO delay-slot fills come for free from natural source order. See `game_uso_func_00005780` for the reference pattern.

**How to apply:**

- For "if (cond) return; body;" patterns, write the early-return at the top — DO NOT wrap the body in `if (!cond) { body; }`. The scheduler needs the early-return branch as the carrier for the ra save.
- Don't pre-spill ra or insert dummy locals trying to "encourage" the scheduler — the natural pattern works.
- This is the OPPOSITE of `feedback_ido_unfilled_store_return.md` (which describes when IDO leaves the delay slot empty for store-then-return patterns in leaf setters); the difference is that here we have an early-return guarded by a condition, with body code following.

---

---

<a id="feedback-ido-used-arg-dead-home"></a>
## Used incoming arg ALSO dead-spilled to its outgoing-shadow — CRACK with `int *p = &param; ...(*p)` (take the param's address)

_A function that passes param `aN` to its first call sometimes also has `sw aN,off(sp)` (storing aN to its outgoing-arg shadow / caller home slot) in that jal's delay slot — a DEAD store (never reloaded). Plain -O2 C puts a `nop` there instead, so the build is exactly 1 instruction short (~94-96%)._

**THE LEVER (found by the permuter 2026-05-24, base 215 → 0): take the parameter's
address.** `int *p = &aN; ... use *p` forces IDO to home `aN` to its stack slot
(`sw aN,off(sp)`) — exactly the missing store. Verified on `gl_func_0006A5B0`:
`if (gl_func_00000000(*p) != 0) { do {} while (gl_func_00000000()); } gl_func_00000000(293);`
with `int *p = &a0;` → **byte-exact, report 100** (96 → 100). Use the **do-while**
(not `while`) for an if+spin-loop to avoid an extra leading `beq`.

**Earlier dead-ends (don't bother, go straight to `&param`):** `(void)aN;` is DCE'd
when aN is already used (only works for *unused* args); `-g/-g1/-g2` add a full
frame; register/volatile-local hints spill to a *local* slot, not aN's shadow.

**`&param` with an UNUSED `p` (no `*p` deref) ALSO works — IF the function does
other pointer stores/loads.** `int *p = &aN;` then never using `p` normally gets
DCE'd (the address-take is elided — see the `volatile` workaround at
`#feedback-ido-volatile-param-spill`). BUT when the function ALSO writes/reads
through *other* pointers (e.g. `*a1 = X; *a2 = Y;`), IDO can't prove they don't
alias `&aN`, so it conservatively homes `aN` — the same barrier `volatile` gives,
for free. Verified `game_libs_func_00034BDC` (`*a1=D_A; *a2=D_B;` + dead `a0`):
plain `int *p = &a0;` (unused) → byte-exact `sw a0,0(sp)` home, report 100. So:
pure leaf with no aliasing ops → need `volatile int *p`; function with pointer
stores → plain `int *p` suffices. (2026-05-24)

Distinct from the unused-arg `(void)a` spill and the 3-save arg-preserve pattern.
The prologue-less variant (no frame, home to caller sp+4) appears on
`game_libs_func_0002BA08` — try the same `&param` lever there. **This reclassifies
the "arg-home cap" as CRACKABLE; re-grind any function NM-wrapped with a single
`sw aN,off(sp)` residual using `&param`.**

**SECOND EFFECT (2026-05-24): `&param` also fixes "global load hoisted to $v0
BEFORE the sp-adjust".** When the target has `addiu sp; lui/lw global(t6); sw ra;
...` but your C emits `lui/lw global(v0); addiu sp; ...` (the independent global
load scheduled before the prologue), adding `int *p = &aN;` forces aN into the
prologue's home stores, which anchors the sp-adjust FIRST and keeps the global
load after it. Verified gl_func_00035188: 79.2% -> 98.4% (the lever fixed BOTH
the missing a0-home AND the pre-sp global hoist in one shot; only a v0-vs-t6/t7
register-renumber on the global remained, permuter 75->55 not 0).

<a id="feedback-ido-and-local-dead-spill-no-reload"></a>
## `&local` forces a dead home-spill WITHOUT a reload; `volatile` forces the spill WITH a reload (1 insn longer)

_The COMPUTED-LOCAL generalization of the `&param` crack above. When the target
spills a computed value to a stack slot as a DEAD store, then uses the same
register copy directly afterward (no reload), the C must produce the spill while
keeping the register live._

Target shape (`gl_func_0003604C`, 10 insns):
```
lw   t6, 20(a0)      ; t6 = a0[5]
sw   t6, 28(sp)      ; DEAD spill of t6 (slot never reloaded)
jal  callee
addiu a1, t6, 0x30   ; delay: uses t6 DIRECTLY (no reload)
```

- **`volatile int t = a0[5];`** emits the spill but ALSO re-reads it on the next
  use (`lw a1, 28(sp)` then `addiu a1, a1, 0x30`) → **1 insn too many** (the
  documented "non-volatile dead spill" cap noted this and stopped here).
- **`int t = a0[5]; int *p = &t; … use t; (void)p;`** — taking the local's
  address forces IDO to home `t` to its stack slot (the dead spill) **but it
  keeps the register copy live** for subsequent uses (no reload, because nothing
  writes through `p`). `(void)p;` reads only the pointer value (no deref → no
  load). **Byte-exact.**

This is the same `&X`-homes-without-reload mechanism as the `&param` lever; the
distinction worth remembering is the contrast with `volatile`: **`volatile`
gives spill+reload, `&local` gives spill+keep-register.** When a near-miss is
exactly 1 insn LONGER than target because of a `lw` reload right after a dead
`sw`, swap `volatile` → address-taken. Verified 2026-05-28. **Re-test any cap
note that only lists `plain local / volatile / register+pad` variants — the
address-taken form is the one they missed.**

<a id="feedback-ido-empty-body-do-while-emits-branch-likely"></a>
## IDO -O2 emits branch-likely for empty-body do-while loops; move call into the body to get plain branch + nop delay

> **DEPRECATED-MENTIONS 2026-05-23.** This section mentions INSN_PATCH/PROLOGUE_STEALS; those mechanisms were REMOVED as match-faking — see `feedback_no_instruction_forcing_matches_policy`. Non-recipe content (recognition patterns, debug tips, byte-level analysis) is still useful; just don't treat any "→ INSN_PATCH" / "→ PROLOGUE_STEALS" advice as a fix.


_`do { } while (func() & MASK)` (empty body, call in condition) compiles to beqzl/bnezl (branch-likely) with the call's lui hoisted into the annulled delay slot. Restructure to `int r; do { r = func(); } while (r & MASK)` (call in body) to get plain beqz/bnez + nop delay slot. For surrounding if-then-skip-loop guards, IDO ALSO uses branch-likely + hoists the post-loop instruction — INSN_PATCH the 2-word `branch+nop` pair._

**Verified 2026-05-04 on func_8000487C (kernel RSP status poller):**

Original C body:
```c
if ((func() & 0x2000) == 0) {
    do {
    } while ((func() & 0x2000) == 0);    // empty body, call in cond
}
*(volatile u32*)0xC000000C = 0;
if (func() & 0x2000) {
    do {
    } while (func() & 0x2000);           // empty body, call in cond
}
```

→ IDO emits `beqzl`/`bnezl` (branch-likely) for BOTH the inner do-while
back-edges AND the outer if-then-skip-loop guards. Plus it HOISTS the
post-loop `lui` instruction into the annulled-on-not-taken delay slot
of each branch-likely. ~91% NM, structurally locked from C.

**The fix — two layers:**

**(1) C-body restructure: move call into the loop body, not while-cond.**
```c
int r = func();
if ((r & 0x2000) == 0) {
    do {
        r = func();              // call in BODY now
    } while ((r & 0x2000) == 0);
}
```

This gives the inner do-while loops plain `beqz`/`bnez` instead of
`beqzl`/`bnezl`. Match goes 91% → 95%.

**(2) For the outer if-then-skip-loop guards: INSN_PATCH the 2-word
branch+delay pair.**

The outer `if (cond) { /* skip loop */ }` STILL emits as `bnezl + lui
(hoisted)`. Target has `bnez + nop`. Fix in Makefile:

```makefile
build/src/<seg>/<file>.c.o: INSN_PATCH := <func>=<off>:<plain_bnez>,<off+4>:0x00000000,...
```

Where `<plain_bnez>` is the bnez/beqz word with offset adjusted (the
branch-likely word has `branch_likely_op | offset+1` because of the
+1 to skip the annulled delay slot vs plain branch's `branch_op |
offset`).

**Diff signature**: build has `5XYY00NN` and `3XAB00CD` at consecutive
offsets; expected has `1XYY00NM` (one less) and `00000000`. Pattern is
universal IDO hoisting; recognize the byte signature.

**Why this matters**: hand-written status-polling code in libultra-style
libraries (rmon, audio, video managers) often has this idiom. If you see
a wait-for-status-bit poller at 91-95% with the documented "branch-likely
forms" diff, restructure + INSN_PATCH is the recipe.

**Companion to:** `feedback_insn_patch_for_ido_codegen_caps.md` (general
INSN_PATCH usage), `feedback_ido_arg_save_reg_pick.md` (other unflippable
IDO codegen choices).

---

---

<a id="feedback-ido-empty-void-matchable"></a>
## IDO -O2 `void f(void) {}` produces exactly `jr ra; nop` — empty functions ARE matchable

_The CLAUDE.md general note ("Empty functions should stay as INCLUDE_ASM — the compiler typically omits the delay slot nop") is WRONG for IDO 7.1 at -O2. Empty `void f(void) {}` emits 8 bytes: `jr ra; nop`. Matches target bytes exactly._

**Rule:** `void f(void) {}` at IDO -O2 compiles to exactly:
```
jr $ra
nop
```
Size: 0x8. This IS the target bytes for the standard `jr ra; nop` leaf empty function.

**Tested flags (2026-04-21):**
| Flag | Bytes |
|------|-------|
| `-O2` | `jr ra; nop` (0x8) ✓ matches target |
| `-O2 -g3` | `jr ra; nop` (0x8) ✓ |
| `-O2 -g` | `jr ra; nop; jr ra; nop` (0x10) ✗ adds dead trailer |
| `-O1` | same as -O2 |

**What CLAUDE.md's note was about:** The "typically omits the delay slot nop" advice was likely about a different compiler (KMC GCC 2.7.2 at Glover) where empty functions emit `jr ra` only (1 insn, 4 bytes). But that's a different compiler — IDO emits the nop.

**How to apply:**
1. Check target `.s` is exactly `jr ra; nop` (2 insns, 0x8 size).
2. grep size header confirms 0x8.
3. Replace INCLUDE_ASM with `void f(void) {}`.
4. Build + verify objdiff 100%.

**Candidates to sweep:** Any USO's 2-insn `jr ra; nop` func — often appears as USO-entry stubs right after split-fragments runs on a bundled entry point. Common pattern: first 3 funcs of a USO are "entry trampoline (b +offset); empty (jr ra; nop); real entry point".

**Siblings of other "empty void" matches already landed:**
- func_00010344, func_000102E8, func_00010308, func_00010AA8, func_00011D70, func_00011DB4, func_00011DF8 (bootup_uso — all landed with `void f(void) {}`)
- h2hproc_uso_func_0000000C
- eddproc_uso empty stubs (check)
- USO tail empties post-split-fragments

**Variant: K&R implicit-int empty `f() {}` for mixed-caller compatibility (added 2026-05-05).**

Same byte emit (`jr ra; nop`, 0x8) but different type signature. Use this form when same-TU callers have inconsistent return-value usage:

- Some lines: `func(...)` (discard return)
- Other lines: `int ret = func(...)` (use return)

`void f(void) {}` produces a cfe error at the value-using sites
(`Reference of an expression of void type`). Explicit `int f() { }` would
emit junk for $v0. K&R `f() {}` (no return type, K&R empty-args) accepts
both call patterns and IDO -O2 still emits exactly `jr ra; nop`.

Verified 2026-05-05 on `bootup_uso/func_00000000` (the splat synthetic
JAL-target-0 symbol) — it had been left as INCLUDE_ASM specifically because
"every caller supplies their own forward decl with the return type they
need." K&R empty resolves the same goal at the C definition site.

**Origin:** 2026-04-21 agent-a /decompile run. Source=2 (sibling of recently-matched). Sibling of h2hproc_uso_func_00000014 (split earlier this session). CLAUDE.md warning disproved for IDO compiler.

---

---

<a id="feedback-ido-f0-implicit-zero-at-entry"></a>
## Function reads $f0 at entry without setting it — caller-context "implicit zero" pattern

_Some IDO -O2 functions store $f0 (float return reg, NOT a standard arg) to memory at the start of the body. This means the caller arranges $f0=0.0f at the call site (e.g. tail-called immediately after a function that returns 0.0f, or compiler-arranged via inline expansion). Plain C `0.0f` literals would emit `mtc1 $zero, $fX`, not `swc1 $f0`. Recognition fingerprint: function's first FPU instruction is `swc1 $f0, N(sp)` or `swc1 $f0, N($aX)` and there's no preceding `mtc1` / `lwc1` / `c.X.s` to set $f0._

**Fingerprint (verified 2026-05-02 on `game_uso_func_000003F8`):**

```
addiu $sp, $sp, -0x60
addiu $t6, $sp, 0x54
swc1  $f0, 0x54($sp)    ; ← stores $f0 with no prior set
swc1  $f0, 0x58($sp)
swc1  $f0, 0x5C($sp)
...
```

**What it means:**
The function's source reads something like `*p = 0.0f` (or initializes a Vec3 with zeros), but instead of emitting `mtc1 $zero, $fX; swc1 $fX, ...`, IDO uses `swc1 $f0` directly — only valid if $f0 is provably 0.0f at the call site. The caller must therefore arrange $f0=0.0f immediately before the jal:
- Tail-call after a function whose `return 0.0f` leaves $f0=0.0f
- Inline-expanded into a context where `$f0 = 0.0f` was just set
- Custom convention with the float zero as a reg-passed arg

**Why matching from C is hard:**
Plain C `void f(T *p) { *p = (Vec3){0,0,0}; }` emits `mtc1 $zero, $f4; swc1 $f4, ...` (or a similar pattern), NOT `swc1 $f0`. To get `swc1 $f0`, you'd need:
- A non-standard signature like `void f(T *p, float zero_in_f0)` with $f0 ABI placement (not standard MIPS o32)
- An `__asm__("mtc1 $zero, $f0")` barrier at function start (but IDO doesn't accept `__asm__` — see `feedback_ido_no_asm_barrier.md`)
- The function inlined into its caller (defeats per-function matching)

**How to apply:**
When you see `swc1 $f0, N(sp)` as the first FPU op with no prior $f0 setter, recognize this as a caller-arranged zero pattern. Document it in the NM-wrap and move on; exact match is structural-cap territory unless you can identify the calling convention (e.g. a tail-call sequence in the caller's asm). If multiple unrelated functions in the same USO show this pattern, suspect a hand-written asm callee with a custom convention.

**Related:**
- `feedback_ido_no_asm_barrier.md` — can't insert `mtc1` barriers from IDO C
- `feedback_ido_o32_float_in_int_reg.md` — sibling case for $f12/$f14 vs $aN argument placement quirks

---

---

<a id="feedback-ido-f2-intermediate-unreproducible"></a>
## IDO -O2 always folds `return 0.0f` paths through $f0 directly — `mtc1 $0, $f2; mov.s $f0, $f2` unreachable from C

_Target 4-insn leaves that return 0.0f via an intermediate ($fN != $f0) like `mtc1 $0,$f2; nop; jr $ra; mov.s $f0,$f2` cannot be reproduced from any tested IDO-O2 C body — literal, local var, volatile local (→stack spill), negate, cast, union punning, arg-ignore. Don't grind; NM-wrap with partial C._

## Float-const register choice ($f0 vs $f2) follows C source order of the constants' first use — reorder to flip
<a id="feedback-ido-float-const-reg-by-source-order"></a>

For a multi-constant float-init (the classic case: an identity matrix — 1.0f on
the diagonal, 0.0f on the off-diagonals), the target picks ONE constant for $f0
and the other for $f2:

```
mtc1  zero, $f2        # 0.0f -> $f2  (computed first in asm)
lui   at, 0x3F80
mtc1  at, $f0          # 1.0f -> $f0
swc1  $f2, 4(a0)       # 0.0f stores...
... swc1 $f2 ...
swc1  $f0, 0(a0)       # 1.0f stores (diagonal)
```

The register a constant lands in is decided by **which constant's stores come
FIRST in C source order**, NOT by the asm store order. IDO assigns $f0 to the
first-used constant, then its scheduler reorders the actual `swc1`s. So when the
target keeps 1.0f in $f0 but emits the 0.0f stores first in asm, write the
**1.0f stores first** in the C body:

```c
void f(float *a0) {
    a0[0] = 1.0f; a0[5] = 1.0f; a0[10] = 1.0f;   /* 1.0f first -> owns $f0 */
    a0[1] = 0.0f; a0[2] = 0.0f; /* ... rest 0.0f -> $f2 */
}
```

IDO still emits the 0.0f stores before the 1.0f stores in the final asm, but
1.0f stays in $f0. Writing the 0.0f stores first gives the reversed (capped)
allocation. This **flips the "float-register-swap (f0 vs f2)" cap** — it's a
C-source reorder, not a permanent cap. Verified 2026-05-23 on
`game_libs_func_0005E83C` (3x4 affine identity init, 14/16 → byte-exact).

<a id="feedback-ido-int-zero-through-float-ptr-forces-second-zero-reg"></a>
### Force a SECOND zero FP reg (defeat the 0.0f CSE): store INT `0` through a `float*` variable

When the target materializes TWO zero FP regs for a multi-float-zeroing function
(e.g. `mtc1 zero,$f0` for most stores + `mtc1 zero,$f4` for one store that the
scheduler hoists into a `jr` delay slot), plain `*(float*)p = 0.0f` everywhere
won't reproduce it: IDO CSEs the `0.0f` constant to a SINGLE reg, leaving you 1
insn short. `float z = 0.0f` also CSEs (same value). **Lever:** for the store
that needs the distinct reg, assign through a `float*` *variable* and store the
INT literal `0` (not `0.0f`):

```c
void f(int *a0) {
    float *p;
    *(int *)((char *)a0 + 0x2B4) = 0;
    *(float *)((char *)a0 + 0x164) = 0.0f;   /* these CSE to $f0 */
    *(float *)((char *)a0 + 0x168) = 0.0f;
    *(float *)((char *)a0 + 0x16C) = 0.0f;
    p = (float *)((char *)a0 + 0x2A0);
    *p = 0;                                  /* int 0 via float* var -> fresh $f4 */
}
```

The int-`0`-stored-to-`float` (implicit conversion) through a separate pointer
variable doesn't CSE with the `0.0f` constant, so IDO emits a second `mtc1
zero,$fN`. Verified 2026-05-29 on `timproc_uso_b5_func_00003890` (7/8 → byte-exact;
permuter-found, then minimized — disproved its "0.0f CSE not C-controllable" cap
comment). Companion to [float-const reg by source order](#feedback-ido-float-const-reg-by-source-order).

**Pattern:** function body is 4 words, returning zero via a non-$f0 intermediate register:
```
mtc1 $0, $f2       ; zero into intermediate
nop
jr $ra
mov.s $f0, $f2     ; delay slot copies to return reg
```

**Why IDO won't emit this:** IDO -O2 always allocates the return register directly for the final rvalue. Tested on 2026-04-20 for `game_uso_func_00007ABC` — 13+ C variants all fold to direct `mtc1 $0, $f0; jr $ra; nop`:
- `return 0.0f;`
- `float x = 0.0f; return x;`
- `float a = 0.0f; float b = a; return b;`
- `float x = (float)(int)0; return x;`
- `double d = 0.0; return (float)d;`  (produces mtc1 + cvt.s.d pair, not this)
- `int i = 0; return *(float*)&i;` (stack spill)
- `volatile float x = 0.0f; return x;` (stack spill)
- `return -0.0f;` (produces lui+mtc1 with 0x80000000, not this)
- `float x = 0.0f; return -x;` (same)
- `float x = 0.0f; return x * 1.0f;` / `+ 0.0f;` (folded)
- Cast/ignore-arg variants (same)

**Rule:** if the target has `mtc1 $0, $fN` where N>0, and then `mov.s $f0, $fN`, stop grinding and NM-wrap. The extra `nop` between the mtc1 and jr is a pipeline hazard artifact that's not reachable from any valid C idiom we've found.

**Related but distinct:**
- `feedback_ido_mfc1_from_c.md` — mirror case for int-returning-float-bits (mfc1 aN, $f12)
- `feedback_ido_o2_tiny_wrapper_unflippable.md` — tiny wrappers with prologue-order issues

---

---

<a id="feedback-ido-fabs-dead-mov"></a>
## IDO's fabs idiom leaves an unreachable `mov.s` at the merge point — branch-likely artifact unmatchable from C

_IDO emits fabs as `bc1fl fall_taken; mov.s fDst, fSrc (taken=positive); b merge; neg.s fDst, fSrc (delay-always=negative); mov.s fDst, fSrc (fallthrough, unreachable); merge:`. The trailing `mov.s` is dead code — both arms jump straight to the merge label. C `fabsf(x)` or ternary `(x<0)?-x:x` emits without the dead instruction, so you lose 1 insn's worth of match._

**Target pattern (IDO -O2, fabs of a float):**
```
c.lt.s   $fSrc, $f16        ; compare fSrc < 0.0 (f16 typically 0.0)
nop
bc1fl    +4 (→ merge)       ; branch-likely-false: taken when fSrc >= 0
mov.s    $fDst, $fSrc       ;   delay slot (on taken): fDst = fSrc (positive)
b        +2 (→ merge)       ; else fallthrough: fSrc < 0
neg.s    $fDst, $fSrc       ;   delay slot (always): fDst = -fSrc
mov.s    $fDst, $fSrc       ; UNREACHABLE — dead code
; merge:
...use fDst as abs(fSrc)...
```

The final `mov.s $fDst, $fSrc` at the fallthrough is UNREACHABLE — both paths branch to `merge` past it. It's a compiler artifact from how IDO generates branch-likely for the fabs idiom.

**C forms that DON'T reproduce it (all lose 1 insn vs target):**
- `f14 = fabsf(f12)` — emits bc1fl + neg.s + b + mov.s, NO trailing dead mov.
- `f14 = (f12 < 0) ? -f12 : f12` — same as above.
- `if (f12 < 0) f14 = -f12; else f14 = f12;` — typically emits branch-likely with the same shape, again no dead mov.

**Implication:** when a function uses fabs AND you can match everything else, the last-insn-of-body gap is likely this dead `mov.s`. Cap the match at `(insns-1)/insns` and note the artifact.

**Origin:** 2026-04-20, game_uso_func_00007538 insn 0x768C decode. The dead `mov.s $f14, $f12` is part of a fabs+mod9 sub-expression within the function's arg1 & 0x20 dispatch arm. Identified as unreachable by flow analysis (both bc1fl taken and b-fallthrough paths branch to the merge label, bypassing 0x768C).

---

---

<a id="feedback-ido-forced-frame-tiny-predicate"></a>
## Tiny branch-predicate funcs with forced `addiu sp, -8/+8` frame + explicit `b` to epilogue — unreachable from IDO -O0/-O1/-O2

_Some 7-9-insn predicate functions (e.g. `return (a & MASK) != 0;`) have a target shape with a forced stack frame (`addiu sp, -8` prologue / `addiu sp, +8` in jr delay slot) AND an explicit `b` to the epilogue-merge block — even though IDO at any opt level emits a leafy variant without the stack frame. Signals a per-file-override compile or hand-written asm. Keep NM; not worth grinding._

**Pattern — example, gl_func_0006F3BC (2026-04-20):**

Target bytes (9 insns, 0x24):
```
addiu sp, sp, -8
andi  t7, a0, 0x3
beq   t7, zero, .L_ret0  ; (+3, into merge block)
 nop                      ; (unfilled delay)
b     .L_epi              ; explicit jump to epilogue
 addiu v0, zero, 1         ; (delay: false-path v0)
.L_ret0:
or    v0, zero, zero       ; v0 = 0
.L_epi:
jr    ra
 addiu sp, sp, 8           ; (delay: pop frame)
```

Equivalent C: `int f(int a0) { if ((a0 & 3) == 0) return 0; return 1; }`

IDO at -O0/-O1/-O2 all emit LEAF variants:
```
andi t6, a0, 0x3
bnez t6, .L_one
 li v0, 1   (or move v0, zero for the true-path delay)
jr ra
 move v0, zero
.L_one:
jr ra
 nop
```

No stack frame. No explicit `b` to merge. Can't reach target from any C form tested (plain, `int x;` local, `(void)&a0;`, opt-level flip).

**Detection:**
1. Function size 0x1C–0x30 (7–12 insns)
2. Asm has `addiu sp, sp, -N` (N=8 is typical) when the body is pure computation with no calls
3. Merge/epilogue block at `jr ra; addiu sp, sp, +N`
4. Explicit `b .Lmerge` rather than `jr ra` fall-through

**What to do:** NM-wrap with the semantics-correct C. Don't grind — the forced frame is compiler-variant-specific. Similar shape to `feedback_ido_o2_tiny_wrapper_unflippable.md` (2-insn wrappers) but affects predicates too.

**Distinct from:**
- `feedback_ido_o2_tiny_wrapper_unflippable.md` — 2-insn wrapper `void f(void) { func(&SYM); }` insn-order swap
- `feedback_ido_unfilled_store_return.md` — `sw; jr; nop` unfilled delay in setters
- This memo — tiny PREDICATE functions with forced stack frame

**Origin:** 2026-04-20, agent-a, gl_func_0006F3BC. Tested -O0/-O1/-O2 + `int x;` local + `(void)&a0;` — all produced leafy no-frame output.

---

---

<a id="feedback-ido-fpu-reduction-operand-order"></a>
## IDO -O2 final-add operand order in FPU reductions (`add.s fd, fs, ft`) follows source evaluation; can't easily flip without changing load order

_For dot products and chained FPU adds like `a[0]*b[0] + a[1]*b[1] + ... + a[n]*b[n]`, IDO emits the final reduction `add.s fd, fs, ft` with `fs` = running-sum register and `ft` = last-product register. If target has them swapped (`add.s fd, last_product, running_sum`), naive source rewrites that try to flip operand order also flip load order — net regression._

**Pattern (verified 2026-05-02 on `game_uso_func_000000A0`, a 4-element dot product):**

Target asm:
```
... loads + 4 mul.s ops (matching IDO's natural source order) ...
mul.s  f8, f6, f18      ; f8 = b[3] * a[3]  (last product)
add.s  f0, f8, f10      ; f0 = f8 + f10 = last_product + running_sum
```

Naive C `a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + b[3]*a[3]` produces 15/16 instructions matching, with the only diff being the final add operand order: IDO emits `add.s f0, f10, f8` (running_sum on left, last_product on right) instead of target's `add.s f0, f8, f10`.

**What was tried (all failed or regressed):**

1. `b[3]*a[3]` (swapped operand order on the LAST product) — fixed load order for the last pair but didn't change the final-add operand order. Stuck at 15/16.
2. `float r = a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; return b[3]*a[3] + r;` — temp variable forced different register allocation, regressed to ~70 % (multiple instruction diffs throughout).
3. Parens-driven grouping `b[3]*a[3] + (a[0]*b[0] + ...)` would force load order to start with b[3] (breaking earlier load-order match).

**Why it's hard to flip:** the final reduction add's `fs`/`ft` register choice is downstream of IDO's expression-tree-walk. Target's source must have written `last + running` (last on left), which forces b[3] and a[3] to be loaded BEFORE the running sum is computed — but the loads visible in target's asm clearly match natural left-to-right evaluation of `a[0]..b[3]`. So target's source likely had something we can't reproduce in plain C: a custom intrinsic, an already-precomputed running sum from a prior function, or a different IDO version.

**How to apply:** for FPU dot-product / vector-reduction leaves, expect a 1-instruction final-add operand-order cap if your output otherwise matches. **2026-05-29: this "structural cap" framing is partly SUPERSEDED — see [the assignment-expression operand-order lever below](#feedback-ido-fp-commutative-operand-order-assignment-lever), which DOES flip `mul.s` operand order by forcing one operand into a register at the op via `other * (tmp = wanted_fs)`.** Before wrapping a 1-insn FP-operand near-miss NM, try that lever (and/or the permuter).

**BUT — the lever does NOT extend to float reduction final-adds (cap CONFIRMED 2026-05-29 on `game_libs_func_0005D588`, a cross+dot product).** When BOTH final-`add.s` operands are already-computed temps in fixed registers (running-sum `$f8` + last-product `$f6`) and only the `fs`/`ft` ENCODING differs (target `add.s $f4,$f8,$f6` vs ours `$f4,$f6,$f8`), the lever is inert: the `(tmp = sum)` / `(tmp = prod)` assignment is dead-eliminated (the value is already materialized), so it doesn't pin anything. Verified-fail on 0005D588: grouped-swap `p3+(p1+p2)`, `(t=sum)+p3`, `sum+(t=p3)`, named-local `s=...; s+p3`, AND permuter (160s, no zero-score). The lever works when one operand is a fresh `lwc1`/literal that the `tmp=` can actually pin (the `mul.s` scale×coord case); it CANNOT reorder two pre-computed reduction temps. So: try the lever first, but if both operands are computed sub-expressions (dot/reduction tail), it's a genuine NM cap — don't burn permuter time.

**Related:**
- [assignment-expression operand-order lever](#feedback-ido-fp-commutative-operand-order-assignment-lever) — the lever that flips this
- `feedback_ido_v0_reuse_via_locals.md` — sibling case for integer register choice
- `feedback_ido_arg_save_to_sreg_in_bne_delay.md` — IDO instruction-scheduler caps from C

<a id="feedback-ido-fp-commutative-operand-order-assignment-lever"></a>
## Commutative FP op operand order (`mul.s`/`add.s` fs vs ft) IS flippable via an assignment-expression: `coord * (tmp = scale)` forces `scale` as fs

_For a commutative FP op `A * B` (or `A + B`), IDO -O2 does NOT reliably emit the source-left operand as `fs`. In scale×coordinate vector math, after a fresh `lwc1` of the coordinate, IDO emits `mul.s fd, coord, scale` (the freshly-loaded coord as `fs`) even when source is written `scale * coord`. To force the OTHER operand (`scale`) as `fs` — matching targets that keep a persistent multiplier in the low reg — wrap it in an assignment-expression at the multiply: `coord * (tmp = scale)`. The `tmp =` forces `scale` into a register right at the op, so IDO uses it as `fs`. The `tmp` var is write-only (a pure operand-ordering lever). The same form on a negation, `coord * (tmp = -orig_scale)`, additionally lands the target's specific result reg (e.g. `$f8` vs `$f10`) for the `neg.s`._

**Verified 2026-05-29 on `game_uso_func_00003FAC`** (53-insn FPU 2D-rotation-like vector builder), which had been documented as a "genuine cap... not C-reachable" stuck at 99.245% (5 diffs: 3 commutative `mul.s` operand swaps + an `$f8`↔`$f10` `neg_scale`/coord allocation pair). All 5 closed:

```c
/* near-miss: each `scale * a2[k]` emits coord-as-fs (wrong) */
a0[0] = orig_scale * a2[2] + new_scale * a2[0];
a0[2] = new_scale * a2[2] + neg_scale * a2[0];
a1[0] = new_scale * a2[0] - a2[2] * orig_scale;
a1[2] = new_scale * a2[2] + orig_scale * a2[0];

/* byte-exact: force the scale into a reg AT the multiply */
a0[0] = (orig_scale * a2[2]) + (a2[0] * (ns  = new_scale));
a0[2] = (new_scale  * a2[2]) + (a2[0] * (neg = -orig_scale));  /* also lands $f8 */
a1[0] = (new_scale  * a2[0]) - (a2[2] * (os  = orig_scale));
a1[2] = (new_scale  * a2[2]) + (a2[0] * (nsd = orig_scale));
```

**How it was found:** decomp-permuter's `X * (var = Y)` mutation (its assignment-into-temp randomization) hit it; then minimized by hand. The permuter floored at score 35–45 (didn't reach 0 in 280s) but its partial source revealed the lever, which manual application then completed.

**How to apply:** any 1-to-few-insn FP near-miss whose diffs are pure commutative-operand-order (or a coupled small-reg allocation swap on a `neg.s`/load) — `objdump -M no-aliases` shows `mul.s fd, X, Y` vs `mul.s fd, Y, X`, same operands — is a candidate. Identify which operand the target wants as `fs`, then write `<other_operand> * (tmp = <wanted_fs>)`. Declare throwaway `float tmp;` levers (set-but-unused warnings are harmless). This generalizes the old "final-add operand order can't flip" cap above; try it before NM-wrapping. Counterpart to [`feedback-ido-fp-compound-assign-load-order`](#feedback-ido-fp-compound-assign-load-order) (which fixes load order via `*=`); this fixes op-operand order via the assignment-expression.

**Generalizes to INTEGER commutative ops (`or`/`and`/`xor`/`addu`) — verified 2026-05-29.** The same lever flips integer-`or` operand order. `timproc_uso_b{3_00002700,1_000024F4}` (588B GBI display-list emitters) were stuck at 99.5% with 8 identical `or a1, s1, tN` diffs: target keeps the hoisted constant `0x260000` (in saved reg `s1`) as `rs`, but IDO defaults the freshly-computed value (`tN`) to `rs`. **Source operand swap (`const | var` → `var | const`) AND a named-local const were both no-ops** (confirming the long-standing note above that source order doesn't move commutative encoding). The fix: `value | (t = 0x260000)` — the assignment-expr pins the const as `rs` at the op. CSE collapsed the 8 `t = 0x260000` assignments back into the single `lui s1, 0x26` (no extra instructions). All 8 diffs closed → byte-exact. So: for an integer commutative-op operand-order near-miss, write `<other_operand> <op> (t = <wanted_rs>)` with a throwaway `int t;`. This **supersedes** the older [`feedback-ido-commutative-op-operand-order`](#feedback-ido-commutative-op-operand-order) "split into a named local" advice for the case where naming alone fails.

**Related:**
- [final-add operand order in FPU reductions](#feedback-ido-fpu-reduction-operand-order) — the cap this supersedes
- [FP read-modify-write compound `*=`](#feedback-ido-fp-compound-assign-load-order) — sibling load-order lever
- [commutative-op operand order (split into named local)](#feedback-ido-commutative-op-operand-order) — the weaker integer lever this assignment-expr form supersedes when naming fails

**Single-call mul.s variant (verified 2026-05-06 on `gl_func_00052104`):** for `result = jal_returns_float() * fresh_loaded_float`, IDO assigns the FRESHLY-LOADED operand to `fs` and the call-return ($f0) to `ft` regardless of C operand order. Tried 3 variants — operand swap (`x*y` vs `y*x`), inlining the call into the multiplication, and decl-first ordering — all hit the same fs=fresh / ft=$f0 emit. If target has fs=$f0 / ft=fresh (call return on the LEFT in mul.s), no C-source variant flips it. Clean promotion: INSN_PATCH at the mul.s offset with the byte-swapped operands (e.g. `0x46003202` → `0x46060202` flips fs/ft from `$f6,$f0` to `$f0,$f6`). Promoted gl_func_00052104 from 99.38 % → byte-correct via `gl_func_00052104=0x2C:0x46060202` in the per-`.o` INSN_PATCH list.

**Companion — `multu` two-memory-operand load order (verified 2026-05-06 on `gl_func_000520B8`):** IDO `multu` of two memory operands loads the RIGHT operand into `$t6` first, the LEFT into `$t7` (right-to-left evaluation of the binary expression). If the target's first `lh` is from offset `lo` and the second is from offset `hi`, the C must be `(a + hi) * (a + lo)` — the offset-`lo` operand on the RIGHT. The conventional left-to-right form `*(short*)(a+lo) * *(short*)(a+hi)` produces swapped `lh` order. Multiplication is commutative so the int product is identical, but the load order is observable in the diff. Combined with the single-call mul.s cap above, gl_func_000520B8 promotes byte-exact via operand swap + INSN_PATCH at offset 0x38.

---

---

<a id="feedback-ido-g3-disables-delay-slot-fill"></a>
## IDO `-g3` disables delay-slot filling while keeping -O2 optimization — unfilled-`sw; jr; nop` IS matchable

_Compiling with `-O2 -g3` produces unfilled-delay-slot epilogues (`sw; jr ra; nop` instead of `sw; jr ra; sw(delay)`). This SUPERSEDES feedback_ido_unfilled_store_return.md which claimed the pattern was unmatchable. Add as a per-file Makefile `OPT_FLAGS := -O2 -g3` override for functions whose target has trailing-nop epilogues after stores/work._

**Rule:** If a target function ends in `<body>; jr ra; nop` (unfilled delay slot) and IDO `-O2` gives you `<body_except_last>; jr ra; <last>(delay)`, try `OPT_FLAGS := -O2 -g3` per-file. The `-g3` flag disables IDO's reorg-pass delay-slot filler without bloating with `-O0`/`-O1` shadow-saves.

**Contrast with other -g levels:**

| Flag  | Delay-slot fill | Dead-epilogue bloat |
|-------|-----------------|---------------------|
| (none) / -g0 | filled (`jr; sw(delay)`) | none |
| -g / -g1 / -g2 | unfilled (`sw; jr; nop`) | +2 insns (`jr; nop` trailer) |
| **-g3** | **unfilled (`sw; jr; nop`)** | **none** |

`-g3` is the sweet spot. -g/-g1/-g2 add 2 trailing insns of dead epilogue that ruin the match. -g3 emits the SAME `sw; sw; jr; nop` sequence at 0x10 bytes exactly.

**Test recipe:**

```bash
cat > /tmp/test.c <<'EOF'
void target_func(int *a0) {
    *(int*)((char*)a0 + 0x168) = 0;
    *(int*)((char*)a0 + 0x16C) = 0;
}
EOF
for flag in "" "-g" "-g0" "-g1" "-g2" "-g3"; do
    tools/ido-static-recomp/build/7.1/out/cc -c -G 0 -non_shared -Xcpluscomm -Wab,-r4300_mul \
        -O2 -mips2 -32 $flag -o /tmp/test.o /tmp/test.c 2>/dev/null
    size=$(mips-linux-gnu-objdump -t /tmp/test.o 2>&1 | grep 'target_func' | awk '{print $(NF-1)}')
    echo "$flag: size=$size"
done
```

**How to apply (per-function):**

1. Identify NM-wrapped functions whose comments blame "unmatchable unfilled delay slot" or reference `feedback_ido_unfilled_store_return.md`.
2. In the Makefile, add: `build/src/<path>/<file>.c.o: OPT_FLAGS := -O2 -g3` next to any existing `TRUNCATE_TEXT` line.
3. Remove the NM wrap — replace with plain C function.
4. Rebuild, byte-verify, contaminate expected, log episode, land.

**Caveat on file-wide effect (updated 2026-04-20):** `OPT_FLAGS` applies to the whole file. Initial concern: functions that DID match fine under plain `-O2` (filled delay slots) might break under `-g3`.

**Small files (< ~50 funcs, mostly leaf setters): SAFE.** Tested on bootup_uso_tail3a.c (34 functions, 7 previously matched). Adding file-wide `-O2 -g3` promoted 3 unfilled-delay-slot NM wraps to 100 % matches with ZERO collateral damage. Tested on bootup_uso_tail2.c (5 functions) — no regressions, +1 match. Tested on bootup_uso_tail3b_bot_b.c (2 functions) — no regressions.

**Large files (> ~100 funcs, many non-leaf): UNSAFE.** Tested 2026-04-20 on bootup_uso.c (255 functions, 134 previously matched) — **73/134 matches regressed** (54 % of existing matches broke). The delay-slot fill IS load-bearing for non-leaf functions whose target epilogues use filled delay slots. File-wide -g3 is a sledgehammer here.

**Rule of thumb:** Apply file-wide `-O2 -g3` only for files ≤ ~50 functions that are predominantly short leaf setters. For bigger files or files with mixed leaf/non-leaf, either split the target function into its own file with its own override (see `feedback_non_aligned_o_split.md` + `feedback_pad_sidecar_*`) OR accept the NM wrap.

The reason: most of the 7 pre-matched functions were either empty (`void f() {}`) or short setters that compile identically at `-O2` vs `-O2 -g3`. Delay-slot filling only matters when there's an instruction available to schedule into the slot; many target functions simply don't trigger a different output.

**Apply file-wide `-g3` first**, only split out a dedicated file if you actually observe matched functions regressing after the flag change.

**Confirmed variants (2026-04-20):** `sw` store-then-return AND `swc1` store-then-return (e.g. func_000102F0, `*(float*)(a0+0x70)=(float)a1;`). Both reproduce unfilled delay slot at -O2 -g3. The pattern is "integer or float store whose body is 1–2 stores with no compute after" — scheduler fills the slot at -O2, stays put at -g3.

**Outdated memory to update:** `feedback_ido_unfilled_store_return.md` claims "IDO -O0/-O1/-O2 all fill the jr's delay slot". That's WRONG — the test didn't try `-g3`. Mark that memo as superseded. Candidates for re-promotion in bootup_uso: func_00010A9C (`sw zero,0x78`), func_0001207C (`sw a1,0x128`), func_00012090 (`addiu t6,-1; sw`), func_00012BF8 (`sw; sw` — done in ee1085f). The "save-arg-to-stack" sentinel pattern (func_0000214C, func_0000F7F4 family) might also be `-g3`-recoverable — untested yet.

**Origin:** 2026-04-20 agent-a, user pushback "a lot of giving up" on an NM wrap of func_00012BF8. Grind uncovered `-g3` as the previously-unknown matching knob. Commit ee1085f landed at 100 % after the Makefile override.

**What `-g3` does NOT change** (negative results to save future-me from re-running):

- **Integer constant CSE.** Distinct named locals all set to the same int value (`s32 c1=1, c2=1, c3=1, c4=1`) STILL get CSE'd into a single `li $v1, 1` reload. -g3's debug-friendliness preserves *names in symbols*, not the underlying allocator's CSE pass. If target asm has `addiu rN, $zero, 1` × 4 with each `1` in a fresh register, that's NOT reachable from naming-tricks at -O2 -g3. Verified on bootup_uso/func_00012188 2026-05-07.
- **Loop-invariant constant hoisting.** A constant used only inside a loop body (`s32 c2a = 0x2A; sb c2a, ...`) STILL gets hoisted before the loop. -g3 does not disable LICM.
- **Constant folding through named locals.** `register int one = 1; ... = one;` folds to literal `1`; `register` doesn't prevent the fold. (See also feedback-ido-v0-reuse-via-locals — that's about address-of-symbol, not int constants.)

`-g3` ONLY affects the reorg pass (delay-slot filling). Other -O2 passes (CSE, LICM, constant folding, register allocation) operate identically at -g0..-g3.

---

---

<a id="feedback-ido-g-flag-does-not-suppress-delay-slot-fill"></a>
## IDO -g does NOT suppress delay-slot fill (unlike KMC GCC -g2) — don't borrow the Glover technique

_KMC GCC -g2 disables delay-slot reordering (per project_compiler_findings.md). It would be tempting to assume IDO behaves the same. **Verified 2026-05-04 standalone: IDO -O1 with `-g` produces IDENTICAL filled jr-ra delays as IDO -O1 without `-g`.** The "unfilled jr ra; nop" target shapes in 1080 IDO code do NOT come from a -g flag._

**Verified 2026-05-04 (IDO 7.1, MIPS2):**

Same C source `int v3(int *a0, int a1) { if (count < a1) goto body; return 0; body: ... }` compiled with:

```bash
ido-7.1/cc -O1 -mips2 -32 -o /tmp/o1.o /tmp/test.c        # no -g
ido-7.1/cc -O1 -g -mips2 -32 -o /tmp/o1g.o /tmp/test.c    # with -g
```

**Both produced byte-identical output** (verified `cmp`):
- `beqz at, .body`
- `nop` (slt-bne load delay)
- `jr ra`
- `move v0, zero` ← **delay slot FILLED** (in both -g and no -g)

This is the OPPOSITE of KMC GCC behavior, where `-g2` disables delay-slot
reordering and produces UNFILLED `jr ra; nop` (per
`project_compiler_findings.md` for the Glover project).

**How to apply:**

When you see a 1080 (IDO) function with the unfilled-delay shape:

```
or v0, zero, zero       ; explicit
jr ra                   ; (no body insn in delay slot)
nop                     ; delay slot is just nop
```

DO NOT assume "this was compiled with -g, just need to flip the flag." That
trick works on Glover/KMC, not 1080/IDO. The unfilled delay must come from
some other source — possibly:
- Hand-written asm (libreultra `.s` files)
- A different IDO version with different scheduler heuristics
- Post-processing tooling that nopped out filled slots
- Cross-function tail-share (delays don't get filled across symbol boundaries)

For a function suspected of having unfilled-delay caps, check
`feedback_function_trailing_nop_padding.md`,
`feedback_cross_function_tail_share_unmatchable_standalone.md`, or
`reference_libreultra.md` (for hand-written candidates) BEFORE assuming
-g flag is the answer.

**Origin:** 2026-05-04, /decompile tick on `func_00011D40` (bootup_uso). The
existing wrap doc speculated "Common IDO -O2 -> O1-style unfilled-slot
mismatch" — implying -O1 produces unfilled slots. Verified empirically that
neither -O0 nor -O1 (with or without -g) produces the target's exact shape.
The wrap was updated to remove the speculative -g claim.

**TRAP — IDO `-g2` silently disables optimization** (verified 2026-05-05 on
n64proc_uso_func_00000014 variant 26): adding `-g2` to an `-O2` invocation
makes IDO's `uopt` pass emit `Warning: file not optimized; use -g3 if both
optimization and debug wanted` and produces -O0-style stack-spilled code.
The .o grows 25-30% (e.g. 1788 → 2228 bytes for func_00000014). If you
need debug info AT optimization, use `-g3` — that preserves -O2 codegen
and only inflates the .mdebug section. Don't use `-g2` thinking it adds
debug-info "harmlessly"; it's a silent regression to unoptimized.

---

---

<a id="feedback-ido-global-cse-extern-base-caps-unrolled-loops"></a>
## IDO -O2 globally CSE's `&D_00000000` (and other large-extern bases) into a single $sN, breaking per-iter lui reloads in unrolled-loop matches

_When a function references the same large-extern symbol (`&D_00000000`, `&func_00000000`, etc.) at MANY sites, IDO -O2 caches the high half (lui+addiu) into a single saved register ($s3 typical) and reuses it across all references — eliminating the per-use `lui $at, hi(SYM+offset)` instruction. Target asm often has the lui per-use (no CSE), and the C body cannot replicate this without breaking the CSE. Verified 2026-05-05 on game_uso_func_000044F4: 41-iter unrolled loop with `*(float*)((char*)&D_00000000 + N)` per iter; mine emits 1 insn per scalar load (lwc1 via $s3), target emits 2 (lui+lwc1) — net 41 insns gap, ~3.5pp fuzzy. Compounded with similar arg-spill pattern absences across the function, the total gap caps at ~38pp. Failed mitigations: `char *_arg_buf; char **_ptr = &_arg_buf;` indirection (IDO optimized away); `volatile char pad[200]; pad[0]=0;` to force frame size (IDO allocated 0x1B0 frame, way too big). Both regressed by 0.6-1.6pp._

**The trap (verified 2026-05-05 on game_uso_func_000044F4)**:

You write a C body for a function with N references to the same large
extern (`&D_00000000`, a USO data placeholder, or a per-segment global
table). For example, an unrolled loop that does `*(float*)((char*)&D_00000000 + 0xA0)`,
`...+0xA4)`, `...+0xA8)`, etc. for 30+ different offsets.

Expected asm shows each access as 2 insns:
```
lui $at, %hi(D_00000000 + 0xA0)
lwc1 $f4, %lo(D_00000000 + 0xA0)($at)
```

But your IDO -O2 emit shows each access as 1 insn:
```
lwc1 $f4, 0xA0($s3)        ; $s3 = &D_00000000 (cached at function entry)
```

IDO's global allocator (priority-based per `docs/gcc-2.7.2/global.c`)
sees that `&D_00000000` is referenced N times across the function and
ALLOCATES IT INTO A CALLEE-SAVED $s REGISTER. The per-use `lui+addiu`
is replaced by a single function-entry `lui+addiu` and per-use `lwc1`
with $s register as base + offset.

This is OPTIMAL code, but doesn't match the target asm which has the
per-use lui (no CSE).

**Why it's a structural cap**:

The CSE is BAKED INTO IDO. There's no `-fno-cse` flag for IDO. The
optimization runs unconditionally at -O2.

To DEFEAT the CSE, you'd need to either:
1. Make each reference look like a DIFFERENT symbol (impossible — they
   really are offsets from the same base).
2. Force IDO to think the value changes between accesses (volatile pointer).
3. Use `__asm__("")` barriers (IDO doesn't parse __asm__).

Option (2) is the most promising in theory but in practice causes
cascade regressions:

**Failed mitigation 1**: indirection via local pointer
```c
#define INIT_ITER(SLOT, TMPL_OFF, FLOAT_EXPR) do { \
    char *_arg_buf; \
    char **_arg_ptr = &_arg_buf; \
    *_arg_ptr = *(char**)((char*)&D_00000000 + (TMPL_OFF)); \
    /* ... */ \
} while (0)
```
Result: IDO optimized away the indirection (saw `_arg_ptr = &_arg_buf`,
inlined the deref); zero effect on the per-iter `lui` insn count.
Regressed -1.6pp due to side effects on register allocation.

**Failed mitigation 2**: stack padding to force per-iter spill
```c
volatile char pad[200];
pad[0] = 0;
```
Result: frame went from -0x28 to -0x1B0 (way bigger than expected
-0xE8). The volatile store landed at a different sp offset than
target's spill slots, shifting all subsequent `sw at, N(sp)` insns.
Regressed -0.6pp.

**What actually works (from sibling memos)**:

- `feedback_unique_extern_at_offset_address_bakes_into_lui_addiu.md`:
  declare unique extern at OFFSET address, not 0. Forces IDO to use
  HI16/LO16 with a different symbol per use → defeats CSE. But this
  requires having a per-offset symbol declared (only practical when
  symbol table can be augmented).
- `feedback_unique_extern_with_offset_cast_breaks_cse.md`: N unique
  externs all at 0x0 + `((char*)&sym + OFFSET)` cast. This works for
  the &D-CSE problem because each cast looks like a different symbol
  to IDO.
- decomp-permuter PERM_RANDOMIZE around the macro: random insertion of
  scheduling barriers may find a shape that breaks CSE.

**When to accept the cap**:

If the function is a long unrolled loop with N scalar loads from a
single large extern, and you've already applied a macro-based unroll
to reach 50-70% fuzzy, the residual gap is usually structural. Accept
the cap; rely on byte-correct ROM via INCLUDE_ASM until permuter or a
sibling-memo trick finds a way to break the CSE.

**Related**:
- `feedback_unrolled_loop_via_c_macro_for_decomp.md` — the macro
  technique that gets you to 50-70% before this cap appears
- `feedback_unique_extern_with_offset_cast_breaks_cse.md` — sibling
  trick that defeats &D CSE in different contexts
- `docs/gcc-2.7.2/global.c` — the global register allocator that does
  the CSE
- `feedback_uso_entry0_trampoline_95pct_cap_class.md` — different
  cap class (post-cc recipes), but conceptually similar "by-design
  fuzzy ceiling"

**Inverse case — when target IS hoisting and you need to match it (verified 2026-05-08, game_libs_func_00037E98):** if the target's asm has a single hoisted `lwc1 $f0, %lo(SYM)($at)` ABOVE a loop or unrolled-block of N uses, but your C emits N per-iter `lwc1` because each iteration's expression re-reads the address, hoist the load into a local FP variable: `float divisor = *(float*)((char*)&D + 0xN);` then use `divisor` inside the loop. IDO -O2 will then CSE the load to a single hoisted lwc1, matching target. This is the OPPOSITE of the 044F4 cap (where target had per-iter and my emit was hoisted) — that case can't be fixed at the C level because the lui/addiu/symbol-base CSE is non-defeatable; the scalar-FP-load-CSE here YIELDS to local introduction. Lever rule of thumb: if the target's hoist is a single FP load (lwc1/ldc1), local-introduction works; if it's a $s-reg holding a struct/array base across calls or an extern-base, CSE is non-defeatable.

---

---

<a id="feedback-ido-zero-term-via-memory-load-not-literal"></a>
## Replace literal `0.0f * 0.0f` with `local[N] * local[N]` (where local[N] holds 0.0f) to force IDO to emit the redundant mul/add insn pair

_When target asm has an explicit middle 0-term in a sum (e.g. `sqrlen = a*a + 0 + c*c` with a literal mul.s on the zero), C `0.0f * 0.0f` gets constant-folded out of the expression by IDO -O2 — the result is `sqrlen = a*a + c*c` with no middle term. Reference a memory-stored 0.0f local (`local_xz[1]`) instead — the lwc1 + mul.s + add.s chain emits as expected._

**Verified 2026-05-08 on `game_uso_func_00001DDC`** (+0.73pp from this single line change, 17.52→18.26%):

```c
/* Wrong (17.52%): literal 0.0f*0.0f gets constant-folded */
sqrlen = local_xz[0]*local_xz[0] + 0.0f*0.0f + local_xz[2]*local_xz[2];

/* Right (18.26%): memory-loaded local_xz[1] (which IS 0.0f from line above)
 * forces lwc1 + mul.s + add.s emission, matching target's 3-term sum-of-squares */
local_xz[1] = 0.0f;
sqrlen = local_xz[0]*local_xz[0] + local_xz[1]*local_xz[1] + local_xz[2]*local_xz[2];
```

**How to apply:**
- When the asm shows `mul.s f?, f0, f0; add.s …, f?` with `f0` being a known-zero result of an earlier `mtc1 zero, f0` or `lwc1 f0, sp+N` (where sp+N was just zero-stored), the source has an explicit `0 * 0` term. Don't write `0.0f * 0.0f` literally — it folds. Read from a memory slot that's known to hold 0.0f.
- Generalizes to other "compute X * 0 + ..." patterns where the asm has the explicit redundant operation. Constant-folder kills the term in C; memory load preserves it.
- Companion: the `volatile T**` recipe forces re-loads of the same address; this entry forces re-emit of a constant-result mul.

**Scope limit (verified 2026-05-08 on game_uso_func_00001DDC's scaled_y block):** the memory-loaded zero must be *close in dataflow* to the use site. Reusing `local_xz[1] = 0.0f` from earlier in the function across an intervening `sqrt() + normalize3()` call sequence + `{}` scope boundary doesn't work — IDO's optimizer still folds the mul to zero. Worked +0.73pp on the FIRST sum-of-squares (right after the local_xz[1]=0.0f init), 0pp when applied to a y-axis scale 50+ insns later. If the asm's zero comes from `mtc1 zero, fX` (a register-source zero, not memory), the recipe is fundamentally inapplicable — declare a CLOSER-in-scope `float zero_f = something_zero;` if you need to force the mul there.

---

<a id="feedback-ido-type-split-unique-extern-breaks-cse"></a>
## Type-different unique externs (`int X` + `char Y`, both at addr 0) break IDO CSE between sibling lui+addiu in the same call

_When a single call passes two values derived from different externs at the same link-resolved address (0 in USO segments), IDO -O2 by default CSE-folds the `lui+addiu` pair so both values reuse one register. Target's asm often shows TWO separate `lui+addiu` pairs — that's because the original C declared the externs as DIFFERENT types. Same-type unique-name externs do NOT break the CSE; type difference does._

**Verified 2026-05-05 on `func_0000553C` in bootup_uso (84.20% → 88.40%, +4.2pp):**

```c
/* Wrong (84.20%): same type — IDO CSE-folds into one lui+addiu */
extern char D_X;
extern char D_Y;
func_00000000(p, arg0, *(int*)&D_X, &D_Y);
/* emit: lui a3, 0; addiu a3, a3, 0; lw a2, 0(a3); ... — single lui shared */

/* Right (88.40%): int + char split — IDO emits 2 distinct lui+addiu */
extern int D_X;          /* int-typed: dereferenced as the value */
extern char D_Y;          /* char-typed: address-of as the pointer */
func_00000000(p, arg0, D_X, &D_Y);
/* emit: lui a2, 0; lui a3, 0; addiu a3, a3, 0; lw a2, 0(a2); ... — 2 luis */
```

**Why:** IDO CSE works on type-erased load expressions. Two `extern char` accesses (even at different symbols) get `lui+addiu` for ONE base address; the loaded values then come from `lw $rN, %lo(SYM)($rN)`. With `extern int` for one and `extern char` for the other, the load expressions have different IR types — CSE doesn't fold them, so each gets its own lui+addiu pair.

**Doesn't help when:**
- The CSE you're trying to break is across MANY sites (loop, multi-iter), not 2 in one call. That's the `feedback-ido-global-cse-extern-base-caps-unrolled-loops` cap class — frame-saved register caching, not load-expression CSE.
- The target's 2 luis come from different OFFSETS off the same base (`*(int*)((char*)&D + 0x10)` vs `*(int*)((char*)&D + 0x20)`). For that, use unique-extern-with-offset (declare `extern int D_X_AT_10` at the offset address).

**Companion entries:**
- `feedback-ido-global-cse-extern-base-caps-unrolled-loops` — different cap class, applies to MANY sites
- `feedback_unique_extern_with_offset_cast_breaks_cse.md` — unique externs at OFFSET addresses (different mechanism — addresses differ, not types)

**2026-05-06 same-type unique-extern variant (cross-statement context):**

The "same-type aliases don't break CSE" claim above is true for SAME-CALL-ARG context (both uses passed to one jal). But same-type aliases DO break CSE for CROSS-STATEMENT uses — verified on `func_00008F18` (75.97% → 100% via this technique alone, after `goto end`):

```c
/* Wrong (93.61% after goto-end): IDO CSE-folds the two &D_00000000 across statements */
*(char**)(self + 0x28) = &D_00000000;       /* vtable store */
handle = func_00000000(0, &D_X, &D_00000000, 0);  /* call-arg use */
/* emit: lui $a2, 0; addiu $a2, 0; sw $a2, 0x28(s0); ... a2 reused for call arg */

/* Right (100%): same-type but distinct names break CSE */
extern char D_8F18_vtable;       /* both at link-addr 0x0 */
extern char D_8F18_call_arg;
*(char**)(self + 0x28) = &D_8F18_vtable;
handle = func_00000000(0, &D_X, &D_8F18_call_arg, 0);
/* emit: lui $t6, 0; addiu $t6, 0; sw $t6, 0x28(s0); lui $a2, 0; addiu $a2, 0; ... */
```

Generalization: "same-type aliases" rule above only applies WITHIN a single call's arg list. ACROSS statements (store + later call), distinct symbol names alone are enough to break CSE — no type split needed. The CSE engine seems to only consider "same value in registers" if uses are close enough (within one expression / one call-arg-list); cross-statement uses are tracked as separate pseudos by name.

**Application:** when target shows separate `lui+addiu` for two uses of `&D` (one as struct-field-store, another as later call-arg), declare two `extern char D_alias_N;` aliases at 0x0 in `undefined_syms_auto.txt`. No type split required.

**Caveat — does NOT help cluster-load patterns** (verified 2026-05-06 on `game_uso_func_0001001C`, regressed 84.05% → 81.26%): when target uses ONE base reg + multiple offsets (`p = &D + 0xDD0; arg1 = p[0]; arg2 = p[1]` emitting `lui+addiu p; lw 0(p); lw 4(p)`), declaring two unique externs at the offset addresses (e.g., `D_arg1 = 0xDD0; D_arg2 = 0xDD4`) FORCES two separate `lui+addiu` pairs, breaking the cluster. The unique-extern technique only helps when target ALREADY emits two separate base loads — never when target uses cluster-load. Also doesn't help precall-arg-spill caps (`sw a1, 4(sp)` in jal delay slot is structural, not symbol-CSE).

---

<a id="feedback-ido-cse-bust-via-near-symbol-pointer-arith"></a>
## Break `&X` ↔ `*(int*)&X = 0` CSE by expressing the second use as pointer-arithmetic from a NEAR symbol

_When target emits `*(int*)&X = 0` (naked store: single `lui at; sw 0(at)`, 2 insns) AND separately uses `&X` as a pointer bound (e.g., `end = &X`), the natural C — naked-store-plus-`end = &X` — triggers IDO -O2 to CSE the address load. Built emits `lui v?, hi(X); addiu v?, v?, lo; sw 0(v?); ...; end = v?` — the address materialization is hoisted into a $v-register and reused, growing the store to 3 insns and changing the schedule. Express the second use via pointer arithmetic from a near (same-link-resolution) symbol to break the CSE while preserving post-link byte-identical addresses._

**Verified 2026-05-13** on `func_80001184` (kernel zero-init): 72.10% → 81.58% (+9.48pp) by writing `end = D_80012D3C + 8` instead of `end = &D_80012D5C`. Both expressions resolve to VRAM 0x80012D5C at link time, but the pointer-arithmetic form has no syntactic reference to `D_80012D5C` → no CSE between it and the `*(int*)&D_80012D5C = 0` store. Prologue collapses to target's `lui at; sw 0(at)` form.

**Pattern recognition** — apply when:
- Target asm starts with `lui at, hi(X); sw zero, lo(X)(at)` (2-insn naked store)
- Built emits `lui v?, hi(X); addiu v?, v?, lo; sw 0(v?); ... ; mov vN, v?` (3 insns with $v-reg CSE)
- And the C separately needs `&X` for a pointer bound OR for a struct-field-pointer-store

**Mechanism:** IDO's CSE pass folds `&X` references across the function body. The optimizer doesn't track that `*(int*)&X = 0` is a STORE to X (which doesn't need the address kept around) vs a LOAD of `&X` (which does). It just sees two `&X` SSA values and CSE-folds them into a single materialization, keeping the address live in a register across the store.

**Constraints — when this works:**
- A "near symbol" exists at predictable offset from X (in the same .data block or array). Pointer arithmetic `Y + N` must post-link to `&X`.
- Same-link-resolution is enforced by the linker (extern declarations of contiguous data). Verify with `nm` or `objdump -t` that addresses match.
- This is NOT the same as declaring `D_X` and `D_Y` as separate externs at the same address (that's `feedback-ido-cse-bust-via-distinct-externs`); here, the SECOND symbol (`D_80012D3C`) is a real, distinct address — we're using its offset to LAND on X's address.

**Doesn't help — same-call CSE** (use `feedback-ido-cse-bust-via-distinct-externs` or `feedback-ido-type-split-unique-extern-breaks-cse` instead): if both `&X` uses are within the SAME function call's argument list, pointer-arith reformulation won't separate them because IDO CSEs at the call-arg-marshaling stage. Use distinct-extern aliasing for that case.

**Companion entries:**
- `feedback-ido-cse-bust-via-distinct-externs` — for same-call-arg CSE
- `feedback-ido-type-split-unique-extern-breaks-cse` — type-split for arg-list CSE

---

---

<a id="feedback-ido-goto-epilogue"></a>
## Use `goto end` for early-return from alloc-check; plain `return` emits extra branch

_IDO compiles `return a0` from inside a nested if into `b + lw ra` redundancy, not a direct `beqz/bnez` to the epilogue. A `goto end_label` at the sole `return` at the bottom produces the clean single-path branch that matches typical libgdl/libc code._

**Quick decision tree** — when your wrap has `if (X == 0) return 0;`-style early-exits and built fuzzy is well below target's, look at where the target's alloc-fail beq LANDS:

1. **Full epilogue** (`lw ra; addiu sp; jr ra`) AND success path returns an arg unchanged → **UNIFIED form**: `goto end; ... end: return arg;`
2. **Full epilogue** AND success path returns a DERIVED value (`*(v0+N)`, etc.) AND target has `beq zero,zero,.L_epi` + lw-in-DS → **SPLIT form**: `goto end_zero; ... return DERIVED; end_zero: return 0;` (explicit returns at each exit)
3. **Mid-body** (some body insns still execute after the branch target) → **FALL-THROUGH-WITH-NULL-GUARD form**: `if (X != 0) { partial body }` instead of `return 0;` — the post-guard body is shared between X==0 and X!=0 paths

Get the form WRONG and you'll plateau at the original fuzzy or regress. Get it RIGHT and typical gains are +15-30pp on a single restructure (verified 2026-05-14 on three functions).

**Rule:** When the target asm for an alloc-or-init wrapper has a single shared epilogue that the alloc-fail path branches to via `beqz $v0, .Lepilog`, write C with a single `return a0;` at the bottom and a `goto end;` for the fail case — not a `return a0;` inside the nested if.

**Why:** IDO -O2 doesn't always collapse multiple `return` paths into a branch to the common epilogue. If you write:
```c
if (a0 == 0) {
    a0 = alloc();
    if (a0 == 0) return a0;   // ← extra branch + lw ra
}
do_stuff();
return a0;
```
IDO emits `bnez v0, .L_continue; b .L_exit; lw ra ...` — a conditional over the continue path plus an unconditional to the exit, with the ra reload hoisted up.

Using a single-return + goto:
```c
if (a0 == 0) {
    a0 = alloc();
    if (a0 == 0) goto end;
}
do_stuff();
end:
    return a0;
```
IDO emits `beqz v0, .Lepilog` directly — one branch, straight to the common epilogue. Matches the hand-rolled-feeling structure you see in libgdl/libc allocator wrappers.

**How to apply:**
- Indicator in target asm: a `beqz $v0, .LepilogTag` immediately after the alloc, where `.LepilogTag` is the function's single `lw ra; addiu sp; or v0,a0,0; jr; nop` block.
- Write every early-exit in the C as `goto end;` pointing to one `end:` label just before `return <val>;` — regardless of how many branches there are.
- Single-branch structure seems to be how the original source was written (or the old compiler's pattern), so the goto form is more faithful anyway.

**Example (bootup_uso func_00001DB8, matched 2026-04-18):**
```c
void *func_00001DB8(void *a0, int a1, int a2) {
    if (a0 == 0) {
        a0 = (void*)func_00000000(0x48);
        if (a0 == 0) goto end;        // ← key: goto, not return
    }
    func_00000000(a0, a1);
    *(int*)((char*)a0 + 0x40) = a2;
end:
    return a0;
}
```
All 20 insts match byte-for-byte. Plain `return a0` in the inner if would produce 22 insts (one b + one extra lw ra).

**Related:** the skill's `decomp-permuter` section has `PERM_GENERAL(if (old == 0xA) { *arg0 = val; return val; }, if (old == 0xA) goto store)` as a common variation — same idea.

### Variant — SPLIT-epilogue form (use when target's success path is `beq zero,zero,.epi` + lw-in-delay-slot, NOT a unified `return v0` epilogue)

The above form (`goto end; ... end: return a0;`) is the UNIFIED-epilogue recipe — all paths converge at one `return a0;` where the compiler emits `or v0, a0, zero; jr ra` as the shared exit. This works when:
- The function returns an arg unchanged on the success path (e.g., `return a0;` where a0 is the input/alloc'd pointer).
- The zero-arm wants the same value zeroed (the arg-equal-zero case naturally has v0=0 since a0=0).

But when the SUCCESS path computes a DIFFERENT return value (e.g., `return *(v0 + 8);` — dereferences a field rather than returning the alloc'd pointer), and target has the SPLIT-epilogue shape:
```
   beq  v0, zero, .L_zero_arm
   lw   t6, OFF(sp)               ; DS — body starts here
   sb   t6, 2(v0)
   ... rest of body ...
   beq  zero, zero, .L_epilog     ; unconditional skip past zero-arm
   lw   v0, 8(v0)                  ; DS — compute success return value
 .L_zero_arm:
   or   v0, zero, zero             ; explicit-zero return for fail path
 .L_epilog:
   lw   ra, ...
```

…then the UNIFIED-epilogue form (`goto end; ... v0 = *(v0+8); end: return v0;`) DOESN'T match. IDO hoists the `lw v0, 8(v0)` early (right after the entry beq) and uses a different reg (v1) to carry the result across the body — producing the wrong shape.

The SPLIT-epilogue form is what works:
```c
char *v0 = (char *)alloc(a0);
if (v0 == 0) goto end_zero;
v0[2] = (char)a1;
*(int*)(v0 + 0xC) = a2;
v0[1] = a3;
return *(void**)(v0 + 8);     // explicit return at success path
end_zero:
return 0;                      // explicit return at zero-arm
```

Two explicit `return` statements + a `goto end_zero;` at the alloc-fail branch. IDO -O2 then emits:
- `beq v0, zero, .L_zero` at the alloc-check (skip body)
- Body stores inline (delay slot of beq filled by first body load)
- `beq zero, zero, .L_epi` + `lw v0, 8(v0)` (DS) at success-path return
- `or v0, zero, zero` at `.L_zero` label (the zero-arm body)
- Shared `.L_epi:` for `lw ra` + epilogue

**Why this works:** the explicit `return *(v0+8);` at the success path keeps `lw v0, 8(v0)` as a LATE computation (right before the return), forcing IDO to schedule it in the delay slot of the unconditional `beq zero,zero,.L_epi`. The separate `return 0;` at the zero-arm label keeps it as a distinct emit (`or v0, zero, zero`) rather than being merged with the success path's return.

**Verified 2026-05-14 on `gl_func_00021E08`:** the unified form (`goto end; ... end: return v0;`) gave 68.65 %; the split form (`goto end_zero;` + two explicit returns) gave 100 %.

**Decision rule:**
- Target's success path returns the alloc'd pointer / an arg unchanged → UNIFIED form (one return at `end:` label).
- Target's success path returns a DERIVED value (`*(v0+offset)`, `v0->field`, etc.) AND the asm shows a `beq zero,zero,.L_epi` + lw-in-DS pattern → SPLIT form (explicit return at each exit, `goto` only to the zero-arm label).

Pick the form from target's asm shape — don't default to unified.

### Variant — FALL-THROUGH-WITH-NULL-GUARD (use when alloc-fail branches into a partial body, not a full end-return)

For functions that allocate MULTIPLE objects in sequence (e.g. `p1 = ... ; p2 = ...`), don't assume every alloc-fail is an early-return. If target's asm shows the SECOND alloc-fail branching into a PARTIAL body (not the function's full end), the original C uses an `if (X != 0) { ... }` INNER-GUARD around the part of the body that uses `X`, rather than an `if (X == 0) return 0;` early-return.

**Example pattern (verified 2026-05-14 on `titproc_uso_func_00001B10`):**

The function has two allocs:
```
p1 = a0;
if (p1 == 0) p1 = alloc(0x40);
if (p1 == 0) return 0;          // ← FULL end-return on p1 fail
p2 = a1;
if (p2 == 0) p2 = alloc(0x2C);
                                 // ← NO early-return on p2 fail
if (p2 != 0) {                  // inner-guard around p2-init only
    gl_func(p2, ...);
    *(p2 + 0x28) = ...;
}
*(p1 + ...) = ...;              // p1-init runs regardless
gl_func(p1, p2);                // even called with p2 == 0
return p1;
```

The C compiler-author knew `gl_func(p1, p2)` is safe with `p2 == 0` (callee handles null), and `*p2 = ...` is the only operation that needs the inner guard. The asm reflects this: `beq v0, zero, .L_partial_body` skips only the `*p2 = ...` block, not the whole function.

**Diagnosis: look at where the alloc-fail beq LANDS:**
- Lands at the function's `lw ra; addiu sp; jr ra` epilogue → use `goto end; ... end: return ...` (unified or split form).
- Lands MID-BODY (some body insns still execute after the branch target) → use `if (X != 0) { partial body }` inner-guard form. The post-guard insns are shared between the X==null and X!=null paths.

**Verified 2026-05-14 on `titproc_uso_func_00001B10`:** changing `if (p2 == 0) return 0;` to `if (p2 != 0) { p2-init body }` (with p2 falling through to the post-init shared body) pushed 51.93% → 73.40% (+21.47pp).

**Second verification 2026-05-14 on `titproc_uso_func_00001D7C`** (sibling of 1B10): dead-arm second alloc with the same `if (X == 0) return X;` → `if (X == 0) sub = alloc(...);` fall-through form. Combined with fixing a typo where `*(self+0x28) = base` appeared TWICE in the C source (should have been `sub` for the first store, `self` for the second — TWO distinct pointers, even though `sub == self` in the typical reachable path). Pushed 59.36% → 84.20% (+24.84pp). The two-pointer encoding is target-mandated even when the dead-arm path means both pointers usually alias — IDO preserves the source-level distinction in the emit (two separate `sw rN, 0x28(...)` instructions with different base registers).

**Third verification 2026-05-14 on `titproc_uso_func_00001840`** (third sibling in the same family): same fix applied identically. Pushed 76.87% → 84.26% (+7.39pp).

**Recipe payoff scales INVERSELY with body size:** the alloc-cascade-fix's contribution is a fixed ~6-8 insn diff, so on a function with a longer body the proportional gain is diluted. 1B10 (42-insn) → +21pp; 1D7C (44-insn) → +25pp; 1840 (68-insn) → +7pp. When choosing whether to apply the recipe, weigh against function size — a 200-insn function with the same alloc-cascade-fix yield is ~3-5pp, often not worth the source churn.

### Variant — -O0 alloc-cascade (homed-args, saved-reg vars): 5-lever recipe (2026-05-25)

The recipes above are all -O2. The -O0 USO files (e.g. bootup_uso `o0_*` splits) emit alloc-cascades very differently — homed args reloaded per use, no register promotion of plain locals, `b .+1` BB markers. To match a -O0 alloc-cascade (verified on `func_0000FD4C`, 76/85 insns byte-exact standalone -O0), apply these five levers:

1. **`register` the cascade pointers.** The target carries the per-arm allocation results in saved registers `$s0`/`$s1` (saved at prologue `0x14`/`0x18`). Plain `void *s0, *s1;` go to stack slots at -O0 — you MUST write `register void *s0, *s1;` to land them in `$sN` (same as `func_0000FBCC`'s `register int *p` in the same file).
2. **Short-circuit `||` form for each arm, NOT nested early-return.** `if ((p != 0) || (p = alloc(N), p != 0)) { arm-body }` maps EXACTLY to the target's `bnez p, .arm; ...alloc...; beqz p, .skip` structure, and an inner arm-fail (`beqz p, .skip`) just falls past that arm's body to the next field-init. A nested `if (p==0){p=alloc; if(!p) return;}` instead creates MULTIPLE return paths (extra `b epilogue` per arm). One trailing `return arg0;` outside the whole `if` = the single shared exit.
3. **Saved-reg REUSE in the tail.** After the cascade, the now-dead `$s0`/`$s1` get reused as scratch for the field writes. Reproduce by REASSIGNING the register vars: `s0 = arg0; s1 = &D_X; *(int*)((char*)s0 + 0xC) = (int)s1;` (and `s0 = arg0;` again before the last call's arg) — this extends their live range into the tail so IDO keeps them in `$sN` instead of grabbing fresh `$tN`.
4. **Direct global access folds the `+offset` into `%hi/%lo($at)`; pointer-cast does NOT.** `*(int*)((char*)&sym + 0x2C) = v` and `sym_arr[11] = v` both MATERIALIZE `&sym` into a `$tN` register first at -O0, then offset-store (`lui t;addiu t;sw v,0x2C(t)`). The target uses the folded absolute store `lui $at,%hi(sym+0x2C); sw v,%lo(sym+0x2C)($at)` — to get it, access a global STRUCT FIELD on a typed extern: `extern struct {char _p[0x2C]; int f2C; ...} sym; sym.f2C = v;`. Same for a global pointer slot: declare `extern void *g;` (real type, not `char`) and write `g = expr;` / read `g` directly → folded `lui $at; sw/lw ,%lo($at)`.
5. **Unlinked-vs-linked reloc display is NOT a diff.** When diffing the standalone .o, `sw rt,%lo(sym+0x2C)` shows offset `0x2C` (sym resolves to 0 unlinked) while the target shows `0x34` (sym at module-offset 8, 8+0x2C). Same reloc — mask symbol-relocated offsets before comparing (see N64_FORENSICS "don't panic at the unlinked view").

**Residual cap:** even with all five levers, -O0 emits one EXTRA dead `b .+1; nop` BB-marker at the function tail (the statement-list-end marker) that the target lacks — the same un-removable -O0 marker documented for `arcproc_uso_func_000000B4` (8 source variants tried there; INSN_PATCH is banned). So a -O0 alloc-cascade lands ~96% NM (body exact, +2-3 insn tail), not 100%. Apply the recipe for the body-correctness/struct-field-typing win and the migration-ready body; do NOT expect a clean match. (Also: these `o0_*` functions only build at -O0 after the per-file split migration — bare INCLUDE_ASM in the -O2 tail file can't host a -O0 body.)

---

---

<a id="feedback-ido-hoists-save-reg-init-above-jal"></a>
## IDO -O2 hoists `move sN, aM` above adjacent jal when no data dependency; source order `jal; p = a0;` doesn't keep them in source order

_When you write `func(...); p = a0;` in C, IDO -O2 schedules the `move sN, aM` (the p=a0 emit) BEFORE the jal because there's no data dep. To get the target's "lw count; move sN, aM; blezl count" order (with the move AFTER the jal+lw), straight C source order is insufficient. Caps loop-init scheduling diffs._

**Pattern (verified 2026-05-02 on game_uso_func_00001644):**

C source:
```c
i = 0;
game_uso_func_00000280((int*)((char*)a0 + 0x1D0));   // jal
p = a0;                                               // wanted: AFTER jal
while (i < *(int*)((char*)a0 + 0x1D0)) { ... p++; ... }
```

Target asm:
```
move  s1, zero            ; i = 0
jal   game_uso_func_00000280
addiu a0, s2, 0x1D0       ; delay
lw    t8, 0x1D0(s2)       ; load count for blezl
move  s0, s2              ; p = a0  ← AFTER lw, BEFORE blezl
blezl t8, +N              ; skip loop if count <= 0
```

My emit:
```
move  s1, zero
move  s0, s2              ; p = a0  ← HOISTED above jal
jal   game_uso_func_00000280
addiu a0, s2, 0x1D0
lw    t8, 0x1D0(s2)
blezl t8, +N
```

IDO's scheduler hoists `move s0, s2` ABOVE the jal because s0 isn't read by the jal arg setup (which uses s2 directly via `addiu a0, s2, 0x1D0`), and there's no data dep blocking the hoist.

**Why it matters:**
- 3-insn schedule diff caps the function at 96 % vs target's 100 %.
- The "obvious" fixes (re-order C statements, declare p later) don't work because IDO's reorg pass re-schedules anyway.

**What didn't work (game_uso_func_00001644, 2026-05-02):**
- Swapping `i = 0;` and `p = a0;` order: helps the FIRST emit position (`move s1` vs `move s0` in init pair) but doesn't push p=a0 past the jal.
- Removing the named local p (using `a0+i*4` indexing): changes loop body too much.
- `extern void f(...)` declaration before use: makes IDO emit relocation-form jal (`0c000000` + R_MIPS_26) instead of resolved jal (`0c0000a0`); doesn't fix the schedule.

**Likely fixes (untried):**
- Restructure as `do { ... } while (++i < count)` with the count load explicitly forced via `if (cond) { p = a0; do { ... } while (...); }`.
- Use the count as a "fake dependency" for p=a0 — e.g., `p = (int*)((char*)a0 + (count - count));` (always equals a0). May force the schedule.
- Permuter random mode for ~500 iters to find the right permutation.

**How to apply:**
- For 2-loop init functions following the "func_setup; loop alloc/init" pattern: expect a 3-insn ceiling unless permuter helps.
- Don't grind register/decl order for this specific schedule — it's hoist-driven, not allocation-driven.
- Document the diff and move on; ≥95 % NM wraps with documented schedule diffs are acceptable per the workflow's "preserve partial C" rule.

**Related:**
- `feedback_ido_swap_stores_for_jal_delay_fill.md` — store BEFORE jal in C → folded into delay slot. (Reverse problem: how to push something INTO the delay slot.)
- `feedback_ido_v0_reuse_via_locals.md` — named locals → $v0; this is similar reasoning for $s allocation.
- `feedback_permuter_1000_plus_structural.md` — when permuter helps vs when it doesn't (≤1000 = scheduling, ≥1000 = structural).

---

---

<a id="feedback-ido-if-guarded-do-while-defers-reg-move"></a>
## IDO -O2 if-guarded do-while defers register-only assignment past jal

_When a `p = a0;`-style register-only move is hoisted by IDO ahead of an unrelated jal (no data dep), wrapping the loop as `if (count > 0) { p = a0; do { ... } while (i < count); }` forces the move AFTER the count load and into the blezl/blezl-skip region. The if-guarded do-while creates an implicit dep ordering that the plain `while` form lacks._

**Symptom:** function has two parallel loops with the same shape — `jal init; p = a0; while (i < count) { ... p++; i++; }`. The first loop matches; the second loop has `or s0, s2, zero` (p = a0) hoisted BEFORE the second jal, vs target's placement BETWEEN `lw count` and `blezl`.

**Why the first loop matches:** in source order, the jal comes BEFORE the assignments. IDO schedules `or s1; or s0` after the lw because they're written after the jal in source.

**Why the second loop diverges with plain while:** when the source has `i = 0; jal; p = a0; while`, IDO is free to hoist the register-only `or s0, s2, zero` (no data dep on jal's return) to fill scheduling slots before the jal. The plain while form gives the scheduler full latitude.

**The fix that works (verified on `game_uso_func_00001644` 96.15 % → 100 % on 2026-05-02):**

Wrap the loop as if-guarded do-while:

```c
i = 0;
init_call((int*)((char*)a0 + 0x1D0));
if (*(int*)((char*)a0 + 0x1D0) > 0) {
    p = a0;
    do {
        ... body uses p ...
        i++;
        p++;
    } while (i < *(int*)((char*)a0 + 0x1D0));
}
```

This produces:
```
or s1, zero, zero          ; i = 0  (free to hoist before jal — same as before)
jal init_call
addiu a0, s2, 464          ; delay slot
lw t8, 464(s2)             ; first count read
or s0, s2, zero            ; p = a0  (now scheduled here, between lw and blezl)
blezl t8, end              ; skip if 0
lw ra, 36(sp)              ; (delay slot, branch-likely path)
... loop body ...
```

The if-guard's count test gets fused with the do-while's count test (IDO sees both reload the same memory) and emits a single `lw t8 + blezl` pair. The `p = a0` lands between them because the if-then block establishes a basic-block boundary that the scheduler respects.

**When to apply:** plain-while loop with parallel sibling that already matches; structural diff is a single `move sX, sY` (register-only assignment) hoisted past the loop's setup jal. Convert ONLY the diverging loop, leave the matching sibling alone.

**Don't confuse with:** `feedback_ido_no_asm_barrier.md` (no `__asm__("")` available in IDO), `feedback_ido_swap_stores_for_jal_delay_fill.md` (different scheduling lever, applies to stores not register moves).

**Reverse direction (if you need to HOIST a move BEFORE a jal):** plain while with the move written before the jal (default IDO behavior).

---

---

<a id="feedback-ido-implicit-decl-extern-conflict"></a>
## IDO implicit decl conflicts with later explicit extern

_K&R-implicit `int func()` from a call BEFORE the explicit `extern void func()` declaration causes IDO cfe to error "Incompatible function return type"_

In game_uso.c (and other USO files) there's a single `extern void game_uso_func_00000000();` partway through the file, used by the cluster of functions that call the in-segment placeholder. If you write a NEW function that calls `game_uso_func_00000000(...)` and place it BEFORE that extern, IDO cfe errors:

```
cfe: Error: src/.../game_uso.c, line N: redeclaration of 'game_uso_func_00000000'; previous declaration at line M in file '...'
cfe: Error: Incompatible function return type for this function.
```

The first call (above the extern) gets implicitly declared as `int func()` per C89/K&R rules. The later `extern void` then conflicts.

**Why:** IDO follows C89 implicit declaration: any call to an undeclared function defaults the function to `int func()` with unspecified args. That implicit decl is a real declaration in the file's symbol table, so a later explicit `extern void func()` is a redeclaration with mismatched return type.

**How to apply:** Place your decompiled function AFTER the existing `extern void game_uso_func_00000000();` line in the file (typically near the cluster of other callers). Don't try to add a second `extern` higher up — there's already one and duplicating it triggers the same error in reverse. Don't add a forward decl with `void` either; trust the existing extern and order your code below it.

(For the inverse — calling `game_uso_func_00000000` with a float arg — see `feedback_ido_knr_float_call.md`. That one isn't matchable at all from C; this one is just a placement issue.)

**Alternative — relax the existing `void(void)` extern to `int()`:** when the file already has `void some_placeholder(void);` somewhere and you need to call it with multiple args (e.g. asm shows `g(a0, 0x8C, t->[0x6B0])`), placement-after-extern doesn't help because `void(void)` rejects any args at the call site. Change the existing decl to `int some_placeholder();` (K&R unspecified-args, int return):

- Existing void-discarding callers (`some_placeholder();`) still work — they ignore the now-int return value.
- Your new multi-arg caller compiles cleanly because `int func()` permits any arg count.
- The relaxation is safe because the underlying symbol is a placeholder (target=0) that's runtime-patched to whatever the loader chooses; no caller actually depends on the return type.

Used at arcproc_uso.c (2026-04-19) for `arcproc_uso_func_00001B88` — relaxed `void arcproc_uso_func_00000000(void);` to `int arcproc_uso_func_00000000();`. Both the new 3-arg caller and the existing no-arg caller (`arcproc_uso_func_00001488`) matched.

---

---

<a id="feedback-ido-indirect-call-t9"></a>
## Inline function-pointer call → IDO uses `jalr $t9`; naming as local → `$a1` or other

_For indirect calls via a struct member (`(*struct->callback)(args)`), keep the function-pointer EXPRESSION inline inside the call. A named local `fn_t f = struct->callback; f(args);` makes IDO allocate `$a1` (or other `$a`-reg) and emit `jalr $a1`; inline form emits the canonical MIPS `jalr $t9`._

**Rule:** If the target asm has the canonical MIPS O32/PIC indirect-call pattern:

```
lw $t9, off($reg)
...
jalr $t9
```

…do NOT introduce a named local for the function pointer. Keep it inline inside the call expression.

**Non-matching C (named local — IDO picks `$a1`):**
```c
int (*func)(char*) = *(int(**)(char*))(p2 + 0xC);
short off = *(short*)(p2 + 0x8);
func(p1 + off);
```
Emits `lw $a1, 0xC($v1); lh $a2, 8($v1); jalr $a1; addu $a0, $a2, $v0` — wrong register.

**Matching C (fully inline):**
```c
(*(int(**)(char*))(p2 + 0xC))(p1 + *(short*)(p2 + 0x8));
```
Emits `lw $t9, 0xC($v1); lh $t6, 8($v1); jalr $t9; addu $a0, $t6, $v0` — ✓ canonical.

**Why:** `jalr` defaults to `$t9` as target register; IDO seems to special-case the "call a sub-expression that is a function pointer" pattern to reserve `$t9`. Once the function pointer gets NAMED and stored (even with `int (*func)() = ...`), it becomes a regular local subject to the general allocator, which tends to pick an `$a-reg` or `$v-reg` depending on liveness.

**How to apply:**

- When the target asm has `jalr $t9` for an indirect call: write the call as one expression with the function pointer deref inline.
- When the target asm has `jalr $aN` (unusual): name the function pointer as a local first — that shifts IDO away from `$t9`.

**Related:** see `feedback_ido_v0_reuse_via_locals.md` for the general "named local vs inline" register-allocation rule. This memory is the specific case for indirect calls.

**Caveat:** this only fixes the `$t9` allocation. The v0/v1 assignment for the surrounding pointer chain (p1 in $v0 vs $v1, etc.) is separately determined by IDO's SSA renumbering and is often NOT controllable from C without decomp-permuter.

**Origin:** 2026-04-19 game_libs gl_func_0004E150. With named `int (*func)() = ...`: 95.8 %. With fully inline call: 97.5 % (only v0/v1 swap remained). NON_MATCHING wrapped at 97.5 %.

---

---

<a id="feedback-ido-infinite-loop-unreachable-epilogue"></a>
## IDO `while(1){}` always emits unreachable jr-ra epilogue + 2 alignment nops — caps short infinite-loop stubs

_For functions whose target is a tight infinite-loop stub (`b .; nop; …nops; jr ra; nop`), IDO emits jr $ra at offset 0x20 with seven nops between (size 0x28). If the target's jr is earlier (e.g. offset 0x18 with five nops, size 0x20), neither size nor body matches from C. Wrap NM._

**Class of unmatchable functions:** "halt" / "panic" / "infinite-loop" stubs whose only body is `while (1) {}`. The target asm looks like:

```
beq $zero,$zero,<self>   # branch to self
nop                       # delay slot
nop … nop                 # N unreachable nops
jr $ra                    # unreachable epilogue
nop                       # delay slot
```

**What IDO emits from `void f(void) { while (1) {} }`:**

```
beq $zero,$zero,0    # at offset 0
nop                   # offset 4
nop nop nop nop nop nop nop   # SEVEN nops at offsets 8..0x1C
jr $ra                # offset 0x20
nop                   # offset 0x24
+ alignment nops      # 0x28..0x2F
```

**Symbol size: 0x28.** Same at -O0, -O1, -O2, -O3.

**Why it doesn't match a 0x20 target:**
- Target has 5 middle nops; IDO emits 7. Two extra IDO scheduler alignment nops before the "unreachable" basic block (the epilogue).
- Target's jr $ra is at offset 0x18; IDO's is at 0x20.
- TRUNCATE_TEXT can shrink the symbol to 0x20, but only by chopping the jr+nop+padding at the end — leaves bytes at offset 0x18 as nop instead of jr $ra. Off-by-one byte.

**Variants tried (all produce identical bytes):**
- `while (1) {}`
- `for (;;) ;`
- `goto here; here: goto here;`
- `void f(void) { int dummy[2]; dummy[0] = 0; while (1) {} }`
- `void f(void) { int x = 0; while (1) { x++; } }`

**Why C can't reach it:**
- Adding side-effects (function calls) inside the loop body changes the prologue (sp adjust, ra save) and changes the b-target offset.
- IDO doesn't parse `__attribute__((noreturn))` (cfe rejects).
- IDO rejects `__asm__()` (per `feedback_ido_no_asm_barrier.md`).
- The two extra middle nops are added by IDO's scheduler unconditionally for the unreachable epilogue — no C transformation suppresses them.

**Recipe:** wrap NM with `void f(void) { while (1) {} }` body and a comment that records the size mismatch. Don't grind further; don't try TRUNCATE_TEXT (it doesn't fix the offset-0x18 byte).

**Likely targets in 1080:** `__osPanic`, `__halt`, `_exit`, "stop the world" handlers. Look for ROM bytes `1000FFFF 00000000 00000000…03E00008 00000000` in any segment — same blocker applies.

**Related:**
- `feedback_function_trailing_nop_padding.md` — different class (trailing pad blocks ~75% cap, nothing to do with infinite loops).
- `feedback_pad_sidecar_unblocks_trailing_nops.md` — would unblock IF the only diff were trailing nops; but here the middle bytes also differ.

---

---

<a id="feedback-ido-inline-deref-v0"></a>
## Inline nested pointer deref uses $v0; named local forces $t-reg

_When target asm uses `lw $v0, off(a0); lw $tN, 0x10($v0)` for a two-step pointer deref, keep the expression inline as `*(int*)(*(int*)(a0 + off) + 0x10)` — a named local `int *t = ...; t[...]` makes IDO pick a $t-reg (e.g. t6) instead of $v0._

**Rule:** For an intermediate pointer that's used only once, inline the dereference. If you name it, IDO promotes it to a $t-reg.

**Target asm pattern:**
```
lw    $v0, 0x3c($a0)
lui   $a0, %hi(sym)
lw    $t6, 0x10($v0)
bnezl $t6, .skip
lw    $ra, 0x14($sp)         # delay slot
jal   func
addiu $a0, $a0, %lo(sym)
```

**Matching C (inline):**
```c
void f(char *a0) {
    if (*(int*)(*(int*)(a0 + 0x3C) + 0x10) == 0) {
        gl_func_00000000(&sym);
    }
}
```

**NON-matching C (named local — uses $t6 instead of $v0):**
```c
void f(int *a0) {
    int *t = (int*)a0[0xF];    /* $t6 */
    if (t[4] == 0) {           /* $t7 check */
        gl_func_00000000(&sym);
    }
}
```

**Why:** when an intermediate value has a name, IDO treats it as a "variable" and gives it $t-reg priority (liveness matters). When it's an anonymous sub-expression with a single use, IDO emits a load into $v0 (the default "temporary return" register) and discards it after use. The live range is visibly shorter, so allocation prefers $v0.

**How to apply:**

- If your build shows `lw $t6, off(...)` but target has `lw $v0, off(...)`: collapse the named intermediate into an inline expression.
- Works best when the intermediate is used in ONE place (the comparison or the next load). If it's used twice, naming it is unavoidable.

**Related but different:** `feedback_ido_v0_reuse_via_locals.md` — that memory covers `$v0` reuse when you WANT $v0 (named locals get $v0 for simple assignments from function calls). This rule is about $v0 for single-use pointer dereferences.

**Caveat — also tested 2026-04-19 gl_func_0000836C:** a SINGLE `*a1 == 9` inline comparison (no nesting, no further use of the loaded value) picks `$t6` instead of `$v0`. So "inline → $v0" only applies when the inlined load is part of a CHAINED deref (two or more levels) OR gets used more than once. A single-use compare doesn't trigger $v0 promotion.

**Origin:** 2026-04-19 game_libs gl_func_00055264 (nested deref). Named `int *t = (int*)a0[0xF]` got 98.5 % (t6/t7 instead of v0/t6). Inlined `*(int*)(*(int*)(a0 + 0x3C) + 0x10)` got 100 %. Caveat discovered same day via gl_func_0000836C.

**Counter-example — single-use ptr deref FLIPS the rule (timproc_uso_b5_func_0000BBC8, 2026-05-05):**

For a 5-insn float-store leaf:
```
mtc1  $a1, $f12
lw    $t6, 0x2B8($a0)     # ← target uses $t6, NOT $v0
swc1  $f12, 0x2A0($a0)
jr    $ra
swc1  $f12, 0x120($t6)    # delay
```

NAMED `int *t = *(int**)((char*)a0 + 0x2B8); ...; *(float*)((char*)t + 0x120) = a1;` → IDO picks `$v0`. Wrong.
INLINE `*(float*)((char*)*(int**)((char*)a0 + 0x2B8) + 0x120) = a1;` → IDO picks `$t6`. Correct.

So for SINGLE-USE ptr derefs (one read of the loaded ptr), INLINE → $tN and NAMED → $v0 — the opposite of the chained-deref rule above. Try BOTH variants when the .o disasm differs in regiser choice between $v0 and $tN; whichever variant matches expected wins.

**Counter-example — naming an arg of a `lw+addiu+bne` triple swaps the $t6/$t7 allocation order (arcproc_uso_func_00000D70, 2026-05-05):**

For a comparison like `if (p[2] == v1 + 1)`:

NAMED `int v1 = p[1]; if (p[2] == v1 + 1)`:
```
lw    $t7, 8($v0)        # p[2] FIRST → $t7   (HIGHER reg)
addiu $t6, $v1, 1        # v1+1 SECOND → $t6  (LOWER reg)
bne   $t6, $t7, ...
```

INLINE `if (p[2] == p[1] + 1)`:
```
lw    $t6, 8($v0)        # p[2] FIRST → $t6   (LOWER reg)
addiu $t7, $v1, 1        # p[1]+1 SECOND → $t7 (HIGHER reg)
bne   $t6, $t7, ...
```

(IDO CSE keeps `p[1]` in `$v1` either way — it's the comparison-arg allocation
that flips.)

If expected uses the inline-shape register order ($t6 for the first-computed
value, $t7 for the second), drop the named local and inline both reads.
This was a 2-byte (2-insn) diff at 99.83% NM. Verified arcproc_uso_func_00000D70.

**Counter-example — named local can land in $v1, not $tN (game_uso_func_0000FBF8, same day):** when the function ALSO has a named `int v` local that takes $v0, IDO sometimes assigns the second named ptr-local `int *t` to `$v1` rather than the next $tN. The expected target had `$t6` for `t` and `$t7` for the const-1 temp; my output had `$v1` for `t` and `$t6` for the const-1, a one-step register shift. So "named → $t-reg" is a TENDENCY, not a guarantee — when $v1 is otherwise free and the live range doesn't cross any caller-saved boundary, IDO will use $v1 even for named locals. No clean source-level fix found in 2 attempts; wrapped NON_MATCHING at 98.67 %.

---

---

<a id="feedback-ido-inline-fnptr-call-drops-arg-spill"></a>
## Inlining intermediates into a fn-ptr call expression drops IDO's defensive arg-register spill

_When IDO -O2 spills caller-arg regs ($a1) defensively before an indirect call, factoring out the named local intermediates and inlining the deref chain INTO the call expression keeps the arg dead at the spill point — IDO drops the `sw aN, callerslot(sp)`. Applied 2026-05-03 to gl_func_0000DE30 family (4 dispatchers); promoted 13/20→16/20 insns and unblocked the matching frame fix._

**The pattern:** an indirect dispatcher of shape:

```c
void f(int **a0, int a1) {
    int local = K;
    int **base = (int**)((char*)a0[0x44/4] + a1 * 96);
    int *p = *base;
    short adj = *(short*)((char*)p[0x28/4] + 0x28);
    ((void(*)(int, int*))p[0x2C/4])((int)p + adj, &local);
}
```

IDO -O2 emits an EXTRA `sw a1, 0x2C(sp)` (defensive caller-arg-slot spill)
near the start, BEFORE the natural overwrite via `addiu a1, sp, 0x2C` (=&local).
The spill is unnecessary — a1 is dead by the time of the addiu — but IDO
inserts it because the named locals (`base`, `p`, `adj`) extend a1's
liveness analysis past the spill-defeat point.

**Workaround:** inline the entire deref chain INTO the call expression:

```c
void f(int **a0, int a1) {
    int pad_top[2];
    int local = K;
    int pad_bot[4];
    int *p = *(int**)((char*)a0[0x44/4] + a1 * 96);  /* p still named (used twice) */
    ((void(*)(int, int*))p[0x2C/4])(
        (int)p + *(short*)((char*)p[0x28/4] + 0x28), &local);
}
```

The `base`, `adj` named locals dropped; the deref-into-fnptr call done in
one expression. IDO's allocator sees a1 die at `addiu a1, sp, ...` and
omits the spill. Bonus: the multiplication chain shifts from $t9 to $t8
(matching target).

**Verified 2026-05-03 on gl_func_0000DE30/DE80/DED0 family** (4 sibling
dispatchers in src/game_libs/game_libs.c). Pre: 13/20 insns matched
(90.85 % NM), frame 0x28, a1 spilled at sp+0x2C. Post: 16/20 insns
matched, frame 0x38, no a1 spill, local at sp+0x2C. Remaining 4-insn
diff is a $v0/$v1 shift in the deref/jal block (target uses v1/v0/t0
where mine uses v0/t0/t1) — not C-flippable from inside the function.

**Why it works:** IDO's spill heuristic isn't pure liveness — it's
conservative when a value crosses many "named pseudo" boundaries. Inlining
collapses the boundaries; the analyzer sees a1's death directly.

**When to try:** any indirect call (`fnptr(...)`) where IDO emits an
unexpected `sw aN, callerslot(sp)` at function entry and the call is the
function's main work. Also useful for value-returning dispatchers where
the result is consumed inline (don't name the deref chain).

**Pad recipe combo:** for these dispatchers the inline-form fix is
PARTIAL until you also apply the split-pad recipe per
feedback_ido_split_pad_for_buf_offset.md to land local at the right sp
offset within the right frame. `pad_top[2] + local + pad_bot[4]` lifts
a 0x28-frame call to 0x38 with local at sp+0x2C.

**Related:**
- feedback_ido_split_pad_for_buf_offset.md — split-pad for stack offset.
- feedback_ido_volatile_unused_local_forces_local_slot_spill.md — similar
  arg-spill control via volatile.
- feedback_ido_unused_arg_save.md — IDO doesn't dead-eliminate arg spills.

---

---

<a id="feedback-ido-inline-keeps-t-regs"></a>
## IDO inline expression keeps $t6/$t7 registers, named local moves to $at/$v1

_For pointer-arithmetic functions like `return a0 + idx*N + K`, fully inline single-expression form keeps temps in $t6/$t7 registers (matching target's natural pick); naming a local for the offset shifts temps to $at/$v1. Tradeoff: inline gets t-regs but addu operand-order flips; named gets correct operand order but wrong registers_

**Pattern:** A leaf utility function returning a pointer expression like `a0 + idx*N + K` where `idx = *(int*)(a0+OFFSET)`.

**The two C forms produce different register assignments AND different addu operand orders:**

```c
// Form A — inline single expression (NO named locals):
char *f(char *a0) {
    return a0 + *(int*)(a0 + 0x7C) * 0x28 + 0x84;
}
// Emits: lw t6, 0x7c(a0); sll t7, t6, 2; addu t7, t7, t6; sll t7, t7, 3;
//        addu v0, t7, a0;     <- t-regs MATCH but addu operand order: t7 FIRST
//        addiu v0, v0, 0x84

// Form B — named offset local:
char *f(char *a0) {
    int off = *(int*)(a0 + 0x7C) * 0x28;
    return a0 + off + 0x84;
}
// Emits: lw at, 0x7c(a0); sll v1, at, 2; addu v1, v1, at; sll v1, v1, 3;
//        addu v0, a0, v1;     <- addu operand order CORRECT (a0 first), but $at/$v1 not $t6/$t7
//        addiu v0, v0, 0x84
```

**Why:** IDO's addu operand-order decision flips on whether the second operand is "freshly computed" or "register-stable". Inline (no named local) → t7 was just-defined → IDO picks t7 first. Named local → off is treated as register-stable → IDO picks the lexically-first source operand (a0). Register identity follows from the named-local-vs-inline distinction: inline lets IDO use the natural $t6/$t7 register sequence; named locals get $at/$v1 from the global allocator.

**`register int off` does NOT split the difference** — IDO treats it the same as plain named local: a0-first ordering AND $at/$v1 registers. The hint isn't strong enough to flip register identity here.

**How to apply:**
- If the target asm uses `$t6/$t7` for the multiply chain AND `addu v0, a0, $t7`: cap is real, neither inline nor named-local form gets both attributes simultaneously. ~7/8 inline form is the best achievable from C; the final addu operand-order needs permuter or -O0 split.
- If you have to pick between the two forms, prefer **inline** — fewer wrong instructions overall (1 wrong vs 2 wrong), and the wrong one (operand order) is more cosmetic than register identity.
- Don't burn variants on `register T x` hints for this class of issue.

**Origin:** 2026-05-03, bootup_uso/func_00010324 (8-insn pointer-arithmetic leaf). 11+ variants tested across 2 sessions; inline form is strictly best for this class.

**Related:** `feedback_ido_addu_operand_order.md` (general guidance on splitting addu operands — but that recipe COSTS register identity here).

---

---

<a id="feedback-ido-knr-float-call"></a>
## K&R-declared extern can't be called with float args under IDO (no way to get direct jal)

_In game_libs (1080), `gl_func_00000000` is declared as `extern int gl_func_00000000();` (K&R / no prototype). Calling it with float args produces either float→double promotion (with K&R) or `jalr` via function-pointer cast (no direct jal). You cannot redeclare with a compatible `(float, float)` prototype — IDO cfe rejects "prototype and non-prototype declaration found ... not compatible after default argument promotion". Functions that need a direct `jal gl_func_00000000` with `mov.s $f14, $f12` in the delay slot are unmatchable._

**Rule:** When the asm has:
```
jal   gl_func_00000000
mov.s $f14, $f12       # delay slot (pass single float to both f12 and f14)
```

...and the top-level file declares `extern int gl_func_00000000();` (K&R), there is no C form that produces this exact output. Keep the function as INCLUDE_ASM.

**What fails (tested on gl_func_00067AC8, 2026-04-19):**

1. `extern int gl_func_00000000(); void f(float x) { gl_func_00000000(x, x); }`
   → K&R promotes float→double: `cvt.d.s f12, f4; mov.d f14, f12` (wrong, 4 extra insts)

2. `void f(float x) { extern int gl_func_00000000(float, float); gl_func_00000000(x, x); }`
   → cfe error: "prototype and non-prototype declaration found for gl_func_00000000, the type of this parameter is not compatible with the type after applying default argument promotion"

3. `void f(float x) { ((void(*)(float,float))gl_func_00000000)(x, x); }`
   → `mov.s f14, f12` is correct, but uses `lui $t9; addiu $t9; jalr $t9` instead of `jal gl_func_00000000`. 70 % fuzzy — below NON_MATCHING threshold.

4. Replacing the top-level `extern int gl_func_00000000();` with `extern int gl_func_00000000(float, float);`
   → breaks every OTHER caller that passes int args.

**Why this is a hard blocker:**
- K&R-style function declarations in C promote float → double at the CALL site.
- IDO's cfe treats the K&R declaration as authoritative for compatibility across the compilation unit.
- Function-pointer-cast calls go through `$t9` → `jalr`, not direct `jal`.
- `gl_func_00000000` is a single **placeholder symbol** for ALL dynamic relocation in game_libs — it's called by wrappers with wildly varying signatures (1-4 int args, float args, mixed). No single prototype works for all callers.

**How to apply:**

- If asm has `jal gl_func_00000000` + `mov.s $f14, $f12` (or any single-float arg setup) and the file has the K&R extern: **skip, keep as INCLUDE_ASM**.
- If asm has `jal gl_func_00000000` with ALL-INT arg setup (`$a0..$a3`): the K&R extern works fine, just use int args.
- If your body doesn't need direct `jal` (e.g., no arg dep on the specific instruction form): NON_MATCHING wrap if ≥80 %, else INCLUDE_ASM.

**VERIFIED workaround (2026-05-14, gl_func_0003787C):** Declare a DIFFERENTLY NAMED prototyped extern at function scope. The fresh name doesn't conflict with the K&R `gl_func_00000000` declaration. For 1080 USO segments the linker resolves both via R_MIPS_26 (jal opcode `0x0C000000` + reloc-to-symbol) — both names resolve to the same target offset 0 in the same segment, so post-link bytes are identical to calling `gl_func_00000000` directly.

```c
/* file scope: extern int gl_func_00000000(); — K&R */
/* function scope: */
extern int gl_proto_3787C(void*, void*, void*, int, float, int);
void gl_func_0003787C(void *a0) {
    gl_proto_3787C(/* args */, 6.0f, 0);  /* emits direct jal + swc1 singles */
    gl_func_00000000(a0);                  /* still uses K&R extern */
}
```

Result: `jal` direct call, `swc1` singles (no float→double promotion). Byte-exact on gl_func_0003787C (84 bytes, 0 diffs).

The name `gl_proto_3787C` is arbitrary — pick a unique name per use site (e.g. `gl_proto_<funcname>`). It's only used for prototype enforcement at this call site.

**REQUIRED: add a linker entry for the fresh name.** Add `<proto-name> = 0x00000000;` to `undefined_syms_auto.txt` (alongside `gl_func_00000000_va`). Without this entry the per-`.o` byte verification passes (objdiff sees the call as a clean reloc with addend 0), but the final `ld` of `tenshoe.elf` fails with `undefined reference to '<proto-name>'`. The R_MIPS_26 reloc encodes the immediate from the jal opcode, but `ld` still needs the symbol to resolve before it can compute the final address. Earlier draft of this entry incorrectly claimed no linker entry was needed — verified 2026-05-14 by hitting the link break on a clean rebuild.

**Other previously-untried workaround (still untried):**
- Move the function to a SEPARATE .c file that doesn't include the K&R declaration, declares its own prototyped version. Add to Makefile + linker script. The named-extern trick above is simpler — recommended.

**Scope of the workaround — partial support for int-arg-share patterns (verified mixed 2026-05-14):**

The named-typed-extern trick fixes the K&R float→double promotion. For "share $a0 across adjacent K&R calls when both pass the same int value":

- **Mid-sequence arg-share (e.g. calls 1, 2, ..., N all pass same value): NOT reproducible.** The named-typed-extern produces independent call sites with full arg setup per typed-extern call. Verified negative on `gl_func_00066210` (calls 1+2 share $a0=1).
- **Last-call arg-carry: REPRODUCIBLE via arg-less call form.** Writing the FINAL call as `gl_func()` with NO C-source args (K&R extern accepts this) makes IDO emit zero arg-setup insns for that call, letting prior call's $a0 carry. Verified positive on `gl_func_00065D08`: 7-call cascade with last call as `gl_func()` produces target's `nop` delay slot exactly (vs explicit `or a0, sN, 0` for `gl_func(a0)`).

```c
/* shape that works */
for (...) gl_func(a0);          /* N-1 calls with arg */
gl_func();                       /* final call inherits a0 */

/* shape that DOESN'T work */
gl_func(1);                      /* mid-sequence share */
g = gl_func(1);                  /* IDO re-emits li a0, 1 */
```

The arg-share is IDO's internal escape-analysis on the K&R callee — works when the C source TRULY OMITS the arg (so IDO has no syntactic arg-binding to honor), not when the source repeats the same value.

**Origin:** 2026-04-19 game_libs gl_func_00067AC8. Tried 3 variants; all failed for the reasons above. Reverted to INCLUDE_ASM.

**Float-RETURN inverse case (2026-05-07, mgrproc_uso_func_000005D0):**

The float-arg case above is "C wants to pass float, K&R extern doesn't allow it." There's an inverse case: "C wants to USE the return value as float, but K&R extern says it returns int." This *is* solvable via function-pointer cast, even though the float-ARG case isn't.

Shape: caller does `jal gl_func` then `mul.s f0, f0, f4` on the FPU return register `$f0`. From C, `((int)gl_func_00000000() * something_float)` doesn't work — IDO promotes through int math.

**Workaround that works:**

```c
extern int gl_func_00000000();   // K&R, file-wide
typedef float (*FloatFn)(void);  // local typedef
...
val = ((FloatFn)gl_func_00000000)() * scale_float;
```

The cast doesn't change the call shape — it's still `jal gl_func_00000000` with no arg setup (matches asm). It just lets C treat the return as float. IDO emits the post-call `mul.s f6, f0, f4` chain correctly.

**Why this works when the float-ARG case doesn't:**
- For ARGS: K&R promotion happens at the call site BEFORE the jal — the prologue-stage arg setup goes through `$f12 → $f12,$f13` (double) instead of `$f12` alone. The cast can't undo this because the K&R declaration is consulted for promotion, not the cast.
- For RETURN: K&R declaration affects how the COMPILER interprets `$v0` (or `$f0`) after the jal. A function-pointer cast IS the type at the call site, so the compiler treats `$f0` as the float return. The asm shape (jal address + delay slot) is identical between the int-typed and float-typed variants.

**How to detect this case:** asm has `jal gl_func_00000000` (no arg setup, void→float) followed by an FPU instruction (`mul.s`, `add.s`, `swc1`, `mfc1 $tN, $f0`, etc.) that consumes `$f0`. C code needs to feed the return into a float operation.



The same K&R-promotion issue affects **stack-passed float args** (5th+ position in O32). Target asm:
```
lwc1  $f4, 0x34(sp)      ; caller's stack arg slot 5 (float)
...
swc1  $f4, 0x10(sp)      ; outgoing arg slot 4 (4-byte stack store)
jal   gl_func_00000000
```

`void f(..., float arg5, ...)` with K&R callee produces `lwc1; cvt.d.s; sdc1` (8-byte double store) — **regresses to ~58 %**.

`void f(..., int arg5_bits, ...)` (declare as int, pass as int) produces `lw; sw` (4-byte int load + store, same bytes as the float but different opcodes) — **recovers to ~67 %**.

The remaining 32 % gap is the lw-vs-lwc1 opcode diff: target uses float-reg pipeline (lwc1/swc1) which only happens with a true `float` parameter, but a true float parameter triggers promote-to-double. **Catch-22**: no clean C signature reproduces target's float-reg pass-through bytes when callee is K&R-declared.

**The int-bits workaround is strictly better than float-with-promotion** when both fail to reach 100 %. Use it when target has lwc1+swc1 stack pass-through and you can't reach exact match — at least the stack-store width matches (4 bytes), avoiding the worst diffs.

**Future direction (not yet implemented):** the file-split + per-prototyped extern recipe (mentioned above for Yay0 USOs is blocked) would also unlock float pass-through for these cases.

---

---

<a id="feedback-ido-load-cse-swap-v0-v1"></a>
## IDO load-CSE swap to flip $v0/$v1 regalloc

_Decl-order trick that flips IDO's $v0/$v1 assignment for a chained pointer-deref pair via CSE_

For a pattern `p1 = a0->X; p2 = p1->Y; ...use(p1,p2)`, IDO -O2's natural emit
puts `p1=$v0, p2=$v1` (first-loaded gets lowest free $v). When the target asm
has it swapped (`p1=$v1, p2=$v0`), the **load-CSE trick** flips the assignment:

```c
/* Wrong (97.5%): natural decl order */
int p1 = *(int*)(a0 + 0x2C);
int *p2 = *(int**)((char*)p1 + 0x28);

/* Right (100%): declare p2 FIRST with p1's load expression inline,
 * then re-declare p1 with the same load — IDO CSE's the dup load. */
int *p2 = *(int**)((char*)*(int*)(a0 + 0x2C) + 0x28);
int p1 = *(int*)(a0 + 0x2C);
```

**Why:** IDO's CSE pass spots the duplicate `*(int*)(a0+0x2C)` and emits ONE
load. The first complete value (p2) gets $v0; the CSE'd intermediate (p1)
ends up in $v1. Writing p1 first reverses this.

**Why:** This is the inverse of the "first-loaded gets $v0" rule —
syntactically declaring the *downstream* value first, with the upstream
load inlined, makes IDO compute the upstream value as a CSE byproduct
rather than as a "first-class" first-loaded value.

**How to apply:** When NM-wrap doc says `Pure $v0/$v1 swap` for a
chained-deref function and earlier variants concluded "decl-order is a
no-op", try this load-CSE form before declaring the cap structurally
locked. Verified 2026-05-04 on TWO functions:
- `timproc_uso_b5_func_00008F98` (97.5%→100%) — 16 prior variants
- `gl_func_0004E150` (97.5%→100%) — sibling pattern, same fix
Both share `p1 = a0->K; p2 = p1->L; ((fn)p2->M)(p1 + p2->N)` shape.
Search NM docs for "v0/v1 swap" or "first-loaded" — likely applies to
other instances. Doesn't apply when the two values use different load
expressions (e.g., `p1 = a0->X; p2 = a0->Y;` — no shared subexpression
to CSE).

---

---

<a id="feedback-ido-inline-deref-vs-cache-flips-vN-tN"></a>
## Inlining `(*a0)` 3+ times instead of caching `p = *a0` flips IDO from $tN to $v1 for the int** spill-load

_When target keeps a `int**` arg in `$v1` across post-call uses (multiple `lw tN, 0(v1)` reloads), explicit caching `p = *a0;` lets IDO pick a $t-reg instead. Inlining `(*a0)` at every use forces 3 separate reloads which IDO assigns via `$v1`. Same C semantics, different IDO output._

**Verified 2026-05-05 on `titproc_uso_func_00000B6C` (97.50% → 100%):**

```c
/* Wrong (97.50%, $t0): explicit cache + reuse */
int *p = *a0;
p[5] = 0;
if (a1 != -1) {
    int *q = (int*)((*a0)[2]);
    *(int*)((char*)&D_00000000 + 0x168) = q[2];
    q = (int*)((*a0)[2]);
    *(int*)((char*)&D_00000000 + 0x170) = q[1];
}

/* Right (100%, $v1): inline (*a0) at every site */
(*a0)[5] = 0;
if (a1 != -1) {
    *(int*)((char*)&D_00000000 + 0x168) = ((int*)((*a0)[2]))[2];
    *(int*)((char*)&D_00000000 + 0x170) = ((int*)((*a0)[2]))[1];
}
```

**Why:** the cached form gives IDO a single `lw $tN, 0(spill)` that emits ONE load and propagates `$tN` to all uses. The inline form forces three independent `*a0` derefs that IDO CSE-folds into "load `&a0` once into a reg, then `lw 0(reg)` per use." IDO picks `$v1` for the cached `&a0` because it's the cheapest caller-save register that survives the dead phase between the 3rd jal and the post-call code (no other register competes for that slot in the function's lifetime graph).

**Diagnostic:** target's post-call asm has `lw $v1, SPILL_OFFSET($sp)` (loading the spilled arg) followed by 2-3 `lw $tN, 0($v1)` reloads of `*$v1`. Built has `lw $tN, SPILL_OFFSET($sp)` and 1 reload. The +2 extra reloads in target are the signal that IDO sees the value as "live across multiple sites" — which is what the inlined-deref form mimics.

**When to apply:** post-call code reads `*a0` at 2+ sites within the same basic block. The cached-pointer form is the natural decode but produces the wrong register class.

**Doesn't apply when:** the function only reads `*a0` once post-call (then there's nothing to CSE), or when target itself has the cache (one `lw t6, 0(spill)` followed by `lw tN, 0(t6)` reuses).

**Single-use mirror case (2026-05-08, game_libs_func_00037F10):**

The opposite-direction lesson at smaller scale. For a tiny FPU function that reads a value through one pointer and converts to float via `mtc1` in ONE use site:

```c
/* Wrong (1-insn diff, $v1): cache the value */
int *p = (int*)a0[1];
int val = *p;        /* IDO picks $v1 for `val` since it's caller-save and dead after mtc1 */
*a1 = (float)val / *(float*)((char*)&D + K);

/* Right (byte-equal, $t7): inline the deref */
int *p = (int*)a0[1];
*a1 = (float)*p / *(float*)((char*)&D + K);
```

**Why:** with `int val = *p;` the local `val` becomes a named pseudo with a (very short) live range — IDO assigns it $v1 (cheap caller-save). Inlining `*p` at the use site doesn't create a pseudo; the lw target register goes through standard temp-reg allocation, picking $t7 (next free higher-numbered $t).

**Pattern recognition:** target asm has `mtc1 $tN, $f4` where N is high (e.g. $t7 = $15) and there's no separate "value" local in the natural decode. Build emits `mtc1 $v1, $f4` instead.

**Use count is the discriminator** — the multi-site rule above goes the OTHER direction (inline → $v1, cache → $tN). Single-use prefers inline for $t-reg; multi-site prefers cache for $t-reg. They look inverted but both are "minimize the named-pseudo footprint at the right phase of liveness analysis."

**Companion to** `feedback-ido-load-cse-swap-v0-v1` (above) — both are about controlling which register IDO assigns to a deref intermediate. That entry is for `$v0` vs `$v1` swap on chained derefs (different values); this entry is for `$v1` vs `$tN` choice on repeated derefs (same value, multiple sites).

---

---

<a id="feedback-ido-local-ordering"></a>
## IDO places locals first-declared-highest; add leading pad local to shift scratch slot down

_If your local `scratch` ends up at sp+0x1C but the target wants sp+0x18, declare an extra `int pad` BEFORE scratch. IDO places first-declared locals at the HIGHEST stack offset and subsequent ones lower, so `int pad, scratch;` puts pad at +0x1C and scratch at +0x18._

**Rule:** IDO -O2 allocates stack locals in declaration order, highest offset first. When your single scratch local lands 4 bytes too high relative to the target, declare a throwaway `int pad` BEFORE scratch — GCC puts pad at the "original" slot and scratch drops one slot lower.

**Why:** IDO reserves stack slots in reverse declaration order starting from the highest address below ra/saved registers. A bare `int scratch;` claims the first available slot (highest). Adding `int pad, scratch;` makes pad claim that slot, pushing scratch 4 bytes lower. Both locals still allocate, the compiler just won't emit any loads/stores for an unused pad.

**Related but different:** `feedback_ido_buf_array_alignment.md` covers `T buf[2]` vs `T buf` — that's about *alignment* (arrays forced to 8-byte alignment). This rule is about *ordering* (first-declared = highest offset). They solve different mismatches.

**Real example (2026-04-18 game_libs pattern-C wrapper, 24 functions):**

Target asm:
```
addiu sp, sp, -0x20
sw a0, 0x20(sp)
sw ra, 0x14(sp)
lui a0, 0
addiu a0, a0, 0
addiu a1, sp, 0x18       <- scratch at sp+0x18
jal 0
addiu a2, zero, 0x4
lw t6, 0x18(sp)          <- reload scratch from sp+0x18
...
```

Bad C (scratch ends up at sp+0x1C):
```c
void gl_func_XXXXXXXX(int *dst) {
    int scratch;
    gl_func_00000000(gl_func_00000000, &scratch, 4);
    *dst = scratch;
}
```

Good C (scratch moves to sp+0x18):
```c
void gl_func_XXXXXXXX(int *dst) {
    int pad, scratch;    /* pad takes sp+0x1C, scratch takes sp+0x18 */
    gl_func_00000000(gl_func_00000000, &scratch, 4);
    *dst = scratch;
}
```

**How to apply:**

- Check the target asm's `addiu aN, sp, OFF` — that's the intended scratch slot.
- Compare with your build's emitted offset.
- If build is +4 higher than target: add `int pad, scratch;` (two locals, pad first).
- If still off by more: add more leading pads (e.g., `int pad1, pad2, scratch;`). Each adds 4 bytes of offset.
- Alternative: reorder other existing locals so scratch is declared LATER.

**When it does NOT apply:** stack-frame size mismatches (target 0x20, build 0x18) aren't fixed by adding locals — IDO may optimize away unused locals and keep the frame small. For those, try varying arg counts, adding `int pad[2]` for 8-byte alignment, or reviewing the function's calling pattern. The pad trick only reshuffles slots WITHIN an already-correct frame.

**Counter-example for "IDO may optimize away unused locals" (2026-05-08, game_uso_func_00001DDC):** the "may" caveat above is real but not deterministic — a `char frame_pad[184];` declared at function scope, address never taken, never read or written, and NOT marked `volatile`, *did* allocate its full 184 bytes of stack space. Built frame grew exactly from 0xC8 to 0x180, matching target. So for LARGE byte-exact frame deltas on functions where you've decoded the structural layout but not the body details (typical mid-grind constructor / spine function), a non-volatile `char N[exact_byte_delta];` is worth trying — it's lighter than `volatile char N[]; N[0]=0;` (which adds extra reads and was documented as regressing on `game_uso_func_000044F4` in the long-extern-CSE entry above). Picking 184 vs 200 may matter (IDO's allocator alignment + free-slot reuse interact with the size); use the EXACT byte gap from `addiu sp,sp,-N` diff. Frame size correction alone won't shift fuzzy% if the body is dominated by other diffs, but it unblocks future grinding that depends on correct stack offsets.

**Limit-case (2026-05-08, gl_func_000088B4):** the bare-char-array trick above does NOT work for SMALL gaps. `gl_func_000088B4` had an 8-byte frame gap (0x20 vs target 0x28). Tested:
  - `char pad[8];` — elided.
  - `volatile char pad[8];` (no access) — elided.
  - `char pad[16];` — elided.
  - `volatile int pad; pad = 0;` — frame grew to 0x28 but added a `sw zero, N(sp)` insn that target doesn't have, so net fuzzy% unchanged.

Hypothesis: IDO -O2 only honors a non-accessed unused array for frame-rounding when the function ALREADY has enough register-pressure spill traffic that the slot can be coalesced into a "real" spill plot (the 1DDC case had 0x180 of spill-heavy traffic). Small wrappers with low spill traffic — like the 36-insn `gl_func_000088B4` — get the unused array elided. **Practical rule:** the bare-char-array pad reliably works only when the gap is large (≥0x40-ish) AND the function already has multiple spill slots. For small (8-byte) gaps in low-spill functions, no clean C lever for frame growth has been found; the path forward is regalloc grinding (to flip ptr-holding register from `a2` to `v1` in 88B4's case) or post-cc INSN_PATCH.

**Origin:** 2026-04-18 game_libs batch. 24 size-0x3C "external call + store result" wrappers — a bare `int scratch` put the local at sp+0x1C; single `int pad` declared before scratch fixed all 24 at once.

---

---

<a id="feedback-ido-long-long-v1-move"></a>
## `or v0, v1, zero` after jal = wrapper returning low word of callee's 64-bit return

_In 1080 USO wrappers, the target `or v0, v1, zero` right before `jr ra` means the callee returns a `long long` and the wrapper returns only the low 32 bits. IDO puts the low word in $v1 (big-endian MIPS O32 puts high in $v0, low in $v1), and `(int)r` casts move it back to $v0 via `or v0, v1, zero`._

**Rule:** When a USO chain wrapper ends with:

```
lw    $ra, 0x14($sp)
addiu $sp, $sp, 0x18
or    $v0, $v1, $zero    ; <-- move v1 to v0
jr    $ra
 nop
```

…the wrapper is returning the LOW 32 bits of a `long long` return value from the callee:

```c
long long callee(int a0);
int wrapper(int a0) {
    long long r = callee(a0);
    return (int)r;   // truncates to low word, which on big-endian MIPS is $v1 → moved to $v0
}
```

**Why:** MIPS O32 returns 64-bit values in `($v0, $v1)` as (high, low). `(int)long_long` on big-endian takes the low 32 bits (which is the little-end of the bit layout for integer purposes) → $v1. IDO emits the explicit move to relocate it to the single return register $v0.

**Related caveat — the a0 spill in the jal delay slot:** the target for `gl_func_00035164` also had `sw $a0, 0x18($sp)` in the jal delay slot (saving a0 to caller's arg save area). I could NOT reproduce this spill from C declarations alone — varargs on callee didn't trigger it, neither did varargs on caller. 93 % is as close as you get without grinding. Wrap NON_MATCHING at that point.

**Origin:** 2026-04-19 game_libs gl_func_00035164. `or v0, v1, zero` is the signal — recognize it immediately as 64-bit-return-truncation idiom. Matched instruction count, structure, register move exactly; only the a0 spill in delay slot differs.

---

---

<a id="feedback-ido-mfc1-from-c"></a>
## Target asm with `mfc1 $aN, $f12` (float-bits-to-int-reg) is hard to reproduce from IDO C

_When the target has a single `mfc1 aN, $f12` instruction converting a float arg's bits to an int register for passing as arg, IDO's C compiler emits a stack round-trip (swc1 + lw) instead — at least 14 C variants tried (union, cast, K&R, register-asm, inline asm, double type, varargs) all produced the round-trip or worse. No known C expression forces `mfc1` directly._

**Rule:** If the target asm has `mfc1 $aN, $f12` (or `fa0`) to pass a float arg's bits as an int to the next callee, **give up and keep it as INCLUDE_ASM**. IDO's C compiler does not emit single-instruction mfc1 for float→int bit reinterpretation; it always goes through a stack slot.

**Target asm pattern:**
```
swc1/mfc1 — either works in the ROM, but MFC1 is what matters here:
  ...
  mfc1 a1, $f12
  jal callee
  ...
```

This means: caller expects callee to accept `(int arg0, int arg1_float_bits)` where arg1 contains the float's bit pattern.

**14 C variants tried (2026-04-19 on gl_func_0002DF68):**

1. `gl_func_00000000(..., *(int*)&a2);` — 95% (sw a1 stack roundtrip)
2. `union { float f; int i; } u; u.f = a2; ... u.i` — 78%
3. `int bits = *(int*)&a2; ... bits` — 95%
4. `__asm__("mfc1 %0, $f12" : "=r"(bits))` — 95% (asm-processor strips or ignores)
5. `void f(int a0, double a2) { ... *(int*)&a2 ... }` — 68%
6. `register int bits asm("$5"); register float a2r asm("$f12") = a2; __asm__("mfc1 %0, %1" : "=r"(bits) : "f"(a2r))` — 68%
7. `register int bits; __asm__("mfc1 %0, $f12" : "=r"(bits) : "f"(a2))` — 95%
8. Back to variant 1 — 95%
9. `void f(float a0, int a2)` (swap arg order) — 57%
10. Split args into locals — 95%
11. K&R style declaration — 24% (arg promotion breaks structure)
12. `void f(int a0, float a1, float a2)` (3-arg to shift positions) — 78%
13. `void f(float a2)` (single float arg) — 72%
14. Union typedef with assignment — failed (mtc1 at wrong position, sw a1 + stack roundtrip)

**All variants produce `swc1 f12, OFF(sp); lw aN, OFF(sp)` instead of `mfc1 aN, $f12`.**

**Why it's non-obvious:** MIPS has a single-instruction FP-to-int-register move (`mfc1`). From C, the canonical way is `*(int*)&floatvar`, but IDO's compiler implements this via stack spill + load rather than direct mfc1. This is consistent across arg/local/union/cast variants and appears to be a fundamental IDO codegen limitation for this specific operation.

**How to apply:**
- If you see a single `mfc1 $aN, $f12` (or similar) in the target AND your best C attempt gets 95% with a `swc1 + lw` round-trip instead: **stop and mark the function as INCLUDE_ASM**. Don't waste more time on variants.
- Exception: if the mfc1 is followed by more complex ops (e.g., bit manipulation then re-move-back-to-fp), a multi-step sequence might match. But for a simple pass-through to a call, just INCLUDE_ASM.

**Workaround attempts that might still be worth trying on other functions:**
- Maybe a per-file `-O1` or `-O0` override emits mfc1 directly
- `decomp-permuter` with PERM_GENERAL over the bits-access expression
- Writing an inline-asm stub at file scope (not inside the function) that IDO's asm-processor honors

**Origin:** 2026-04-19 game_libs gl_func_0002DF68. 14 variants tried over a few decomp loop ticks; best was 95% with scheduler diff. Reverted to INCLUDE_ASM.

**Inverse case IS reproducible (`mtc1 $aN, $f12` for incoming float arg):** the OPPOSITE direction — when the callee receives a float in an int-position register `$aN` and needs to use it as a float — works trivially in IDO. Just type the parameter as `float` in the C signature:

```c
void func_000144B4(int *a0, int a1, int a2, float a3, float arg5) {
    *(float*)((char*)a0 + 0x88) = a3;   // emits: mtc1 $a3, $f12; swc1 $f12, 0x88($a0)
    *(float*)((char*)a0 + 0x8C) = arg5; // emits: lwc1 $f16, 0x10($sp); swc1 ...
}
```

The float arg lands in `$a3` because positional MIPS O32 ABI puts arg #4 there regardless of declared type; IDO emits `mtc1 a3, f12` to move it into an FP register for the swc1 store. Matched first try at func_000144B4 in bootup_uso. So the asymmetry is: **incoming float → int-reg works (mtc1 from C)**, but **outgoing float-bits → int-reg arg does NOT (mfc1 from C is unreproducible)**.

---

---

<a id="feedback-ido-mix-named-and-inline-per-usesite"></a>
## Mix named-local and inlined access in the SAME function to get per-use-site reg allocation (named → $v, inline → $t)

_When a function has the same expression (e.g. `(int*)a0[OFF/4]`) used both in pre-call argument setup AND in post-call follow-up stores, the natural choice (one named local) caps below 100% because IDO reuses the local's $v reg in the post-call chains. Mix instead: name it for the pre-call use only, inline EACH post-call access — pre-call gets stable $v, each post-call chain gets a fresh $tN._

**Background:** `feedback_ido_v0_reuse_via_locals.md` says "named locals → $v0/$v1, inlined exprs → $t-regs." That's true at the function level. The non-obvious extension: you can apply this PER USE SITE within one function.

**Pattern (verified 2026-05-02 on `timproc_uso_b5_func_0000B9F0`, 28 insns):**

Function shape: load `p = a0->FOO`, use `p->A` and `p->B` as call args, then 3 follow-up stores each chained through `a0->FOO->...`.

| C variant | match% | Why |
|-----------|--------|-----|
| All named: `int *p = a0->FOO; ... ; p = a0->FOO; *(...) = ...;` ×3 | 97.14% | IDO assigns p to $v1, reuses it (or v0 derived from it) for all 3 chains — target wants fresh $t8/$t9/$tA/$tB/$tC/$tD per chain |
| **Mixed: `int *p = a0->FOO;` for pre-call only, INLINE `(int*)a0[FOO/4]` in each post-call chain** | **100%** | Pre-call uses share $v1 (compactly setup args 1+2); each post-call chain gets fresh $tN pair (no v-reg involvement) |
| All inlined (no named local): | regresses | Pre-call would shuffle for arg setup |

**Concrete code shape:**
```c
void f(int *a0) {
    int *p = (int*)a0[OFF/4];                     /* named: p in $v1 */
    gl_func(p->A, p->B, ...);                     /* uses $v1 cleanly */
    *(int*)((char*)*(int*)((char*)(int*)a0[OFF/4] + N1) + N2) = X;  /* fully inlined → $t8/$t9 */
    *(int*)((char*)*(int*)((char*)(int*)a0[OFF/4] + N1) + N3) = Y;  /* fully inlined → $tA/$tB */
    *(int*)((char*)(int*)a0[OFF/4] + N4) = Z;                       /* fully inlined → $tC */
}
```

The trick: re-typing `(int*)a0[OFF/4]` inline each time prevents IDO from CSEing back to the named `p`. IDO's optimizer DOESN'T realize `(int*)a0[OFF/4]` is the same as `p` because the cast happens at each use site — each is a fresh expression in IDO's view.

**When to use:**
- Function has 1 pre-call use of `p` (or N tightly-clustered uses) AND M scattered post-call uses
- Target asm shows fresh $t-reg pairs per post-call chain (not $v reuse)
- Naming `p` everywhere caps in the 95-99% range

**When NOT to use:**
- Function uses `p` heavily in a single linear sequence (named local is right)
- Target uses $v reuse intentionally (asm shows `lw v0, X; ... lw t, Y(v0); ... lw t, Z(v0)` chains)

**Related:**
- `feedback_ido_v0_reuse_via_locals.md` — base rule (named → $v, inline → $t)
- `feedback_ido_inline_deref_v0.md` — inline nested derefs to flip allocation

---

---

<a id="feedback-ido-named-base-forces-addiu-split"></a>
## Named intermediate `char *t = base + OFFSET` forces IDO to split `lw/sw` addressing into `lw + addiu + sw(N)` even when the offset fits in 16 bits

_When target has `lw t, 0x30(a0); addiu t, t, 0x758; swc1 fN, 0x10(t)` but inline-deref C generates `lw t, 0x30(a0); swc1 fN, 0x768(t)` (merged offset), use a named local `char *t = ... + 0x758;` followed by `*(float*)(t + 0x10) = ...;` to force IDO to emit the intermediate addiu._

**Problem:** your 3-insn-per-iteration output vs target's 4-insn-per-iteration. Function size differs.

**Pattern in target asm:**
```
lw    v0, 0x30(a0)
lwc1  f4, 0x4C8(a0)
addiu v0, v0, 0x758      ; ← this intermediate base-adjust
swc1  f4, 0x10(v0)        ; ← store with +0x10 offset from adjusted base
```

**Nested inline deref (WRONG shape):**
```c
*(float*)(*(char**)(a0 + 0x30) + 0x768) = *(float*)(a0 + 0x4C8);
```
Produces:
```
lwc1  f4, 0x4C8(a0)
lw    t6, 0x30(a0)
swc1  f4, 0x768(t6)       ; full offset baked in, no addiu
```

**Named intermediate (MATCHES):**
```c
char *t = *(char**)(a0 + 0x30) + 0x758;
*(float*)(t + 0x10) = *(float*)(a0 + 0x4C8);
```
Produces:
```
lw    v0, 0x30(a0)
lwc1  f4, 0x4C8(a0)
addiu v0, v0, 0x758
swc1  f4, 0x10(v0)
```

**Why it works:** IDO's instruction selector treats the named `t` assignment as a required intermediate. The subsequent `t + 0x10` store uses whatever offset you wrote, not a fused one. With the inline version, IDO is free to combine the two `+ 0x758` and `+ 0x10` into a single immediate (0x768) and use a single sw.

**When to apply:**
- Target has `lw/lui + addiu + sw/lw` triples where the `addiu` has a 16-bit offset
- Your output has `lw/lui + sw/lw` pairs with a combined immediate offset
- Size of built function is smaller than target

**Related:** this is a more specific case of "inline vs named-local controls instruction shape". Similar pattern for v0 register usage in `feedback_ido_v0_reuse_via_locals.md` and inline-deref-$v0 in `feedback_ido_inline_deref_v0.md`. This memo is specifically for the ADDRESS-COMPUTATION split (base + const-offset + field-offset).

**IMPORTANT refinement (2026-04-20, game_uso_func_00007448):** the trigger is that the BASE POINTER is obtained **inline via `*(char**)(a0 + 0x30)`**, not from a cached local. If `table` is a pre-existing local (e.g. `char *table = *(char**)(a0 + 0x30);` at top of function) and you then write `char *t = table + 0x758; *(f32*)(t + 0x10) = ...;`, IDO **still folds the offset** and emits a single `lwc1 fN, 0x768(table_reg)` — because `t` is trivially dead after its one use and IDO's optimizer collapses it.

So the full rule: `*(char**)(a0 + 0x30) + OFFSET` (inline deref + add) produces the split. `table + OFFSET` (where table is cached) produces the merge. This is why 74D8 reloads a0[0x30] per-iteration in its matched C — that reload is what triggers the split, not the named `t` variable itself.

**When you need the split without reloading the base** (rare — 7448's inbound copies do this): not currently known to be achievable from C. The target function likely used a struct-field access in source that forced an intermediate address computation the optimizer couldn't fold. Leave NM-wrap.

**Origin:** 2026-04-20, agent-a, game_uso_func_000074D8 (mirror 4 floats back to table, 17 insns exact). Refined 2026-04-20 via 7448 (refused to split despite named-base pattern; cached-table was the culprit).

**2026-05-06 extension (compound vs explicit op):** the same trick works
for integer RMW. `*(int*)(*(char**)(a0 + 0xB4) + 0xA58) ^= 0x40;`
(compound `^=`) keeps the +0xA58 folded into the sw imm. Rewriting as
`int *p = (int*)(*(char**)(a0 + 0xB4) + 0xA58); *p = *p ^ 0x40;`
(named pointer + explicit `= *p ^ k`) emits the addiu split. Compound-assign
forms tend to encourage the optimizer to fuse offsets; explicit `*p = *p OP k`
with a named base pointer keeps them split. Verified on
game_uso_func_0000D6E4 (93.73% → 100%, the missing addiu was the only
size delta).

**2026-05-06 NEGATIVE-RESULT counter-case** (gl_func_0002D710): the
named-pointer trick does NOT apply when the cap is **lui PLACEMENT**, not
sw immediate folding. Symptom: target has the `lui rN, %hi(SYM)` sitting
INLINE between prologue and sw (e.g. `addiu sp,...; lui at,0; ...; sw a0,0(at)`
with $at chosen as a fresh temporary). C-emit instead materializes
`&SYM` into a saved-class register (`$v0`) UPFRONT via `lui v0; addiu v0`
BEFORE the prologue, producing a 2-insn prefix (the prologue-stolen-
predecessor pattern). Both compound `D_NNN = val` and named `int *p = &SYM; *p = val`
produce the same 2-insn upfront materialization. The trick only helps
when the issue is "sw imm folded vs split" (single store with an offset);
when the issue is "where lui sits in the stream", neither form moves it.
Recipe in this case: PROLOGUE_STEALS=8 alone is insufficient because the
inner body's register allocation also diverges (got uses $v0+spill where
target uses $at+inline). Falls back to NM wrap.

---

---

<a id="feedback-ido-named-char-v0-vs-t6"></a>
## Named `unsigned char c = *p;` forces $v0; inline `*p` in the comparison keeps the load in $t6

_When the target has `lbu $t6, 0($sN)` for a char loaded from memory and compared immediately, declaring it as a local (`unsigned char c = *p`) forces IDO to allocate $v0 for the load instead. Inlining the deref (`if (*p != 0x20)`) matches target's $t6 behavior._

**Rule:** For an 8-bit memory load (`lbu`) that feeds directly into a comparison, don't name the intermediate. Inline the deref.

```c
/* Target has `lbu $t6, 0($s1)` followed by `beql $s4, $t6, ...` — $t6 holds the char */

/* WRONG — IDO allocates $v0 for c, emits `lbu $v0, 0($s1)` */
unsigned char c = *p;
if (c != 0x20) { ... } else { ... }

/* RIGHT — inline *p in the condition, IDO picks $t6 */
if (*p != 0x20) { ... } else { ... }
```

**Why:** IDO's register allocator reserves `$v0` for fresh temporary results when the value flows into an expression that may itself produce a return-like intermediate. A named local of narrow type gets `$v0` by default. Inlining the deref makes the loaded byte an unnamed intermediate that IDO schedules into `$t6` (the default `$t`-class register for intermediate chars).

This is the **narrow-type reverse** of `feedback_ido_v0_reuse_via_locals.md` — that memo says "name the local to force $v0". But for a CHAR load feeding a compare, the default allocation is ALREADY $v0 for the named local, so naming doesn't "force" anything useful — it keeps the load in $v0 when target wants $t6. Inlining flips it.

Related knobs from the same function grind (gui_func_00001514):
- **Decl order = $s-register order:** `unsigned char *p = a1; unsigned int i = 0;` gave $s1=p, $s2=i. Reversing put p in $s2, i in $s1 — target has the former.
- **`unsigned int` loop counter for `sltu`:** `int i; while (i < func())` → `slt`. `unsigned int i; while (i < (unsigned)func())` → `sltu`. If target has `sltu`, must cast both sides.
- **Arm-swap for beql vs bnel:** IDO picks branch-likely based on which arm is the "taken" one. `if (c != 0x20) X else Y` → `bnel $s4, $tN, Xarm`. `if (c == 0x20) Y else X` → `beql $s4, $tN, Yarm`. Read target's branch mnemonic to pick.

**How to apply:** Before settling for a 90-99% NM wrap, run through these 4 IDO-register-allocation knobs in order. They're each cheap (one-line rewrite) and each can be the last thing between NM and 100%.

**Origin:** 2026-04-20 agent-a, gui_func_00001514 (text-width accumulator). Went from NM wrap → 89% → 81% → 19% → 0% diffs via this 4-step sequence in one tick. Commit ff54d31.

**Generalization (2026-05-08):** the same `inline-vs-named` flip applies to INT counts/limits, not just char/byte loads. When a target's loop has `lw vN, OFF(base)` for the FIRST load of a count/limit at function entry AND that count is ALSO the loop-bound comparison RHS, naming the count as a local (`int n = base[N]; if (n == 0) return; ... while (j < n)`) forces IDO to allocate `$v0` for the named local — pushing all subsequent loads up by one register. Inlining the count access at each comparison (`if (base[N] == 0) return; ... while (j < base[N])`) frees `$v0` for the natural first load and unblocks the next register downstream. Verified 2026-05-08 on `gl_func_000687B8` (51-insn nested-loop vtable dispatch): inlining `n_outer`/`n_inner` named locals + `unsigned` for loop counters lifted NM 88.82% → 97.06%. Both flavors of this knob (char + int) come down to the same rule: for loads that feed directly into a compare/branch with no algebraic transformation, inline the deref.

---

---

<a id="feedback-ido-named-float-local-globally-shifts-fpu-schedule"></a>
## A SINGLE named float local in tight FPU code globally restructures IDO's entire FPU schedule — not just the immediate computation

_In tightly-scheduled FPU code (dot products, vector reductions), introducing ANY named `float` local — even just to name an intermediate sum — shifts IDO's FPU register allocation and instruction order across the WHOLE function, not just the named expression. The companion memo `feedback_ido_named_float_locals_enable_load_batching.md` documents the BENEFICIAL direction; this memo documents the HARMFUL direction. Default to all-inline expressions in FPU code unless you can confirm the named-local form matches._

**The phenomenon**: a 4-element dot product like
`return a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + b[3]*a[3];`
matches at 99.38 % (1-insn cap on final add.s operand order). Naming
the dot3 accumulator:
```c
float dot3 = a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
return dot3 + b[3]*a[3];
```
DROPS to ~50 %. The named `dot3` doesn't just affect the final add —
it shifts mul.s operand order across all 4 muls AND changes the final-add
register choice from $f8/$f10 to $f6/$f2.

**Verified 2026-05-03 on game_uso_func_000000A0** (4-element dot product).

**Why it happens**: IDO's FPU register allocator picks register numbers
based on live-range analysis. A named local creates a long live range
for the partial sum, which displaces the temp registers IDO would
otherwise use for ongoing mul.s operands. The change cascades through
the whole function because every FPU op chooses fs/ft from the
currently-allocated pool.

**Companion to** `feedback_ido_named_float_locals_enable_load_batching.md`:
- That memo: naming float locals can FORCE load-batching when you
  want all loads before all stores (int reader pattern).
- This memo: naming float locals can BREAK an existing tight-scheduled
  FPU computation by globally shifting register allocation.

The SAME C-level lever (named float local vs inline expression) has
opposite effects depending on the function shape. **Default for FPU
reduction code: all-inline.** Default for load-then-store buffer code:
named locals.

**Detection**: if your IDO C-emit shows mul.s/add.s with TOTALLY
different fs/ft ordering than target across multiple instructions
(not just one), check whether you have a named float local that
should be inlined.

**FRAME-SIZE variant (verified 2026-05-29, gl_func_0000E84C):** a named float
local can reserve a DEAD stack home slot that bloats the frame, even when the
value otherwise lives entirely in an FP reg. There, two `float f38, f3C;` locals
(each read from a struct field, passed to a callback) added a dead 8-byte stack
slot → frame `-56` vs target `-48`, the ONLY residual at 99.84%. INLINING the
field reads at the call site (`f(p, *(float*)&s->a, *(float*)&s->b, *(float*)&s->a, *(float*)&s->b)`)
dropped the dead slot AND IDO still CSE'd the repeated reads into single f0/f2
loads → frame `-48`, byte-exact. So when a near-miss bottoms out on a small
frame-size delta and the function names float temps, try inlining them — the
CSE keeps the loads minimal while shedding the dead home slot.

**Related**:
- `feedback_ido_fpu_reduction_operand_order.md` — the underlying
  1-insn cap on FPU reductions.
- `feedback_ido_v0_reuse_via_locals.md` — the analogous int-side rule
  (named local vs inline → $v vs $t register).

---

---

<a id="feedback-ido-named-float-locals-enable-load-batching"></a>
## IDO -O2 needs named float locals to load-batch all loads before stores; inlined float derefs interleave load/store

_When asm shows `lwc1 f14; lwc1 f12; lwc1 f2; lwc1 f0; swc1 f14; swc1 f12; swc1 f2; swc1 f0` (4 loads then 4 stores), the C source MUST have 4 named float locals. Inlining the derefs (`*(v + off) = *(a0 + off)`) makes IDO emit one-load-one-store interleaved._

**Verified 2026-05-02 on `timproc_uso_b5_func_0000CE6C`.**

This is the OPPOSITE of `feedback_ido_inline_deref_v0.md` (which says inline
nested int derefs to keep them in $v0 vs forcing $t-reg via local naming).
For floats, the story flips:

**Target asm pattern:**
```
lw   v0, 0x2B8(a0)
lwc1 f14, 0x294(a0)
lwc1 f12, 0x264(a0)
lwc1 f2,  0x260(a0)
lwc1 f0,  0x25C(a0)
swc1 f14, 0x118(v0)
swc1 f12, 0x10C(v0)
swc1 f2,  0x114(v0)
jal  ...
swc1 f0,  0x110(v0)   ; delay
```
All 4 loads, then all 4 stores (last in jal delay).

**C with named locals — emits the all-loads-first pattern:**
```c
char *v;
float a, b, c, d;
v = *(char**)(a0 + 0x2B8);
a = *(float*)(a0 + 0x294);
b = *(float*)(a0 + 0x264);
c = *(float*)(a0 + 0x260);
d = *(float*)(a0 + 0x25C);
*(float*)(v + 0x118) = a;   // store batch starts here
*(float*)(v + 0x10C) = b;
*(float*)(v + 0x114) = c;
*(float*)(v + 0x110) = d;
gl_func_00000000();
```
Result: 97.2% match (only $f-register-renumber diff remains).

**C with inline derefs — REGRESSES:**
```c
char *v = *(char**)(a0 + 0x2B8);
*(float*)(v + 0x10C) = *(float*)(a0 + 0x264);  // load+store inline
*(float*)(v + 0x110) = *(float*)(a0 + 0x25C);
*(float*)(v + 0x114) = *(float*)(a0 + 0x260);
*(float*)(v + 0x118) = *(float*)(a0 + 0x294);
gl_func_00000000();
```
Result: emits `lwc1 f4; swc1 f4; lwc1 f6; swc1 f6; ...` — one-load-one-
store interleaved, loses the all-loads-first pattern entirely.

**Why:** IDO -O2's float scheduler treats each named-local assignment as
"load now, store later" — so it pools all 4 loads upfront. Inline derefs
collapse to single use-site expressions, which IDO schedules per-statement
(one round-trip each).

**How to apply:**

When the target asm has N float loads followed by N float stores (N=2-6
typical for Vec3/Vec4/Mat copies), declare N named float locals at the
top of the C body. Don't try to inline.

For mixed types: name the FLOATS, inline the int/pointer derefs (per the
opposite-direction `feedback_ido_inline_deref_v0.md`).

**Caveat:** the float-register renumber ($f0/$f2/$f12/$f14 vs target's
order) is a separate cap that decl-order can't flip — IDO assigns
declaration-order to f0/f2/f12/f14 and it's not C-controllable.

**Related:**
- `feedback_ido_inline_deref_v0.md` — opposite direction for int derefs
- `feedback_ido_no_gcc_register_asm.md` — `register T x asm("$fN")` rejected
- `feedback_function_trailing_nop_padding.md` — pad-sidecar for trailing nops

---

---

<a id="feedback-ido-named-local-reuse-across-alloc-blocks"></a>
## reusing one named local across sequential alloc-then-populate blocks regresses IDO match

_When a function has multiple `out = alloc(N); if (out!=0) write(out, ...)` blocks back-to-back, sharing one named `out` local across them confuses IDO's dataflow tracking and tanks the match. Each alloc result needs its own named local._

When a function (e.g. game_uso dispatcher) has 3+ sequential blocks of
the alloc-or-passthrough ternary pattern:

```c
out = ptr1 ? ptr1 : alloc(N);
if (out != 0) { writes... }
out = ptr2 ? ptr2 : alloc(N);   // SAME named local
if (out != 0) { writes... }
out = ptr3 ? ptr3 : alloc(N);   // SAME named local
...
```

IDO conflates the dataflow on `out` across blocks. Adding a SECOND
`if (out != 0) { writes }` block to a partial-decode function that
previously had only one such block can REGRESS NM-build% by 5-10
percentage points (observed 2026-05-03 on `game_uso_func_00009B88`:
17.92% → 8.46% from one extra block).

**Why:** IDO's register allocator picks allocations based on the
first-encountered pseudo for each named local. Multiple writes through
the same local create a single allocno with extended live range,
forcing IDO to keep `out` in an $s-reg across all the `jal alloc`
calls, displacing the t-reg/v-reg allocations target uses for the
just-returned alloc result.

**How to apply:**
- For multi-alloc dispatcher functions, give each alloc result its
  own named local: `out1`, `out2`, `out3`, ... — even if semantically
  they're "the same role" (output buffer).
- Or write each alloc-write block as its own scope:
  `{ int *out = alloc(N); if (out) writes; }` — block-scoped locals
  get separate pseudos.
- For partial-decode multi-tick passes on big spine functions, decode
  ONE alloc block at a time and verify NM% doesn't regress before
  moving to the next. If a new block regresses, immediately reach for
  separate-named-locals before assuming logic error.

---

---

<a id="feedback-ido-narrow-arg-promotion"></a>
## IDO emits extra `andi`/`sll+sra` for narrow (char/short) function parameters

_Declaring a function arg as `char` or `short` makes IDO insert byte/halfword promotion at the prologue that breaks matching. Use `int` arg + cast at the store site._

**Rule:** Never declare function parameters as `char` or `short` (signed or unsigned) when trying to match IDO codegen for a byte/halfword store. Use `int a1` and cast at the store: `((char*)p)[N] = (char)a1;`.

**Why:** IDO 7.1 treats `char a1`/`short a1` as "narrow arg that must be normalized" — it inserts:
- `andi a1, a1, 0xff` for `unsigned char` or `char`
- `sll a1, a1, 16; sra a1, a1, 16` for `short`

right after the prologue, regardless of whether the value is actually used as wide. It also spills the arg to stack (`sw a1, 4(sp)` etc.) as part of arg-slot bookkeeping. These extras are pure noise when the target is just `sb a1, N(p)` or `sh a1, N(p)` — the target trusts the caller to pass a byte-valued int in the low 8 bits.

**Target asm** (what the original produces for `*ptr_u8 = arg1`):
```
sb $a1, N($v0)
```

**Broken C** (`void f(int **a0, char a1)`) compiles to:
```
sw $a1, 4(sp)           <-- extra
lw $v0, 0($a0)
andi $a1, $a1, 0xff     <-- extra (byte promotion)
beqz $v0, .L
nop
sb $a1, N($v0)
```

**Matching C** (`void f(int **a0, int a1)` + `(char)a1` at the store):
```
lw $v0, 0($a0)
beqz $v0, .L
nop
sb $a1, N($v0)          <-- the `int → char` cast doesn't emit an andi;
                            IDO uses $a1's low 8 bits directly for sb
```

**How to apply:**
- Every decomp candidate where the asm stores a subword (sb, sh) from an arg register, and has no `andi`/`sll+sra` prologue: use `int` arg type, cast at the store.
- Same applies to return-sized narrow types — `char func(...)` will get a return-value normalization. Use `int` returns unless the asm has the normalization.
- Conversely, if the target DOES have `andi $aN, $aN, 0xff` or `sll+sra` right after the prologue, narrow the source: **use `arg & 0xFF` (bitwise mask in the call expression) NOT `(unsigned char)arg` cast.** Both narrow semantically, but the cast emits `lbu $aN, off+3(sp)` (read low byte from already-spilled slot) when the arg has been spilled to caller-home; the explicit `& 0xFF` emits `andi $aN, $aN, 0xff` (in-register mask). Verified 2026-05-13 on `gl_func_0002DD90`: `(unsigned char)a0` produced `lbu`, `a0 & 0xFF` produced `andi` → byte-exact match.

**Origin:** hit 2026-04-18 on bootup_uso func_00000A50 and func_00000B14 (both `if (*a0) ((char*)*a0)[N] = a1;`). Target was 6 insts with a bare `sb`; `char a1` gave 8 insts (+andi +spill sw), `int a1 + (char)a1` matched exactly.

**Forwarding variant (2026-04-19 game_libs gl_func_000005A4):** when narrow args are FORWARDED to another callee (no local byte store), the target pattern is `sw $aN, off(sp)` (save word) followed by `lbu $rT, off+3(sp)` (read low byte of word — big-endian). This is exactly what `char`/`short` args produce when they survive a live range across a jal. In this case, DECLARE the args as `char`/`unsigned char`:

```c
void gl_func_000005A4(char *a0, char a1, char a2, char a3) {
    gl_func_00000000(a0 + 0xE4, &gl_ref_X, a1, a2, a3);
}
```

matches the `sw $aN, off(sp); lbu $rT, off+3(sp)` pattern for each narrow arg that's passed forward. Check the target: if you see `sw` + `lbu off+3` → narrow arg; if you see `andi $aN, 0xff` → also narrow but different codegen. If neither, use `int` + cast.

**Generalizes to LOCAL counters too:** `short i; for (i=0; i!=N; i++)` produces a redundant `sll i, i, 16; sra i, i, 16` pair after EACH `i++` — IDO normalizes the value back to short width after every increment. Use `int i` + cast at any narrow-store site. Verified 2026-05-08 on `game_libs_func_00031580` (loop counter, +11.76pp from this single-line type change).

---

---

<a id="feedback-ido-no-asm-barrier"></a>
## IDO doesn't accept bare `__asm__("")` as a scheduling barrier

_The GCC trick of `__asm__("")` to force an instruction ordering barrier is NOT supported by IDO 7.1. IDO's cfe does not recognize the GCC-style `__asm__` keyword; it treats `__asm__(...)` as a call to an undefined function, which links with `undefined reference to __asm__`. No equivalent barrier exists in IDO C._

**Rule:** In IDO-based projects (1080 Snowboarding game_libs, kernel, bootup_uso, etc.), do NOT write:

```c
int tmp = a1;
__asm__("");           /* FAILS: ld: undefined reference to `__asm__' */
result = tmp << 24;
```

The compile step (cfe) silently accepts it as a function call; the linker then fails. Even if you workaround-declare it as `extern void __asm__(char*);`, the call emits a real `jal` that corrupts delay-slot scheduling.

**What GCC (Glover) supports:** `__asm__ volatile("")` as an empty-inline-asm scheduling barrier — see the /decompile skill's GCC section. That trick does NOT transfer to IDO.

**Alternative barrier strategies in IDO:**

1. **Structural**: rewrite the C so the intermediate has a dependency the optimizer can't collapse (e.g., an OR with 0, a store/load pair, a struct field access).
2. **`volatile` on the variable**: `volatile int tmp = a1;` forces a stack spill + reload, which changes instruction ordering. Heavier than a barrier — actually adds `sw/lw` pair.
3. **Dummy struct/union**: occasionally prevents DCE without emitting instructions, but hit-or-miss.
4. **Live through a function call**: if the barrier is to force a register copy BEFORE a sll/shl, put the shift inside a wrapper that the compiler can't see through. Overkill for most cases.
5. **Accept NON_MATCHING**: if you needed the barrier specifically to match `or a2, a1, zero` + `sll from a2`, IDO won't emit it without structural reasons. Wrap as NON_MATCHING if ≥ 80 %.

**How to apply:**

- Never copy a `__asm__("")` barrier from a GCC/Glover solution into an IDO project.
- If you see `undefined reference to __asm__` at link time, grep for `__asm__` in the .c and remove.

**Worse failure mode under asm-processor (1080 pipeline)**: with asm-processor enabled (1080 kernel/game_libs/all USOs), `__asm__("");` does NOT trigger a link error. asm-processor silently treats `__asm__` as a real function symbol, emits a `jal 0 <__asm__>` (relocation against an undefined target), grows the frame ~0x30 bytes for prologue/epilogue, and pivots register allocation through a save/restore. The build SUCCEEDS but produces a function-call wrapping the barrier. Symptoms in the .c.o: function starts with `addiu sp,sp,-0x30` (or similar enlarged frame) instead of the natural prologue, plus a `jal 0` to symbol `__asm__` somewhere in the body. **If you see this after inserting `__asm__("")`, remove it immediately** — there's no asm-processor-safe barrier equivalent in IDO. Confirmed 2026-05-08 on `func_800000B0` retest.

**Related:** `feedback_ido_no_gcc_register_asm.md` (IDO rejects `register T var asm("$N")`). `feedback_ido_register.md` (plain `register` keyword IS respected as an allocation hint). These three cover the main GCC-style pinning/barrier tricks that don't work in IDO.

**Origin:** 2026-04-19 game_libs gl_func_00026C6C. Tried `__asm__("")` to force a register copy for the `or a2, a1, zero` pattern — got `undefined reference to __asm__` at link time. Wrapped as NON_MATCHING (91 %). Updated 2026-05-08 with asm-processor silent-failure mode discovered during func_800000B0 cap retest.

---

---

<a id="feedback-ido-no-cse-arg-immediates"></a>
## IDO does not CSE repeated immediate args at -O2

_Passing the same literal constant (e.g. 1) to multiple stack-arg slots and a register-arg in one call materializes a fresh `addiu rN, zero, K` per slot — no shared register_

When you write `f(a0, x, 4, 1, 1, 1)` (one arg in a3 plus two in stack slots, all the same literal), IDO -O2 does NOT reuse a single temp register for the repeated `1`. Each destination gets its own `addiu rN, zero, 1`:

```
addiu t6, zero, 1   ;  for stack[0x10]
addiu t7, zero, 1   ;  for stack[0x14]
sw    t7, 0x14(sp)
sw    t6, 0x10(sp)
addiu a2, zero, 4   ;  arg2
jal   <callee>
addiu a3, zero, 1   ;  arg3 (delay slot)
```

**Why:** IDO emits separate immediate-load instructions per arg slot during the calling-convention lowering. The scheduler doesn't lift one register copy and reuse it across slots even when constants are equal. (Plain GCC 2.7.2 would CSE this into one `li` and reuse via register copies.)

**How to apply:**

- Write the call exactly as the literals appear: `f(a, b, c, 1, 1, 1)` — no `int one = 1; f(a, b, c, one, one, one);` shortcut. The latter would CSE-via-local into a single register and produce a different instruction sequence.
- Don't be surprised by the count of `addiu rN, zero, 1` instructions in IDO output — count one per arg slot using that constant, not one total.
- This holds for stack-arg constants too: 4-arg + N-stack-arg calls with repeated literals expand cleanly without local helpers.

**Origin:** game_uso_func_00011428 (2026-04-19) — `f(a0, *(int*)(a0+0x74), 4, 1, 1, 1)` matched first try when written with three literal `1`s; using a local `int one = 1` would have shrunk to one `addiu` and broken the match.

---

---

<a id="feedback-ido-no-gcc-register-asm"></a>
## IDO cfe does not accept `register T var asm("$N")` (GCC extension)

_The `register T var asm("$register")` trick for forcing a specific MIPS register — which IS supported by KMC GCC 2.7.2 (Glover) — is NOT supported by IDO 7.1's cfe. Using it yields "Syntax Error" at the `asm` keyword. Do not copy this technique from Glover/GCC memory into IDO projects._

**Rule:** In 1080 Snowboarding / any IDO-based project, you CANNOT write:

```c
register char *p asm("$7") = incoming_arg;
```

IDO's cfe rejects it with:
```
cfe: Error: src/<file>.c, line N: Syntax Error
     register char *p asm("$7") = incoming_arg;
 --------------------^
```

**What IDO supports:** plain `register T var;` (without the `asm()` constraint). IDO treats `register` as a strong allocation HINT (e.g., to push a local into `$s0` for a libultra interrupt-disable function — see `feedback_ido_register.md`), but it does NOT let you pin a specific register number from C.

**What GCC 2.7.2 (Glover) supports:** the full `register T var asm("$N")` form — see the decompile skill's "Register swap" section which correctly calls it out in the GCC/Glover context. That guidance does NOT transfer to IDO.

**Why it's worth a memory:** I tried this on gl_func_000671E4 in game_libs to force an `or a3, a0, zero` copy. The first attempt reported 100 % via `objdiff-cli report generate` — but that was reading a **stale `.o`**. The next `make` failed with a syntax error. The stale-.o memory (`feedback_stale_o_masks_build_error.md`) catches the general case; this one catches the specific GCC-syntax-in-IDO confusion.

**How to apply:**

- When you want to force a specific MIPS register from IDO C, the options are:
  1. **Structural**: re-arrange the C so IDO naturally allocates the register you want (add a 4th parameter, introduce an intermediate variable, change the live ranges).
  2. **asm-processor GLOBAL_ASM**: write the single instruction as a hand-rolled `.s` fragment. Tricky for a partial-function override.
  3. **decomp-permuter**: random search for a matching C form.
  4. **NON_MATCHING wrap**: accept the partial and move on.

- **Never** use `register T var asm("$N")` in IDO C. If you see it in your working copy, revert.
- **Always** run `make RUN_CC_CHECK=0` and confirm it compiles clean (no `cfe: Error` in output) before trusting `objdiff-cli report generate` — the stale-.o memory covers the mechanism.

**Origin:** 2026-04-19 game_libs gl_func_000671E4. 92 % with plain C; tried `register asm("$7")` and the tool cache lied about a 100 % match. Real behavior is compile error. Reverted to NON_MATCHING wrap.

**Extension (2026-05-07, func_00005068 dead-spill cap):** IDO 7.1's CFE
also rejects PLAIN inline-asm blocks (`__asm__ volatile("sw $a1, 0x4($sp)")`)
— not just the `register asm("$N")` decl form. Same `cfe: Error: Syntax Error`
at the `__asm__` keyword. The full GCC inline-asm extension is unavailable
in IDO. If you need to inject a single instruction (e.g., an outgoing-arg
spill IDO's scheduler refuses to emit), the only paths are:
  - INSN_PATCH at a fixed offset (post-cc bytes-overwrite)
  - SUFFIX_BYTES / PREFIX_BYTES at function head/tail
  - asm-processor GLOBAL_ASM partial fragment (heavyweight)

Do not waste time trying `__asm__("nop")` as a scheduling barrier or
`__asm__ volatile(...)` for forced emit — the parser stops at the keyword.
GCC scheduling-barrier idioms borrowed from Glover/decompile-skill notes
do not apply.

---

---

<a id="feedback-ido-o0-empty-stub"></a>
## 0x14 stub `sw a0,0(sp); b +1; nop; jr ra; nop` = `void f(int a0) {}` compiled at -O0

_The IDO -O0 output for `void f(int a0) {}` is exactly 5 instructions — no prologue/epilogue, a0 spilled to caller's arg slot, a redundant forward-1 branch. Not reproducible from -O2 C_

**Rule:** Asm pattern

```
sw    $a0, 0($sp)         # to caller's arg slot
b     .+1                  # forward branch to next instruction (10000001)
nop                        # delay slot
jr    $ra
nop                        # delay slot
```

= empty-body function compiled at `-O0`:

```c
void f(int a0) {}
```

**Why:** IDO `-O0` emits the literal semantic template: arg spill → function body (empty → `b` to epilogue) → epilogue (`jr ra`). No optimization reorders or elides the spill or the branch. `-O1`/`-O2` both collapse the whole thing to `jr ra; sw a0, 0(sp)` (2 instructions in delay-slot-filled form).

Confirmed by testing all 4 opt levels on `void f(int a0) {}`:
- `-O0` → 5 instr matching the stub exactly
- `-O1`/`-O2`/`-O3` → 2 instr (`jr ra` + spill-in-delay-slot)

**How to apply:**

- If the .s shows the exact 5-instruction pattern above with size 0x14, the original C is `void f(int a0) {}` BUT the file needs to be compiled at `-O0`, not `-O2`.
- Matching requires a per-file Makefile override. In 1080 Snowboarding, bootup_uso has at least 5 such functions (0xF7F4, 0xF808, 0x1024C, 0x10310, 0x12DA4) scattered across the binary — each would need its own isolated `.c` file with `-O0` override and linker-script placement to land at the exact address.
- This is high-effort background work (5 matches for ~1 hour of file-splitting) — not worth grinding during call-graph-priority work. Leave as INCLUDE_ASM until a mass -O0 sweep is planned.

**Related:** `feedback_ido_unfilled_store_return.md` captures the separate issue of `sw; jr; nop` leaf setters (also not matchable from -O2 C but via a different mechanism — scheduler bias).

**Origin:** 2026-04-19 while scanning bootup_uso for small candidates. Empirically tested with `-O0`/`-O1`/`-O2`/`-O3` on IDO 7.1.

---

<a id="feedback-ido-o2-empty-void-emits-jr-ra-plus-nop"></a>
## `void f(void) {}` at IDO -O2 emits `jr ra; nop` (2 insns, 8 bytes) — matches alt-entry-stub bundles

_CLAUDE.md says "Empty functions should stay as INCLUDE_ASM — the compiler typically omits the delay slot nop". That's WRONG for `void f(void) {}` at IDO -O2: the emit is exactly 2 insns (`jr ra; nop`), 8 bytes, with the nop preserved in the delay slot. Match-rule: any 8-byte alt-entry stub whose .s contains only `jr ra; nop` decompiles directly to `void f(void) {}`._

**Verified 2026-05-08** on `game_libs_func_00024B8C` — a 2-insn alt-entry stub split off from `gl_func_00024B28`'s bundle. Empty `void` body produces exactly the target's 8 bytes.

**Distinction from feedback-ido-o0-empty-stub above:**
- `void f(int a0) {}` at -O0 → 5 insns (sw a0; b+1; nop; jr ra; nop) for the arg-spill version
- `void f(int a0) {}` at -O2 → 2 insns (`jr ra; sw a0, 0(sp)` with sw in delay slot) — collapsed
- `void f(void) {}` at -O2 → 2 insns (`jr ra; nop`) — no arg, so the delay slot stays nop

**When CLAUDE.md's "compiler omits the nop" claim applies:** non-`void` arg lists. For `void f(int)` the spill fills the delay slot, so the emit is 2 insns *with content*. For `void f(void)` there's nothing to spill, so the emit is `jr ra; nop`.

**Caveat:** the asm-processor wrapper sometimes adds a #pragma GLOBAL_ASM(_pad.s) after the function (when its size doesn't 16-byte-align with the next function's start). When present, that's separate alignment padding — not part of the 2-insn function body. Don't count `_pad.s` insns when matching.

**Related:** `feedback-ido-o0-empty-stub` (-O0 variant), `feedback_ido_unfilled_store_return.md` (sw-jr-nop leaf setters).

---

---

<a id="feedback-ido-o0-eq-operand-swap-for-load-order"></a>
## IDO -O0 swap == operands to control which side loads FIRST

_For an `if (LHS == RHS)` comparison in IDO -O0 mode, the side on the RIGHT of `==` is evaluated FIRST. To match a target asm whose memory load order is X-then-Y, write the comparison as `Y == X` (NOT `X == Y`). Verified 2026-05-03 on arcproc_uso_func_000000B4 (-O0): swapping `a0[1]+1 == a0[2]` to `a0[2] == a0[1]+1` flipped the load order from `lw a0[2]; lw a0[1]; addiu` to target's `lw a0[1]; addiu; lw a0[2]; bne`._

**The lever**: For `==` (and likely other comm. binops at -O0), IDO
evaluates the RHS first.

**Concrete case** — arcproc_uso_func_000000B4, -O0 mode, target asm:
```
lw t7, 4(t6)        ; load a0[1]
addiu t8, t7, 0x1   ; t8 = a0[1] + 1
lw t9, 8(t6)        ; load a0[2]
bne t8, t9, ...     ; compare
```

C variants tested:
- `if (a0[1] + 1 == a0[2])` → builds: `lw a0[2]; lw a0[1]; addiu; bne` (WRONG order)
- `if (a0[2] == a0[1] + 1)` → builds: `lw a0[1]; addiu; lw a0[2]; bne` (CORRECT order)

**Why it happens**: at -O0 IDO walks the AST in a specific order; for
binary `==`, it evaluates the right operand first into one set of regs,
then the left operand. So whichever side you want IDO to emit FIRST goes
on the RIGHT side of `==`.

**How to apply**: when target asm shows a specific load-then-compute order
that doesn't match your current C, try swapping the operands of `==`
(or `!=`, possibly `<`/`>`). It's a 1-character source change and costs
nothing.

**Why:** The general -O0 mantra is "IDO emits what you wrote in source
order" — but for binops the source-LHS is evaluated AFTER source-RHS.
This is opposite from naive intuition.

**How to apply:** When grinding -O0 wraps with a load-order mismatch in
the comparison expression: 1) confirm the diff IS in the comparison's
load order (not later in the function), 2) swap LHS/RHS of the `==`
operands, 3) re-build. If it flips the order to match, you're done with
that diff.

**Related**:
- `feedback_ido_o0_pre_increment_keeps_register.md` — different
  -O0 lever (`++j < N` vs `j++; while (j < N)`)
- `feedback_ido_v0_reuse_via_locals.md` — int-side
  named-local-vs-inline rule (-O2)

---

---

<a id="feedback-ido-o0-load-order-not-expression-driven"></a>
## IDO -O0 field-load order isn't controlled by C expression order

_At -O0, reading two fields from the same base pointer (`p[1]` and `p[2]`) inside a single boolean expression emits loads in the OPPOSITE order from what the C says — and flipping the expression doesn't flip the emitted order. Example: target's `lw 4(base); lw 8(base)` is not reachable by `p[1]+1 == p[2]` (emits `lw 8; lw 4`), nor by `p[2] == p[1]+1` (same). Tested 2026-04-20 on arcproc_uso_func_000000B4 — 82% cap._

**Symptom (arcproc_uso_func_000000B4, 2026-04-20):**

Target at -O0 reads `a0[1]` THEN `a0[2]` (source-order):
```
lw t6, 40(sp)     ; reload a0
lw t7, 4(t6)       ; t7 = a0[1]
addiu t8, t7, 1    ; t8 = a0[1] + 1
lw t9, 8(t6)       ; t9 = a0[2]
bne t8, t9, ...
```

But C `if (a0[1] + 1 == a0[2])` at -O0 emits:
```
lw t6, 24(sp)      ; reload a0
lw t7, 8(t6)        ; t7 = a0[2]   <- wrong, loaded first
lw t8, 4(t6)        ; t8 = a0[1]
addiu t9, t8, 1     ; t9 = a0[1] + 1
bne t7, t9, ...
```

Flipping to `if (a0[2] == a0[1] + 1)` — SAME output (same wrong order). The -O0 code-gen emits the RHS-then-LHS field loads regardless.

**Why:** IDO -O0 evaluates comparisons by generating code for both sides into fresh registers, then compares. The "which side is loaded first" is driven by AST traversal order, not source order, and for `==` IDO appears to traverse right-side-first (or the optimizer reorders even at -O0 for simple loads).

**Workarounds tested:**
- `int next = a0[1] + 1; if (next == a0[2])` — doesn't help (next materialized fresh, then a0[2] loaded).
- `register int *p = a0; if (p[1] + 1 == p[2])` — helps with $s0 allocation but NOT load order.
- Ternary / pointer offset — no effect.

**Implication:** For -O0 ref-count / bounds-check patterns, the load order is a ~5-instruction-off cap you cannot flip from C alone. Leave as NM wrap. Documented cap: 82-85% depending on frame size.

**Distinct from -O2 load reorder knobs:** at -O2, expression refactoring and named-local tricks routinely flip load order. -O0 is stricter because the AST-to-code translation is more rigid.

---

<a id="feedback-ido-o0-each-arg-use-emits-fresh-reload"></a>
## IDO -O0 emits a fresh reload for EACH source-level use of an arg — no peephole-combining of adjacent uses

_At -O0, every C-level reference to a function arg (via its name in the C source) produces an independent `lw rN, frame_offset(sp)` from the arg's caller-slot — even when two adjacent statements use the SAME arg with no intervening writes. IDO -O0 doesn't peephole-combine consecutive reloads of an unchanged stack value. Target asm that reuses an already-loaded arg-register across uses is NOT reachable from natural -O0 C — there's always a +1-insn gap from the extra reload._

**Symptom (func_0000FEA0, 2026-05-08):**

Target at -O0 (18 insns):
```
lw t6, 0x28(sp)        ; FIRST reload of a0
lw s0, 0x28(t6)         ; uses t6 to fetch *(a0 + 0x28)
lh t7, 0x60(s0)
addu a0, t7, t6         ; REUSES t6 (still holds a0)  -- NO second reload
```

C-emit at -O0 (19 insns) — every variant tested (4 forms: register-p, register-a0, register-p+register-off, typed-struct):
```
lw t6, 0x28(sp)         ; FIRST reload
lw s0, 0x28(t6)
lh t7, 0x60(s0)
lw t8, 0x28(sp)         ; SECOND reload  ← +1 insn vs target
addu a0, t7, t8
```

The C source has TWO uses of `a0`: once in `*(char**)(a0 + 0x28)` and once in `a0 + offset`. Each emits a separate `lw rN, 0x28(sp)`. Target's emit only has ONE — implying either the original source had a single-use form OR IDO had a peephole pass that's not active in our build.

**Workarounds tested:**
- `register char *self = a0;` — adds an $s0/$s1 spill, frame grows, doesn't merge reloads.
- `register char *a0` parameter — emits cleanest 19-insn form but still has the extra reload.
- Single combined expression `((void(*)(char*))*(int*)(*(char**)(a0+0x28)+0x64))(a0+*(short*)(*(char**)(a0+0x28)+0x60))` — IDO -O0 evaluates both `*(char**)(a0+0x28)` accesses independently (no CSE).
- Typed-struct accessor `a0->p28; a0->p28->fn(...)` — same shape as named-local form.

None close the gap. The +1-insn cap is structural to IDO -O0's "no peephole" emit model.

**Implication:** -O0 file-split candidates with target asm that reuses a register across multiple arg-uses cannot byte-match from C alone. They need either:
- 2-insn INSN_PATCH to collapse `lw tN, off(sp); addu` into `nop; addu rD, rA, t6` (using the earlier reload's register), plus TRUNCATE_TEXT to absorb the size delta.
- Permuter find that produces some non-natural C shape avoiding the second arg-reference.

**Generalizes to:** any -O0 function whose target asm shows N uses of an arg but only K reloads where K < N. The natural C will produce N reloads. The K-vs-N gap is the cap.

**Verified 2026-05-08** on `func_0000FEA0` (18-insn target, 19-insn C cap across 4 variants). Documents a +1-insn cap that can be RECEIVED post-cc via INSN_PATCH but NEVER reached via C source rewriting.

---

---

<a id="feedback-ido-o0-lui-lw-reuse"></a>
## IDO -O0 `lui tA; lw tA, %lo(D)(tA)` reuse is the default; forcing fresh-temp `lw tB` is unreliable

_When the target asm reads a D_* global at -O0 with `lui tA; lw tB, %lo(D)(tA)` (fresh register for dest), plain `if (D == C)` produces the reuse form `lw tA, %lo(D)(tA)`. Multiple C variants (cast, struct, array, volatile, pointer local, register local) all fail to flip this without adding instructions. Treat as a potential blocker for exact match._

**Rule:** At IDO -O0, reading a simple extern `int D_XXX` in a compare like `if (D_XXX == CONST)` emits:

```
lui tA, %hi(D_XXX)
lw  tA, %lo(D_XXX)(tA)     # reuses base register as dest
```

If the target emits fresh-temp form (`lw tB, %lo(D)(tA)` with `tB != tA`) in a 2-instruction sequence with the same HI16/LO16 relocations, **no ordinary C rewrite produces it**. Tried for `1080/bootup_uso/func_00012818` (99.73 % match, still blocked):

- `extern int D;` → reuse (lw tA into tA)
- `extern volatile int D;` → reuse
- `extern const int D;` → reuse
- `extern int D[]; D[0]` → adds an `addiu` (lui+addiu+lw, 3 insns)
- `extern struct { int x; } D; D.x` → reuse
- `int val = D; if (val == C)` → spills val (sw+lw, 2 extra insns)
- `register int val = D;` → goes into $s1 (adds sw s1 to prologue, not wanted)
- `*(volatile int*)&D` → same as plain extern
- `int *p = &D; *p` → 3+ extra insns
- `(int)D`, `~~D`, `D + 0`, `D | 0`, `D - CONST == 0` → reuse

Fresh-temp form DOES appear naturally when the `lw` destination is an ARG register (`$a0..$a3`) — see bootup_uso's `func_00006808`, `func_000055A0`, kernel `func_80008C00`. If the compare is a function argument like `if (myfunc(D_XXX) == C)`, IDO generates `lui tA, %hi; lw $aN, %lo(tA)` with fresh arg reg as dest. But when comparing directly (`if (D == CONST)`), there's no fresh-reg demand.

**How to apply:**
- If `≥80 %` match with only this diff, wrap as NON_MATCHING per the skill and move on.
- Don't burn more than 4-5 variant attempts — this is likely a decomp-permuter task or requires a construct IDO semantic I haven't enumerated.
- If the compiler's register allocator deems the base register "dead after this lw," it reuses. If something keeps the base alive (e.g., another use of `&D_XXX` in the same basic block), it may pick fresh — but typically at the cost of additional insns.

**Related:** The `.NON_MATCHING` symbol asm-processor adds when INCLUDE_ASM is in effect makes `objdiff-cli report` tag the function as 0 % (non-matching) even when .text bytes are byte-identical to expected. That's by design — INCLUDE_ASM is not a decomp match. So wrapping a partial C in `#ifdef NON_MATCHING ... #else INCLUDE_ASM ... #endif` still reports 0 % in the default build; the wrap's value is preserving the C body for future permuter/agent runs, not boosting report stats.

**Origin:** 2026-04-19, 1080 bootup_uso/func_00012818 (Run 10, dead-s0 + hw-register check).

---

---

<a id="feedback-ido-o0-pre-increment-keeps-register"></a>
## IDO -O0 — `++j < N` keeps j in register across back-edge slt; `j++; while(...)` spills+reloads

_For do-while loops at IDO -O0, `do {...} while (++j < N)` keeps the incremented j in $t8 across the loop-end `slt at, j, N` test. The semantically-equivalent `j++; } while (j < N);` form spills j to stack via `sw t8, 0(sp)` then reloads via `lw t9, 0(sp)` before the slt — adding 1 dead lw insn per iteration. Verified +6.5 pp on arcproc_uso_func_0000019C (88.5% -> 95.0%)._

**Pattern in target asm** (do-while back-edge):

```
addiu t8, t7, 0x1     ; t8 = j + 1
sw    t8, 0x0(sp)     ; spill j+1 to local
lw    t9, 0x4(a0)     ; load N (loop bound)
slt   at, t8, t9      ; at = (j+1 < N) — uses t8 directly
bnez  at, .Ltop       ; back-edge
```

**Mismatched C** (`j++; } while (j < N);`):

```
addiu t8, t7, 0x1     ; t8 = j + 1
sw    t8, 0x0(sp)     ; spill
lw    t9, 0x0(sp)     ; (extra) reload — IDO drops register liveness here
lw    t0, 0x4(a0)     ; load N
slt   at, t9, t0      ; uses reloaded t9, NOT t8
bnez  at, .Ltop
```

**Matching C** (`} while (++j < N);`):

```c
if (a0[1] > 0) {
    do {
        i += a0[8 + j];
    } while (++j < a0[1]);   // pre-inc keeps j in t8 across the slt
}
```

**Why:** at IDO -O0, the increment expression `j++` is treated as a separate
statement that ends a "use sequence" — IDO's local-alloc considers j's
register liveness ended after the spill, so the loop test starts a new
use sequence and reloads. `++j` keeps the increment INSIDE the comparison
expression, so IDO sees the result-of-increment value as still live for the
slt without the intermediate reload.

**How to apply:** When matching IDO -O0 do-while loops at the bottom-test
back-edge, ALWAYS prefer the prefix-increment-in-condition form:

```c
do { ... } while (++var < bound);   // GOOD: keeps var in register
```

Avoid:

```c
do { ... var++; } while (var < bound);   // BAD: extra lw between increment and slt
```

Same logic, different IDO -O0 emit. The distinction does NOT apply at
-O2 (both forms compile identically).

**Origin:** 2026-05-03, arcproc_uso_func_0000019C lift session.
65.92% (if/else form) -> 75.07% (early-return arm-flip) -> 88.51%
(do-while + entry guard + j++) -> 95.0% (changed j++ to ++j). The
final +6.5 pp jump was traced to the eliminated stack reload between
the increment and the back-edge slt.

---

---

<a id="feedback-ido-o0-prefix-match-dead-epilogue"></a>
## IDO -O0 gives target-prefix bytes for unfilled-delay-slot leaves, but adds dead trailing jr-nop — not trimmable from C

_For 3-insn leaf setters (`sw X, off(a0); jr ra; nop`) that IDO -O2 compacts into 2 insns (`jr ra; sw X, off(a0)`) — the classic `feedback_ido_unfilled_store_return.md` cap — -O0 DOES emit the 3 target insns as a PREFIX, but adds 2 extra dead insns (`jr ra; nop`) for epilogue, giving 0x14 output vs target's 0xC. There's no C technique to trim the trailing dead pair; putting the next empty function (e.g. `void f2(void) {}`) in the same .c at -O0 also fails because IDO independently emits epilogues for each function._

**The test (2026-04-20, bootup_uso/func_00010A9C):**

Target (0xC bytes, unfilled):
```
AC800078  sw  $zero, 0x78($a0)
03E00008  jr  $ra
00000000  nop
```

IDO -O2 output (0x8 bytes, filled — classic cap):
```
03E00008  jr  $ra
AC800078  sw  $zero, 0x78($a0)   ; in delay slot
```

IDO -O0 output (0x14 bytes — prefix matches target, then dead):
```
AC800078  sw  $zero, 0x78($a0)     ; matches target[0]
03E00008  jr  $ra                   ; matches target[1]
00000000  nop                       ; matches target[2]
03E00008  jr  $ra                   ; DEAD (extra epilogue)
00000000  nop                       ; DEAD
```

**What I tried and why it doesn't work:**

- Putting func_00010AA8 (`void f(void){}`, adjacent empty-function sibling) in the same .c at -O0: still produces a separate 0x14-byte func_00010A9C + 0x10-byte func_00010AA8. IDO doesn't fold adjacent functions' trailing deaths together.
- `__attribute__((naked))` at -O0: gives 0x8 bytes (just the `sw`), no `jr` or `nop` at all — unusable without inline asm (which IDO rejects).
- `return;` / `if (1) body` / `a0[30] = 0` wordings: no change at -O0.
- -O1 / -O2 / -O3: all give the compacted 0x8 output — can't un-fill the delay slot.

**Why pad-sidecar can't save it either:** pad-sidecar adds local bytes AFTER the function symbol. Here I need to REMOVE trailing bytes from the primary symbol. Can't be done from a .c file.

**Bottom line:** cap is real. -O0 is an interesting finding but doesn't open a path to match. Supersedes scope of `feedback_ido_unfilled_store_return.md` by documenting what -O0 does (useful negative result — saves future-me from re-running this experiment).

**Only remaining recourse:** permuter, or split the function out to its own .c file and use `#pragma GLOBAL_ASM` for just that function (effectively still INCLUDE_ASM).

---

---

<a id="feedback-ido-o0-register-and-inline"></a>
## IDO -O0 respects `register` for $s0 and inline-callable exprs avoid stack spills

_At -O0, IDO normally assigns every local to a stack slot and reloads on every use. But `register T *p` forces $s0 allocation (survives intervening calls), and inlining an fn-pointer expr into its call site avoids a spilled temporary_

**Rule:** Two knobs to match -O0 functions whose target asm uses `$s`-registers or avoids a stack temp:

1. **`register T var;`** — IDO at -O0 honors the `register` storage class as an allocation hint. Variables declared `register` land in `$s0`, `$s1`, … (with save/restore in prologue/epilogue), not on the stack. Without it, the same variable spills to stack and reloads before every use.

2. **Inline a function-pointer expression into its call site** — instead of:
   ```c
   void (*fp)(T*) = *(void (**)(T*))(p + 0x74);
   fp(arg);
   ```
   write:
   ```c
   (*(void (**)(T*))(p + 0x74))(arg);
   ```
   At -O0 the first form spills `fp` to stack then reloads; the inlined form goes straight `lw t9, 0x74(p); jalr t9` with no spill.

**Why `register` works at -O0 specifically:** IDO's `-O0` still runs `stupid_life_analysis` / pre-codegen; it doesn't allocate across basic blocks but does respect storage-class hints for the lifetime of the variable. For a struct pointer that survives an indirect call (`jalr`), `register` is effectively the only way to get $s0 usage at -O0 — without it, every intervening call forces a spill before + reload after.

**Example (1080 `func_0000F76C` in -O0 Run 2):**

Target asm stores `a0->0x28` to $s0 and keeps it across a `jalr` call:
```
sw   s0, 0x18(sp)       # prologue saves s0
lw   t6, 0x28(sp)
lw   s0, 0x28(t6)       # s0 = a0->0x28  (lives across jalr)
lh   t7, 0x70(s0)
addu a0, t7, t8
lw   t9, 0x74(s0)
jalr t9
```

Matching C:
```c
void func_0000F76C(char *a0) {
    register char *p;                              /* forces $s0 */
    func_00000000((void*)0);
    p = *(char**)(a0 + 0x28);
    (*(void (**)(char *))(p + 0x74))(*(short*)(p + 0x70) + a0);   /* fp inlined */
    func_00000000(a0);
}
```

Without `register`: 28 instructions (0x70), extra stack slot + reloads for `p`.
With `register` + inlined fp call: 25 instructions (0x64), matches exactly.

**How to apply:**

- If the target asm at -O0 shows `sw $s0, N($sp)` in the prologue and uses `$s0` to hold a pointer across `jal`/`jalr`: declare that variable `register T *p;` in the C.
- If the target lacks a stack slot for what would naturally be a function pointer variable: inline the pointer-deref expression into the call.
- For -O0 non-leaf functions with saved regs (`$s0`, `$s1`, `$s2`), the count of `register` variables should match the `sw $sN` count in the prologue. Usually one per long-lived pointer.

**Related:** `feedback_ido_no_gcc_register_asm.md` warns that IDO rejects GCC's `register T x asm("$N")` form — but the plain `register T x;` is fine and works exactly as described here. The key difference: `register` alone lets IDO pick any free $s-reg; the `asm("$N")` form is GCC-specific.

**Origin:** 2026-04-19 while matching `func_0000F76C` in 1080 bootup_uso's -O0 Run 2. First non-trivial -O0 function (struct-fp indirect call with a saved register).

---

**Addendum (2026-04-19, `func_00012B7C` in Run 10):** The SAME inlining principle applies to **chained pointer derefs used in multi-arg calls** — not just function-pointer calls.

Target asm:
```
lw t0, 0x14C(t9)   # t0 = a0->0x14C
lw t1, 0x8(t0)     # t1 = t0->0x8  (2-level deref stays in t1)
lw a1, 0x8(t1)     # arg1 = t1[2]
lw a2, 0x4(t1)     # arg2 = t1[1]  (t1 still live, reused)
```

Wrong C (2 extra instructions: sw t1 + lw t2):
```c
char *p = *(char**)(*(char**)(a0 + 0x14C) + 0x8);   /* p spills to stack at -O0 */
func_00000000(a2, *(int*)(p + 0x8), *(int*)(p + 0x4));
```

Right C (matches exactly):
```c
func_00000000(a2,
    ((int**)(*(char**)(a0 + 0x14C) + 0x8))[0][2],
    ((int**)(*(char**)(a0 + 0x14C) + 0x8))[0][1]);
```

The inline form recomputes the 2-level deref path TEXTUALLY twice, but IDO at -O0 still loads the intermediate into `t1` once and keeps it live for both fetches (it's the SAME basic-block expression). The named `char *p` is worse because IDO treats it as a separate variable and mandatorily spills it.

**Heuristic for chained derefs:** if the target asm shows a chain ending in ≥2 uses of the final pointer `tN`, and no `sw/lw tN` spill in between, inline the chain in the C expression. If there IS a spill, use a named local. If it's a `$s`-reg (saved across a call), use `register T *p;`.

---

---

<a id="feedback-ido-o0-register-count-matches-target-s-saves-exactly"></a>
## At IDO -O0, count target's `sw sN, ...` saves to set the EXACT number of `register T x;` declarations

_At -O0, IDO promotes register-typed locals to s0/s1/s2/... in declaration order. Each one adds an `sw sN, OFF(sp)` to the prologue and an `lw sN, OFF(sp)` to the epilogue. Target's exact s-save count is the diagnostic: count `sw sN, OFF(sp)` instructions in the target's prologue. Use exactly that many `register T x;` declarations — fewer means IDO falls back to per-statement reload (load-fresh-from-spill pattern), more means extra s-saves that target doesn't have. Verified on func_0000F6C4: 1 register decl matches target (91.31%); 0 register decls produces per-load pattern (63%); 2 register decls overshoots (81.74%)._

**Rule:** At IDO -O0:
1. Count `sw sN, OFF(sp)` instructions in the target prologue. That's the magic number `K`.
2. Use exactly `K` `register T x;` declarations in your C body. The first declared local gets s0, second gets s1, etc.
3. The most-dereferenced local in the body should be declared FIRST (ends up in lowest s-reg).

**Verified 2026-05-05 on `func_0000F6C4` (-O0 method dispatcher, 42 insns):**

| C declarations | s-saves emitted | Fuzzy |
|---------------|----------------|-------|
| `char *m;` (no register)            | 0 saves | 63.49 % |
| `register char *m;`                 | 1 save (s0) ← matches target | 91.31 % |
| `register char *m, *r = a0;`        | 2 saves (s0, s1) | 81.74 % |

Target prologue had exactly 1 `sw s0, 0x18(sp)`. The +18pp from K=0 → K=1 is the largest gain; the −10pp from K=1 → K=2 is the wrong direction because each extra register decl:
- Adds `sw sN; lw sN` to prologue/epilogue (cost paid in the function's s-save count)
- Reserves a 4-byte stack backup slot for the register at -O0 (per `feedback_ido_o0_register_locals_reserve_backup_stack_slots.md`)
- Caches a value the target deliberately reloads fresh

**The "most-deref'd local" rule:**

If your function has `m = a0[0x28]; m[0x60]; m[0x64]; m[0x68]; m[0x6C];` (m deref'd 4×) AND `a0[0x2C]; a0[0x28]` (a0 deref'd 2×), put `register char *m;` BEFORE other declarations. IDO declaration order maps to s-reg numbering, and lower s-regs are typically more "valuable" — but more importantly, the FIRST register-typed local is what target's s0 holds.

**Diagnostic workflow:**

```
# Count target's s-saves:
grep -c "AFB[0-9]00[0-9]" asm/nonmatchings/<seg>/<func>.s
# (matches sw s0..s7 — adjust regex per your asm format)
```

Then write your C body with exactly that many `register T x;` decls, ordering by deref-frequency (most-deref'd first).

**Why this is non-obvious:**

The standard "use register hints to force s-saves" advice doesn't say HOW MANY register hints. Adding more feels safe (more caching = better, right?) but at -O0 the s-save count is a structural feature of the prologue. Mismatch breaks the prologue byte-for-byte and cascades through register-renumber.

**Necessary-but-not-sufficient — strength-reduction caveat (verified 2026-05-05 on `func_800007D4` -O1):**

The rule is necessary (count must match) but NOT sufficient: at higher -O levels, IDO's optimizer will collapse register-typed locals it deems redundant. Example: when two register-typed locals are both COMPILE-TIME-CONSTANT addresses with a known offset between them, IDO strength-reduces one into `addiu sN, other, OFFSET`, dropping its s-reg slot.

`func_800007D4` declares 4 register locals (p, end, arg0, state). Target saves 4 s-regs (s0/s1/s2/s3). Build saves only 3 — IDO collapses `end = &D_80012F7C` into `addiu sN, p, 0x21C` because `&D_80012F7C - &D_80012D60 = 0x21C` is a strength-reducible constant. No C-source variant (separate decl, decl-then-init, register-init order) defeats this collapse at -O1.

Workarounds attempted and their result:
- Split `register T x; x = init;` from `register T x = init;` — same emit (-O1 allocator is weight-driven, ignores syntactic ordering).
- Proxy-zero extern (`(int)&D_x + (int)&D_zero_proxy`) — known regression class (introduces a new pseudo that re-numbers OTHER s-regs; net negative).

Implication: when target's source has multiple register-typed locals that are all compile-time-constant addresses with known offsets, the s-save count rule predicts what target wanted but IDO may not honor it. Document the cap and move on; permuter is the only remaining lever.

**Companion memos:**

- `feedback_ido_register.md` — base behavior of register keyword.
- `feedback_ido_o0_register_locals_reserve_backup_stack_slots.md` — the per-register stack-slot overhead at -O0.
- `feedback_uso_accessor_template_reuse.md` — the -O0 cluster split context where this matters most.

---

---

<a id="feedback-ido-o0-register-decl-order-flips-a-alloc"></a>
## IDO -O0 with two `register` locals — declaration order flips which gets $a2 vs $a3 (later-declared gets HIGHER-numbered $a-reg)

_When matching an -O0 function that uses two `register` locals filling the unused $a-slots (e.g., $a2 and $a3 when only a0/a1 are real args), the order you DECLARE them controls which gets which slot. Declaring `register A; register B;` in the natural order gives A=$a2, B=$a3. Reversing the source order to `register B; register A;` swaps to A=$a3, B=$a2 — useful when target swaps from your "natural" assignment._

**Verified 2026-05-02 on `func_00011C70`** (bootup_uso, 13-insn -O0 append-to-array helper).

**Function:** `void f(s32 *a0, s32 a1) { idx = a0->0x120; a0->0x120 = idx+1; a0[idx*4 + 0xE0] = a1; }`. Two pseudos needed: a saved copy of `a0` (for the `lw/sw` of offset 0x120) and `idx` (the loaded count). Args use $a0/$a1; pseudos go to $a2/$a3 since they're free arg slots.

**Initial attempt** — natural declaration order:
```c
register s32 *p = a0;       /* p declared first */
register s32 idx = ...;     /* idx declared second */
```
Result: p → $a2, idx → $a3.  Target had p → $a3, idx → $a2.

**Fix** — swap declaration order:
```c
register s32 idx;           /* idx declared first */
register s32 *p = a0;       /* p declared second */
idx = *(s32*)((char*)p + 0x120);  /* assign after */
```
Result: idx → $a2, p → $a3. **Byte-identical to target.**

**Mental model:** at -O0, IDO seems to assign $a-slots to `register` locals in REVERSE declaration order (later-declared = higher slot number). This is unintuitive — most allocators assign first-declared first. Source order matters; verify with the .o disasm.

**How to apply:**

When matching an -O0 leaf function:
- Identify which target $a-reg holds which value (count vs pointer vs counter, etc.).
- Map each value to a `register` local in C.
- If your build's $a-reg assignment is BACKWARDS from target's, swap the declaration order in the C source.

The same idea may apply at -O1/-O2 for $s-reg ties when ref counts and live lengths are equal. (At -O2, ref-count usually dominates per `feedback_ido_local_ordering.md`; at -O0 source order is the primary lever.)

**Anti-pattern to avoid:** trying to flip via `register T x asm("$aN")` — IDO rejects that GCC syntax (per `feedback_ido_no_gcc_register_asm.md`).

**Related:**
- `feedback_ido_local_ordering.md` — first-declared-at-highest-stack-offset (for stack locals, opposite direction)
- `feedback_ido_no_gcc_register_asm.md` — `register T x asm("$N")` rejected
- `feedback_ido_register.md` — IDO honors `register` keyword as strong $s-reg hint

---

---

<a id="feedback-ido-o0-register-locals-reserve-backup-stack-slots"></a>
## IDO -O0 reserves a 4-byte backup stack slot for EACH `register`-typed local — adds frame overhead beyond what target needs

_At -O0, IDO honors `register T *p` hints to save callee-save s-regs (s0/s1/s2/s3) — but ALSO reserves a 4-byte backup stack slot per register-typed local. With 4 register decls, frame grows by 16 bytes vs target's frame. Verified on func_0000F2EC: 4 register Vec3*/float* decls correctly saved s0-s3 but frame went 0x58 → 0x68 (+0x10). At -O2 the register keyword does NOT reserve backup slots; this is -O0-specific._

**Rule:** At IDO -O0, every `register T x;` declaration costs 4 bytes of frame even when the value is kept in an s-reg the whole time. With N register decls, expect frame +N*4 bytes vs a target compiled with regular locals. If your target's frame is precisely calibrated, the register-hint approach to forcing s-saves at -O0 will overshoot the frame size.

**Verified 2026-05-05 on `func_0000F2EC`:**

Wrote 4-register C body to force IDO -O0 to save s0-s3:
```c
register Vec3 *p1 = dst;
register Vec3 *p2 = p1;
register Vec3 *q;       /* used once but never read */
register float *src = (float*)&tmp;
```

Result: s0/s1/s2/s3 all correctly saved at sp+0x14..0x20 ✓. tmp at sp+0x34, raw at sp+0x48 — local layout matches target. BUT frame is -0x68 (build) vs -0x58 (target), +0x10 = 16 bytes too big. IDO at -O0 added 16 bytes of "backup storage" for the 4 register-typed locals between the locals area and caller's a0-spill slot.

Cascade: the +0x10 frame causes:
- a0 spill at sp+0x68 vs sp+0x58 (offset shift)
- s-reg-numbering renumber (build uses s0/s2 where target uses s1/s3 etc.)
- ~12 cascade word-diffs from the position shift

Net fuzzy: 84.61% on a function that's structurally exactly right. Remaining diffs are all from the 16-byte frame overhead.

**Why this is non-obvious:**

- At -O2, `register T x` does NOT reserve backup slots — IDO trusts the s-reg holds the value, no spill area needed.
- The standard "use register hints to force s-saves at -O0" recipe (per `feedback_ido_register.md` and similar) doesn't mention this overhead.
- Agents see "frame off by N*4 bytes" and might add `pad` adjustments to compensate — but reducing pad just shifts the problem to other offsets. The register-decl backup slots are AT FIXED OFFSETS reserved by IDO, not movable.

**Diagnostic:**

If your -O0 build has frame = target_frame + N*4 where N = number of register-typed locals, that's the IDO -O0 backup-slot overhead. Check by comparing build's `addiu sp, sp, -X` vs target's. If the diff is exactly N*4 (where N matches register-decl count), this gotcha applies.

**How to apply:**

For -O0 functions where frame size is critical:
1. Don't use 4+ register-typed locals if you only need s0-s3 saved. Try `register T *p;` (1 decl) and see what s-reg gets saved.
2. If target needs N s-regs but only has K register-typed locals (K < N), there's no recipe — IDO -O0 won't save more s-regs than register-decl count needs.
3. If target needs N=4 saves AND has frame matching ours +0x10, target was likely compiled with a different IDO -O0 version that didn't reserve backup slots, OR target's source uses a different mechanism (like __register-asm-binding which IDO rejects per `feedback_ido_no_gcc_register_asm.md`).
4. Accept the cap and document: 4 s-saves achieved structurally; +0x10 frame is the residual that's not C-source-reachable.

**Companion memos:**

- `feedback_ido_register.md` — base register-keyword behavior at higher opt levels.
- `feedback_ido_no_gcc_register_asm.md` — `register T x asm("$N")` is rejected by IDO.
- `feedback_uso_accessor_template_reuse.md` — the accessor template family this affects.

**2026-05-06 bifurcation confirmation (func_0000F2EC):**

Tested partial-removal of `register` qualifiers — only the bifurcation works at -O0:

- All 4 register vars (p1, p2, q, src): frame `0x68`, s-regs s0-s3 saved ✓ — +16 byte overhead, 84.61% fuzzy.
- 3 register vars (drop register from `q`, an unused-late-assigned local): frame `0x68` STILL — IDO -O0 reserves backup slots based on register-decl count at func entry, not just on used-vars. Removing register from a "barely-used" var does not save backup slots. Same +16 overhead, same 84.61% fuzzy.
- 0 register vars (Vec3 *p1 = dst; etc., all stack-resident): frame `0x58` (matches target!) but `$tN`-only code, no $sN saves — different cap class (s-saves missing). Worse fuzzy.

There is no middle ground: register-qualified locals at -O0 are all-or-nothing for the +N*4 backup overhead (where N = register-decl count >= 1). Either commit to register (correct s-reg usage, +16 frame) or no-register (correct frame, no s-regs). Neither byte-matches; the cap is structural.

**2026-05-07 — analogous behavior at -O2 for non-register named pointer locals (different mechanism):**

At -O2, IDO reserves stack slots for named-local pointer variables based on the COUNT OF DECL'D POINTERS at function entry, even when the allocator subsequently keeps them all in registers. Verified on `game_uso_func_0000C12C` (16-int copy with unroll-by-3): adding 3 named ptrs (`int *src; int *end; int *dst;`) bloats frame from target's 88 bytes to 104 bytes (+16 = 12 bytes for 3 ptrs + 4 alignment). Output asm confirms src/end/dst all live in $v0/$a0/$v1 registers — never spilled — but the 16-byte gap between buf and ra reservation persists.

Distinct from the -O0 case (which is about `register` keyword backup slots): at -O2 the slots are reserved for ANY named pointer local, regardless of `register` hint, and remain dead even when the allocator keeps the value in a $-reg.

**How to apply:** if your -O2 build has frame = target_frame + 4*N where N = named pointer locals, AND those locals all show up in registers (no `lw/sw` to their slots in the body), the cap is the same dead-slot reservation. INSN_PATCH on the prologue's `addiu sp` immediate is technically possible but the offset cascade through the rest of the function makes it impractical — accept the structural cap.

---

---

<a id="feedback-ido-o1-delay-slot-s-reload"></a>
## IDO -O1 target `lw $sN, spill(sp)` in jal delay slot — can't force via explicit C assignment

_rmon-style -O1 funcs spill arg `a0` to caller slot, then fill the first jal's delay slot with `lw $s0, SPILL(sp)` to promote msg into a callee-saved reg for later use. Our IDO fills the same slot with a benign `lw $a0, SPILL(sp)` (wasted) unless we explicitly assign `register p = msg;` — but that adds a `move s0, a0` or `lw t6; move s0, t6` elsewhere. Net: can't reach 100% from C; stays at 99.7%._

**Pattern:** Target asm shows this idiom after the first jal:

```
sw   a0, SPILL(sp)         ; spill arg
sw   s0, SAVE(sp)
jal  firstCallee
lw   s0, SPILL(sp)         ; DELAY — msg now in $s0 for later blocks
beqz v0, .L_ok             ; check firstCallee return
... (error path) ...
.L_ok:
... (use $s0 as msg) ...
```

IDO's scheduler chose `lw s0` in the delay slot because later basic blocks read `$s0` as `msg`. This requires that `msg` be dataflow-live into $s0 at that exact program point.

**What doesn't work from C (all tested on kernel_054/func_8000969C 2026-04-20):**

1. `register s32 *p;` (uninit) + dead `p = msg;` at end → IDO treats p as garbage and fills delay slot with `lw a0, SPILL(sp)` (wasted, $a0 already holds msg).
2. `register s32 *p = msg;` at declaration → emits `lw t6, SPILL(sp); move s0, t6` = 2 extra insns somewhere (often at top of function before jal).
3. Drop `p`, use `msg` directly in body → IDO's -O1 heuristic decides NOT to promote msg to a callee-saved reg; frame shrinks; loop reloads msg from spill each iter. Much worse (15+ extra reloads in a loop).
4. `p = msg;` between jal and next-block → extra `lw s0, SPILL(sp)` emitted at the join point (1 insn after the spill check); the jal delay slot still gets `lw a0`.

**Why:** IDO's delay-slot filler picks an instruction from the "taken" path. If the taken path's first use is `lw s0, SPILL(sp)` then delay gets that. If the taken path first reads something else, that goes in the delay slot. We can influence what's read first BUT every C expression adds its own baggage (lui/la/move).

**When to accept:** after 3-4 C variants at 99% match, the remaining 1-2 insn delta is a scheduler decision. Leave NM wrap. Permuter may find it via random insn-order shuffling; manual C rewrite won't.

**Related:** `feedback_ido_register_promotes_class_not_number.md` covers the $s-class vs $s-number distinction. This memo is about the *timing* of when $s-reg gets filled, not *which* $s-reg.

**Origin:** 2026-04-20, agent-a, kernel_054/func_8000969C. Permuter previously ran 14k iters with best score 15 — structural diff is real, not just scheduling noise.

---

---

<a id="feedback-ido-o2-loop-unroll-and-constfold"></a>
## IDO -O2 auto-unrolls simple count-bounded pointer-chase loops 4x; also constant-folds `/ const` to `* recip`

_A bare `for (i=0; i<n; i++) p = p->next;` loop at IDO -O2 compiles to a Duff's-device-style 4x unrolled body with a remainder prologue. Don't try to write the unrolled version — the simple loop matches exactly. Separately, IDO constant-folds `x / 2.0f` into `x * 0.5f`, so target asm with explicit `div.s x, 2.0` is unreproducible from `x / 2.0f`._

**Rule 1 (auto-unroll):** When the target asm shows this shape:

```
loop_prologue:
  andi a2, a1, 3       # remainder = count % 4
  beqz a2, main_loop   # if multiple of 4, skip
  <remainder block: +1 counter, 1× chain step>
main_loop:
  <chain step×3>
  addiu v0, 4
  bne v0, count, main_loop
  <chain step×1 in delay slot>
```

It's a 4x-unrolled linked-list walker. The ORIGINAL C is just:

```c
void *f(char *a0, int a1) {
    void *p = *(void**)(a0 + offset);
    int i;
    for (i = 0; i < a1; i++) {
        p = *(void**)((char*)p + chain_offset);
    }
    return p;
}
```

**Don't write the unrolled version by hand.** IDO's -O2 loop optimizer finds these patterns (counted loop, single pointer step, no other work) and unrolls them automatically. The simple C form matches byte-for-byte.

**Example (1080/bootup_uso/func_00001FC8, 19 insns):** matched on first attempt with the plain loop.

**Rule 2 (const-fold division):** IDO -O2 always constant-folds `x / 2.0f` into `x * 0.5f`:

- Target with `lui at, 0x4000; mtc1 at, f16; div.s fD, fN, f16` (divide by 2.0) = UNREPRODUCIBLE from `/ 2.0f` in C.
- `x / 2.0f` emits `lui at, 0x3f00; mtc1 at, f16; mul.s fD, fN, f16` (multiply by 0.5).
- Using a `float half = 2.0f; x / half` doesn't help — IDO propagates the constant.
- Same applies to other power-of-2 divisors: `/ 4.0f` → `* 0.25f`, etc.

If the target asm insists on `div.s` by a power-of-2 constant, it's probably either (a) the original C used a non-constant divisor, or (b) a decomp-permuter task — not worth grinding 10 variants.

**How to apply:**
- Target asm has `andi a2, aN, 3; beqz; <4 chain steps in a loop body with +4 counter>`: write a plain `for` loop with the single step, let IDO unroll.
- Target asm has `div.s` against a small power-of-2 constant (2.0, 4.0, 8.0): keep as INCLUDE_ASM or try non-const C (e.g., divisor loaded from struct field).

**Origin:** 2026-04-19. `func_00001FC8` matched first-try with plain for-loop. `func_000102A4` (float formula with `/ 2.0f`) blocked by const-fold — reverted to INCLUDE_ASM after 2 variants.

---

---

<a id="feedback-ido-o2-tiny-wrapper-unflippable"></a>
## IDO -O2 `sw ra; lui a0` order for 1-arg 1-call void wrappers is unflippable from C

_Simple `void f(void) { func(&SYM); }` wrappers at IDO -O2 always emit `addiu sp; sw ra; lui a0; jal; addiu a0(delay)`. If the target has `addiu sp; lui a0; sw ra; jal; addiu a0(delay)` (lui before sw ra), 13+ C variants (pointer locals, register, volatile, cast, (void) return, int r = ..., etc.) don't flip it. Stops at 77 % (7/9 insns). Below NON_MATCHING threshold — keep as INCLUDE_ASM._

**Rule:** For tiny 1-arg 1-call void wrappers of the shape `void f(void) { func_00000000(&SYM); }`, IDO 7.1 at -O2 always emits:

```
addiu sp, sp, -0x18
sw ra, 0x14(sp)
lui a0, %hi(SYM)
jal func_00000000
addiu a0, a0, %lo(SYM)   # delay slot
lw ra, 0x14(sp)
addiu sp, sp, 0x18
jr ra
nop
```

If the target rearranges the first two useful instructions to `lui a0; sw ra` (lui BEFORE sw ra), **that cannot be reproduced from C**. Exhausted knobs:

1. Plain `func(&SYM)`
2. `char *p = &SYM; func(p);`
3. `register char *p = &SYM; func(p);`
4. `volatile char *p = &SYM; func(p);`
5. `func((int)&SYM);`
6. `func(&SYM, 0);` — extra noop arg (changes delay slot but not prologue)
7. `(void)func(&SYM);`
8. `int r = func(&SYM);`
9. Local forward-decl with varargs (IDO rejects — conflicts with K&R)
10. -O0 and -O1 also don't flip it (same pattern, just more bloat on -O0)
11. Inline `&(SYM)` with parens
12. Pointer-to-void local
13. Early-compute idiom `{ char *p; p = &SYM; func(p); }`

All land at 77.78 % fuzzy match (7/9 insns). **Below the 80 % NON_MATCHING threshold — leave as INCLUDE_ASM**.

**Why:** IDO's scheduler prefers to emit frame-save ops (sw ra) as close to the prologue as possible, then set up arg registers. The target's order suggests a different compiler variant or hand-scheduled asm. Not worth grinding.

**How to apply:**
- When sampling tiny wrappers: disassemble first. If `lui` immediately follows `addiu sp` (BEFORE sw ra), skip and mark as known-blocked.
- If `sw ra` comes immediately after `addiu sp`: match is possible; try the straightforward C first.

**Example (blocked):** `1080/bootup_uso/func_00006204` — 77.78 %.

**Related:** `feedback_ido_unfilled_store_return.md` (similar "unfixable at C level" scheduler quirks in bootup_uso tiny funcs — different pattern but same "skip it" advice).

**Origin:** 2026-04-19, 1080 bootup_uso/func_00006204. 13 C variants tried; all 77 %.

---

---

<a id="feedback-ido-o32-float-in-int-reg"></a>
## O32 passes floats in $aN when preceded by a non-float arg — use `mtc1 aN, fM` reconstruction

_When a function signature is `(int_like, float, ...)`, MIPS O32 passes the float in $a1 (the int register), not $f14. The asm starts with `mtc1 $aN, $fM` to move the bits into the FPU. In C, just declare the param as `float` — IDO's ABI handles the move automatically. Also: IDO commonly hoists pure-function float ops (div.s, mul.s, add.s) into the next branch's delay slot, so guarded stores should have the ARITHMETIC written unconditionally BEFORE the `if`._

**Rule 1 (O32 ABI for float after non-float):** In MIPS O32, if the FIRST arg of a function is not a float, subsequent float args are passed in the INTEGER registers ($a1, $a2, $a3), NOT the float registers. The asm recovers them with `mtc1 $aN, $fM` (move to coprocessor 1).

In C, just declare the param as `float` — the compiler handles the move automatically:

```c
void func(int *a0, float a1) {   /* a1 arrives in $a1 (int reg), not $f14 */
    ...
}
```

If the first arg IS float, that one goes in `$f12`, and the second float goes in `$f14`. Only after a non-float first arg does the ABI switch to int-reg passing.

**DON'T bit-cast via `*(float*)&intArg`** — this triggers IDO's "address taken" path and emits a stack round-trip (`sw aN, K(sp); lwc1 $fN, K(sp)`) instead of the clean `mtc1 aN, $fN`. Verified 2026-05-17 on `game_libs_func_0000254C`: with `int a1, int a2` + `*(float*)&a1` the body became 7 insns (sw/lwc1 pair per arg); with `float a1, float a2` the body became 5 insns matching target's two mtc1's. The trap is intuitive ("I want bit-cast"), but the right tool is just declaring the param `float` — the ABI conversion is what produces the mtc1.

**Rule 2 (IDO hoists pure float ops into delay slots):** For patterns like "compute float value, then maybe store it":

```c
/* IDO might produce:
   beqz v0, skip
    div.s f12, f12, f4     <-- hoisted into delay slot, unconditional
   swc1 f12, 0x10(v0)
   skip:
*/
```

**If the target asm has `div.s`/`mul.s`/`add.s` in a `beqz` delay slot, write the arithmetic BEFORE the `if`:**

```c
void func(void **a0, float a1) {
    a1 = a1 / D_00000068;           /* division unconditional, before guard */
    if (*a0 != 0) {
        *(float*)((char*)*a0 + 0x10) = a1;
    }
}
```

**NOT** inside the `if`:
```c
/* WRONG — division inside the guard; IDO may keep it inside and produce a
 * different schedule. */
if (*a0 != 0) {
    *(float*)((char*)*a0 + 0x10) = a1 / D_00000068;
}
```

**Example (1080/bootup_uso/func_00000B2C, 9 insns):**

Target asm:
```
lw   v0, 0(a0)
lui  at, %hi(D_00000068)
mtc1 a1, f12                      # a1 → f12 (float ABI)
lwc1 f4, %lo(D_00000068)(at)
beqz v0, .L
 div.s f12, f12, f4               # division in delay slot (unconditional)
swc1 f12, 0x10(v0)
.L:
jr ra
 nop
```

C that matches exactly:
```c
extern float D_00000068;
void func_00000B2C(void **a0, float a1) {
    a1 = a1 / D_00000068;
    if (*a0 != 0) {
        *(float*)((char*)*a0 + 0x10) = a1;
    }
}
```

**How to apply:**
- If the asm has `mtc1 $aN, $fM` at the top: the function takes a float arg, but ABI passes it in int reg because of preceding non-float. Declare as `float` in C — compiler handles the rest.
- If the asm has a float arithmetic op (`div.s`, `mul.s`, `add.s`, etc.) in a `beqz`/`bnez`/`beq` delay slot: write the arithmetic as a standalone statement BEFORE the branch, not nested inside the branch body.

**Origin:** 2026-04-19, 1080 bootup_uso/func_00000B2C (guarded float-divide-store).

---

---

<a id="feedback-ido-o32-mixed-mode-float-in-a1"></a>
## o32 mixed-mode ABI — when first arg is int, a float second-arg passes in $a1 (int reg) not $f14, triggering `mtc1 $a1, $f12` at function entry

_o32 reserves $f12/$f14 for floats only when ALL leading args are floats. As soon as an integer arg appears in position 1+, subsequent floats fall back to int registers ($a1, $a2, $a3). IDO emits `mtc1 $aN, $fM` at function entry to move the float-bytes into FPU. This is correct C-side: `void f(int *a0, float a1) { ... }` matches because the compiler knows the int+float signature → uses mixed-mode passing. Verified 2026-05-05 on timproc_uso_b5_func_0000BBC8 (5-insn float store, byte-correct first try)._

**The pattern (verified 2026-05-05 on timproc_uso_b5_func_0000BBC8)**:

Asm shows a function whose first instruction reads from `$a1` and immediately moves it to FPU:

```asm
44856000  mtc1 $a1, $f12       # NOT mfc1 — moving int-reg → float-reg
8c8e02b8  lw   $t6, 0x2B8($a0)
e48c02a0  swc1 $f12, 0x2A0($a0)
03e00008  jr   $ra
e5cc0120  swc1 $f12, 0x120($t6) # delay slot
```

The `mtc1 $a1, $f12` is the diagnostic: the function's FLOAT second-arg arrived
in $a1 (the integer register), not $f14. Why? **o32 mixed-mode**: as soon as
position 1 is non-float, all subsequent args use the integer register file.

The C signature that matches:
```c
void timproc_uso_b5_func_0000BBC8(int *a0, float a1) {  /* a0 int → a1 float in $a1 */
    int *t = *(int**)((char*)a0 + 0x2B8);
    *(float*)((char*)a0 + 0x2A0) = a1;
    *(float*)((char*)t + 0x120) = a1;
}
```

IDO sees `int *a0` in position 0 → uses int-reg ABI for everything that
follows. Position 1's `float` lands in $a1, then the function body needs
$f12 for `swc1`, so IDO emits `mtc1 $a1, $f12` at entry.

**Don't confuse with**:

- **First-arg float** (`void f(float a)`) → arg in $f12, no mtc1 needed.
- **Two floats** (`void f(float a, float b)`) → $f12, $f14, no mtc1.
- **Int + Int + Float** (`void f(int a, int b, float c)`) → $a0, $a1, $a2;
  `mtc1 $a2, $fM` for the float.
- **K&R extern w/ float caller** (`extern f();` and `f(myfloat)`) → covered by
  `feedback_ido_knr_float_call.md`. Different problem (callee can't be matched).

**How to recognize at the asm level**:

1. Function entry has `mtc1 $aN, $fM` (where $aN is $a1/$a2/$a3 — integer arg
   register — and $fM is a float reg).
2. NO preceding instruction sets $aN — it's a function arg.
3. Subsequent instructions use $fM for `swc1`/`lwc1`/float arithmetic.

**The C fix is just to write the signature correctly** — the compiler does
the rest.

### Sub-trap: source-order of float-arg use determines mtc1 mapping

When a function takes TWO+ float args via mixed-mode (e.g., `void f(int *p, float a1, float a2)`), IDO's mtc1 mapping is driven by **first-use order in the C body**, not by ABI arg position. If the body uses `a2` before `a1`, IDO maps `a2 → $f12` and `a1 → $f14` (REVERSED from the natural "first-arg-to-f12" assignment). Verified 2026-05-15 on `gl_func_000402A4` (3-float-arg Vec3 add):

```c
// Source order: a1 (dx) used first → IDO emits mtc1 a1, f12; mtc1 a2, f14
void gl_func_000402A4(int *a0, float dx, float dy, float dz) {
    *(float*)(a0 + 0xB4) += dx;   // dx used first → a1 → f12 ✓
    *(float*)(a0 + 0xB8) += dy;
    ...
}

// Source order: a2 (dy) used first → IDO emits mtc1 a2, f12; mtc1 a1, f14 (SWAPPED)
void gl_func_000402A4(int *a0, float dx, float dy, float dz) {
    *(float*)(a0 + 0xB8) += dy;   // dy used first → a2 → f12 (ABI-swapped)
    *(float*)(a0 + 0xB4) += dx;
    ...
}
```

The swapped form cascades through the function (the FPU regs holding dy and dx flip downstream), producing different bytes even when the C is semantically equivalent. If the target asm has `mtc1 a1, f12; mtc1 a2, f14` (natural ABI ordering), the source must use the 1st-float-arg BEFORE the 2nd-float-arg.

**Sub-cap on gl_func_000402A4 (97.75% NM):** This rule conflicts with target's apparent statement ordering (B8 store before B4 store via addiu-base-update). Either keep ABI-correct mtc1 (correct C order, target's natural-emit cap) OR keep target's store order (ABI-swapped mtc1, regress). For Vec3-style fields with mixed-mode floats, the cap may be unbreakable from C alone.

**Companions**:

- `feedback_ido_knr_float_call.md` — the inverse: when CALLER tries to pass
  float args to a K&R-declared callee. Different failure mode.
- `feedback_ido_mfc1_from_c.md` — `mfc1 $aN, $fM` is the OTHER direction
  (FPU → int reg) for a different pattern.

---

---

<a id="feedback-ido-o3-equals-o2-for-single-file-compile"></a>
## IDO -O3 produces byte-identical output to -O2 for single-file compiles — file-split with OPT_FLAGS=-O3 only adds value for inter-module (IPO) builds, which the per-.c.o pipeline doesn't use

_When a function is stuck at -O2 codegen and you're considering file-split-with-OPT_FLAGS to try -O3, don't bother — IDO's -O3 differs from -O2 only in inter-module optimization (requires `cc -O3 -j ...`). For single-file `cc -c -O3 file.c` it emits the SAME bytes as `cc -c -O2 file.c`. IDO even warns: "-O3 should not be used with ucode on a single file; use -j instead."_

**Rule:** For 1080's per-.c-file build pipeline (each function/group goes through `cc -c <flags> file.c`), `-O3` and `-O2` produce byte-identical .o output. There is NO codegen difference to exploit by switching from -O2 to -O3.

**Why:** IDO's -O3 is the inter-procedural optimization level. It performs cross-function inlining, escape analysis, and global register allocation across module boundaries. These passes only fire when `-j` is passed (IPO mode), which 1080's per-.c.o build does NOT use. Without `-j`, -O3 collapses to -O2's per-function optimization.

The cc warning makes this explicit:
```
cc: Warning: -c should not be used with ucode -O3 -o32 on a single file;
    use -j instead to get inter-module optimization.
```

**How to apply:**

When considering a file-split-with-different-OPT_FLAGS to fix a codegen cap:
- **-O1 ↔ -O2**: Real codegen difference. file-split is worth trying. (Verified on `func_80008030` 2026-05-05: -O1's stack-spill 12-insn vs -O2's 9-insn no-frame.)
- **-O2 ↔ -O3**: NO codegen difference. Don't bother file-splitting for this. (Verified on `n64proc_uso_func_00000014` 2026-05-05: -O3 byte-identical to -O2 standalone.)
- **-O0 ↔ -O1/-O2**: Real difference (-O0 emits stack stores for every local, no register promotion). Worth trying.
- **-g flag**: NO codegen difference (per `feedback_ido_g_flag_does_not_suppress_delay_slot_fill.md`).

**Companion:**
- `feedback_file_split_needs_paired_expected_o_refresh.md` — file-split mechanics
- `feedback_ido_g_flag_does_not_suppress_delay_slot_fill.md` — IDO -g is also a no-op
- `feedback_o0_int_reader_template_variant.md` — example of meaningful -O0 vs -O2 difference

---

---

<a id="feedback-ido-offset-in-instruction-vs-reloc"></a>
## `&BASE + 0xOFFSET` vs `extern SYM_AT_OFFSET` produces different .o byte patterns even when addresses are equal

_When target asm has `lw $reg, 0xNNN($at)` (offset baked into the instruction), write `*(int*)((char*)&BASE + 0xNNN)` in C — this emits `lw $reg, 0xNNN(...)` matching the target. Using `extern int SYM_AT_NNN` (as a separate extern at the combined address) emits `lw $reg, 0(...)` because IDO bakes the offset into the relocation addend instead of the instruction. These encodings differ at the .o byte level even though the linked final address is identical._

**Observed 2026-04-20 on titproc_uso_func_00000388**:

**Target asm** (from disasm of expected .o):
```
lui  $a0, %hi(D_00000000)    ; lui $a0, 0
lw   $a0, 0xA8($a0)          ; offset 0xA8 baked INTO the lw
```

**What produces this in C:**
```c
extern char D_00000000;
// ... use:
*(int*)((char*)&D_00000000 + 0xA8)
```

**What does NOT produce this (produces wrong bytes):**
```c
extern int D_000000A8;  // added to undefined_syms_auto.txt: D_000000A8 = 0x000000A8;
// ... use:
D_000000A8
```

The second form compiles to `lw $a0, 0($a0)` (offset=0) with the 0xA8 encoded in the relocation addend. Same final linked address (0xA8), different .o bytes.

**When to care:** only when comparing .o files (objdiff) — which is how we measure match %. The linked ROM bytes are identical either way, so if you're only validating the final ROM, both work. But 100% match in objdiff's per-function check requires the .o byte pattern, so use the `&BASE + OFFSET` form.

**Rule of thumb:**
- Target asm has non-zero offset in the lw/sw/lwc1/swc1 instruction → use `&BASE + OFFSET` in C
- Target asm has offset=0 in the instruction → use `extern T SYM_AT_FULL_ADDRESS` (a separate extern at the combined address)

**Refinement (2026-05-06): use a fresh `int[]` alias, NOT a re-cast of an existing function symbol.** When BASE is already declared elsewhere as something else (e.g. `extern int func_00000008();`), the natural `*(int*)((char*)&func_00000008 + 0x20) = ...` fails — IDO emits `lui at, %hi(BASE); addiu at, at, %lo(BASE); sw t6, 0x20(at)` (3 insns, 2 luis + 2 addius for the base computation) instead of the compact `lui at, %hi(BASE); sw t6, %lo(BASE+0x20)(at)` (2 insns, single reloc pair).

**Working pattern:** declare a NEW `int[]` extern at the same base address, index it with `[N]`:

```c
extern int D_func_00000008_struct[];   // in undefined_syms_auto.txt: D_func_00000008_struct = 0x00000008;
D_func_00000008_struct[8] = (int)&D_other;   // [8] = byte offset 0x20
```

This emits the single-reloc-pair form with the offset folded into the addend of `%lo(D_struct + 0x20)`. Post-link bytes match target's `lui at, 0; sw t6, 0x20(at)` form (`ac2e0020`).

**Why the type matters:** when BASE is typed as a function (`int f();`) and you cast `(char*)&f + N`, IDO treats the result as an arbitrary computed pointer and emits the full base-address sequence. When BASE is typed as `int[]`, IDO recognizes `BASE[N]` as direct global-array access and emits the compact form. The relocation type (and thus the .o byte pattern) follows the type at the C level — even though the linker sees the same address either way.

**Observed:** func_0000E9FC bootup_uso, 2026-05-06. Promoted 75% (3 diffs) → 83.3% (2 diffs) by the alias-array trick. Remaining diff is the `sw ra; lui a0` prologue swap (unflippable, separate cap).

**Relation to extern-split memo:** `feedback_ido_adjacent_store_extern_split.md` describes the INVERSE: when target emits `lui $at; sw X, 0($at); lui $at; sw Y, 0($at)` for two INDEPENDENT symbols at adjacent offsets (offset=0 in each instruction), declare two separate externs. That's the "offset-in-relocation" case. This memo is the "offset-in-instruction" case. Which to use depends on target's byte encoding.

**Origin:** 2026-04-20, titproc_uso_func_00000388. First attempt used `D_000000A8` extern → wrong bytes (offset=0 instead of 0xA8). Switched to `&D_00000000 + 0xA8` → correct bytes. Promoted 90%→98.3% (remainder was register-allocation diff).

---

---

<a id="feedback-ido-pointer-walk-loop-unroll-guard-unflippable"></a>
## IDO -O2 auto-unrolls do-while pointer-walks with subu/andi alignment guard regardless of bounds origin

_For a do-while loop walking through memory clearing fields (`do { ptr += 4; ptr[-4]=ptr[-3]=ptr[-2]=ptr[-1]=0; } while (ptr != end);`), IDO -O2 emits TWO loops + a `subu/andi 0x3F` alignment guard. Whether `end` is `&extern_global` (separate symbol) or `D_array_base + 8` (same-array offset) doesn't matter — the auto-unroll triggers on the loop shape itself. 5 variants tried (do-while, for(i<8), explicit end, 8-way unroll, same-array end). Cap on func_80001184: 0% NM._

**Pattern (verified 2026-05-04 on func_80001184):**

```c
void func(void) {
    s32 *ptr = D_80012D3C;     /* array base */
    s32 *end = &D_80012D5C;    /* OR D_80012D3C + 8 — same emit either way */
    do {
        ptr += 4;
        ptr[-4] = 0; ptr[-3] = 0; ptr[-2] = 0; ptr[-1] = 0;
    } while (ptr != end);
}
```

Target asm is a single 4-store loop (8 insns):
```
addiu v1, v1, 0x10
sw zero, -0x10(v1)
sw zero, -0xC(v1)
sw zero, -0x8(v1)
bne v1, v0, .L
sw zero, -0x4(v1)
```

IDO -O2 emit is a duplicate-loop + alignment guard:
```
subu a1, a2, a3      ; (end - start) bytes
andi a1, a1, 0x3F    ; bytes mod 64
beq a1, zero, .skip  ; if mod-64-aligned, skip the residual loop
... residual single-step loop ...
.skip:
... 4-at-a-time loop ...
```

Even with `end = D_80012D3C + 8` (same array, compile-time-known offset), the
emit is unchanged. IDO doesn't propagate the same-array constraint into
the alignment-guard pass; it always emits the guard for safety.

**Variants tried (all 5 produce equivalent shape, all 0% NM):**
1. `do { ... } while (ptr != end)` (the one shown above)
2. `for (i = 0; i < 8; i++) D_80012D3C[i] = 0` — different shape, also unrolled
3. Explicit `s32 *end = &D_80012D5C` — same as variant 1
4. 8-way explicit unroll (no loop) — different shape, doesn't trigger guard
   but emits 8 lui/sw pairs with different relocs than target
5. `end = D_80012D3C + 8` — same-array offset, same auto-unroll emit

**Why "no flippable knob from C":** the auto-unroll happens in IDO's loop
optimizer pass before alignment analysis. The C source's bound expression
(extern symbol vs same-array arithmetic) doesn't reach that pass — it's all
flattened to a `while ($ptr != $end_reg)` shape by then. The target was
likely compiled with a different IDO flag set OR with a `memset`-style
intrinsic call that compiled inline.

**How to apply:** if you see this auto-unroll-with-guard cap on a do-while
pointer-walk, don't grind variants on the loop shape — the cap is in IDO's
optimizer. Instead document the cap and move on.

**Origin:** 2026-05-04, func_80001184 5th-variant grind. Wraps doc was
already documenting 4 prior variants as failed; the 5th confirms the
loop-optimizer-pass nature of the cap.

**2026-05-07 UPDATE — `while(1) { body; if (cond) break; }` DEFEATS the cap.**

The 7th variant on func_80001184 was a structural reshape from `do-while` to:

```c
while (1) {
    ptr += 4;
    ptr[-4] = 0; ptr[-3] = 0; ptr[-2] = 0; ptr[-1] = 0;
    if (ptr == end) break;
}
```

This produces target's SINGLE-LOOP shape (no duplicate, no `subu/andi` guard). Confirmed via standalone IDO -O2 build. The auto-unroll trigger is keyed on detecting a count-bounded `do-while`/`for` shape that the loop optimizer can prove has a constant trip count from bound expressions. `while(1) { ...; if (...) break; }` looks like an unbounded loop with an early-exit to the optimizer, so the unroll pass doesn't kick in.

**Why this works where 5 prior variants didn't:** the prior variants all kept the `do-while` or `for` keyword as the loop construct. IDO's loop optimizer recognizes those as count-bounded by walking the condition expression. `while (1)` with internal `break` is parsed as an infinite loop and the optimizer skips it.

**Apply this whenever:**
- Target has a single-iter loop body of zeroing/copying stores
- Your IDO -O2 emit duplicates the body with a `subu/andi 0x3F` alignment guard prefix
- Bound is an extern address or same-array offset

Switch the `do-while` to `while(1) { body; if (cond) break; }`. An explicit
label/goto loop with the condition at the tail works for the same reason and
is sometimes the more direct way to preserve the target back-edge shape.
Verified on func_80001184 (kernel_000.c).

---

---

<a id="feedback-ido-unsigned-char-param-homes-and-extends"></a>
## Declare a byte arg as `unsigned char` to reproduce its `sw aN` home + `andi 0xFF` zero-extend (and the s-reg-order caveat that follows)

When a target both **homes** an incoming int-register arg to its shadow slot AND **zero-extends** it to a byte before use:

```
move    s3,a1
andi    s4,a2,0xff      # zero-extend a2 -> s4, hoisted before the loop
andi    s5,a3,0xff      # zero-extend a3 -> s5
sw      ra,52(sp)
sw      a2,64(sp)       # dead home of full a2
sw      a3,68(sp)       # dead home of full a3
```

…the args (a2, a3) are **`unsigned char` parameters**. Two competing C shapes:

- `int a2` + `cb(p, a1, a2 & 0xFF, ...)` → produces the `andi` mask but **NO home** (`sw a2,64`). Comes out 2 insns short.
- `unsigned char c2` → produces the home **and** the hoisted `andi` zero-extend together. This is the cleanest way to match a dead-arg-home that coexists with a byte mask (the home appears *only* with the char type; `&a2`-address-taking would also home it but adds a reload).

**CAVEAT — eager extension flips $s-reg order (verified 2026-05-29, gl_func_0000A7B4).** The char zero-extends are emitted EAGERLY at the prologue, so the extended pseudos (c2, c3) are *born before* a sibling plain-`int` arg's loop-invariant copy (e.g. `move sX,a1`, hoisted out of the loop after the prologue). Born-earlier-but-shorter-range char pseudos grab the LOWER $s-regs (s3, s4); the int arg lands one $s higher (s5) than the target wants (target: a1/c2/c3 → s3/s4/s5; IDO emits c2/c3/a1 → s3/s4/s5). **Char-arg homing and "int-arg-first allocno order" are therefore mutually exclusive** — no C shape gives both. A function needing both lands as a clean cyclic $s-reg renumber with everything else (size, control flow, homes, hoisted masks) byte-exact. NM-wrap that residual; it's the documented reg-renumber cap, not a logic miss.

---

<a id="feedback-ido-precall-arg-spill-unreachable"></a>
## IDO pre-call outgoing-arg spills (`sw aN, N(sp)` before jal) — **SOLVED 2026-05-28: pass the pair as a struct by value** (this "cap" was WRONG)

**DISPROVEN — see [`#feedback-ido-struct-by-value-homes-arg-pair`](#feedback-ido-struct-by-value-homes-arg-pair).** The `sw a1,4(sp); sw a2,8(sp)` outgoing home-stores are produced by passing the adjacent int pair AS A 2-INT STRUCT BY VALUE: `f(x, *(Pair2*)p, k)` (NOT `f(x, p[0], p[1], k)`). IDO places the struct in a1,a2 and homes them to sp+4/sp+8. Verified on game_uso_func_00011168 (61.2%→93.92%). The text below (claiming "no C variant reproduces these spills") is retained only for historical context — it was wrong because it never tried struct-by-value.

**FAMILY-WIDE SWEEP RESULT (2026-05-28).** The entire game_uso "E2C-family" cluster — every NM wrap that passed an adjacent `D[]` int pair to a USO call — was previously labeled with an assortment of distinct-sounding "NATURAL CEILING" sub-caps: _precall-arg-spill_, _constant-address-fold_, _t8/t0-base form for the D-table reload_, _3rd-call tail reshape_, _base-adjust register names_, even a _58% ceiling_ and a _trailing alt-entry stub boundary_. **All of these were the same single root cause — the un-homed pair — and ALL fell to struct-by-value.** 11 byte-exact matches landed in one session from this one lever: `game_uso_func_` `00010DC8 / 00011368 / 000113C8 / 000114FC / 0000FA54 / 0001001C / 0000FABC / 00010FB8 / 0000D8A8 / 000105DC / 00010B38`. Two needed a companion: D8A8 also needed the inlined-deref trick (named `t6` local landed the B4-child in `$v0`; inlining `*(int**)(a0+0xB4)` into the if-condition shifted it to `$t6` for the target's contiguous t6/t7/t8 numbering). **Lesson: do not trust a "NATURAL CEILING" / sub-cap label on a pair-passing function — the various symptom names were all artifacts of one missing transform.** The lone genuine residual in the family is `game_uso_func_0000F948`, which has a real FPU Vec3 copy-chain body + frame-size mismatch BEYOND the pair (the pair component there is now solved too); that one is a separate multi-tick FPU-matching problem, not this cap.

**EXTENSION — 4-int / Quad stack buffers, not just 2-int register pairs (2026-05-28).** The same struct-by-value mechanism reproduces a fixed-stride stack buffer copied to a callee's *outgoing stack-arg area*. `game_libs/gl_func_00061934` builds a 4-float buffer (`vec[4]` via swc1) and the target then copies it **int-by-int** (`lw t,N(buf); sw t,M(sp)`) into the callsite stack args at sp+0x18..0x24. Passing the four values as individual float args (`f(..., vec[0],vec[1],vec[2],vec[3])`) emits `swc1` *directly* to the callsite (wrong path); passing `*(Quad4*)vec` (Quad4 = `struct{int a,b,c,d;}`) by value emits the int-by-int lw/sw copy, byte-exact. So: build the buffer with its natural float type, but hand it to the K&R callee as an int struct-by-value. Companion knobs that closed the last few diffs: `char pad[16]` to grow the frame (0x48→0x58), declare the buffer `vec[]` *before* the pad so it lands in the high stack slots, and write the zero-stores in the order IDO emits them (here 2,1,0 then the non-zero tail). Lesson: any "stack-arg buffer / fixed-stride copy" cap on a call into a K&R callee is a struct-by-value candidate regardless of element count.

**RECEIVING-SIDE analog — struct-by-value param forces the CALLEE's own dead arg-home-stores (2026-05-28, partial).** A function whose target homes its *incoming* register args at entry (`sw a1,4(sp); sw a2,8(sp)` with no later reload) gets those stores from declaring the corresponding incoming pair as a **struct-by-value parameter**: `f(int *buf, Pair2 p, int a3, int idx)` instead of `f(int *buf, int a1, int a2, int a3, int idx)`. This fixed `game_libs_func_0001D944`'s instruction count (36→39, matching target) where neither separate-int args (no homes emitted) nor the `(void)&a1`/`(void)&a2` address-taken trick (DCE'd away → no homes) produced the stores. **Caveat (unsolved):** the struct-by-value frontend treats the members as *memory*, so each `p.a`/`p.b` access RELOADS from the home slot, whereas the target keeps the value in the incoming register `$5`/`$6` AND has the home store as a *dead* store. That register-resident-plus-dead-home combo is a regalloc shape neither pure struct-by-value nor address-taken reproduces directly — left as a permuter candidate (logic + insn count correct, ~25 pure-regalloc diffs incl. cmd landing in `$v1` vs target `$t0`). Still: when a leaf's only "cap" is dead incoming-arg home-stores, the struct-by-value param is the way to materialize them.

_Some IDO-compiled functions emit extra `sw $a1, 4(sp); sw $a2, 8(sp)` stores IMMEDIATELY before a jal, saving the OUTGOING arg values (just loaded from global memory) into the caller's arg-save slots. When the callee is K&R (`extern int f();`) and the outgoing args are `*(int*)&D_XXX` reads, no C variant tried reproduces these spills — leaves a ~2-insn gap capping match at ~75-80%. [OBSOLETE — the missing variant was struct-by-value; see above.]_

**Pattern (target):**
```
lui    $tN, 0           ; load &D_XXX upper
addiu  $tN, 0xHHH       ; load &D_XXX lower
...
lw     $a1, 0($tN)      ; a1 = D_XXX[0]
sw     $a1, 4($sp)      ; ← extra spill of outgoing a1
lw     $a2, 4($tN)      ; a2 = D_XXX[1]
jal    0                ; gl_func_00000000 (K&R)
sw     $a2, 8($sp)      ; ← extra spill in delay slot
```

The `sw $a1, 4(sp)` and `sw $a2, 8(sp)` write the OUTGOING arg values to the caller's arg-save slots (sp+0..sp+0xC) before the jal. No post-jal code reads those slots.

**What it doesn't happen with (tried on `game_uso_func_0000D8A8`, 2026-04-20):**
- `gl_func_00000000(a0, D_00000E70[0], D_00000E70[1])` — with `extern int D_00000E70[];` as a file-scope array
- `gl_func_00000000(a0, *(int*)&D_00000E70, *(int*)((char*)&D_00000E70 + 4))` — inline pointer casts
- `int x = D_00000E70[0]; int y = D_00000E70[1]; gl_func_00000000(a0, x, y);` — named locals
- `register int *p = D_00000E70; gl_func_00000000(a0, p[0], p[1]);` — register hint (actually regressed from 74.6% to 71.8%)

All emit the same 15-insn layout without the pre-call spills. Callee is declared K&R (`extern int gl_func_00000000();`) at file scope per `feedback_ido_unspecified_args.md`.

**Hypothesis:** target was built from a different callee declaration (e.g. a prototyped `int gl_func_00000000(int, int, int)` somewhere the spill is needed, or a compiler pragma forcing K&R-style). Could also be an IDO version / flag difference. Not currently cracked.

**Practical rule:** for null-check + 3-arg call patterns on game_uso / similar USO code, wrap NM at ~75%. Don't grind past 10 attempts — the diff is a 2-insn "pre-jal arg-save" gap that no tried C form triggers. The wrapped C is still useful as semantic-reference.

**Related cap stones:** `feedback_ido_f2_intermediate_unreproducible.md`, `feedback_ido_return_flowing_v0_unflippable.md`, `feedback_ido_sw_before_addu_unreachable.md`, `feedback_ido_spill_slot_picks_low_offset.md`, `feedback_ido_arg_save_reg_pick.md` — all similar "scheduler picks X, no C form flips to Y" cap stones.

**Origin:** 2026-04-20, game_uso_func_0000D8A8 NM wrap at 74.6% after trying 5+ variants.

**2026-04-20 update (game_uso_func_0000A374, 86.7% cap):** even using an aliased callee (`gl_func_00000000_va` → 0x0 in undefined_syms, distinct from shared `gl_func_00000000`) does NOT trigger pre-jal spills:
- `extern int gl_func_00000000_va();` (K&R) — no spill
- `extern int gl_func_00000000_va(int, ...);` (varargs) — no spill

Trying to declare the callee varargs via a LOCAL `extern int gl_func_00000000(int, ...);` inside the caller function FAILS with cfe error: `"prototype and non-prototype declaration found for gl_func_00000000, ellipsis terminator not allowed"`. IDO's cfe won't tolerate file-scope K&R + function-scope varargs for the same symbol. Workarounds: use a distinct alias name (unique-extern pattern), but IDO still doesn't emit the pre-call spills for the aliased varargs call.

**Cross-family extent (2026-05-07 audit):** in 1080's game_uso this cap applies family-wide to a 7+ function cluster sharing the same "alloc + 2-call + null-init + table-lookup-then-call" shape:
- `game_uso_func_0000A374` (86.7%)
- `game_uso_func_0000D8A8` (74.6%)
- `game_uso_func_00010DC8` (88.6%)
- `game_uso_func_00010E2C` (88.6%)
- `game_uso_func_00011124` (~88%)
- `game_uso_func_00011368` (87.4%)
- `game_uso_func_000113C8` (86.9%)
- `game_uso_func_000114FC` (~88%)

When you encounter a new game_uso function that grinds to 86-89% with the same structure (table at `&D_00000000+OFFSET`, two `lw` reads adjacent, single downstream call after the table reads), don't re-test the entire knob set — confirm this pattern by checking the 2nd jal's delay slot for `sw a1/a2, N(sp)` precall spills and wrap NM directly. Future cluster-wide promotion would need INSN_PATCH per call site (not C-level levers).

Bottom line: this cap is not fixable from any C-level declaration variation we've tested. Permuter-grinding is the only remaining recourse.

**2026-05-02 expansion (game_uso_func_0000FABC, 18-insn 3-call wrapper):**

Decomposed the blocker into TWO independent issues:

**Issue 1: Base-adjust in address load** (`addiu $tN, +0xE40; lw 0($tN); lw 4($tN)` instead of natural `lw 0xE40($tN); lw 0xE44($tN)`).

This IS reachable. Recipe: declare `extern int gl_log_args_E40[2];` and add `gl_log_args_E40 = 0x00000E40;` to `undefined_syms_auto.txt`. Then access as `gl_log_args_E40[0]` / `gl_log_args_E40[1]`. IDO emits `lui+addiu(%lo)+lw 0(reg)+lw 4(reg)` — after link relocation patches, this becomes the target's `lui+addiu(0xE40)+lw 0+lw 4` exactly. Verified with standalone IDO 7.1 build of `extern int D_at_E40[]; ... D_at_E40[0]; D_at_E40[1]`.

So the "base-adjust trick is unreachable" claim from `feedback_ido_base_adjust_for_clustered_offsets.md` is technically wrong — it's reachable for ANY cluster of accesses around a constant offset `&D + N`, by declaring an extern array at that absolute address.

**Issue 2: Variadic-style stack spill** (`sw $a1, 4(sp)` before jal, `sw $a2, 8(sp)` in jal delay slot).

Tested 2026-05-02 — none of these flip it:
- IDO 7.1 vs IDO 5.3 (same output)
- `-Wf,-y/-Y/-Xv`, `-Wb,-coff` flag combos
- Function pointer call: `(*fp)(a0, x, y)` where `extern int (*fp)(int,int,int);` — no spill
- Struct field access: `s.a, s.b` instead of named locals — no spill
- 5-arg call (forces stack arg): triggers `sw zero, 16(sp)` for arg 5, but NOT `sw $a1, 4(sp)`
- 4-arg call with explicit `(int, int, int, int)` prototype — no spill
- volatile address-of args — emits `sw $a1, 28(sp)` to a LOCAL slot, not sp+4

Tested 2026-05-05 — none of these flip it either:
- `volatile int x = p[0]; volatile int y = p[1]; func(a0, x, y);` — frame grew
  by 16 bytes (volatile locals), emits `lw t7,0(p); lw t8,4(p); sw t7,SPILL_LOC;
  sw t8,SPILL_LOC; lw a1,SPILL_LOC; jal; lw a2,SPILL_LOC` 6-insn round-trip,
  significantly worse shape (18 insns vs target's 17, 14 vs target's 17 was
  baseline). Volatile forces the loads to live in stack slots independent of
  arg-save area; doesn't reach the sp+4/sp+8 outgoing-arg slots target uses.
- `int *p = (int*)&D_E70;` declared BEFORE the `if` (instead of inside) —
  IDO assigns lui directly to $a1 / $a2 (one each, two separate luis, no
  shared addiu+base register), emits `lw a1, 0(a1); lw a2, 4(a2)` self-base
  loads. 14 insns total but the lui+addiu+lw+lw shape is GONE — replaced by
  2× `lui aN; lw aN, 0/4(aN)`. The hoisted-lui pattern is even further from
  target than the in-block declaration.

Conclusion: the spill is NOT reachable from IDO 7.1 / 5.3 with any tested input. Likely the original was built with a non-IDO toolchain (KMC GCC?) for these specific log-printf-like helpers, or with an IDO patch we don't have.

**Practical:** for the ~15-30 functions in game_uso following this 3-call log-printf pattern, partial fix #1 (base-adjust via extern array) shaves the diff from 4 insns to 2 insns, but #2 (the spills) keeps them from byte-exact. NM-wrap is the only option until the missing toolchain artifact is identified.

---

---

<a id="feedback-ido-reg-only-store-ordering"></a>
## IDO -O2 multi-arg setters — put register-only stores LAST in source order to keep stack-arg lw/sw pairs adjacent

_For 6+arg setters where stack args (sp+0x10, sp+0x14) go to struct fields, IDO's scheduler hoists cheap register-only stores (`sw aN, N(a0)`) into load-use gaps. Putting the register-only store last in source order places it between the last stack-arg `lw` and `jr`, so the last-stack-arg `sw` fills the delay slot naturally._

**Rule:** For IDO -O2 void setter wrappers with mixed register and stack args, write the C stores in this order:
1. Register-only stores first (in target order)
2. Stack-arg lw+sw pairs next (in target order)
3. The **register-only store that corresponds to the last `sw <Xreg>, <offset>(a0)` BEFORE `jr ra`** goes LAST
4. The stack-arg `sw` in the delay slot will be from the PENULTIMATE C statement

**Why:** IDO's scheduler tries to keep `lw tN; <something>; sw tN` together for load-use separation (legacy MIPS I habit, harmless but real on MIPS II). If a cheap register-only `sw aX` sits between a `lw tN` and its `sw tN`, the scheduler hoists it there — giving a different instruction order than target. Putting the register-only `sw` after all lw+sw pairs forces it to schedule after the last lw+sw completes. IDO then moves it BEFORE jr and fills the delay slot with the previous statement's sw.

**Example (1080/bootup_uso/func_00002060):**

Target (0x20 = 8 insns):
```
sw a1, 0x80(a0)       # arg1 → 0x80
sw a2, 0x84(a0)       # arg2 → 0x84
lw t6, 0x10(sp)       # arg4 from stack
sw t6, 0x88(a0)
lw t7, 0x14(sp)       # arg5 from stack
sw a3, 0x8C(a0)       # arg3 here — AFTER lw t7
jr ra
sw t7, 0x7C(a0)       # delay slot
```

**WRONG** (source order matches asm/ observation order):
```c
void func_00002060(char *a0, int a1, int a2, int a3, int a4, int a5) {
    *(int*)(a0 + 0x80) = a1;
    *(int*)(a0 + 0x84) = a2;
    *(int*)(a0 + 0x88) = a4;
    *(int*)(a0 + 0x8C) = a3;    /* ← sw a3 hoisted between lw t6 and sw t6 */
    *(int*)(a0 + 0x7C) = a5;
}
```
Produces wrong schedule: `lw t6; sw a3, 0x8C; sw t6, 0x88; lw t7; jr; sw t7, 0x7C`.

**RIGHT** (move register-only `= a3` store to LAST):
```c
void func_00002060(char *a0, int a1, int a2, int a3, int a4, int a5) {
    *(int*)(a0 + 0x80) = a1;
    *(int*)(a0 + 0x84) = a2;
    *(int*)(a0 + 0x88) = a4;    /* stack-arg pair 1 */
    *(int*)(a0 + 0x7C) = a5;    /* stack-arg pair 2 (will fill delay) */
    *(int*)(a0 + 0x8C) = a3;    /* register-only, last → IDO schedules after lw t7 */
}
```
Matches exactly.

**How to apply:**
- When decompiling an N-arg setter: identify which args are from stack (first 4 in regs + rest on stack at 0x10(sp), 0x14(sp), ...)
- In the target asm, identify the sw in the jr delay slot — that's your 2nd-to-last statement in C
- Any register-only `sw aN, N(a0)` that appears AFTER its stack-arg pair in the target — put it LAST in C

**Related:** A similar issue blocks `func_000020AC` (82 %, NON_MATCHING-wrapped) — "swap-of-independent-stores scheduling issue." Same family of fix; try reordering the final two stores if stuck at ≥80 %.

**Origin:** 2026-04-19, 1080 bootup_uso/func_00002060 (6-arg struct setter).

---

---

<a id="feedback-ido-register"></a>
## IDO register keyword for $s0 allocation

_IDO respects 'register' as a strong hint — required to match libultra interrupt-bracket functions_

IDO 7.1 (and 5.3) respects the `register` storage class as a **strong hint** for callee-saved register allocation. Without it, IDO spills to stack.

**Pattern:** `register s32 sr = func_800066B0();` → `or $s0, $v0, $zero`
**Without:** `s32 sr = func_800066B0();` → `sw $v0, offset($sp)` (stack spill)

**Why:** OoT and all matching N64 decomps use `register` for interrupt state variables. IDO's default heuristic at -O1/-O2 prefers stack over $s0 unless told otherwise.

**Caveat — `register` is REDUNDANT when weight-based allocator already wants $s:** the keyword is a hint, not a directive. For locals with high enough refs/live_length weight (e.g. read across N≥3 jal calls), IDO promotes them to $s automatically. Removing `register` is a no-op in those cases. Verified on `n64proc_uso_func_00000014` (2026-05-07): all 5 register-typed locals (`base`, `base10`, `cur`, `flag`, `one`) produced byte-identical .o whether `register` was on all five, just one, or none. The earlier "remove register → regress to 33%" claim from that function's wrap log applied to a pre-goto-chain shape; in the current shape the allocator's weight calc already gives all 5 their $s slots. Bottom line: add `register` opportunistically (no harm), but don't pile on more variants assuming a missing `register` hint is what's blocking the match — verify with cmp on .o bytes between with-and-without-keyword forms first.

**How to apply:** For ANY function that saves a call result in $s0 across subsequent calls, add `register` to the variable declaration. This applies to all disable-int/do-work/restore-int patterns in libultra.

**Leaf function variant (O1):** `register` also changes register allocation in leaf functions at -O1. `register u32 status = *(volatile u32*)0xA4800018;` loads into `$a0` with no stack spill. Without `register`, IDO loads into `$t7` and spills to stack in the branch delay slot. This is the pattern for `__osSiDeviceBusy` and similar HW status checks.

**Unused-arg-reg variant (O1, polled HW reads):** `register u32 s; s = HW_REG;` with the variable read repeatedly in a loop pushes IDO to allocate `s` to `$a2` (the first unused arg reg) instead of `$t7`/`$t0`. Without the hint IDO picks the next free temp and every downstream register name shifts. This is the difference between matching and not for `func_800029B0` (PI bus read in 1080 Snowboarding) and any libultra function that wait-loops on a HW status reg. Pattern:
```c
register u32 s;
s = PI_STATUS;
if (s & 3) { do { s = PI_STATUS; } while (s & 3); }
```

**IDO -O2 unused arg saves:** At -O2, `void func(s32 arg) {}` still generates `sw $a0, 0($sp)` — IDO saves all args to the caller's save area even when unused. This means empty functions and "return constant" functions with args are matchable at -O2.

**`s32` vs `u8` for "saved byte" check (strcpy-style loops):** When you need IDO to emit `or $a3, $a2, $0` (a 32-bit move) for the loop-condition variable instead of `andi $a3, $a2, 0xff` (8-bit truncation), declare the saved-value variable as `register s32`, not `register u8`. The byte load (`lbu`) zero-extends into a 32-bit register, and an s32 destination just needs a `move`; a u8 destination forces the truncate. This was the difference between matching and not for `func_80006754` (1080's `__osStrcpy`).

**Pre-iteration + `while` instead of `do-while` (loops with first-iter side effects):** When the target asm has a "pre-loop block that always runs once" followed by a near-duplicate loop body, write the pre-iter explicitly then a `while`. A `do-while` collapses both bodies into one tight loop in IDO -O1, halving the instruction count. Pattern:
```c
// pre-iter (always runs once)
c = *src; dst++; src++;
saved = c;
*(dst-1) = c;
while (saved != 0) {
    c = *src; dst++; src++;
    saved = c;
    *(dst-1) = c;
}
```
A `do { ... } while (c)` produces fewer instructions but does NOT match the original ROM layout for libultra strcpy/memcpy primitives.

**Hoist a body statement OUTSIDE the guarding `if` to control beqz delay-slot fill:** IDO's scheduler decides what to put in the delay slot of `beqz` (the early-exit guard at function entry). It picks between the prologue (`addiu $sp, -N`) and a body statement based on what's "available." When you write:
```c
if (ctr != 0) {
    n--;        // inside the if — IDO puts prologue in delay slot
    do { ... } while (ctr != 0);
}
```
IDO emits `beqz a3, end / addiu $sp, -8` (prologue in delay slot, n-- after). But when you hoist:
```c
n--;            // outside the if — runs regardless
if (ctr != 0) {
    do { ... } while (ctr != 0);
}
```
IDO emits `addiu $sp, -8 / beqz a3, end / addiu $a2, -1` (prologue first, n-- in delay slot). The hoisted n-- becomes the delay-slot candidate. Matters for ROM-byte matching when the target has prologue at instruction 1.

**No-temp inline `*dst = *src` for memcpy bodies:** With `c = *src; ...; *(dst-1) = c;` IDO at -O1 either spills `c` to stack ($t6 with sw/lw pair) or uses `$t0` (with `register`). Writing `*dst = *src` directly with no named temp lets IDO's scheduler keep the load result in `$t6` across the loop body without spilling — matching libultra memcpy primitives. Pattern:
```c
do {
    *dst = *src;
    ctr = n;
    n--;
    dst++;
    src++;
} while (ctr != 0);
```
The store happens before the increments, but IDO schedules `addiu $a0, +1 / addiu $a1, +1 / bnez ... / sb $t6, -1($a0)` so the store ends up in the bnez delay slot using `$t6` from the earlier `lbu`. Apply when the target has `lbu $t6, 0($a1)` at top of loop and `sb $t6, -1($a0)` in the bnez delay slot.

**Use the permuter even when its output looks wrong:** When `decomp-permuter` finds a low-score candidate that's semantically broken (e.g. wrong offset because it dropped a temp variable), the *structural* changes it made are still informative. For func_800066F0, the permuter's score-10 candidate had `n--;` hoisted outside the `if` — semantically equivalent but I'd never have tried that manually. Read the permuter outputs with `for f in nonmatchings/output-*/source.c; do echo === $f; cat $f; done` and look for structural patterns, not literal copy-paste.

**Merging fragments with named alt-entry points: OK for objdiff, breaks runtime:** When `func_X` has a contiguous tail fragment `func_Y` AND `func_Y` has callers (`jal func_Y` in other asm), merging them works fine for objdiff scoring — the callers' .o files have a relocation to the `func_Y` symbol, which we set = 0xY_addr in `undefined_syms_auto.txt`, and the relocation bytes match the original. **But** the resulting ROM is runtime-broken: in our shifted layout, address 0xY_addr no longer contains the alt-entry's instructions, so any `jal func_Y` jumps to garbage. Since this project never executes the ROM (only byte-compares against baserom), the runtime issue is irrelevant for matching progress. The 1080 kernel has at least one such pair: `func_80004FD0` + `func_80004FE0` (5 callers of FE0, merged and counted as matched).

**Unused `f32 dummy = 0.0f` preserves mtc1+swc1 in the prologue:** Like `char pad[4]` forces an unused stack slot, declaring `f32 dummy; ... dummy = 0.0f;` forces IDO to emit `mtc1 $zero, $f4 / swc1 $f4, OFFSET($sp)` even though the value is never read. Required for matching libultra/rmon functions that zero a float local at entry (often as part of FPU pipelining or unused stale state). Declare `dummy` FIRST among locals so it gets the highest stack offset.

**Aliasing memory write between assign and use forces IDO to keep an `if` check:** When the target asm has `if (counter < N)` after `counter = 0` followed by an unrelated store, IDO at -O1 sometimes constant-propagates `counter` through the if and elides the check. To force IDO to keep the check, sequence the C so the assignment happens BEFORE an unrelated memory write that IDO can't prove doesn't alias the counter's stack slot. Pattern from `func_80006FF8` (rmon reply):
```c
totalRecv = 0;        // store to stack
*arg0 = arg1;          // unrelated memory write — IDO can't prove no alias
p = (char*)&arg1;      // takes address of stack slot — adds to alias uncertainty
if (totalRecv < 4) ...  // IDO RELOADS totalRecv from stack and emits slti+beqz
```
Without the alias-creating store/address-of in between, IDO collapses `if (totalRecv < 4)` to true and skips the check. Also: declaration order of `char* p; s32 totalRecv;` (vs the reverse) determines stack offsets, and only one ordering will produce the exact target offsets — try both.

**`char*` cast is symmetric — use it only when target uses register-indexed addressing (IDO -O1):** The existing memory entry says "use `*(s32*)((char*)&buf + 0x14) = val` when asm uses `addiu $tN, $sp, base; sw $val, offset($tN)` (register-indexed)". The converse is equally important: when target uses **direct sp-relative** addressing like `sw $t4, 0x40(sp)`, you must NOT use the char* cast — it will force IDO to emit `addiu $tN, $sp, base; sw` (register-indexed) and cost you 2 extra instructions per store. For direct sp-relative targets, define a typed struct with fields at the exact offsets you need (add `char pad_NN[M]` fillers between fields) and assign via `buf.field_NN = val`. For `func_8000894C`, target had `sh $t8, 0x48(sp); sh $t9, 0x4A(sp); sw $t4, 0x40(sp)` so I made a struct with `s16 field_24; s16 field_26; s32 field_1C` at those offsets and matched directly. Rule of thumb: if target schedules an `addiu $tN, $sp, X` right before a group of stores, use char*; otherwise use typed struct.

**"Repeated `lui/addiu` for the same global" in target asm = target was compiled at -O1, not -O2 (IDO):** If you decompile at -O2 and your build uses `$s3 = &g; ...; func($s3); ...; func($s3)` (address hoisted once, reused) but the target asm does `lui $a0, %hi(g); addiu $a0, $a0, %lo(g); func(); ...; lui $a0, %hi(g); addiu $a0, $a0, %lo(g); func()` (reloaded each call site), IDO is hoisting at -O2 where the original didn't. This is a strong signal to move the function to an -O1 file. This is especially common for thread functions with `while(1) { ... func(&g, ...); ... }` bodies — -O2 sees `&g` as loop-invariant and promotes it to a callee-save `$s` register; -O1 doesn't do loop-invariant code motion for global addresses, so the lui/addiu is emitted each iteration. For `func_800051F0` (rmon RdbReadThread), splitting from kernel_004 (-O2) to kernel_055 (-O1) dropped non-jal diff count from 46 to ~0 (linker-resolvable).

**IDO -O2 `$v0` vs `$a1` for shift/mask temps — hard to override:** For a leaf classifier like `func_800087B4` (extract 6-bit opcode, branch on it), target emits `srl $a1, $a0, 26; andi $t6, $a1, 0x3F; or $a1, $t6, $0` — using `$a1` (an unused arg register) for the opcode temp. My IDO emits `srl $v0, $a0, 26; andi $v0, $v0, 0x3F` using `$v0` (return register) instead. Tried `s32` vs `u32` opcode, inline vs split expression, `register`, `switch` — all produced `$v0`. Target's `$a1` choice is probably driven by surrounding code context (e.g. extra tmp that pushes `$v0` to arg-reg) that isn't easily reproducible from the minimal C. For single-arg leaf functions doing bit extraction, accept NON_MATCHING if the only diff is `$v0` ↔ `$aN` for a shift result. Don't burn hours — 37 instructions logically identical is already a full decomp.

**IDO -O1 won't hoist `p = msg` into a jal delay slot — pick your battles:** In target asm like `jal func(msg); lw $s0, 0x38(sp)  # delay`, IDO is promoting `msg` (an arg) to `$s0` (callee-save) by reading it back from the caller-save area in the jal delay slot. This pattern cannot be reliably reproduced from C. I tried for `func_8000969C`:
 - `p = msg;` BEFORE the if-check → IDO eagerly emits `or $s0, $t6, 0` via a $t6 intermediate (extra instructions, wrong layout)
 - `p = msg;` AFTER the if-check → IDO emits `lw $s0, 0x38(sp)` AFTER the branch, not in the delay slot; and fills the delay slot with a pointless `lw $a0, 0x38(sp)` reload
 - `register RmonMsg* p = msg;` at declaration → same as eager form
 - `register s32* msg` on parameter, no `p` variable → IDO doesn't promote msg at all, just reloads inside the loop
 - `p = msg;` as unreachable statement AFTER `return 0;` (permuter's best score-15 trick) → IDO allocates $s0 for p but still doesn't emit the delay-slot load

The permuter confirmed this with 14k iterations, best score 15 (not 0). Conclusion: when target has this "promote arg in jal delay slot" pattern, wrap as NON_MATCHING — don't burn hours on it. Sign of this pattern: target's jal delay slot is `lw $sN, <argsave_offset>(sp)` where $sN is a callee-save register that holds msg through the rest of the function.

**Last struct store before a `jal` is the delay-slot candidate (IDO -O1):** When you write `pkt.A = x; pkt.B = y; pkt.C = z; func(&pkt, ...);`, IDO schedules the last store (`pkt.C = z`) into the jal delay slot — *if* its source load can be pulled forward to fill the non-delay gap. The earlier stores get emitted in front of the jal in whatever order keeps load→store pipelines tight. This means you can **choose which store lands in the delay slot by making it the last statement in C**. For `func_800091FC` I wrote `field_0C; type; flags` → `sb type` ended up in delay (target had `sb` in delay). For the sibling `func_80009148` the target had `sw field_0C` in delay instead, so I wrote `type; flags; field_0C` — same three stores, different final-statement → different delay-slot pick. Siblings with identical structure can still need opposite C orderings.

**Timing of `register p = msg` vs `register p; ...; p = msg`:** `register RmonMsg* p = msg;` (initializer at declaration) makes IDO assign `$s0` from the start and use it for the first access → `lw $s0, 0x40(sp); ... lbu $t7, 0x9($s0)`. Whereas writing `register RmonMsg* p; /* no init */` followed later by `p = msg;` produces `lw $t6, 0x40(sp); ... lbu $t7, 0x9($t6); or $s0, $t6, 0` — IDO reloads the arg into `$t6` (the natural arg-reload register at O1), uses `$t6` for the first access, THEN emits `or $s0, $t6, 0` at the exact source line where `p = msg;` appears. Crucially, placing `p = msg;` BEFORE the early-exit guard (`if (msg->field_09 != 0) return -2;`) puts the `or $s0, $t6, 0` right after the initial arg reload. Placing it AFTER the guard pushes IDO to emit `lw $s0, 0x40(sp)` (a fresh stack reload) much later in the code. This was the matching/non-matching difference for `func_800091FC` in 1080 Snowboarding.

---

---

<a id="feedback-ido-register-keyword-doesnt-block-constant-fold"></a>
## IDO `register T x = const;` does NOT prevent constant-folding through reads of x

_Declaring `register int one = 1;` in IDO -O2 does NOT pin `one` to a $s-register for all reads. IDO's constant-propagation pass folds the literal `1` through every read site BEFORE register allocation. So `flag = one;` emits `addiu s1, zero, 1` (literal), byte-identical to `flag = 1;`. Implication: when grinding for "$s-reg vs literal" diffs, don't assume `register int x = N;` keeps the read-site as an `or`-from-$s. IDO will constant-fold and emit the literal regardless._

**Rule:** In IDO 7.1 -O2, a local declared `register int x = const_expr;` whose later reads compile to literal-immediate insns is constant-folded BEFORE the register allocator runs. The `register` keyword influences only spillability for non-constant-folded reads; it does NOT block the optimizer's CSE/constant-propagation pass.

**Verified 2026-05-05 on `n64proc_uso_func_00000014`:** the function declares `register int one = 1;` and uses `flag = one;` at two sites (post-jal flag-set in body0/body1). Two builds:
- C with `flag = one;` → emits `addiu s1, zero, 1` at both sites.
- C with `flag = 1;` → emits `addiu s1, zero, 1` at both sites.
- `cmp build/.o build/.o` → IDENTICAL.

This means the matching technique of "use `register int one = 1; flag = one;` to emit `or rD, $s_one, $zero`" does NOT work in IDO. The compiler folds the constant through the assignment regardless of register hints.

**Why this is non-obvious:** GCC handles `register` slightly differently — older GCCs sometimes preserve the variable's read site as an actual register-source. IDO's optimizer is more aggressive about constant-prop on register-locals. So tactics borrowed from GCC matching guides ("use register int one = 1; to keep one in a $s") fail silently — the bytes don't change but you might assume they did because the build still hits a fuzzy plateau.

**How to apply:**
- Don't use `register int x = compile_time_const;` as a knob to force "$s-reg-source" instruction shape. It won't work; IDO folds the constant in.
- If your target uses `or rD, $sN, $zero` where $sN holds a constant, the source has a NON-constant assignment chain into $sN, OR target was compiled at a different opt level / with different IDO flags. From the same -O2 source you cannot reach this shape via constant-only locals.
- The OTHER case still holds: `register int *base = &D_X;` (pointer-to-extern) IS preserved as $s-reg in some cases — pointer assignments aren't constant-folded the same way, since the address is link-resolved. So `register T*` for extern-derived addresses can still affect codegen even when `register int = literal` cannot.

**Same fold applies to comparison immediates (sltu+addiu vs sltiu).** When the C is `unsigned int chunk = 0x2710; if (len < chunk) ...`, IDO -O2 folds `chunk` to its constant and emits `sltiu at, len, 0x2710` (immediate form) — even though chunk is a named local with a long live range that spans the call and gets spilled to $s0. Target's `addiu s0, 0, 0x2710; sltu at, len, s0` (register form) is unreachable from this source — same root cause as the `flag = one` example: constant-prop runs before reg-alloc. Verified 2026-05-15 on `gl_func_00066720` (chunked-copy loop, 17/29 = 58.6% cap). Knob to break it would need an opaque 0x2710 (extern const, memory load, or `__asm__("" : "+r"(chunk))` barrier) — none of which the source likely had.

**Companion memos:**
- `feedback_ido_local_ordering.md` — IDO's local-declaration order doesn't drive $s-reg numbering (allocator is weight-driven).
- `feedback_unique_extern_with_offset_cast_breaks_cse.md` — for pointer-to-extern, you CAN break CSE with a proxy zero, at the cost of register-renumber penalty.
- `feedback_ido_no_gcc_register_asm.md` — IDO rejects `register T x asm("$N")`, so explicit register binding is unavailable.

---

---

<a id="feedback-ido-register-promotes-class-not-number"></a>
## IDO `register` keyword promotes to $s-class but doesn't pin the $s-number

_Adding `register T x;` on locals forces IDO to allocate them to callee-saved $s-regs instead of caller-saved $t/spills. But WHICH $s-number (s0 vs s1 vs s2...) remains weight-driven (refs × live-length per `feedback_ido_sreg_order_not_decl_driven.md`). Useful to unblock a "0% in $t-regs" starting point to a "N% in $s-regs but wrong numbers" intermediate — permuter can then hit the right numbers._

**Rule:** The `register` keyword on an IDO local is a class-level hint: "put me in a callee-saved register." It does NOT dictate which $s-register (s0, s1, s2…).

**Why:** IDO's register allocator splits decisions into two phases:
1. **Class**: spill vs $t vs $s. The `register` keyword bumps a local from "leave as pseudo, pick at allocation time" into "prefer $s-class" (callee-saved, stable across calls). Worth it when you observe the local being spilled or reloaded through $t-regs around a jal.
2. **Number within class**: weight-driven (priority ≈ `floor_log2(n_refs) × n_refs / live_length`). The local with the highest weight gets the lowest number ($s0 < $s1 < $s2 …). Tied weights → first-encountered-pseudo wins.

The `register` keyword only affects phase 1. Phase 2 remains unchanged.

**How to apply:**
- If your output has locals in $t-regs / spills but target has them in $s-regs: add `register` hints. Expect percent to jump significantly.
- If after `register` hints your locals are in $s-regs BUT with different numbers than target: stop reordering decls (it's a no-op per `feedback_ido_sreg_order_not_decl_driven.md`) and either (a) redistribute refs (e.g., eliminate a local constant by inlining literals), or (b) run the permuter.
- Never combine `register` with `asm("$N")` — IDO rejects (see `feedback_ido_no_gcc_register_asm.md`).

**Example (n64proc_uso_func_00000014, 2026-04-20):**

Before (no `register`): locals spilled to stack and reloaded through $t6/$t7 around each jal. Target kept them in $s3/$s4/$s5.

After adding `register char *base`, `register int flag`, etc.: IDO promoted all 6 locals to $s0-$s5. But $s2=`base` in ours vs $s2=`one` in target — weight tiebreaker landed differently. Class promotion worked; number matching didn't.

**Signal to distinguish the two failure modes:**
- **Class miss**: you see `lw $t_N, N(sp)` reloads of your locals around jals; target has no spills. Add `register`.
- **Number miss**: you see `s2`/`s3`/etc. used consistently BUT swapped with target. Don't keep trying `register` — it won't help. Redistribute refs or permute.

**Origin:** 2026-04-20, agent-a, n64proc_uso_func_00000014 promotion from ~33% to partial-$s-reg allocation. All 6 locals ended up in $s-regs after adding `register`, but $s2/$s3 swap blocked byte match.

---

---

<a id="feedback-ido-return-flowing-v0-unflippable"></a>
## IDO picks $v0 (not $v1) when a literal flows to the return register — unflippable

_When asm has `addiu $v1, $zero, N` preloaded into a branch delay slot + `or $v0, $v1, $zero` at shared return block, IDO cannot reproduce this from C. IDO's allocator always picks $v0 directly for the value that flows to the return register. `register int r = N` is ignored because the value flows into the return register anyway. Unflippable pattern class — wrap NON_MATCHING._

**Recognition:** target has a shared-return block that ends with `or $v0, $v1, $zero` (i.e., `move v0, v1`), with `addiu $v1, $zero, N` pre-loaded into an earlier branch's delay slot, for a case where a value is only returned from multiple branches of a switch-like chain:

```
beq $a1, $at, shared_ret   ; 'n' check
addiu $v1, $zero, 0x8      ; delay: preload 8 in $v1
addiu $at, $zero, 0x73     ; 's'
beq $a1, $at, shared_ret   ; 's' check
nop                         ; delay (empty)
...
shared_ret:
  jr $ra
  or $v0, $v1, $zero       ; v0 = v1
```

**Why it's unflippable from C:**

IDO sees the value that reaches `return N` (or `return r` where `r = N`) and allocates the return register $v0 for it directly. It schedules the constant-load into a nearby delay slot — but places it in $v0, not $v1, because $v0 is already reserved for the return. The `register int r` hint is silently ignored for return-flowing values (different from interrupt-bracket state where `register` does select $s0).

Target's use of $v1 + move appears to be a minor scheduling variation inside IDO's register coloring pass that we don't have a C-level lever for.

**Variants tried (all produce `addiu v0, N` + `jr ra; nop`, not `addiu v1, N` + `or v0, v1, zero`):**

1. Goto chain with `L_shared: return N;` — IDO schedules `li v0, N` into the preceding branch's delay slot
2. Local `int r = N; ... return r;` — constant-propagated, same as (1)
3. `register int r = N;` — register hint ignored (return-flowing)
4. Mid-function `r = N;` declaration (after some of the checks) — same as (1)
5. `||` fusion (`a1 == 'n' || a1 == 's'`) — produces `bnel` chains (branch-likely on miss), structurally different
6. Local-only-on-shared-branches (`r = N; goto out;`) — restructures the whole chain

**Action:** keep as `#ifdef NON_MATCHING` wrap with the best C form (goto chain). Size/instruction count are byte-equivalent with target; only diff is register field in the preload and the final move. Same unflippable class as `feedback_ido_arg_save_reg_pick.md` (IDO always $a1 to save a0) and `feedback_ido_o2_tiny_wrapper_unflippable.md`.

**Don't confuse with:** `feedback_ido_v0_reuse_via_locals.md` — that's about $v0 vs $t-reg for intermediate values, not $v0 vs $v1 for return-flowing values. The techniques in that memo (name/don't-name local) don't apply here.

**Origin:** 2026-04-20, agent-a, `bootup_uso func_00000A9C` (char-to-bitmask map function, 0x78 bytes). 97.8 % match on the goto-chain form; 6 additional variants attempted without flipping the $v0/$v1 choice.

---

---

<a id="feedback-ido-s64-pack-return-via-lo-hi"></a>
## For IDO functions whose asm sets BOTH v0 and v1 as outputs, signature is s64 — return `((s64)hi << 32) | (u32)lo`

_When asm shows distinct values flowing into both v0 (return-low) and v1 (return-high) at the function epilogue (e.g. `or v0, ret_lo, zero; or v1, ret_hi, zero; jr ra`), the function signature is `long long`/s64 (o32 ABI: 64-bit return packs into v0=lo, v1=hi). The C expression `return ((long long)ret_hi << 32) | (unsigned int)ret_lo;` produces the correct emit. The `(unsigned int)` cast on ret_lo is required to avoid sign-extension polluting the high bits._

**Rule:** If the asm epilogue sets BOTH `v0` and `v1` to non-zero, distinct values via separate `or`/`addu`/`addiu` ops (not a `move v1, v0` move), the function returns 64-bit. The o32 ABI packs s64 into (v0=low-word, v1=high-word).

**C idiom:**

```c
long long my_func(...) {
    int ret_lo = 0;
    int ret_hi = 0;
    /* ... function body, mutate ret_lo and ret_hi ... */
    return ((long long)ret_hi << 32) | (unsigned int)ret_lo;
}
```

The `(unsigned int)` cast on `ret_lo` is **required** — without it, signed `int` ret_lo gets sign-extended to s64 (filling the high bits with 0xFFFFFFFF if ret_lo is negative), which then OR's against `(s64)ret_hi << 32` and produces wrong bytes.

**Don't:**

- Use `void` signature when asm clearly sets v1 — the wrapper compiles fine but v1 is left at whatever the last computation deposited there. fuzzy reads ~1pp lower than expected because v1's emit is the wrong register-pair-end.
- Use bit-field tricks (`union { s64 r; struct { int hi, lo; } parts; }`) — IDO emits stack-roundtrip code instead of direct or-pair.
- Reverse the shift (`((s64)ret_lo << 32) | ret_hi`) — gets the LE/BE wrong on big-endian o32.

**Caveat for TRUE LEAF functions (no jal anywhere in the asm):** the `((s64)hi << 32) | (u32)lo` pattern emits `jal __ll_lshift` (libgcc helper for 64-bit shifts) on IDO -O2. Tested 2026-05-05 with `(s64)x<<32`, `(u64)x<<32`, and `s64 r=x; r=r*0x100000000LL` — all produce the helper call. The call forces a stack frame (`addiu sp,-32` + `sw ra,20(sp)`), which makes the function NOT match a leaf-shaped expected/.o.

If `grep -E "0x0C[0-9A-F]{6}" <asm>.s` shows the original is a TRUE leaf (no jal opcodes), the recommended s64-pack idiom isn't usable. Diagnostic: `grep "jal" <built.o-disasm>` shows `R_MIPS_26 __ll_lshift`. Options:

1. **Re-examine whether the function actually returns s64.** Sometimes a function's asm sets v1 internally as a control flag (e.g., `addiu v1,zero,1` inside a branch arm, then later `beq v1,zero,...`) but v1 gets overwritten before the final `jr` (e.g., `lw v1, OFF(rX)` for delay-slot-store addressing). In that case the function returns INT (just v0); the apparent v1-as-return is mis-analysis. Look for `lw v1, ...` near the epilogue — if v1 is reloaded right before jr, it's not a return.
2. **Restructure the C to compute v0 only**, drop ret_hi tracking entirely.
3. **Last resort: post-cc patch.** INSN_PATCH the `__ll_lshift` jal + frame insns out via Makefile recipe (see `docs/POST_CC_RECIPES.md`). High-risk because the helper's input/output regs need manual unwinding.

**Detection signal:**

Look at the function's tail in objdump:
```
or  v0, $sX, zero       ; v0 = ret_lo (low word, 1st return reg)
or  v1, $sY, zero       ; v1 = ret_hi (high word, 2nd return reg)
jr  ra
... delay slot ...
```

If only v0 is set and v1 is left untouched (or v1 was set by a sibling load with no relation to a return value), it's `int`/`u32` return.

**Verified 2026-05-05** on `game_uso_func_00007538` (per-frame event dispatcher + per-bit timer decrementer). Switching from `void` to `long long` return + `ret_hi` tracking lifted fuzzy 36.89→37.51% (+0.62pp). Only one arm currently sets ret_hi (bit-0x04); the bit-0x80 trunk arm also sets it conditionally, so further fuzzy gains will follow once that arm is fully decoded.

**Related:**
- `feedback_ido_double_return_uses_f0_f1_not_f2.md` — analogous gotcha for `double` return (uses $f1, not $f2)
- [Consuming a 64-bit call return: extract hi/lo with a UNION, not `(int)(r>>32)`](#feedback-ido-consume-64bit-call-return-union) — the inverse direction (this entry packs a return; that one unpacks a callee's 64-bit result).

---

<a id="feedback-ido-consume-64bit-call-return-union"></a>
## Consuming a 64-bit (long long) CALL return: extract hi/lo with a UNION, not `(int)(r>>32)`

_When a callee returns a 64-bit value (v0=hi, v1=lo on big-endian o32) and you need BOTH words, `int hi = (int)(r >> 32); int lo = (int)r;` makes IDO -O2 emit a CALL to a 64-bit-shift runtime helper for the `>>32` (huge bloat — one decode went to 0x214 vs a 0x100 target, and objdiff couldn't even score it). Use a UNION instead — it stores v0:v1 to the stack and reads the two words back, which is exactly what the target does (`sw v0,N(sp); sw v1,N+4(sp); lw ...`)._

```c
extern long long callee();   /* 64-bit-returning view of the (K&R) placeholder */
typedef union { long long ll; struct { int hi; int lo; } w; } Pair64;
Pair64 r;
r.ll = callee(a, b, c, d);
int hi = r.w.hi;   /* big-endian: high word at offset 0 */
int lo = r.w.lo;
```

Then do all 64-bit ARITHMETIC with manual int hi/lo (`lo2 = lo - x; hi2 = hi - y - ((unsigned)lo < (unsigned)x);` → subu/sltu/subu), NOT long-long operators (those also emit MIPS3/helper sequences on -mips2). This is the consume-side complement to the produce-side `((s64)hi<<32)|(u32)lo` return idiom above (which has the same `__ll_lshift`-on-leaf caveat). Verified 2026-05-28 on gl_func_000743C4: union extraction + manual hi/lo subtract took the wrap from objdiff-None (shift-helper bloat) → 40% → 55%.

---

<a id="feedback-ido-save-arg-sentinel-empty-body"></a>
## IDO -O2 empty `void f(int a0) {}` produces exactly `jr ra; sw a0, 0(sp)` — save-arg sentinels ARE matchable from C

_The 2-insn "save-arg-to-caller-shadow-space" sentinel (`jr ra; sw a0, 0(sp)`) — previously documented as non-C-expressible — IS matchable from IDO -O2 with the trivial C body `void f(int a0) { }`. SUPERSEDES `feedback_ido_unfilled_store_return.md` claim that these aren't matchable._

**Rule:** `void f(int a0) { }` at IDO -O2 compiles to:
```
jr $ra
sw $a0, 0x0($sp)   (delay slot)
```
Exactly 8 bytes. This is the target pattern for 1080's save-arg sentinels (func_0000214C, func_000031B8, func_00008A38, func_0000DDC4 family).

**What IDO does with empty non-leaf functions:** Even though the body has no `jal`, IDO still spills the arg register to the caller's shadow space (sp+0 for $a0, sp+4 for $a1, etc.) and then jumps back. The `sw` ends up in the jr's delay slot because there's nothing else to schedule.

**Why I thought this didn't work:** Earlier test (feedback_ido_unfilled_store_return.md origin) compiled `void f(void) { }` — NO args — which produces just `jr ra; nop` (no sw). The save-arg only appears when the function takes at least one arg. Empty `void f()` ≠ empty `void f(int a0)`.

**Note on -g3:** At -g3, IDO adds `sw a0, 0(sp)` BEFORE the jr (not in delay slot), producing 3 insns + 2 nops padding (size 0xC). So for these sentinels, KEEP default -O2 (no -g3).

**Quick test recipe:**
```bash
cat > /tmp/test.c <<'C'
void f(int a0) {}
C
tools/ido-static-recomp/build/7.1/out/cc -c -G 0 -non_shared -Xcpluscomm -Wab,-r4300_mul \
    -O2 -mips2 -32 -o /tmp/test.o /tmp/test.c
mips-linux-gnu-objdump -d -M no-aliases /tmp/test.o
```

Target pattern:
```
03e00008 jr    ra
afa40000 sw    a0,0(sp)
```

**How to apply:**
1. `grep -c 03E00008 <func>.s` → 1 (single jr-ra)
2. Check size == 0x8 (2 insns)
3. Second insn is `sw $aN, 0(sp)` (delay slot)
4. Count args: if only $a0 spilled, `void f(int a0) {}`. If $a0 and $a1 both spilled, `void f(int a0, int a1) {}` — though $a1 variant would produce `sw a1, 4(sp)` in the delay slot.
5. Replace INCLUDE_ASM with plain empty C body.

**Outdated memory:** Update `feedback_ido_unfilled_store_return.md` to note this sentinel class IS matchable (was already partially superseded by -g3 memo, now fully superseded).

**Candidates to promote (bootup_uso, h2hproc_uso, eddproc_uso):**
- func_0000214C, func_000031B8, func_00008A38, func_0000DDC4 (bootup_uso, $a0 variants)
- h2hproc_uso_func_0000049C
- eddproc_uso_func_00000144/00000150 ($a0+$a1 variants, see below)

**$a0+$a1 variant:** 3-insn save-arg stubs like `sw a0,0(sp); jr ra; sw a1,4(sp)` — body `void f(int a0, int a1) {}` should match (untested yet).

**Generalization — single-store-to-arg-pointer no-prologue 2-insn leaves are also matchable:** when target is `jr ra; sw aN, OFFSET(aM) [DS]` (single store to a pointer field), plain C `void f(T *aM, U aN) { aM[OFFSET/4] = aN; }` MATCHES at IDO -O2 — IDO schedules the lone store into the jr-ra delay slot AND elides the frame setup entirely (no `addiu sp` prologue). Verified 2026-05-15 on `game_libs_func_00061D80` (2-insn `void f(int *a0, int a1) { a0[1] = a1; }` → exact `jr ra; sw a1, 0x4(a0)`). Differs from the empty-body sentinel above (which spills to caller's $sp slot); this variant stores to the FIRST arg's pointed-to memory. Both share the same "single store + jr ra, no frame" emit shape.

**Return-0 variant — `int f(int, int, int) { return 0; }` emits save-N-arg + `or v0, zero, zero` in jr-ra DS.** When target is `sw a0,0(sp); sw a1,4(sp); sw a2,8(sp); jr ra; or v0,zero,zero [DS]` (size 0x14, 5 insns), the matching C is `int f(int a0, int a1, int a2) { return 0; }`. The save-N-arg pattern still fires (one sw per declared arg), and `return 0` ends up in the jr-ra delay slot via `or v0, zero, zero`. Verified 2026-05-15 on `game_libs_func_0003D538`. Same recipe for 1-, 2-, 4-arg variants: declare `int f(...) { return 0; }` and IDO emits N save-arg slots + return-0 sentinel.

**Origin:** 2026-04-20 tick. Discovered by trying -O2 plain empty body as source=3's first yielded candidate (func_000031B8). Got byte-exact match on first try. Commit landed via land-successful-decomp.sh.

---

---

<a id="feedback-ido-sentinel-rewrite-in-unrolled-loops"></a>
## IDO rewrites pointer-comparison sentinels as `s1 != magic - slot` in unrolled-loop bodies — recognize the pattern

_When IDO encounters `if (s1 + slot != (char*)MAGIC)` inside an unrolled loop and MAGIC doesn't fit a 16-bit immediate, it rewrites the test as `if (s1 != (char*)(MAGIC - slot))` and emits `addiu $at, $zero, sentinel; bne $s1, $at, ...` where `sentinel = MAGIC - slot` fits the imm16. In an unrolled loop, slot increases by sub-obj size per iter (e.g. +0x18), so SENTINEL DECREASES by the same amount per iter. When you see a sequence of unrolled iterations with `addiu $at, $zero, -0xE0`, `-0xC8`, `-0xB0`, `-0x98`, ... (each -0x18 from the previous), that's NOT 4 unrelated comparisons against random sentinels — it's the SAME `s1 + slot != MAGIC` test rewritten per iter to use the iter-specific slot offset. The constant MAGIC is recoverable as `sentinel + slot`. Verified 2026-05-04 on game_uso_func_000044F4 stages 8-A: slot offsets 0x20/0x38/0x50/0x68 paired with sentinels -0xE0/-0xC8/-0xB0/-0x98 → MAGIC = -0xC0 = 0xFFFFFF40 (or similar pointer-coded sentinel) consistent across iters._

**The pattern (verified 2026-05-04 on game_uso_func_000044F4 stages 8-A)**:

In an unrolled loop body, you see sentinel constants in `addiu $at, $zero, -N` decrease by a fixed amount per iteration:

```
iter A (slot 0x20): addiu $at, $zero, -0xE0; bne $s1, $at, +5
iter B (slot 0x38): addiu $at, $zero, -0xC8; bne $s1, $at, +5
iter C (slot 0x50): addiu $at, $zero, -0xB0; bne $s1, $at, +5
iter D (slot 0x68): addiu $at, $zero, -0x98; bne $s1, $at, +5
```

Sentinels: -0xE0, -0xC8, -0xB0, -0x98 (each +0x18 from the previous, in 2's-complement-decreasing-magnitude direction).
Slot offsets: 0x20, 0x38, 0x50, 0x68 (each +0x18 from the previous).

**Sum**: sentinel + slot = -0xC0 = same constant for every iter.

That tells you the C source is:
```c
if ((char*)s1 + slot_offset != (char*)0xFFFFFF40) { ... }
```
or equivalently `s1 + slot_offset != (char*)-0xC0`. IDO rewrote the comparison constant to use the imm16-fittable sentinel-per-iter form because the actual MAGIC address (e.g. -0xC0 sign-extended) doesn't fit clean in 16-bit imm without the `s1 + slot` regrouping.

**Why IDO does this**:

The natural emit for `s1 + slot_offset != MAGIC` would be:
```
addiu $tN, $s1, slot_offset    ; compute s1 + slot
lui   $at, hi(MAGIC)
ori   $at, lo(MAGIC)            ; load MAGIC
bne   $tN, $at, +5
```
That's 4 insns. By rewriting as `s1 != MAGIC - slot`:
```
addiu $at, $zero, MAGIC-slot   ; one insn (if MAGIC-slot fits 16-bit signed)
bne   $s1, $at, +5
```
2 insns. The `addiu $s0, $s1, slot_offset` is needed anyway for `s0 = sub-obj-slot-base`, so it amortizes.

**What this looks like in the asm vs alternative readings**:

Without recognizing the pattern, an agent might write the C as:
```c
if ((int)s1 != -0xE0) { ... }   // iter A
if ((int)s1 != -0xC8) { ... }   // iter B
```
— treating each sentinel as independent. That's WRONG (different magic per iter); the iters all branch on the same `s1 + slot != MAGIC` condition, just rewritten.

The right C decode (per iter, in the doc):
```c
char *s0 = s1 + 0x20;
if (s1 + 0x20 != (char*)MAGIC) {        // iter A: s1 != -0xE0 in asm
    *(int*)s2 = template_ptr;
    s0 = (char*)gl_func_00000000(0x18);
    if (!s0) goto epi;
    /* ... */
}
```

In the doc/wrap, list the per-iter sentinel as data, and note the rewrite — that lets the next pass write `s1 + slot != MAGIC` once and reproduce all iters.

**How to detect**:

In any unrolled loop with `addiu $at, $zero, -N` followed by `bne $s1, $at, ...`:
1. Note the sentinel `-N` per iter
2. Note the slot offset (the `addiu $sN, $s1, K` immediately above)
3. Compute sentinel + slot per iter — if it's CONSTANT across iters, you've found the rewrite

**Related**:
- `feedback_ido_split_or_constant.md` — sibling rewrite pattern for `or` of constants
- `feedback_ido_load_cse_swap_v0_v1.md` — IDO load-CSE patterns

**Verified case**: game_uso_func_000044F4 (4.6 KB constructor, sub-obj init loop, unrolled into 6+ iters at 0x4600-0x47C8). Each iter is 22 insns / 0x58 bytes; the sentinel-rewrite is one of 4 linearly-varying parameters per iter.

---

---

<a id="feedback-ido-sign-test-form-choice"></a>
## IDO -O2 picks bgez vs srl+beqz for sign-test based on C form — `(unsigned)x>>31` forces 2-insn srl+beqz

_For `if (x < 0) {...}`, IDO -O2 emits the 1-insn `bgez x, .Lend` form (branch if non-negative, skipping the body). Target asm sometimes uses the 2-insn `srl t, x, 31; beqz t, .Lend` form (extract sign bit, then branch). To match the latter, write `if ((unsigned)x >> 31) {...}` explicitly — IDO emits srl+beqz instead of bgez._

**The two IDO codegen forms for "if x is negative":**

| C source | IDO -O2 emit | insns |
|----------|--------------|-------|
| `if (x < 0) BODY` | `bgez x, .Lend` (skip body) | 1 |
| `if ((unsigned)x >> 31) BODY` | `srl t, x, 0x1F; beqz t, .Lend` | 2 |

Both are semantically identical — they branch over the body when x's sign
bit is 0 (= x >= 0). But they encode different opcodes / different
register usage.

**When to use the 2-insn form:** target asm shows `srl t, x, 0x1F` followed
by `beqz t, ...` for a sign-test. Without the explicit `>>31`, IDO picks
`bgez` (the more efficient form) and the function won't byte-match.

**When to use the 1-insn form:** target shows `bgez x, ...` directly. Use
plain `if (x < 0)`.

**Verified 2026-05-03 on gl_func_0002DF38:** target uses srl+beqz; my
initial `if (x < 0)` body emitted bgez (1-insn diff). Switching to
`(unsigned)x >> 31` matched exactly.

**Relation to other sign-test idioms:**
- `feedback_ido_signed_divide_2_idiom.md` — different pattern (signed `/2`
  uses `bgez; sra; addiu 1; sra`, also sign-test-driven).
- `feedback_ido_split_or_constant.md` — adjacent codegen knob (OR vs
  ADDIU constant split).

**Generalizable rule:** when target's sign-test is 2 insns (srl + beqz/bnez
on a temp), always try the `(unsigned)x >> 31` form first. Don't grind
register-allocation knobs — the encoding choice IS the source-level lever.

---

---

<a id="feedback-ido-bit-N-test-via-sll-bgezl"></a>
## Test arbitrary bit-N (N != 31) by `((unsigned)x << (31-N)) >> 31` — emits `sll + bgezl/bltzl`

_For `if (x & (1<<N)) {...}` with N != 31, the natural C emits `andi t, x, mask; beqz/bnez t, ...`. To get the target's `sll t, x, K; bgezl/bltzl t, ...` form (K = 31-N), write the test as `((unsigned)x << K) >> 31`. The `<< K >> 31` round-trip leaves the original bit N at position 31 (sign bit), and IDO -O2 specializes the resulting compare to the SLL-then-sign-branch form._

**The two IDO codegen forms for "test bit N of x":**

| C source                           | IDO -O2 emit                               | comment           |
|------------------------------------|--------------------------------------------|-------------------|
| `if (x & (1<<N)) BODY`             | `andi t, x, MASK; bnez t, .Lbody`         | bit-N at ANDI mask |
| `if (((unsigned)x << K) >> 31) BODY` | `sll t, x, K; bltzl t, .Lbody (likely)`  | K = 31-N          |
| `if (((unsigned)x << K) >> 31 == 0) NOTBODY` | `sll t, x, K; bgezl t, .Lnotbody (likely)` | inverse polarity |

Where `K = 31 - N` (for testing bit N).

**Worked example — bit 16 test (verified 2026-05-14 on `h2hproc_uso_func_000015F0`):**
- Target shape: `lw t8, 0x4F0(a1); sll t9, t8, 0xF; bltzl t9, .Lreturn` (test bit 16; return if set)
- C: `if (((unsigned)a1[0x4F0/4] << 15) >> 31) return;` matched first try
- (`andi + bnez` polynomial wouldn't have matched — different opcodes entirely)

**Why IDO picks SLL+bgezl/bltzl over ANDI+bnez:** when the test value is
the result of an expression (load + shift), IDO's combiner notices the
test reduces to "is the sign bit set after this shift?" and emits the
sign-branch form. ANDI doesn't go through the sign-branch path.

**Use cases:** USO field-flag bits where the asm uses `sll <K>; bltzl/bgezl`. Common shifts:
- `sll t, x, 0` → bit 31 → use plain `if (x < 0)` or `(unsigned)x>>31`
- `sll t, x, 0x1` → bit 30
- `sll t, x, 0xF` → bit 16
- `sll t, x, 0x10` → bit 15
- ... etc

**Don't use for:** plain bit-mask tests where target uses `andi`. The two
shapes are not interchangeable from C — pick based on what target emits.

---

---

<a id="feedback-ido-reuse-param-reg-as-counter"></a>
## Reuse the parameter register as a loop counter (declare the param `int`, reassign it)

When the target reuses a parameter's register as a loop counter — recognizable as `move aN, zero` (or `move aN, <init>`) right after the param's last real use — a fresh `int i = 0` local gets allocated to a *different* register (`$v0`/a temp), giving register-renumber diffs on every counter instruction.

Fix: declare the parameter with the integer type you need and reassign it as the counter:
```c
int f(int a0, int a1) {           // a0 declared int, not int*
    int v1 = *(int*)(a0 + 0x34);  // last use of a0-as-pointer (cast inline)
    a0 = 0;                        // reuse a0's register as the counter → move a0,zero
    do {
        if (a0 == a1) break;
        v1 = *(int*)(v1 + 0x84);
        a0++;
    } while (v1 != 0);
    return v1;
}
```
IDO reuses the param register for the counter = exact, where `int i=0` would not. Pair with the loop-shape rule: a `do { if (i==a1) break; ...; i++; } while (cond);` (break at body-TOP) emits `beq i,a1 / bnez cond`; the `while (i != a1) { ...; if (!cond) break; }` form emits `beqz a1 / bnel` instead. Verified 2026-05-23, `game_libs_func_0003E0C0` (clean 12/12 episode).

---

<a id="feedback-ido-andi-fitting-mask-vs-negative"></a>
## Byte-RMW clear-mask: use the 16-bit `andi`-fitting literal (`& 0xFF7F`), not `& ~0x80`

For `*(u8*)p &= ~0x80`: `~0x80` = `0xFFFFFF7F` does NOT fit `andi`'s 16-bit immediate, so IDO materializes `li at, -129; and rd, rs, at` — TWO instructions plus a consumed register, which shifts every subsequent `$t` allocation in the function. Write the equivalent low-16 mask `& 0xFF7F` (identical result for a byte-width value): IDO emits a single `andi rd, rs, 0xFF7F` and the register allocation stays aligned.

Verified 2026-05-23 on `game_libs_func_0001CF68` (a bit-7-clear loop over a 2D global table): `& ~0x80` → 15 diffs incl. a stray `li a1,-129` in a branch-delay slot + a cascading `$t`-renumber; `& 0xFF7F` → 14 diffs and removed the cascade root (the remaining 14 were the loop's own `$t`-renumber, permuter-resistant).

**General rule:** for any `x & MASK` where MASK reads negative / has high bits set, use the 16-bit-truncated positive literal that `andi` accepts whenever the operand width makes them equivalent. Same family as the `lui+ori` vs `lui+addiu` constant-form distinctions.

---

<a id="feedback-rmw-reassign-base-ptr-forces-addiu-sw0"></a>
## Forcing `addiu base,N; sw 0(base)` for a struct RMW: REASSIGN the base pointer (a field-pointer folds to `sw N(base)`)

_When the target writes a struct field via an ADVANCED pointer — `lw t,N(base); addiu base,base,N; sw t',0(base)` (read at offset N, then write through `base+N`) — the natural C `p->fieldN |= x` (or `*(T*)((char*)p+N) |= x`) FOLDS to `lw N(p); sw N(p)` (offset addressing, no addiu), one instruction short. The fix is to explicitly REASSIGN the base pointer between the read and the write:_

```c
int t = *(int*)((char*)v + 0x18);   /* lw t, 24(v)  — read at offset */
v = (int*)((char*)v + 0x18);        /* addiu v, v, 24  — advance base */
*v = t | 4;                          /* sw t', 0(v)  — store through advanced base */
```

This REFINES `feedback_rmw_pointer_local_folds_to_offset_addressing` (which found that a *field*-pointer `int *fp = &p->field; *fp = ...` still folds to `sw OFF(p)`). The distinction: folding happens when the pointer's only use is the one field access; reassigning the **base** variable so it's live as `base+N` forces IDO to materialize the `addiu` and store at `0(base)`. Verified 2026-05-28 on `gl_func_0000E368` (two `v->0x18 |= /&= ~ 4` RMWs): 95.2% → 98.45%, structure fully matched (42=42 insns); only a `$v1`-vs-`$t2` read-temp register-renumber remained. Use when a near-miss is `+4` per RMW site with the diff being `sw N(reg)` (mine) vs `addiu reg,N; sw 0(reg)` (target).

---

<a id="feedback-r4300-mult-hazard-nops-missing"></a>
## Unrolled `multu`/`mflo` loops won't byte-match — build omits r4300 mult-hazard nops

A multiply-accumulate loop like `for (i = 1; i < n; i++) x *= 10;` makes IDO -O2 **unroll by 4** with a `(n-1)&3` remainder loop. The simple C reproduces this structure EXACTLY — the remainder loop and the first `multu`/`mflo` of the unrolled body match byte-for-byte.

The divergence is ONLY in the unrolled body: the ROM separates each `mflo` from the next `multu` with **2 nops** (the r4300 erratum: a `mult`/`multu` too soon after `mflo`/`mfhi` corrupts the result). This build's IDO assembler (`-Wab,-r4300_mul`) emits the `multu`/`mflo` pairs back-to-back with no hazard nops, so the unrolled body is N nops short of the target. (The remainder loop matches because its `addiu` + loop branch already provide ≥2 instructions between `mflo` and the next `multu`.)

This is a build/assembler-config gap, NOT reachable by C restructuring (a non-unrolled loop diverges differently; you can't inject nops from C). **Recognize the shape** (back-to-back `multu;mflo;multu;mflo` in an unrolled loop where the ROM has `multu;mflo;nop;nop;multu`) and NM-wrap. Verified 2026-05-23 on `game_libs_func_000611E4` (pow10 = `a0 * 10^(a1-1)`): matched through the first unrolled multiply, diverged at the 2nd (mine packed, ROM nop-padded).

---

<a id="feedback-1080-67xxx-string-lag-idiom"></a>
## 1080 game_libs 67xxx libc-string family — two-pointer-lag idiom (recognize-and-NM-wrap)

The 67xxx region of game_libs is a cluster of libc string functions: `67C98` strncpy, `67C1C` strcat, `67FA4` strlen, `67B04`/`67B40` strcmp-variants (return 1 on mismatch), `67B78` strstr/match, `67E28` hash (also caller-set v0/v1). All reloc-free.

Their per-character read uses a **two-pointer lag**: `move vL, cursor; lbu c, 0(vL); addiu cursor, 1` (a lag pointer `vL` copied from the live `cursor` each iteration, char read via `vL`, plus a branch-likely `bnezl`/`beql` loop). Clean C does NOT reproduce this:
- `while (*s++) ...` → single-cursor `lbu c, 0(cursor); addiu cursor, 1` (no copy).
- `if (*s) { do { s++; ... } while (*s); }` → offset-fold `lbu c, 1(cursor); addiu cursor, 1`.

Both are structurally off by the lag-copy (verified 13/13 on `67FA4` strlen, 2026-05-23). Likely a compiler-version or idiom gap. **Until cracked: recognize these as the 67xxx libc-string family, NM-wrap with the clean recognized algorithm (byte-match deferred), and move on** (don't re-try the two negative forms above). Cracking the lag idiom (try `*p++` with the prev pointer used, or the permuter) would convert the whole cluster to episodes at once.

---

<a id="feedback-ido-signed-divide-2-idiom"></a>
## `bgez v0; sra t, v0, 1; addiu at, v0, 1; sra t, at, 1` is IDO's signed `/2` lowering

_Signed-integer division by 2 in IDO doesn't become a single `sra`. It expands to a branch-based round-toward-zero sequence: for non-negatives use `v0 >> 1`; for negatives use `(v0 + 1) >> 1`. Recognize this idiom from the target asm and write plain `v0 / 2` in C._

**Rule:** If the target asm has this 4-instruction pattern:

```
bgez  $rv, .pos
sra   $rt, $rv, 1        ; delay slot (executed always)
addiu $at, $rv, 1
sra   $rt, $at, 1
.pos:                      ; (continues here)
```

…the original source was `$rt = $rv / 2` (signed divide by 2) in C.

**Why:** for signed int, C's `/2` rounds toward zero. MIPS `sra` arithmetic shift always rounds toward negative infinity (e.g. -3 >> 1 = -2, but -3/2 = -1). To get C semantics:
- `x >= 0`: `x / 2` = `x >> 1` (sra gives correct result)
- `x < 0`: `x / 2` = `(x + 1) >> 1` (adds 1 to correct the rounding)

GCC (and IDO) emit this 4-instruction sequence for every signed `/2` because there's no single instruction that does the right thing for negatives. The branch skips the "+1" path when the sign bit is clear.

**How to apply:**

- When you see this pattern, write `v / 2` (not `v >> 1`) in C.
- If the result is assigned to a named local (`int t = v / 2;`), IDO usually picks the local's register for `$rt`. Inline form is fine too.
- If the input is `unsigned`, IDO emits just `srl $rt, $rv, 1` — no branch. So `bgez+sra+addiu+sra` means SIGNED int.

**Related:**
- `feedback_ido_bnel_arm_swap.md` covers branch-likely arm ordering (different issue).
- `u32 >> n` emits `srl`; `s32 >> n` emits `sra`. For a plain right-shift with no "+1" correction, the C is `>>`, not `/`.

**Origin:** 2026-04-19 gui_uso gui_func_000014B4. Target had the 4-inst sequence for `result / 2`. Wrote `a1 - (call_result / 2)` in C — matched first try.

---

---

<a id="feedback-ido-sp-frame-without-stack-use"></a>
## IDO -O2 leaf with `addiu sp,-8` but no stack use is unreachable from standard C

_When target has a leaf function with stack frame adjust (`addiu sp, sp, -8` / `addiu sp, sp, +8`) but NO sw/lw using the frame, no standard C idiom produces this at IDO -O2. Unused `char pad[N]`, `int foo[2]`, `register`, and `(void)x` are all DCE'd away (no frame). `volatile int x = expr` creates the frame AND gets the right branch direction, but forces 2 extra insns (sw+lw) for the volatile materialization — so you're always +2 insns over target. Cap around 40-50% match. Likely needs permuter or hand-asm._

**Test case (2026-04-20, gl_func_0006F3BC):**

Target (9 insns):
```
addiu sp, sp, -0x8
andi  t7, a0, 0x3
beqz  t7, +3        ; target of beqz: `or v0,zero,zero`
 nop
b +2
 addiu v0, zero, 0x1 ; delay slot
or    v0, zero, zero
jr    ra
 addiu sp, sp, 0x8
```

**Variants tested (ALL at IDO -O2):**

| Variant | Produces sp=-8? | Produces `beqz`? | Extra insns vs target |
|---|---|---|---|
| `if ((a0&3)==0) return 0; return 1;` | ❌ | ❌ (bnez) | -1 (compacted) |
| `if ((a0&3)!=0) return 1; return 0;` | ❌ | ❌ | -3 (branch-likely) |
| `return (a0&3) != 0;` | ❌ | N/A (sltu) | -5 |
| `char pad[8]` (untouched) | ❌ | ❌ | -1 |
| `char pad[8]; pad[0]=0;` | ❌ | ❌ | -1 |
| `int foo[2]; foo[0]=0;` | ❌ | ❌ | -1 |
| `volatile int pad;` (unused) | ❌ | ❌ | -1 |
| `volatile int pad[2];` (unused) | ❌ | ❌ | -1 |
| `register int dummy; (void)&dummy;` | compile error (IDO rejects `&` on register) | — | — |
| `volatile int x = a0 & 3;` + `if(x==0)` | ✅ | ❌ (bnez) | +2 (sw+lw) |
| `volatile int x = a0 & 3;` + `if(x!=0) return 1; return 0;` | ✅ | ✅ | +2 (sw+lw) |
| `volatile int x = a0 & 3;` + goto/label | ✅ | ❌ | +2 (sw+lw) |

**The irreducible tradeoff:** forcing an `addiu sp,-8` at IDO -O2 seems to require a real stack-addressed local. `volatile` gets it, but every `volatile` local store/load is preserved — you can't have "allocate frame, do nothing with it."

**Hypothesis on what the target's source looked like:**
- `alloca(0)` or `alloca(8)` with result unused — makes sp adjust without loads/stores. Not tested (IDO may not support `__builtin_alloca` portably).
- `setjmp` buffer allocation that's never called — would force frame.
- Hand-written asm or compiler-pragma-controlled output.
- Different IDO version with different DCE aggressiveness.

**UPDATE 2026-05-30 — flag matrix + alloca now tested (still no clean trigger):**
- **Full opt/debug matrix {-O0,-O1,-O2} × {plain,-g,-g2,-g3} = all frameless-leaf.** The "different DCE aggressiveness" and debug-frame hypotheses are FALSE for our static-recompiled IDO 7.1: no `-g` level emits a leaf frame. `-g`/`-g2`/`-g3` only toggle trailing alignment nops and an extra `jr ra`; never an `addiu sp`. So a per-file `-g3` (or any std flag) does NOT crack this — don't bother splitting the file for it.
- **`alloca(8)` (extern decl) WAS tested: it forces the frame AND flips the `andi` dest to `$t7` — the target's exact register** — but it also emits `jal alloca` + frame `-24` + `sw ra/a0` + a0-reload-from-stack. Structurally wrong (target has no call, no reload, frame `-8`). Useful signal though: it confirms the target frame is *real allocation* (not pad), and that the frame is what shifts the andi from `$t6` (frameless) to `$t7` (framed). So any successful trigger must (a) allocate a real ≥1-byte frame, (b) emit zero sw/lw, (c) keep `a0` used directly. No standard-C construct satisfies all three — `volatile` violates (b), unused locals violate (a) via DCE, `alloca` violates (c). Confirmed genuine cap; INCLUDE_ASM build emits correct bytes.

**Rule for next time:** if the target has a plain `addiu sp,-N` / `addiu sp,+N` pair with NO intervening sw/lw and the function body is simple compute/branch logic, don't waste a full /decompile tick grinding — wrap NM with the best `volatile int x =` form and move on. Record the match % in the comment; permuter-eligible.

**Origin:** 2026-04-20, gl_func_0006F3BC. Capped at ~45 % after 30+ variants.

---

---

<a id="feedback-ido-sp-status-check-unreachable"></a>
## kernel/func_80008030 (SP_STATUS & 3 check) not reproducible from C at -O1 or -O2

_Simple `if ((SP_STATUS & 3) == 0) ret |= 1;` function (0x24 = 9 insns, no stack frame, ret in $v0 with `or v0,zero,zero` + `ori v0,v0,1`) is not reachable from IDO C. -O1 spills ret to stack (adds 4 insns); -O2 routes ret through $v1 with trailing `move v0,v1` instead of target's `or/ori v0` in-place. Tried 7 variants. Previously decompiled and reverted (commit d692829 → 3494845). Leave as INCLUDE_ASM._

**Target asm** (kernel/func_80008030, file kernel_031.c, -O1):
```
lui  t0, %hi(D_A4040010)      ; SP_STATUS_REG
lw   t0, %lo(...)(t0)
or   v0, zero, zero            ; ret = 0 (in v0 directly)
andi t0, t0, 3
bnez t0, .L
nop
ori  v0, v0, 1                 ; ret |= 1 (in v0 directly)
.L:
jr ra
nop
```

9 insns, no stack frame, `ret` lives in `$v0` throughout.

**Variants tried (2026-04-20, all fail):**
1. `int ret=0; if ((D&3)==0) ret|=1; return ret;` at -O1 → +stack frame, spills ret
2. Same at -O2 → `ret` in `$v1`, trailing `move v0,v1` in jr delay slot
3. `register int ret = 0;` at -O1 → still spills
4. `register int ret = 0;` at -O2 → still routes via $v1
5. `if (D&3) return 0; return 1;` at -O1 → two jr ra paths, wrong structure
6. `return !(D&3);` → collapses to `sltiu v0,v0,1` (wrong, 1 insn)
7. `volatile int D;` → adds `lui+addiu+lw` pointer expansion (wrong)
8. Pre-AND `int stat = D&3; if (stat==0) ret|=1;` at -O2 → same v1 routing

**Why:** IDO register allocator preferentially uses `$v0` for the first-evaluated expression (the load), routing the return value through `$v1` with a final move. Target has some compiler state (different IDO version? specific RTL pass order?) where `$v0` was held for the return value from the start.

**History:** commit `d692829` decompiled this, reverted 7 minutes later (`3494845`) without documented reason — likely build regression or partial-match cleanup.

**Action:** leave as INCLUDE_ASM in kernel_031.c. Not a candidate for grinding until we understand the IDO $v0 allocation trigger better.

**Origin:** 2026-04-20, agent-a tick.

---

---

<a id="feedback-ido-sparse-switch-beql-preload-unreachable"></a>
## IDO -O2 sparse-case switch (case 0 + case 1) compiles to 3-arm beql dispatch with delay-slot pre-loads — unreachable from C if-else; switch is also rejected (.rodata jumptable)

_When target asm shows `addiu $at,zero,1; beql v0,zero,caseA; <lw delay>; beql v0,$at,caseB; <lw delay>; b end; <lw ra delay>` (3-arm beql dispatch with each delay slot pre-loading the case body's first lw), this is a `switch (v) { case 0: ...; case 1: ...; }` with sparse small cases. C if-else `if (v==0) {...} else if (v==1) {...}` emits std `bne v,0,...; nop; ... bne v,1,...; nop` (no delay-slot pre-loads). Switch is unusable on 1080 (.rodata discarded — see feedback_ido_switch_rodata_jumptable.md). So the dispatch shape is unreachable from C; NM-wrap with logic-correct C, accept the structural cap._

**Verified 2026-05-02 on `n64proc_uso_func_00000268`**:

Target dispatch (offsets relative to func start 0x268):
```
0x270: lw   $v0, 0x50($a0)        ; v = a0->0x50
0x274: or   $a3, $a0, $zero       ; save a0 in $a3
0x278: addiu $at, $zero, 1        ; setup compare value 1
0x27c: beql $v0, $zero, .L0298    ; if v==0 branch (likely)
0x280:  lw  $t6, 0x3C($a3)        ; delay slot — preload case 0's first lw
0x284: beql $v0, $at, .L02E0      ; if v==1 branch (likely)
0x288:  lw  $t5, 0x54($a3)        ; delay slot — preload case 1's first lw
0x28c: b    .L0350                ; default — branch to epilogue
0x290:  lw  $ra, 0x14($sp)        ; delay slot — preload epilogue
0x294:  lw  $t6, 0x3C($a3)        ; *dead code* — never reached
.L0298: addiu $t7, $t6, -1        ; case 0 body uses pre-loaded $t6
...
.L02E0: addiu $t8, $zero, 0xFF    ; case 1 body uses pre-loaded $t5
...
```

Build dispatch from C `if (v == 0) { ... } else if (v == 1) { ... }`:
```
0x14: bne $v0, $zero, +0x13       ; skip case 0 body (regular bne)
0x18: nop                          ; delay slot — no preload
0x1c: lw  $v0, 0x3C($a0)           ; case 0 body starts here
...
0x?: bne $v0, $at, +N              ; skip case 1 body
0x?: nop
```

**Key facts:**

1. Target's pattern is what IDO emits for `switch (v) { case 0: ...; case 1: ...; default: break; }` when cases are SPARSE (0, 1) — no jumptable, just branch chain with beql+preload.

2. The case bodies are positioned AFTER the dispatch chain (not adjacent to their dispatch site). beql branches FORWARD to the body, with the body's first lw hoisted into the dispatch's delay slot.

3. The dead `lw t6` at offset 0x294 (between the default `b` delay slot and case 0's `.L0298` body) is IDO emitting the duplicate of case 0's first lw at the natural fall-through position — only reachable if some path falls through to 0x294 (which doesn't happen in normal flow).

4. **C if-else** at -O2 gives standard `bne; nop; <body>` dispatch — no preload, no beql.

5. **Switch is rejected** on 1080 (and similar projects) because IDO emits the jumptable in `.rodata` which the linker discards (see `feedback_ido_switch_rodata_jumptable.md`).

**How to apply:**

When target asm dispatch starts with `addiu $at,zero,N; beql v0,zero,...; <lw delay>; beql v0,$at,...; <lw delay>; b end`:
- Recognize this as a switch (case 0 + case N).
- Don't grind C if-else trying to flip to beql — it won't.
- Write the if-else C with logic-correct semantics, NM-wrap.
- Document the switch-vs-if-else gap as the structural cap.
- Logic-correct decode IS forward progress (sets up struct types, callee signatures), even if .o-level objdiff stays NM.

**Symptom signature (3-arm beql sparse switch):**
- 1 register prep (`addiu $at,zero,N`)
- 2+ `beql v0,X,target` with delay slots loading values needed by the branch target
- 1 unconditional `b end` with delay slot (`lw $ra,...` or other)
- Often a "dead" duplicate lw between `b`'s delay slot and the first case body label

**EXCEPTION — 2-case store variant IS reachable via `switch` (verified 2026-05-15, `game_libs_func_00047F68`):**

The "unreachable / NM-wrap and accept the cap" verdict above applies to the **lw-preload variant** (delay slots hoist the case body's first `lw`) and/or denser case sets. For the **2-case STORE variant** — exactly `case 0` and `case 1`, each body a single `sw` (no preload `lw` in the delay slots) — a literal C `switch` DOES byte-match, and IDO emits **no `.rodata` jumptable** for just 2 sparse cases (so the linker-discard problem never arises). Confirmed exact (objdiff 100.0):

```c
void game_libs_func_00047F68(int *a0, int a1) {
    *(int*)((char*)a0 + 0x188) = a1;
    switch (a1) {
    case 0: *(int*)((char*)a0 + 0x1E0) = 1; break;
    case 1: *(int*)((char*)a0 + 0x1E0) = 0; break;
    }
}
```
→ `beq a1,zero,caseA; sw a1,0x188(a0)(delay); addiu at,zero,1; beql a1,at,caseB; sw zero,0x1E0(a0)(delay); ...` exactly. `if (a1==0){} else if (a1==1){}` and goto-variants all emit plain `bne/nop` (54%); ONLY `switch` emits the `beq`+`beql` dispatch with the store in the beql delay slot. **Before NM-wrapping a 3-arm beql dispatch as a cap, first try a literal `switch` — if it's ≤2 sparse cases with store (not lw-preload) bodies, it will match and no jumptable is generated.**

**Related:**
- `feedback_ido_switch_rodata_jumptable.md` — switch → .rodata jumptable, discarded by 1080 linker (DENSE switches only; ≤2 sparse cases emit no jumptable)
- `feedback_ido_branch_likely_arm_choice.md` — beql arm-choice rules for SIMPLE if/return patterns

---

---

<a id="feedback-ido-bc1fl-skips-jal-to-epilogue"></a>
## bc1fl with target=epilogue and `lw ra,X(sp)` in delay slot is a CONDITIONAL-CALL marker, not a clamp

_Diagnostic for misreading IDO -O2 trailing FP conditionals: when the LAST `bc1fl` in a function jumps to the epilogue with `lw ra,X(sp)` in its delay slot, that's NOT a clamp/store guard — it's `if (!cond) jal()` where the jal sits between the bc1fl and the epilogue. Decode the C as `if (cond_complement) func();`, not "another clamp branch"._

**Verified 2026-05-05 on `mgrproc_uso_func_00002AFC` (82.34% → 100%):** the function's last bc1fl was misread as a third FP-clamp; the correct decode is `if (v <= 0.0f) gl_func_00000000();` (notify-on-expiry).

**Recognition signal:**

```
2b50: lwc1   $f0, 0x168(a0)        ; reload v
2b54: c.le.s $f0, $f2                ; cond: v <= 0
2b58: nop
2b5c: bc1fl  <epilogue>             ; if cond FALSE (v > 0) → branch
2b60: lw     ra, 0x14(sp)            ; DELAY-LIKELY: ra reload (taken path)
2b64: jal    func                    ; conditionally-called when cond TRUE
2b68: nop
2b6c: lw     ra, 0x14(sp)            ; ra reload (fall-through path, after jal)
2b70: addiu  sp, sp, 0x18            ; epilogue
2b74: jr     ra
```

The two `lw ra` reloads (one in delay-likely, one after the jal) are the fingerprint. Both paths arrive at the same `addiu sp` epilogue; the difference is whether the jal ran. The bc1fl-taken path skips the jal but uses the delay-likely `lw ra` to set up the return.

**Why "cond_complement" in the C:** `bc1fl` branches when the FP cond is FALSE. Branch-taken means SKIP the jal. So:
- Cond TRUE → fall through, run the jal → `if (cond) jal()`
- Cond FALSE → branch to epilogue, skip the jal

If target's c.le.s tested `v <= 0`, the C is `if (v <= 0) jal()`.
If target's c.lt.s tested `0 < v`, the C is `if (0 < v) jal()`.

**Anti-pattern that gets you here:** seeing three c.lt.s/c.le.s + bc1fl sequences in a row and assuming they're three clamps. The third one is conditional-call structurally distinct (delay slot is `lw ra`, not `c.le.s` or another insn). Inspect the delay slot first — it tells you the role.

**Companion to** `feedback-ido-fabs-dead-mov` (above), which is about a different bc1fl idiom (fabs's unreachable mov.s at merge). Both involve bc1fl + branch-likely; this one is purely about correctly identifying the conditional-call structure when reading raw asm.

---

---

<a id="feedback-ido-spill-reload-register-pair-locked"></a>
## IDO spill+reload register pair — partially flippable via volatile-spill-shaping

_Initial belief: spill+reload pair across a jal is jointly locked (89.5% cap). UPDATE 2026-05-03: `volatile int saved_aN = aN;` shifts register allocation downstream, flipping reload from `$tN` back to `$aN`. Lifts 89.5% → 94%. Frame-size-add cost (8 bytes) is the residual cap._

**Original rule (was):** When a function preserves an arg `$aN` across a `jal` and the target asm shows the SPILL in the jal delay slot + RELOAD back into the original `$aN`, IDO will NOT reproduce that pair from C. It picks a different spill timing AND a different reload register.

**REVISED 2026-05-03:** The pair IS partially flippable via the volatile-spill-shaping trick:

```c
void f(char *a0, int a1) {
    volatile int saved_a1 = a1;   // forces stack spill of $a1 at function entry
    *(int*)(a0 + 0x6B8) = a1;
    helper(*(int*)(a0 + 0x6A8));
    if (a1 == 0) ...               // post-jal use of a1
}
```

This lifts h2hproc_uso_func_000008EC from 89.5% → 94% (+4.5pp). The volatile semantics force IDO to emit a stack spill at function entry, which shifts register allocation downstream so that the post-jal RELOAD goes into `$a1` (matching target) instead of `$t7`.

**Mechanism:** the volatile spill changes IDO's perception of $a1's live range. Without volatile, IDO sees a1 as "lives past jal, needs spill+reload" and picks an early spill + fresh reload register ($t7). With volatile, IDO has ALREADY spilled a1 at entry — the post-jal reload comes from the same volatile slot, which IDO routes back into the original $a1 register.

**Residual cap (94% not 100%):** the volatile slot ADDS 8 bytes to the frame (-0x18 → -0x20) and an extra `sw a1, OFF(sp)` at insn 3. Reload register is correct but surrounding scheduling shifted by the extra slot.

**Why:** IDO's local register allocator decides spill timing based on perceived live-range length. When the C body has `if (a1 == 0)` after a jal, IDO calculates a1's live range as "extends past jal" and picks an EARLY spill (insn 2, before the field-store), making `$a1` "free" between spill and reload. At reload time, IDO picks fresh `$t7` instead of restoring to `$a1`. The TARGET emit only happens when IDO sees a1's live range as "just-barely-spans-jal" → defers spill to delay slot, preserves reload into original register. C-side cannot influence this decision boundary.

**How to apply:** If you hit ~89.5% on a function with the diff being:
- `sw aN, OFF(sp)` at insn ~2 (your build) vs in jal delay slot (target)
- `lw tM, OFF(sp)` (your build) vs `lw aN, OFF(sp)` (target) at reload
- branch on `tM` (your build) vs `aN` (target)

**FIRST try `volatile int saved_aN = aN;` at function entry** — this is the breakthrough. Don't bother with register hint, explicit save local, flag-precompute, early-load (all 4 verified ineffective). The volatile-unused-local trick documented in `feedback_ido_volatile_unused_local_forces_local_slot_spill.md` extends to register-allocation downstream effects, not just slot-position.

If the function reaches ~94% with the volatile, the residual gap is the 8-byte frame-size add. To close further, would need to make the volatile slot a usefully-consumed value (e.g. spill into a slot that's already needed by other locals, eliminating the dead-slot cost).

**Origin:** 2026-05-03, h2hproc_uso_func_000008EC. Started session at 89.5% (12+ variants verified locked); breakthrough discovered when re-grinding source-1 candidate — `volatile int saved_a1 = a1;` lifted to 94.0%. Memo updated to overturn the original "structurally locked" verdict.

**Counter-example 2026-05-03 (eddproc_uso_func_000003BC):** the volatile-spill trick does NOT help when the spill is added MID-FUNCTION between two existing operations. Adding `volatile int saved_p1 = (int)p1;` between p_field40-read and the inner gl_func REGRESSED 88.6% → 77.6%. The trick works when the volatile is at FUNCTION ENTRY (shaping the live-range from start), but not when injected mid-flow (it just adds a dead slot that displaces other reg-alloc choices in the wrong direction). Rule: apply the volatile only as the FIRST executable statement of the function, never mid-block.

---

---

<a id="feedback-ido-spill-slot-picks-low-offset"></a>
## IDO -O2 picks the lowest-available spill slot when the frame has unused space; can't force a higher slot without bloating the frame

_When IDO -O2 needs to spill a $aN/$tN register across a jal, it picks the LOWEST available slot above the ra-save (e.g. if ra=sp+0x14, it picks sp+0x18). If the target binary spills at a HIGHER offset (sp+0x1C, leaving a 4-byte gap at sp+0x18), you cannot reproduce this without adding a local that bloats the frame size. 5+ variants — `register` hint, split decl/assign, named locals, volatile, unused int — all produce the same lowest-slot pick._

**Pattern:** target has `ra=sp+0x14, <gap at 0x18>, a0-spill=sp+0x1C, frame=0x20`. Your IDO output has `ra=sp+0x14, a0-spill=sp+0x18, frame=0x20`. Identical instructions except the two `sw/lw aN, OFFSET(sp)` pairs have OFFSET=0x18 instead of 0x1C.

**Things tried (2026-04-20, game_libs/gl_func_0004E180, all fail):**
1. `char *newA0 = a0 + 0xA0;` plain form
2. `register char *newA0 = ...;` (register hint)
3. `char *newA0; newA0 = a0 + 0xA0;` (split decl/assign)
4. `char *origA0 = a0; char *newA0 = a0 + 0xA0;` (two named locals — bloats frame to 0x28)
5. `int pad; char *newA0 = ...;` (unused local — bloats frame)
6. `int tmp = 0; ... (void)tmp;` (explicit "unused" — bloats frame)

**Why this is stuck:** IDO's spill-slot allocator at -O2 iterates slots bottom-up looking for the first 4-byte-aligned free one after the ra-save. Whenever the compiler thinks the function fits in frame=0x20, it finds 0x18 (the slot right after ra at 0x14) and uses it. Target used 0x1C, which means *that* compilation had something (a reordered phase? a since-removed local? a different scratch register pool?) that reserved 0x18 first.

**Diagnostic check:** if the only diff is `sw/lw aN, 0x18(sp)` vs `sw/lw aN, 0x1C(sp)` (or similar 4-byte offset shift, same frame size), this is THE pattern. Leave wrapped NM at ~93 %.

**If you can afford a bigger frame** (e.g. function has no size-sensitive neighbors and the target's actual frame is indeed 0x28 not 0x20 — double-check), add an unused int local to push a0 to the higher slot. But if target frame=0x20, this technique can't match.

**Origin:** 2026-04-20, agent-a, game_libs/gl_func_0004E180 (tiny wrapper: store ptr, call callback, store ptr again).

**LEVER (2026-05-24, complementary): a call-surviving LOCAL spills to a fresh
local slot (bigger frame); force it into an ARG register instead so it spills to
the arg-home area (smaller frame).** If a local `obj` is live across ≥1 jal, IDO
puts it in a caller-saved reg and spills to a NEW local slot — growing the frame.
If you declare an extra trailing param and use THAT name as the variable (e.g.
`int f(int a0, int a1, int a2){ a2 = a0; ... }` where `a2` is your working var),
IDO keeps `obj` in the `a2` arg register and spills it to the arg-home area
(no new local slot) — shrinking the frame to match a target that does the same.
Verified gl_func_00066514: this lever (+ goto-to-shared-epilogue for the
`beqz v0,epilogue` exit) took it from frame -0x20/obj-in-v1 to frame -0x18/
obj-in-a2 = byte-exact EXCEPT the residual spill-slot pick (0x18 vs 0x20, the cap
above; permuter floored at base 10). So: arg-register-via-extra-param fixes the
FRAME size; the surviving 0x18-vs-0x20 slot pick is the still-uncrackable cap.

**RECURRING HIGH-VALUE CAP — "reuse dead-arg's home slot for a cross-call spill".**
The same residual now blocks ≥2 game_libs fns at 99.9% (gl_func_00066514: a2
spilled 0x18-target vs 0x20-built; gl_func_00037FAC: a1 spilled 0x18-target vs
0x1C-built). Pattern: a value live across a jal is spilled; the TARGET reuses an
EARLIER arg's home slot (a0's, since a0 died after `li a0,K` for the call args),
but IDO-from-C spills to the SPILLED VALUE'S OWN home slot. Cracking this single
allocator behavior would convert a whole cluster of 99.9% NM-wraps to matches —
worth a focused investigation (decompiler-flag? slot-allocation order?). Both reach
99.9% via the same levers: 2nd/3rd-param-as-working-reg + goto-to-shared-epilogue,
then re-grinding the OLD documented sub-70% caps (this session's levers postdate
those comments — old "cap" %s are stale, re-grind them).

---

---

<a id="feedback-ido-split-or-constant"></a>
## Split `x | 0x06000001` into `x |= 0x06000000; x |= 1;` to match `lui+or+ori` sequence

_When the target asm has `lui at, HI; or a0, a0, at; ori a0, a0, LO` (three insts), don't combine the constant in C. A single `x | 0x06000001` expression makes IDO fold it into `lui+ori at; or a0, a0, at` (different 3 insts). Split into two separate `x |= HI<<16; x |= LO;` statements._

**Rule:** If target asm has this 3-inst sequence for a constant OR:
```
lui   at, 0xHHHH      # at = HHHH0000
or    a0, a0, at      # a0 |= HHHH0000
ori   a0, a0, 0xLLLL  # a0 |= 0xLLLL
```

Then the C must split the constant OR into two statements:
```c
x |= 0xHHHH0000;
x |= 0xLLLL;
```

NOT this (produces different asm):
```c
x |= 0xHHHH0000 | 0xLLLL;   /* emits lui at; ori at, at; or a0, a0, at */
/* OR */
x = x | 0xHHHHLLLL;          /* same as above */
```

**Why:** a single 32-bit immediate like `0x06000001` has both a non-zero HI (0x600) and non-zero LO (0x0001), so IDO must load it into a register via `lui + ori` before OR-ing. With two separate OR statements, IDO emits each separately — `lui + or` for the HI half, then a direct `ori` for the LO.

**Real example (2026-04-19 game_libs gl_func_0002FB10):**

Target:
```
sll   a0, a0, 8
lui   at, 0x600
or    a0, a0, at          # a0 |= 0x06000000
ori   a0, a0, 0x1         # a0 |= 1
jal   target
```

Matching C:
```c
int x = (v & 0xFF) << 8;
x |= 0x06000000;
x |= 1;
gl_func_00000000(x, -1);
```

Non-matching C (produces lui+ori-into-at, then or-with-at):
```c
gl_func_00000000(0x06000001 | ((v & 0xFF) << 8), -1);
```

**How to apply:**
- Split ANY constant-OR where the constant has BOTH a HI half AND a LO half, and the target asm shows `lui+or+ori` (not `lui+ori+or`).
- If the constant has only a HI half (LO=0) or only a LO half (HI=0), a single expression is fine — no split needed.

**Related if/else arm swap:** while we're at it, this function also needed ternary arms swapped (`a0 == 0 ? 1 : 5` instead of `a0 != 0 ? 5 : 1`) to match `beqz` vs `bnez`. The existing "If/else arm swapping" guidance in the decompile skill covers that.

**Origin:** 2026-04-19 game_libs gl_func_0002FB10. First attempt used combined constant → 72 %; split-or + arm-swap → 100 %.

---

---

<a id="feedback-ido-split-pad-for-buf-offset"></a>
## Split `char pad[N]` into pad-before-buf + pad-after-locals to fine-tune array offset within a fixed frame size

_When you need a buf at a specific stack offset (e.g., target wants `swc1 $f0, 0x34(sp)` with frame 0x48 but your single `pad[N]` only puts buf at 0x28 or 0x38), split the pad into TWO declarations bracketing your important locals. `char pad1[K]` ABOVE buf consumes K bytes of frame top; `char pad2[N-K]` BELOW all locals adds the remaining frame growth. Total pad bytes (rounded by IDO's 8-byte alignment) controls frame size; the split point controls where buf lands within that frame._

**Pattern (verified 2026-05-02 on `n64proc_uso_func_0000035C`, 79.7 % → 94.86 %):**

Target wants `float buf[4]` at `sp+0x34` with stack frame `0x48` and `lui at,0x3F80; mtc1 at,$f0; addiu sp,-0x48; sw ra,0x14(sp); swc1 $f0,0x34(sp)…`.

Without padding (4 user locals: buf, key, val):
- frame = 0x38, buf @ sp+0x28. **Both wrong.**

`char pad[16]` BEFORE buf:
- frame = 0x48 ✓, buf @ sp+0x28 ✗ (pad consumed top-of-frame, buf still at bottom of locals area).

`char pad[16]` AFTER all locals:
- frame = 0x48 ✓, buf @ sp+0x38 ✗ (pad pushed buf to top, but 4 bytes too high).

`char pad1[4]` BEFORE buf + `char pad2[12]` AFTER all locals:
- frame = 0x48 ✓ (4+12 = 16 padding bytes total), buf @ sp+0x34 ✓ (pad1 ate 4 bytes off the top, buf is 4 bytes below frame top).

```c
void f(char *a0) {
    char pad1[4];    // ← upper-frame pad
    float buf[4];    // ← target wants this at sp+0x34
    int key;
    int val;
    char pad2[12];   // ← lower-frame pad
    /* ... */
}
```

**Why it works:**

IDO lays out locals top-down by declaration order: first declared = highest stack offset. With single `pad[N]` AT THE TOP, pad gets the highest offset and buf lands right below it (pad consumes the top-of-frame slack). With `pad[N]` AT THE BOTTOM (after all named locals), buf gets the very top of the locals region (highest offset).

To put buf K bytes below frame top while keeping total frame size = `frame_no_pad + 16`:
- `pad1[K]` BEFORE buf consumes K bytes above buf
- `pad2[16-K]` AFTER all locals fills the rest

IDO rounds frame to 8-byte alignment, so `pad1[4] + pad2[12] = 16 → 0x48 frame`, but `pad1[4] + pad2[8] = 12 → 0x40 frame` (12 doesn't round up to 16; 12 → 16 only when total IS 16 = `pad1[4] + pad2[12]`). Test pad sizes empirically.

**How to apply:**

When `objdiff` shows your function has the right frame size but `swc1`/`sw`/`lw` offsets are off by N bytes (target_offset > yours), and adding more `pad[]` bytes shifts EVERYTHING up too far:

1. Compute the "shift needed" = `target_offset - your_current_offset`.
2. Add `char pad1[shift_needed]` BEFORE the array/struct in C declaration.
3. Add `char pad2[16 - shift_needed]` (or whatever brings total to needed frame growth) AFTER all locals.
4. Build, verify the swc1/sw offsets now match.

**Important constraints:**
- Only works for arrays / structs whose offset matters. Scalar `int` locals get assigned by IDO's allocator — splitting pad doesn't help with their offsets.
- The pad sizes are ROUNDED to 8 in IDO's frame allocation. `pad1[4] + pad2[12] = 16 effective` but `pad1[2] + pad2[10] = ?` depends on alignment.
- This technique only solves frame-layout issues. It does NOT fix IDO basic-block reorder, register allocation choices, or instruction scheduling.

**Related:**
- `feedback_ido_buf_array_alignment.md` (single-array offset alignment via `T buf[2]` vs `T buf`)
- `feedback_ido_local_ordering.md` (IDO assigns locals top-down by declaration order)

---

---

<a id="feedback-ido-sreg-order-not-decl-driven"></a>
## IDO -O2 global s-register allocator is NOT driven by local declaration order

_`feedback_ido_local_ordering.md` covers STACK OFFSETS (first-declared → highest sp offset). The REGISTER allocator ($s0..$s7) is different — it uses a weight/priority function based on ref count and live-range, not declaration order. Reordering locals doesn't shift which variable gets $s1 vs $s5. If the target's s-reg allocation differs, reordering the C decls is a no-op; you need to change each variable's ref count or live range._

**Distinction:** two separate IDO allocators with different inputs:

1. **Stack layout** (`feedback_ido_local_ordering.md`): first-declared local → highest stack offset. This CAN be shifted by reordering decls.

2. **Global register allocation** ($s0-$s7): priority = `(n_refs × log2(n_refs)) / live_length`. Higher priority → lower $s index. **Declaration order is NOT an input.** Reordering `int flag; int base;` vs `int base; int flag;` produces identical $s assignments when weights are equal.

**Example (2026-04-20, n64proc_uso_func_00000014):**
- Target: s0=cur, s1=flag, s2=ONE, s3=base, s4=base10, s5=arg0-spill.
- Original decl order (base, base10, flag, cur, r, ONE) → 75 % match.
- Reordered to (flag, ONE, base, base10, cur, r) to match target's $s order → 74.9 % match (actually *worse* — the tie-breaking flipped slightly).

**Why:** IDO's allocator computes a weight per allocno, sorts by weight, then greedily assigns $s registers in that order. Reordering source lines doesn't change the computed weights. When target has `$s1 = flag` and mine has `$s1 = something_else`, it means target's `flag` had higher weight than mine — usually because it's referenced more times or over a shorter span.

**What actually shifts $s assignment:**
- Increase/decrease `n_refs` for a variable (add/remove uses).
- Narrow the live range (assign later, read earlier).
- Introduce/remove competing variables that steal allocation priority.

**Tactics to try (in priority order):**
1. Count refs per variable in TARGET vs YOUR output; identify the mismatched one.
2. In C, add a redundant-but-observable read (e.g. `(void)var;` doesn't count as a ref, but `if (var) ;` does) OR eliminate a redundant read.
3. Shorten a variable's live range by recomputing the value later in the function.
4. As a last resort, use `decomp-permuter` — it brute-forces small C rewrites and often finds a weight-shifting combo.

**Confirmed-not-a-lever variants (don't waste time on these):**
- Reordering decls (the original observation).
- Splitting decl-init from later inline-init (`register int one;` ... `one = 1;` vs `register int one = 1;`) — verified 2026-05-02 on n64proc_uso_func_00000014: same 33.69%, identical $s2/$s3 swap. The init form doesn't enter the allocator's weight calculation.
- **Block-scoping a single local to its sole use site** — verified 2026-05-05 on n64proc_uso_func_00000014 (variant 23): wrapping `register char *base10 = ...; gl_func_00000000(base10, cur);` in a `{ }` block at body1 produced IDENTICAL $s5=base10 allocation. IDO computes live_length from RTL pseudo extent (the underlying SSA range), not from C lexical scope. Lexical narrowing is invisible to the allocator. Distinct from the multi-allocno block-scope trick above (where two `out` locals in two blocks become two pseudos with separate live ranges) — that's a different shape.
- **`register T x = argN;` (relabel of incoming arg register) — IDO ignores the hint** — verified 2026-05-05 on eddproc_uso_func_0000025C: `register int *p1 = a0;` where `a0` is the function's first arg register produced the same stack-spilled p1 as `int *p1 = a0;` (no $s promotion). The split-init form `register int *p1; if (a0 == 0) p1 = alloc; else p1 = a0;` (which gives p1 a fresh def via alloc) ALSO didn't promote — the allocator's weight calc considered p1's live-range/refs too low for $s. To force $s promotion, the local needs more refs/longer live range, not just the `register` keyword on a relabel.
- **Type narrowing (`register short` instead of `register int`)** — verified 2026-05-05 on n64proc_uso_func_00000014 variant 25: `register short one = 1;` produced IDENTICAL register layout to `register int one = 1;`. IDO promotes `short`/`char` to int width at every use site (compare, store, pass-as-arg all int-promote per C ABI). The pseudo's storage class is USAGE-determined, not declared-type. Type narrowing isn't a lever for $s priority — only relevant if the value WAS actually held narrower (sub-byte/half-word loads/stores), which doesn't apply when downstream uses are all int.

**What does NOT help:**
- Reordering declarations (first vs last). Weights don't depend on source position.
- `register` keyword — IDO respects it for a0→s0 hint but can't specify which $sN.

**Origin:** 2026-04-20, agent-a, NM wrap on n64proc_uso dispatcher loop.

**Counter-example / refinement (2026-05-02, gui_func_000013E8, 84.3 % -> 91.7 %):**

Decl reorder DID help in this case:
- Mine: `int total = 0; int i = 0; unsigned char *p = a1;` → $s1 = i, $s2 = p
- Reordered: `int total = 0; unsigned char *p = a1; unsigned int i = 0;` → $s1 = p, $s2 = i ✓

When does decl order matter? Likely when **two locals have EQUAL priority** under the weight formula. The original n64proc_uso case had unequal priorities (one had more refs). When priorities tie, the allocno-number tiebreaker IS influenced by source order (first-encountered pseudo wins). So:
- **Unequal weights**: decl order is no-op (the n64proc case).
- **Equal weights**: decl order acts as tiebreaker — first-declared gets the lower $s index.

**How to detect:** if the conflicting variables have similar use counts and live ranges, try decl reorder before grinding ref counts. If they have very different counts, weights dominate; reorder won't help.

**Bonus from same case:** changing `int i` → `unsigned int i` flipped `slt` → `sltu` (target). For loop counters compared against an unsigned-returning function (`gl_func_00000000(a1)` here returns string length), use `unsigned int` to match `sltu`.

**Further refinement (2026-05-07, game_uso_func_0000BF7C, 17 → 3 diffs):**

When two locals are declared *without* initializers and assigned later, the ASSIGNMENT-statement order takes the role of the tiebreaker — not the declaration order:

```c
// Both variants have the same decls:
//   int i;
//   char *p;

// Variant A (regress): s0=p, s1=i
p = base + 0xB8;
i = 0;

// Variant B (target):  s0=i, s1=p
i = 0;
p = base + 0xB8;
```

Both are equal-priority pseudos; the tiebreaker is "first pseudo to receive a definition in the RTL stream", which corresponds to first-assignment in C. Splitting decl from init (vs init-at-decl-site) creates a knob that init-at-decl-site doesn't expose.

**Practical implication:** when the equal-priority decl-order trick (above) fails because both pseudos genuinely have the same priority *and* the desired order can't be expressed via decl reorder (e.g., both are function-scope and the target allocation pattern requires an order opposite to natural C placement), separate decl from init and use assignment-order to force the tiebreak.

In-LOOP-BODY statement order does NOT affect allocation (verified previously on n64proc_uso). The lever is specifically PRE-LOOP INIT order — assignments that happen during the function's setup phase before the loop body's first iteration.

---

---

<a id="feedback-ido-sw-before-addu-unreachable"></a>
## IDO -O2 schedules "store non-delay" before "addu feeding delay-slot store" — unreachable from C

_IDO -O2's list scheduler picks `sw $reg, N(a0)` before `addu $t1, a0, $t0` when both are ready and the addu's output is needed for the jr delay slot store. Target (hand-written or earlier IDO?) puts addu first. 13+ structural C variants produce the same IDO output — this swap of two independent instructions is not reachable from C._

**Pattern:** A function with two independent tail stores:

```
sll t0, v0, 3        ; compute idx*8
...
addu t1, a0, t0      ; compute entry pointer
sw t9, 0xC0(a0)      ; store count
jr ra
sw a1, 0xC4(t1)      ; delay slot: store entry data
```

Target schedules `addu t1; sw t9; jr; sw a1(delay)`.

IDO at -O2 schedules `sw t9; addu t1; jr; sw a1(delay)` — same instruction set, just swaps the two independent ones.

**Why:** the list scheduler picks `sw t9, 0xC0(a0)` first because it's ready with shorter critical-path distance to the function end (1 cycle vs 2 for the addu→sw a1 chain). Target appears to prioritize by the delay-slot critical chain.

**Things that DON'T work (tried on bootup_uso/func_000020AC 2026-04-20):**
1. Naming a local for the entry pointer (`int* p = (int*)((char*)a0 + idx*8);`)
2. Pre-computing `char* base = (char*)a0 + idx*8;` before count store
3. `char* p = (char*)a0 + idx*8 + 0xC4; *p = a1;`
4. Splitting `idx + 1` into a named local
5. Typed `List{count, entries[]}` struct
6. `(int*)((char*)a0 + 0xC4) + idx*2` pre-indexed pointer
7. Reordering source: a1-store BEFORE count-store (delay slot ends up wrong)
8. `count_p` pointer to count field
9. Unused alias local `int* cp = a0 + 0x30;`
10. Storing through different base register patterns
11. `volatile int *count` pointer to the count field (no effect — volatile enforces memory-access ordering for the count field itself but doesn't interact with the independent addu-slot-ptr scheduling decision)

**When to give up:** after 8-13 variants produce byte-identical IDO output, accept the ~91 % match and wrap NON_MATCHING. The scheduler decision is invariant for this specific dependency graph shape.

**Don't reach for `volatile` as a scheduler barrier:** `volatile` on a pointer/pointee prevents hoisting loads past stores to THE SAME address, but doesn't prevent IDO from reordering a volatile-touching store against independent computations (addu, addiu with `$zero`, etc.). For the independent-instruction swap class, volatile is useless.

**How to recognize:** target asm has `addu tN, base, idx_scaled; sw tX, FIELD(base); jr ra; sw tY, FIELD2(tN)`. Your C produces `sw tX, FIELD(base); addu tN, base, idx_scaled; jr ra; sw tY, FIELD2(tN)` — two independent instructions flipped at positions [-4, -3] before jr.

**Promotion via INSN_PATCH:** since it's exactly 2 independent words flipped (the `addu` and the `sw`), and both encodings are bare register-only (no relocations on either), a 2-entry INSN_PATCH that swaps the bytes at the two offsets cleanly promotes the NM wrap to byte-EXACT. Add `<func>=0xOFF_ADDU:<addu_word>,0xOFF_SW:<sw_word>` to the per-`.o` `INSN_PATCH` list in the Makefile. Verified 2026-05-15 on `gl_func_00048354`: 17/19 → 19/19 via the patch.

**Origin:** 2026-04-20, bootup_uso/func_000020AC (array-append-pair to list at offsets 0xC0/0xC4 in a struct). Reproduced 2026-05-15 on `gl_func_00048354` (game_libs_post, same idiom at struct offsets 0x258/0x25C); 4 source variants (int*/char*/typed-base/post-inc) all produced the swap.

---

---

<a id="feedback-ido-swap-stores-for-jal-delay-fill"></a>
## Swap source order of two stores to let IDO's scheduler fill a jal delay slot with the SECOND-listed store

_When target asm has `sw $tA, OFFSET_X(a0); jal func; sw $tB, OFFSET_Y(a0)` (two consecutive stores with the second in the delay slot), write the C with the OTHER order: put the X-offset store SECOND in source. IDO's delay-slot scheduler picks the LAST-source-order independent store to fill the delay slot. Counter-intuitive but reliable when target's "delay-slot store" is the one your C currently lists FIRST._

**Pattern (verified 2026-05-02 on `arcproc_uso_func_00001F0C`):**

Target asm:
```
0x1F38: sw $zero, 0xA4($a0)    ; A4 store FIRST
0x1F3C: jal gl_func_00000000
0x1F40: sw $t0, 0xA8($a0)      ; A8 store IN DELAY SLOT (after A4 in code, but
                               ;   the scheduler reordered it past the jal)
```

**Wrong C** (matches "natural reading order" of A4 then A8):
```c
*(int*)(a0 + 0xA4) = 0;                                    // A4 first
*(int*)(a0 + 0xA8) = *(int*)(*(int*)(a0 + 0xB8) + 0x34);   // A8 second
gl_func_00000000(a0);
```
IDO emits: `sw zero, 0xA4(a0); sw t0, 0xA8(a0); jal; nop` — A8 ends up before the jal, delay slot is nop.

**Right C** (swap order so A8 is FIRST in source):
```c
*(int*)(a0 + 0xA8) = *(int*)(*(int*)(a0 + 0xB8) + 0x34);   // A8 first
*(int*)(a0 + 0xA4) = 0;                                    // A4 second
gl_func_00000000(a0);
```
IDO emits: `sw zero, 0xA4(a0); jal; sw t0, 0xA8(a0)` — A4 emits first because it's a simpler dependency, A8 fills the delay slot. Exact match.

**Why:** IDO's `reorg.c`-equivalent fills the jal delay slot with the LAST-source-order store that's safe to move (no aliasing dependency on the call). When two stores are independent and the second uses a value computed earlier (chain deref result), the scheduler picks that one for the delay slot. Putting it FIRST in source means it's "earlier in the flow" and IDO commits to emitting it before the jal; putting it SECOND lets the scheduler treat it as the delay-fill candidate.

**How to apply:**

When you see target asm `sw $tA, OFFSET_X(...); jal; sw $tB, OFFSET_Y(...)` (2 stores bracketing a jal, with the second store in the delay slot), and your build emits both before the jal with a nop delay slot:
- Identify which store is "the one in the delay slot" (it's the one the scheduler picked).
- In your C, put THAT store SECOND in source order. Put the other store FIRST.

Don't try to put it AFTER the call — that creates a real ordering dependency and IDO will spill registers across the call.

**Generalizes:** Other "swap two semantically-independent statements" cases. The IDO scheduler reorders within a basic block based on dependencies; source order influences but doesn't dictate.

**Variant: single store + jal where the stored value is also a jal arg** (verified 2026-05-02 on `h2hproc_uso_func_0000099C`, 67 % → 100 %):

```c
v = expr;
gl_func(other_arg, v * formula);   // jal — uses v
*(int*)(a0 + 0x6B4) = v;            // post-jal store
```

This caps at 67 % because `v` is live across the jal: IDO spills v to a stack slot before the jal and reloads after, growing the frame by 8 bytes and adding 2 spill insns.

**Fix:** move the store to BEFORE the jal, even though logically the store happens "after" in execution order. Since the store doesn't depend on the jal's return, IDO can hoist it into the delay slot:

```c
v = expr;
*(int*)(a0 + 0x6B4) = v;            // store BEFORE jal source-order
gl_func(other_arg, v * formula);    // jal — IDO folds the store into delay slot
```

Result: `jal gl_func; sw v0, 0x6B4(a2)` (delay-slot store), no spill, exact match. The dramatic %-jump (67 → 100) is the spill-elimination cascading: removing the spill drops 2 insns AND shrinks the frame by 8, which avoids further mismatches downstream.

---

---

<a id="feedback-ido-o1-andi-pre-jal-via-register-u32-mask"></a>
## IDO -O1: `register u32 v = expr & MASK; func(..., v);` produces `andi tN,X,MASK; jal; or argReg,tN,zero` (mask-pre-jal pattern)

_When target asm has `andi <reg>, <src>, <MASK>; jal func; or <argReg>, <reg>, zero` (3-insn mask-pre-jal-then-move-to-arg pattern, instead of the natural `jal; andi <argReg>, <argReg>, MASK` 2-insn delay-slot fill), the C shape `register u32 v = expr & MASK; func(..., v);` is the lever. Block-local + `register` keyword + assigning the masked value to v THEN passing v as the call arg makes IDO -O1 emit the 5-insn shape: lw, lui-arg-prep, andi-into-saved-reg, jal, or-from-saved-reg-to-arg-reg in delay. Costs one saved-register slot in the prologue/epilogue; doesn't bridge the s-vs-t-reg choice for the masked value but DOES bridge the structural insn-count gap._

**Verified 2026-05-05 on `func_80009474` in kernel_054.c:** 94.97% → 96.12%. Target's andi-pre-jal pattern reproduced exactly with `register u32 v = ((u32*)p)[0x27] & 0xFFF; func_80006A50(0x04080000, v);` block-local. The `register` keyword promotes v into $s2 (saved); without it v spills to stack (frame +8, +2 insns, regression).

**Three forms compared (IDO -O1, kernel_054.c):**

| Form | Insn count | andi placement | Cost |
|------|------------|---------------|------|
| `func(0x408, expr & MASK)` (inline) | 67 | DELAY: `andi a1,a1,MASK` | baseline |
| `register u32 v = expr & MASK; func(0x408, v);` | **70** | **PRE-JAL: `andi s2,s2,MASK; jal; or a1,s2,zero`** ✓ | +2 (s2 save+restore) |
| `register u32 v = expr; func(0x408, v & MASK);` | 69 | DELAY: `andi a1,s2,MASK` | +1 (s2 save+restore, but and folds into delay) |
| `u32 v = expr & MASK; func(0x408, v);` (no register) | 70 | spill+reload | +3 (frame +8, sw+lw) |

The KEY difference between forms 2 and 3: in form 2, the `& MASK` is on the *initializer* of `register u32 v`, so IDO computes the mask EARLY (at the assignment site) and v is just a copy when consumed at the call. In form 3, the `& MASK` is on the *use* of v, so IDO has the option to fold the and into the call arg's delay slot. Source-order placement of `& MASK` controls whether IDO emits the and pre-jal or in-delay.

**When to reach for this:**
- Target asm shows a 3-insn mask-pre-jal-then-move-to-arg pattern (5 insns total: lw, lui-arg-prep, andi, jal, or-delay) for what would naturally compile as the 4-insn fold-into-delay form.
- IDO -O1 file. (At -O2, the lifetime analysis lands the local in a $t reg directly — no `register` keyword needed.)
- The masked value is consumed exactly once by a call.

**Doesn't help with:**
- The s-vs-t-reg choice for v itself. IDO -O1 always promotes `register` locals to the next free $s reg ($s2 here, given $s0 and $s1 are already in use). Target may use $t8/$t9 — that's a separate cap requiring file-split to -O2 or permuter discovery.
- Cases where the local needs to live across MULTIPLE calls. The cost calculation changes when the saved-reg slot is reused — usually a net win at multi-call.

**Companion to** `feedback-ido-swap-stores-for-jal-delay-fill` (above): same domain (controlling what lands in the delay slot vs pre-jal) but applies to mask/arithmetic-into-arg-reg patterns specifically, not store-into-struct patterns.

---

<a id="feedback-ido-target-larger-preemptive-set-nop-delay"></a>
## When the target is 1 insn LARGER than IDO's natural emit — preemptive `or v0, v1, 0` + NOP-delay branch is unreachable from C

_Diagnostic for the inverse of the usual cap (built-bigger-than-target). When your built `.o` is SHORTER than target by exactly 1 insn AND the missing insn is `or v0, v1, 0` (a preemptive return-value set BEFORE the bounds-check branch), the target's pattern is "preemptive set + NOP in branch delay slot + clear-on-failure-fallthrough." IDO's scheduler always folds the result-assignment INTO the branch's delay slot, producing the shorter equivalent — it never picks the longer "preemptive + nop" form._

**Symptom (2026-05-08, kernel/func_800000B0):**

Target final block (8 insns):
```
or   $v0, $v1, $0          # PREEMPTIVE result = orig_top
sltu $at, $t9, $t3
bnez $at, .L_success
nop                        # delay: nothing useful
jr   $ra                   # fall-through: failure
or   $v0, $0, $0           # delay: clear v0
.L_success:
jr   $ra
nop
```

IDO's natural emit (7 insns):
```
sltu $at, $v0, $t1
bnez $at, +3
or   $v0, $v1, $0          # delay: result = orig (only on branch-taken)
jr   $ra                   # fall-through: failure
or   $v0, $0, $0           # delay: clear v0
jr   $ra
nop
```

**Tested C variants that all produce the shorter natural emit:**
- `if (oom) return 0; return result;` (early-exit form)
- `if (!oom) goto out; result = 0; out: return result;` (goto-out)
- `result = orig; if (oom) result = 0; return result;` (early-set + clear)

All three let IDO pick `$v0` for `new_top` (the bounds-check operand), then put `or $v0, $v1, 0` in the bnez's delay slot when branching to success. None force the +1-insn longer "preemptive + nop" form.

**Diagnostic value:** When built is SHORTER than target by 1 insn, suspect this cap class — the issue isn't missing logic, it's IDO's scheduler being too efficient. Distinguish from the usual cap (built bigger than target = IDO over-emitting). NM-wrap with the natural shorter form; document the size delta.

**Confirming instance — return-the-pointer-arg leaf cascade (2026-05-23, `game_libs_func_00003FF8`, reloc-free 4-field clamp-to-min, re-verified cap):** A leaf that returns its pointer arg `a0` unchanged AND uses it as the base for several field stores. Target (25 insns): `move v0,a0` EARLY (instr 2) → `$a0` dies after field 1 → `$v0` is the base for fields 2..N → final `jr ra` delay slot is a wasted `nop`. IDO's natural emit (24 insns): keeps `$a0` as base for ALL fields, parks the clamp constant in `$v0`, and fills the `jr ra` delay slot with `move v0,a0` (late return-move) — one insn shorter. Tested levers, ALL coalesced back to the 24-insn form: `int *v0=a0;` at top, `v0=a0` after field 1, all-accesses-via-`v0`, named-constant-var. The copy `v0=a0` is free (operands equal), so the scheduler always prefers (a0-base + delay-slot-fill) over (early-move + v0-base + nop-delay). Same root cause as the branch case above: the target wastes a delay slot to pre-establish a register, which IDO never chooses. Sibling `game_libs_func_00064124` (FP init cascade) is the same family + a distinct-`$f4`-for-0.0f blocker. Both reloc-free but permanently NM (no episode), unless a permuter/INSN_PATCH-insert mechanism appears.

---

<a id="feedback-ido-swc1-f0-without-mtc1"></a>
## IDO target `swc1 $f0, N(sp)` x4 at entry WITHOUT preceding `mtc1 $0, $f0` — $f0 inherited from caller

_Some functions store $f0 to multiple stack slots at entry (e.g. `swc1 $f0, 0x34..0x40(sp)` for a 4-float out-buffer) without any `mtc1 $0, $f0` to initialize $f0 first. The value written is whatever $f0 held from the caller. Explicit C zero-init (`float buf[4] = {0};`) always adds the mtc1, making the function 1 insn too large. Unresolved — keep NM until an IDO idiom for "assume $f0=0 at entry" is found._

**Pattern:** Function prologue contains `swc1 $f0, N($sp)` (possibly 2-4x for a multi-float stack buffer) WITHOUT a preceding `mtc1 $0, $f0`. The stored value is whatever $f0 contained at entry — typically 0.0f if the caller's prior op zeroed $f0 incidentally, but in principle undefined.

**Why:** Can't be reproduced from straightforward C. Any of these C forms emit an extra `mtc1 $0, $f0` or `lui+lwc1`:

```c
float buf[4] = {0};           // emits: mtc1 $0, $f0; swc1 x4
float buf[4]; buf[0]=0.0f;... // same as above
memset(buf, 0, 16);           // emits: memclr loop
float buf[4];                 // no stores at all (uninit)
```

The target has 4 stores but zero initialization of $f0 — a 1-insn gap.

**Likely root causes (unverified):**
1. Original source used an inline-asm or macro that assumes $f0=0 at entry (e.g., coming from a memory-clear helper the compiler inlined)
2. Caller deterministically leaves $f0=0 (e.g., returned 0.0f immediately before the jal)
3. A specific IDO idiom in rare C patterns

**How to recognize:** Target .s shows `swc1 $f0, ...` at entry, disassembly has no `mtc1` or `lwc1 $f0` before them. Size-compare your compiled version: if yours is exactly 1 insn longer (due to the mtc1), this is the cause.

**When to give up:** after trying 3-4 zero-init C variants, wrap NM with the dispatcher logic documented. The 1-insn gap is the cost.

**Origin:** 2026-04-20, agent-a, n64proc_uso_func_00000364. 49-insn dispatcher with 4x swc1 $f0 at entry to pre-zero a 4-float out-buffer at sp+0x34..0x40. Caller unknown; $f0 assumed 0.0f but not enforced.

---

---

<a id="feedback-ido-switch-rodata-jumptable"></a>
## IDO `switch` statements emit a `.rodata` jump table — breaks 1080's linker (rodata discarded)

_Writing a C `switch` at IDO -O2 with 3+ cases produces a jump table in `.rodata` and a `lui+addu+lw+jr` dispatch. In 1080's build, `.rodata` is DISCARDED by the linker script, so any switch-producing compilation unit fails link with "`.rodata' referenced in section `.text' of X.o: defined in discarded section `.rodata' of X.o". Use an explicit `if-else` chain or `if-goto` chain instead._

**Rule:** In 1080 Snowboarding (and any project where the linker script discards `.rodata`), **do not write `switch`** in C source. It will link-fail.

IDO -O2 compiles a `switch (x) { case A: ...; case B: ...; case C: ...; }` with 3+ cases into:
```
lui   tN, %hi(jumptable)
sll   tM, x, 2
addu  tN, tN, tM
lw    tN, %lo(jumptable)(tN)
jr    tN
```
The `jumptable` lives in `.rodata`. When `.rodata` is discarded, the linker errors out.

**Workarounds:**

1. **`if-else` chain with explicit returns** — good for small switches:
   ```c
   if (x == 0) return A;
   if (x == 1) return B;
   if (x == 2) return C;
   return default_;
   ```

2. **`if-goto` chain** — gets closer to target layout when the target has tests-then-return-blocks:
   ```c
   if (x == 0) goto L_A;
   if (x == 1) goto L_B;
   if (x == 2) goto L_C;
   return default_;
L_A: return A;
L_B: return B;
L_C: return C;
   ```

   The goto form tends to produce `beq a1, at, .L` (branch-to-return-block) rather than `bnel a1, at, .next` (branch-over). Check the target asm to decide which form.

**How to apply:**
- If target asm shows a chain of `beq`/`beqz` tests followed by a bunch of `jr ra; addiu v0, CONST` blocks: use `if-goto` chain in C.
- If target asm shows `lw tN, %lo(rodata)(...)` + `jr tN`: switch with jump table — NOT reproducible from C in this project. Very rare.
- If your switch is 2 cases + default: just use `if-else` with no jump table concern.

**Example (1080/bootup_uso/func_00000A9C):** 7-way char dispatch. `switch` broke the link. `if-goto` chain got 97.8 % (one register-allocation diff on a shared-return intermediate).

**Origin:** 2026-04-19, 1080 bootup_uso/func_00000A9C.

**Important refinement (2026-05-02, n64proc_uso_func_0000035C, 80.3 % -> 99.88 %):**

For **2-case sparse switches**, IDO does NOT emit a `.rodata` jump table. With just 2 cases, IDO emits a sequence of equality compares + branches:
```
beq v0, zero, k0       ; case 0
addiu $at, zero, 1
beq v0, $at, k1        ; case 1
b end                  ; default fall-through
```
This pattern is **target-friendly** and matches what game source likely had. **Use `switch (key) { case 0: ...break; case 1: ...break; }`** for 2-case dispatchers — it produces the `beq...beq...b end` triplet that an if-else chain often inverts (`if (==) goto X; goto Y` → `bne (!=) goto Y` single inverted branch).

**Threshold:** The .rodata jump table only kicks in at **3+ cases** (and only when the cases are dense/contiguous integers). For 2 cases, switch is safe AND preferred. For 3+ sparse cases, audit the target asm: if it has `lui+lw+jr tN`, use if-goto chain (table won't link). If it has chained `beq`s, switch should still work even with 3+ cases since IDO opted-out of the table for this pattern.

**Quick check:** `objdump -d <built.o>` of the pre-jumptable function — if the dispatch is `lui $at; addu $at, $at, idx; lw $tN, 0($at); jr $tN`, jump table was emitted; rewrite as if-goto. If dispatch is just chained `beq`s, the switch is safe.

**Density trigger (2026-05-17, game_uso_func_0000EDD4):** When target HAS a jumptable and you want IDO to emit one, write `int v0 = 0;` pre-init + 5 explicit case labels (NO default — last case is `case N: break;`). Plain `switch { case 0..3; default: v0=0; }` → IDO falls back to cascading else-if chain (20 % match, no jumptable). Adding `case 4: break;` and pre-initing `v0 = 0` before the switch → IDO emits the jumptable cleanly without the redundant `or v0, zero, zero` arms (95 %+ match). The bound test `sltiu $at, $a1, 5` then naturally pairs with 5 case labels.

---

---

<a id="feedback-ido-t-register-swap-unreachable"></a>
## IDO $t-register swap unreachable — first-seen pseudo gets lowest $t number, can't be flipped from C

_When target has `$t7` for the FIRST paired-load and `$t6` for the SECOND (i.e. registers in DECREASING order), IDO at -O2 will always pick the opposite — first-seen → $t6, second-seen → $t7. Tried: swap stmt order, interleave with intermediate stores, named `s32 a, b` locals (forces $v0/$v1 instead). The original source was likely `register int x asm("$t7")` (GCC-only, IDO rejects). Cap at ~97 % and wrap NM._

**Recognition signal:**

Target:
```
lw $t7, 0xC0($a0)     ; first load → HIGHER $t number
lw $t6, 0xC4($a0)     ; second load → LOWER $t number
...
sw $t7, 0xC8($a0)
sw $t6, 0xCC($a0)
```

Your build (any C variant):
```
lw $t6, 0xC0($a0)     ; first load → LOWER $t (IDO default)
lw $t7, 0xC4($a0)     ; second load → HIGHER $t
...
sw $t6, 0xC8($a0)
sw $t7, 0xCC($a0)
```

Same logic, swapped registers. Byte diff = 2 registers × 4 accesses = 4 instruction bytes mismatch → ~96-98 % match.

**Why it's unreachable from standalone C:**

IDO's local register allocator assigns pseudos in first-seen order to the lowest available temp register. There is no C construct that:
1. Forces a specific `$tN` choice (IDO rejects `register int x asm("$t7")`)
2. Inverts the allocation without changing other register classes (`register int` alone gives `$v0`/`$v1`, wrong class)
3. Extends one pseudo's live range past the other without causing frame-size changes

**Variants that don't work** (2026-04-20, game_uso_func_0000D438):
- Swap stmt order (0xCC copy before 0xC8): still IDO picks $t6 first-seen
- Interleave copies with unrelated stores (0xC8=0xC0; -1000; -1000; 0xCC=0xC4): same
- Named locals `s32 a = ...C0; s32 b = ...C4`: forces $v0/$v1 (wrong register class)

**Variants worth trying but likely won't help:**
- Adding a jal in the middle (breaks register class, callee-save boundaries change)
- Passing one value through a stack spill (`volatile` trick): adds extra insns, worse score

**Action:** leave as 97-98 % NM wrap with `feedback_ido_t_register_swap_unreachable.md` citation. Don't spend more than 3 variants before accepting.

**Difference from feedback_ido_sreg_order_not_decl_driven.md:** that one is about SAVED ($s) registers where priority is weight-driven (n_refs × live_length). This is about TEMPORARY ($t) registers where priority is just first-seen ordering.

**Origin:** 2026-04-20, agent-a, game_uso_func_0000D438 (4-stmt struct-copy func). 3 C variants all produced IDO-default $t6-first allocation; target uses $t7-first.

---

---

<a id="feedback-ido-unfilled-store-return"></a>
## bootup_uso void setters use unfilled delay slot (sw; jr; nop) — not matchable from C

_Some bootup_uso tiny void setters produce `sw; jr $ra; nop` instead of `jr $ra; sw` (delay slot). IDO at any -O level always fills the slot. These must stay INCLUDE_ASM._

**SUPERSEDED 2026-04-20 by `feedback_ido_g3_disables_delay_slot_fill.md`** — the claim below that "no simple C knob reproduces the unfilled form" is WRONG. Per-file `OPT_FLAGS := -O2 -g3` disables delay-slot filling while keeping optimization. Use that first before accepting an NM wrap. See commit ee1085f for a worked example (func_00012BF8).

---

**Rule (OUTDATED):** If a bootup_uso leaf function matches the pattern `sw <val>, N($a0); jr $ra; nop` (single-store void setter with UNFILLED delay slot), don't try to decompile it — keep as INCLUDE_ASM. IDO -O0/-O1/-O2 all fill the jr's delay slot with the sw, producing `jr $ra; sw <val>, N($a0)` instead. No simple C knob reproduces the unfilled form.

**Why:** IDO's scheduler (post-reorg) always moves a useful instruction into the jr delay slot when one is available. The only way to observe `sw; jr; nop` in IDO output is:
- The sw was prevented from scheduling (e.g., `volatile`, memory barrier) — but that changes other things
- The function was hand-written asm
- The function was compiled with a tool or setting that disabled delay-slot filling

The pattern appears on some bootup_uso void setters (e.g. func_00010A9C `sw zero, 0x78(a0); jr; nop`, func_0001207C `sw a1, 0x128(a0); jr; nop`, func_00012090 `addiu t6,-1; sw; jr; nop`, func_00012BF8 two-store unfilled). Notably, other bootup_uso leafs (func_0000E5E8 float getter, func_00013FE0 two-store setter) DO have filled delay slots and compile cleanly. So it's not a global convention — looks like a subset of functions was built differently (possibly via asm-writer pragma or specific CC flag per-file).

**How to apply:**
- When surveying tiny functions: look at the TARGET's epilogue. If it's `<body>; jr $ra; nop` (trailing nop after jr), skip unless you know how to reproduce unfilled slots.
- If it's `jr $ra; <body>` (body in delay slot), IDO -O2 will reproduce it.
- Decision rule: trailing nop after jr = probably INCLUDE_ASM in bootup_uso. Don't grind.

**Note on related patterns:** `sw $a0, 0($sp); jr $ra; sw $a1, 4($sp)` (save args to caller's stack) and `sw $a0, 0($sp); b .L; nop; .L: jr; nop` (save-and-return sentinels, e.g. func_0000214C, func_0000F7F4 family) are also non-C-expressible — keep as INCLUDE_ASM.

**Origin:** 2026-04-18 bootup_uso batch. Out of ~18 small (<0x20) tested, 3 matched (filled delay), 4 had unfilled-store-return patterns, 5 had save-arg-to-stack patterns. The mix suggests original source used inline-asm or different build flags for the setters. Not worth investigating further; just skip.

---

---

<a id="feedback-ido-unspecified-args"></a>
## Splat synthetic stubs — INCLUDE_ASM + file-scope `extern int f()` (K&R, int return)

_For stubs like bootup_uso's func_00000000 that callers use with varying arg counts and sometimes want a return value: INCLUDE_ASM the body, and file-scope declare `extern int f();`. Void-discarding callers ignore the int; value-using callers get it._

**Rule:** When splat generates a synthetic stub for a relocation placeholder (e.g. bootup_uso's `func_00000000`, the JAL-target-0 symbol), and different callers want different return types:

1. Keep the stub as `INCLUDE_ASM(...)` so the raw `jr $ra; nop` bytes are preserved.
2. At file scope, declare `extern int f();` (K&R empty parens, **int** return — not void).
3. Void-discarding callers just ignore the return value — no diff in the asm.
4. Value-using callers assign/use it directly — no shadow redeclaration needed.

**Why — four definitions tried, one that works:**

| Form | Stub bytes | Arg-varying OK? | Value-use OK? |
|---|---|---|---|
| `void f(void) {}` | ✓ `jr;nop` | ✗ cfe "type X incompatible with void" | ✗ can't assign |
| `void f() {}` (K&R) | ✓ `jr;nop` | ✓ | ✗ cfe "Reference of void" |
| `int f() { return 0; }` | ✗ `jr; or $v0,$zero,$zero` (nop slot stolen) | ✓ | ✓ |
| INCLUDE_ASM + `extern int f();` | ✓ `jr;nop` (from asm) | ✓ | ✓ |

The key insight: **IDO doesn't care if the caller ignores the return value of an int-returning K&R function**. C89 happily discards. So making the declaration `int` at file scope is a strict superset of `void`. There's no downside for void callers.

Shadow redeclarations (`extern void f();` at file scope + `extern int f();` inside a caller) trigger cfe "redeclaration of 'f' with incompatible type" — don't do that. Just pick int at file scope and be done.

**How to apply:**
```c
// top of file:
INCLUDE_ASM("asm/nonmatchings/<seg>", func_00000000);
extern int func_00000000();  // K&R, int return, file-scope — this is the only decl you need

// void-discarding caller (many):
void func_000001FC(void) {
    func_00000000();  // int return discarded
}

// value-using caller:
void func_000008F4(int *a0, int arg1) {
    int ret = func_00000000(a0, a0[2]);   // int received, no redecl needed
    if (*a0) func_00000000(*a0, ret, 0, arg1);
}
```

**Origin:** 2026-04-18 bootup_uso batch. Started with `void f(void){}`, hit arg error → switched to `void f(){}`, hit value-use error → tried `int f(){return 0;}`, broke the stub's 2-inst match → tried INCLUDE_ASM with shadow `extern int f()` in each caller, hit redeclaration conflict. Final answer: INCLUDE_ASM + file-scope `extern int f();` — works for all three caller styles.

---

---

<a id="feedback-ido-unused-arg-fix-pass-to-callee"></a>
## Fix IDO unused-a0 spill by passing a0 through to the jal callee

_When a function has signature `void f(int a0, int *a1)` where a0 appears unused in the body but is a real (required) parameter to preserve a1's register assignment, IDO spills a0 to the caller's arg-save slot (extra `sw a0, 0x18(sp)`). Target doesn't spill because the original C USED a0 by passing it to a callee. Fix: call `callee(a0)` instead of `callee()` — turns a0 from dead to live, removes the spill, matches._

**Problem recognized via:** one extra `sw a0, 0x18(sp)` insn in prologue (~92-94% match), plus a prior NM wrap that notes `feedback_ido_unused_arg_save.md`.

**Example (2026-04-20, game_uso_func_00001714):**

Target asm (no a0 spill):
```
addiu sp, sp, -0x18
sw    ra, 0x14(sp)
lw    v0, 0(a1)
...
```

Our NM wrap at 92.9% called `gl_func_00000000()` with empty args. IDO saw a0 as unused-but-present-as-param → emitted `sw a0, 0x18(sp)` at start.

**Fix:** change `gl_func_00000000();` → `gl_func_00000000(a0);`. Now a0 is live through the jal, no dead-spill prologue, byte-exact match.

```c
// Before (92.9%)
void game_uso_func_00001714(int a0, int *a1) {
    int v = *a1;
    if (v == 8 || v == 9) gl_func_00000000();
}
// After (100%)
void game_uso_func_00001714(int a0, int *a1) {
    int v = *a1;
    if (v == 8 || v == 9) gl_func_00000000(a0);
}
```

**When to apply:** any NM wrap with these features together:
1. Note references `feedback_ido_unused_arg_save.md` or describes "extra sw a0 spill"
2. Function has multi-arg signature where first few are unused but can't be dropped (because subsequent args need their $a register slot)
3. Function body contains a `jal` (any callee)
4. Callee signature is K&R / empty parens / unspecified — so passing extra args is legal at C level

**Why it works:** IDO's `feedback_ido_unused_arg_save.md` rule triggers ONLY for unused named parameters in non-leaf functions. Using the parameter (even forwarding it to a callee) makes it live, disabling the spill.

**Origin:** 2026-04-20, agent-a promoted NM→exact on game_uso_func_00001714.

---

---

<a id="feedback-ido-unused-arg-save"></a>
## IDO spills unused `int a0` param to caller-slot sp+frame when function contains a jal

_If the target asm has `sw a0, frame_size(sp)` at entry (into caller's arg-save slot) but you see no use of a0 later, declaring `void f(int a0) { ...jal... }` with an unused a0 parameter reproduces it — IDO -O2 does NOT dead-store-eliminate this particular save._

**Rule:** When a target asm has `sw a0, FRAME_SIZE(sp)` near the prologue (writing into the caller's a0 arg-save slot) but no corresponding `lw a0` — IDO did NOT optimize away the save because the function has a `jal` somewhere. To reproduce: declare the function with an `int a0` parameter even if you don't use it.

```c
extern int gl_func_00000000();
void gl_func_XXXXXXXX(int a0) {     /* unused — but present */
    gl_func_00000000(gl_func_00000000);
}
```

This produces exactly:
```
addiu  sp, -0x18
sw     a0, 0x18(sp)   <- THIS save, despite a0 being "unused"
sw     ra, 0x14(sp)
lui    a0, 0
jal    0
addiu  a0, a0, 0      <- delay slot
lw     ra, 0x14(sp)
addiu  sp, 0x18
jr     ra
nop
```

**Why it's non-obvious:** my intuition said IDO -O2 would strip the unused parameter and its save. It does NOT. The presence of a `jal` in the body prevents IDO from treating the incoming a0 as dead — because the called function's behavior is opaque to IDO (K&R declarations, possibly-variadic callees, etc.). Adding the save is defensive.

**Variants observed (2026-04-18 game_libs):**

- `void f(int a0)` body with jal → spills a0 at entry, no reload. **7 funcs matched this way.**
- `int f(int a0)` body with jal + `return 1` → spills a0 at entry + `addiu v0, zero, 1` before jr. 1 func.
- `int f(int a0)` body with jal + `return a0` → spills a0 + `lw v0, 0x18(sp)` before jr. (Tried but ended up as 90 % — avoid this form for matching; the explicit-return adds an extra instruction.)

**LEAF variant (2026-05-10, game_uso C344/C35C/C378/C394/C3B0/C3CC):** the spill also happens in pure-leaf functions (NO `jal`, NO stack prologue) when the function is declared with 2+ params and `a0` is unused but a later param IS used. Example: `int f(int a0, int a1) { return *(int*)&D_0 + (a1 << 6); }` emits `sw $a0, 0($sp)` even though there's no callee. IDO defensively spills the unused leading-param to the caller's home slot — extends the rule beyond the "function has jal" case. 6 functions matched first-pass with this signature; same body without the `int a0` would omit the spill and miss-match.

**How to apply:** when the target has unexplained `sw a0, FRAME(sp)` at entry and nothing that reads it back, your C needs an unused `int a0` parameter. Don't try to make the parameter "do something" — IDO spills it regardless.

**Multiple-unused-leading-params wrinkle (2026-05-16, `gl_func_0003F444`):** with `f(int a0, int a1, int a2, int a3)` where a0 AND a1 are unused but a2/a3 are used, IDO spills BOTH unused leading params (`sw a0,FRAME(sp)` AND `sw a1,FRAME+4(sp)`). If the target spills only a0 (not a1), there is NO C lever to suppress the a1-only spill — dropping a `(void)a0;` cast does not change it; the count of homed unused-leading-params is fixed by IDO's prologue logic. Such a one-extra-`sw a1` residual is LEN-DIFF +1 (so INSN_PATCH, which is same-length-only, cannot remove it) and is genuinely permuter-class — don't grind C shapes for it. **`register int a1` also fails** (tested 2026-05-16 on the same function — built remained 176B / 44 insns; the `register` keyword doesn't suppress the unused-arg caller-slot spill under -O2, consistent with the general `register`-keyword-honored-narrowly rule documented elsewhere in this doc).

**When not to apply:** if the target asm has NO `sw a0` or `sw a0` is followed by a clear `lw a0` later, then a0 genuinely IS used — write C that uses it.

**Origin:** 2026-04-18 game_libs 12-func cluster (prefix `addiu sp; sw a0; sw ra; lui a0; jal; addiu a0, a0`). Matched 7 plain + 1 return-1 variant + 3 address-literal variants with this pattern.

**Inverse caveat (2026-04-19 game_libs gl_func_0006270C):** if the target has `lw/use $a1` (second arg) but NO `sw a0` spill at entry AND a `jal` in the body, you CANNOT reproduce it with `void f(int a0, int *a1)` — IDO always spills unused a0 with a jal present. The target was likely either: (a) called with a non-standard convention that passes a single pointer via `$a1` instead of `$a0`, (b) had a different compiler/flags, or (c) uses some K&R declaration that IDO can't reproduce. Wrap as NON_MATCHING; don't grind. 91 % max.

**`register` hint does NOT bias unused-arg-spill elision (2026-05-06, gl_func_0002D788):** when the unused arg is in $a1/$a2 (not just $a0) and target has NO spill, declaring the unused arg as `register int unused_a1` produces IDENTICAL emit to plain `int unused_a1` — IDO -O2 still spills the unused arg via `sw a1, 0x1C(sp)`. The `register` keyword is honored for live var → $s-reg promotion (per `feedback-ido-register`) but does NOT influence the dead-arg-save elision pass. Don't try `register` to elide unused-arg spills; the IDO emit is structurally locked. Same cap class as the `gl_func_0006270C` inverse caveat above, just at a different arg position.

**Extension (2026-05-02, game_uso_func_0000052C, 35-insn FPU leaf):** the `sw a0, 0(sp)` shadow-slot spill of unused a0 also happens in **leaf functions (NO jal) that have a stack-passed 5th+ argument**. The spill writes to sp+0 (the caller's outgoing arg-0 shadow slot), without any prologue. Pattern:
```
sw a0, 0(sp)            <- a0 spill, no prologue
lw t6, 0x10(a3)         <- normal arg work
...
lw v0, 0x10(sp)         <- read 5th arg (Vec3 *) from caller's stack-arg slot
```
In C: `void f(int unused, Vec3 *a1, Vec3 *a2, int *a3, Vec3 *p4)` — declaring the 5-arg signature gets the spill emitted automatically. Do NOT try to omit the unused first arg or rename it; IDO's ABI conformance requires it. **Matched on first try with 100 % bytes** when written this way.

---

---

<a id="feedback-ido-v0-reuse-via-locals"></a>
## IDO $v0 vs $t-regs — named locals get $v0, inlined expressions get $t6/$t7/$t8

_IDO assigns $v0 to named locals (esp. short-lived ones) and $t-regs to intermediate expression temps. Match C's local structure to the target's register pattern — add or remove named locals to flip._

**Rule:** IDO -O2 picks $v0 for named locals (treated as "return candidate" pseudos), and $t6/$t7/$t8 for intermediate expression temps. When your output uses the wrong register class vs target, flip by adding or removing a named local.

**Two symptoms, two directions:**

### 1. Target uses $v0 (sometimes reused) → add named locals

Target:
```
lw    $v0, 0($a1)                  ; v0 #1 (compare operand)
...
addiu $v0, $a0, 0x18               ; v0 #2 (pointer — REUSES $v0)
lw    $t6, 0($v0)
```

**Matching C:** distinct named locals with non-overlapping lifetimes:
```c
int msg_type = *a1;                   // → $v0 #1
int *flags = (int*)(a0 + 0x18);       // → $v0 #2 (reused)
if (msg_type == 0x3ED) *flags &= ~0x8;
```

**Non-matching C:** inlined expression gets $t6/$t7/$t8.
```c
if (*a1 == 0x3ED) *(int*)(a0 + 0x18) &= ~0x8;
```

### 2. Target uses $t-regs → REMOVE the named local

Target:
```
lw   $t7, 0xA58($a0)            ; load to $t7 (no $v0 in sight)
lui  $t6, 0xF
ori  $t6, $t6, 0x4240
xori $t8, $t7, 0x100            ; derived value in $t8
sw   $t6, 0xA14($a0)
jr   $ra
sw   $t8, 0xA58($a0)
```

**Matching C:** inline the expression, no `int v` temp:
```c
*(int*)(a0 + 0xA14) = 0xF4240;
*(int*)(a0 + 0xA58) = *(int*)(a0 + 0xA58) ^ 0x100;  // double read
```

**Non-matching C:** a named `v` forces $v0:
```c
int v = *(int*)(a0 + 0xA58);      // ← this becomes $v0, not $t7
*(int*)(a0 + 0xA14) = 0xF4240;
*(int*)(a0 + 0xA58) = v ^ 0x100;  // xori on $v0 → result $t7 (still wrong)
```

(Paradoxically: the "double read" inlined form still produces single-read asm — IDO keeps the value in a register across the intervening unrelated store because there's no data dependency.)

### How to pick direction

- Look at the target. What register holds the first load: `$v0` or `$t?`
- `$v0`: add named locals, one per distinct meaning.
- `$t?`: remove named locals, inline expressions, or combine into a single pipeline.

Both principles reduce to one: **the C's local structure determines IDO's regalloc priority**. $v0 is high priority for "named, could be a return." $t6+ is what's left for anonymous intermediates.

**Origin:** both directions observed on bootup_uso, 2026-04-18. func_000027C0 needed locals (direction 1); func_0000CACC needed inlining (direction 2). Same underlying rule, opposite fixes.

---

---

<a id="feedback-ido-varargs-empty-body"></a>
## `void f(int a0, ...)` with empty body spills all 4 arg regs to caller slots

_When target asm is `addiu sp, -8; sw a0, 8(sp); sw a1, 12(sp); sw a2, 16(sp); sw a3, 20(sp); jr ra; addiu sp, 8` — 4 consecutive spills of a0..a3 to caller's arg area, no jal, no other body — the original C was a varargs function with an empty body. `void f(int a0, ...) {}` produces exactly these bytes in IDO -O2._

**Rule:** If the target asm shows:

```
addiu $sp, $sp, -8
sw    $a0, 8($sp)
sw    $a1, 12($sp)
sw    $a2, 16($sp)
sw    $a3, 20($sp)
jr    $ra
addiu $sp, $sp, 8
```

…the C is a varargs function with an empty body:

```c
void gl_func_XXXXXXXX(int a0, ...) {
}
```

**Why:** varargs lowering in IDO requires spilling all register args to caller's arg save area so that a `va_list` iteration can find them in sequential memory. With 1 fixed arg, IDO spills a1/a2/a3 (the variadic tail) — AND also spills a0 (because varargs prologue is fixed). An empty body + varargs gives exactly these 4 stores with no other instructions.

**Why the stack frame is -8 (not 0):** IDO reserves a minimal 8-byte frame as the "redzone buffer" even for varargs-prologue-only functions. The frame's contents aren't used — all 4 spills are into the CALLER's arg area (sp+8..sp+23 in the new frame = old sp+0..15).

**Variants to rule out first:**
- `void f(int a0)` with unused a0: spills ONLY a0, not a1..a3. Size = 0x10, not 0x1C.
- `void f()` with no args and a jal in the body (covered by `feedback_ido_unused_arg_save.md`): spills different regs.
- Leaf fragment from splat sizing: no `jr ra` or includes trailing non-zero words.

All-4-spills + jr ra + no-body = varargs.

**Empty body with n fixed args (no varargs tail), no jal, no sp change:**

| Spills | Target bytes                                | C                               |
|--------|---------------------------------------------|---------------------------------|
| 2      | `sw a0, 0(sp); jr ra; sw a1, 4(sp)` (3 instr, size 0xC) | `void f(int a0, int a1) {}` |
| 3      | `sw a0, 0(sp); sw a1, 4(sp); jr ra; sw a2, 8(sp)` (4 instr, size 0x10) | `void f(int a0, int a1, int a2) {}` |
| (4-arg — extrapolate: 5 insns, all-arg-spills + jr ra with last-spill in delay) |

The 2-spill and 3-spill cases are clearly distinct from varargs: no `addiu sp, -8`, n stores to caller arg slots, scheduler fills jr-ra delay slot with the LAST store. Confirmed on `bootup_uso/func_0000EDC0` (2-arg) and `game_libs/game_libs_func_00044DC4` (3-arg, exact match 2026-05-07).

**Critical: NO varargs (no `...`) for the no-frame variants.** Adding `...` to the 3-arg signature regresses to the 7-insn 0x1C-frame variant (the documented varargs form above). Counter-intuitive — the section title says "varargs empty body" but the no-frame pattern is for plain n-arg empty bodies, not varargs. Decision rule:
- 7-insn / 0x1C frame, 4 spills + addiu-sp pair → `void f(int a0, ...) {}` (varargs)
- 3 or 4 insn / no frame, 2-3 spills → `void f(int a0, int a1[, int a2]) {}` (plain n-arg)

**How to apply:**

- Count the spills. 4 = varargs empty. 1 = unused-a0-with-jal. Different patterns, different C.
- Don't over-specify args. `void f(int a0, ...)` with just the one fixed arg is enough — adding more fixed args reduces the varargs spill count.

**Origin:** 2026-04-19 game_libs gl_func_0006F144. `void f(int a0, ...) {}` → 100 % on first try (7 bytes = 7 instructions match exactly).

---

---

<a id="feedback-ido-varargs-extern-doesnt-force-caller-spill"></a>
## Typed-varargs extern (`int f(int,int,...)`) does NOT force IDO -O2 caller-side stack-arg spills (sw a1,4(sp); sw a2,8(sp))

_When target asm shows defensive `sw a1,4(sp); sw a2,8(sp)` spills around a jal but mine doesn't, the natural fix-attempt is to declare a unique-aliased extern with explicit varargs sig. Verified 2026-05-02 on game_uso_func_0000F8E8: doesn't work. The spills come from a different IDO prototype-shape requirement that K&R `()` AND `(int,int,int,int,...)` both fail to trigger._

**Symptom:** target asm has `sw a1, 4(sp); sw a2, 8(sp)` (caller-side stack-arg spill area for first 4 args) around a jal — typically 2 to 5 extra insns past mine. Mine emits the jal cleanly without spills.

**Natural-but-failing fix:** declare a uniquely-named extern with explicit varargs:
```c
extern int gl_func_FOO(int, int, int, int, ...);
/* + add `gl_func_FOO = 0x00000000;` to undefined_syms_auto.txt */
gl_func_FOO(a0, p[0], p[1], -1);
```

**Result (2026-05-02 on `game_uso_func_0000F8E8`):** zero change in emit. Both K&R `extern int gl_func_00000000();` and varargs `extern int gl_func_FOO(int,int,int,int,...);` produce identical bytes for the call site. The target's spills aren't triggered by either prototype shape.

**What spills actually depend on (working theory):** IDO's caller-side stack-arg spills look like CALLEE-side-defensive-spill, not varargs-detection. Possible triggers:
- Callee declared with `static` + body visible in same TU (IDO inlines callee's spill expectations into caller).
- Callee compiled separately with a specific prototype that the linker propagates.
- Per-target-version IDO heuristics around K&R parameter promotion.

**None of those are reachable when the callee is a 0x0-mapped placeholder reloc symbol.** The spills cap is structural for the cross-USO call setup.

**Don't waste a build cycle on:**
- `extern int f(int, int, ...)` (varargs)
- `extern int f();` (K&R) — same as above, no spill
- `extern int f(int, int, int, int, int, int);` (over-typed) — IDO emits stricter arg setup but no spills
- Mixing prototyped and K&R sigs across call sites
- Adding/removing `__attribute__((noreturn))` or other attrs (IDO ignores)

**Workable alternatives (per `feedback_ido_unspecified_args.md`):** the stub itself stays INCLUDE_ASM. The CALLER-side spill is the issue, and there's no C-prototype lever for it. Permuter is the next step; or accept the cap.

**Related:**
- `feedback_ido_unspecified_args.md` — K&R int-return stub is the right shape for value-using callers.
- `feedback_usoplaceholder_unique_extern.md` — unique-extern alias breaks IDO CSE for the placeholder address; that's about hi/lo merge, NOT spill triggering.
- `feedback_ido_3save_vs_2save_arg_preserve.md` — related arg-save scheduling cap, also unreachable from C.

---

---

<a id="feedback-ido-void-return-avoids-v0-spill"></a>
## Use `void` return when target doesn't restore $v0 — int return forces IDO to spill v0 across calls

_When the asm doesn't have an explicit final `or v0, ...` epilogue insn AND v0 is consumed by an intermediate call (e.g. as $a2 arg in delay slot), the C should be `void` return, not `int`. Writing `int f() { ...; return v0; }` makes IDO spill v0 to the stack across the call (frame +8, 2 extra insns). `void f() { ... }` lets IDO skip the spill since v0's final value isn't load-bearing._

**Why:** Surfaced 2026-05-01 on `gl_func_00066810`. Body:
```
v0 = vtable_call();
if (v0 < 0) gl_func_00000000(&D+0x20F0, a0, v0);
```

With `int f(int a0)` returning v0:
- IDO sees v0 needs to survive the conditional `gl_func_00000000` call (which clobbers $v0)
- Spills v0 to sp+0x1C BEFORE the call, reloads as $a2 INSIDE delay slot, reloads again after to return
- Frame -32, 2 extra spill/reload insns

With `void f(int a0)`:
- IDO sees v0 only needs to live until the call's $a2 arg is set up
- Move v0 → $a2 via `or $a2, $v0, $zero` in bgez delay slot (the "spill into a register" trick)
- No stack spill needed, frame -24, exact match

**How to apply:**

When the target asm:
- Has NO `or $v0, $tN, $zero` immediately before the final `jr $ra`
- AND v0 from an earlier call gets used as a register-arg ($a1/$a2/$a3) in a subsequent call

→ Write `void f(...)` not `int f(...)`. The caller likely doesn't read the return value anyway (or only reads it on the early-exit path where v0 happens to still hold the right value).

**Anti-pattern:**

Don't reflexively write `int` when the function appears to "compute and return a value". Look at the epilogue. If $v0 isn't restored from a saved location, the caller probably doesn't care.

**Generalizes:** Any IDO function where v0's final value is "incidental" (whatever was last in $v0 from a tail call). Common in error-handling wrappers and event-dispatch helpers.

**Converse — `void → int` does NOT shift first-pseudo allocation off $v0.** Tempting hypothesis when you have a "$v0 vs $v1 first-register cascade" cap: change the function to `int` and `return last_call()`, expecting IDO to reserve $v0 for the return and push the first general pseudo to $v1. Verified 2026-05-07 on `timproc_uso_b5_func_0000C8AC` (86.37% cap with 19-of-51 reg-rename diffs): switching to `int` + `return gl_func_00000000()` produced **NO change** in the .o emit. IDO's pseudo→hardware register allocator is locality-driven; the $v0-as-return use is at jr-ra delay-slot time (after all other pseudos are settled), so it doesn't pre-empt the first-pseudo allocation. Don't try this lever for the $v0/$v1 first-register cap — it's purely permuter / INSN_PATCH territory.

---

---

<a id="feedback-ido-volatile-buf-pointer-indirect"></a>
## `volatile T buf[N]` forces IDO to emit `addiu tA, sp, off; lw tB, 0(tA)` (pointer-indirect load) instead of `lw tB, off(sp)` (direct sp-relative)

_When the target asm uses `addiu tA, sp, off; lw tB, 0(tA)` (materialize stack address into a temp register, then load via the temp) instead of the standard direct `lw tB, off(sp)`, declaring the local buffer as `volatile T buf[N]` forces IDO to emit the pointer-indirect form. Without volatile, IDO folds the +off into the load's immediate._

**Pattern in target asm:**
```
addiu $t7, $sp, 0x18    # materialize &buf into t7
lw    $t9, 0x0($t7)     # load via t7
```
vs. our default C output:
```
lw    $t9, 0x18($sp)    # direct sp-relative load
```

**The fix:** declare the local buffer as `volatile`:
```c
void f(int *dst) {
    volatile int buf[2];                 // <-- volatile on the array
    gl_func_00000000(&D_00000000, buf, 4);
    *dst = buf[0];
}
```

**Why it works:** `volatile` tells IDO the array's storage location matters and the access can't be folded. Without volatile, IDO sees that `buf[0]` is at a known sp-relative offset and emits a direct `lw $t, off($sp)`. With volatile, IDO must materialize the pointer and load through it — exactly the target pattern.

**Equivalent forms tried:**
- `int buf[2]; volatile int *p = buf; *dst = *p;` — works at lower match % (extra storage for `p`).
- `int buf[2]; *dst = *(volatile int*)buf;` — also forces the pattern but with cast at use site.
- `volatile int buf[2]; *dst = buf[0];` — cleanest, same effect.

**Caveat: register choice usually still differs.** Forcing the *structure* match gets you to ~98 %; the remaining 2 % is often register choice (e.g., target uses `t7/t9/t6` — skipping `t8` — vs. our `t6/t7/t8` sequential). Likely related to long-long return reservation (per `feedback_ido_long_long_v1_move.md`) or other allocator state we can't reproduce from C. Wrap NON_MATCHING at 98 %.

**Origin (2026-04-20):** `game_uso_func_0000035C` int-reader variant. Standard `int buf[2]` produced direct sp-relative load (92 % match cap). `volatile int buf[2]` flipped to pointer-indirect form (98.1 % match — only register choice differs).

**How to apply:** When you see a NM wrap with comment "target uses pointer-indirect load" or you see the asm contain `addiu tA, sp, NN; lw tB, 0(tA)` for a stack-local buffer access, try `volatile T buf[N]`. Cheap to test, often unlocks a structural improvement.

**Refinement (2026-05-28, game_uso_func_000044F4): this does NOT extend to keeping `&local` in a SAVED register ($s) across a loop.** The trick above forces a single materialize-then-load (`addiu tA,sp,off; lw tB,0(tA)`) into a TEMP. It does NOT make IDO hold the materialized address in an `$s` register across many iterations. If the target has `addiu s2,sp,0x2c` ONCE in the prologue-region then `sw/lw 0(s2)` reused across N loop iterations (register-indirect via a callee-saved base), a plain `char *s2 = &local;` with N uses will NOT reproduce it: IDO folds every `*s2` back to direct `sw/lw off(sp)` because the address is a known sp+const, and direct addressing is strictly cheaper (zero extra insns) than holding a base in `$s`. Marking the slot `volatile` forces the memory roundtrip but STILL uses direct sp-relative (no `$s` base). To get a held `$s2` register-indirect base, the source must give the slot an address IDO can't prove is sp+const (a pointer param threaded in, an aliased struct field, an opaque-returned pointer) — not reproducible from a bare `&stacklocal`. Net effect: chasing it with `&local` is a regression. See the `game_uso_func_000044F4` NM-wrap comment for the full measurement (70.04 vs 70.53 baseline).

---

---

<a id="feedback-ido-volatile-loop-counter-for-stack-iter"></a>
## `volatile s32 sp4;` forces IDO to keep a loop counter on the stack with per-iteration `lw/addiu/sw` instead of register-promoting it

_When target asm shows a loop body that reloads the counter from `N(sp)` each iteration (`lw rA, N(sp); ... addiu rB, rA, 1; sw rB, N(sp)`), the C source's loop counter must be `volatile` to prevent IDO from promoting it to a register and eliminating the stack roundtrips._

**Rule:** When the target asm's loop body reloads the loop counter from a stack slot each iteration (`lw rA, N(sp)` near the loop head, `sw rB, N(sp)` near the loop tail), the C counter MUST be declared `volatile`. Without volatile, IDO -O2 promotes the counter to a register, eliminating the stack roundtrips and shrinking the loop by 2 instructions per iter.

**Why:** IDO -O2's register allocator naturally hoists scalar locals into registers. For a loop counter `for (i=0; i<3; i++)`, IDO emits `addiu rN, rN, 1` per iter — no memory access. The asm pattern `lw + addiu + sw` per iter is what `volatile int i;` produces: each read/write is observable so IDO can't optimize away.

**Pattern (verified 2026-05-05 on `func_00012188` in bootup_uso_tail3b_top, +10pp from 45 → 55):**

Target asm:
```
0x121C4: sw    zero, 0x4(sp)   ← initial i = 0
.L121C8:
0x121C8: addiu t1, zero, 0x2A
0x121CC: lw    t2, 0x4(sp)     ← reload i from stack
0x121D0: addu  t3, a0, t2
0x121D4: sb    t1, 0x158(t3)
0x121D8: lw    t4, 0x4(sp)     ← reload i again
0x121DC: addiu t5, t4, 1       ← increment
0x121E0: sw    t5, 0x4(sp)     ← store back
0x121E4: slti  at, t5, 3       ← compare
0x121E8: bnez  at, .L121C8
```

Two `lw + addiu + sw` cycles per iter (one for body, one for compare via increment+store).

**Wrong C** (register-only counter):
```c
s32 sp4, next;
sp4 = 0;
do {
    *(a0 + sp4 + 0x158) = 0x2A;
    next = sp4 + 1;
    sp4 = next;
} while (next < 3);
```
IDO emits `lw + addu + sb + addiu + slti + bnez + sw(delay)` — 7 insns, NO stack roundtrips, counter lives in `v0`. Loop body is 2 insns shorter per iter.

**Fix:**
```c
volatile s32 sp4;
s32 next;
sp4 = 0;
do {
    *(a0 + sp4 + 0x158) = 0x2A;
    next = sp4 + 1;
    sp4 = next;            // volatile sw
} while (next < 3);
```
`next` is non-volatile (lives in register, used for the compare); `sp4` is volatile (forces stack roundtrip). IDO emits the target's `lw/lw/sw` per-iter pattern.

**How to apply:**

When you see a loop with `lw rA, N(sp); ... sw rB, N(sp)` IN THE LOOP BODY (not just the prologue/epilogue), the source counter is volatile. Convert your `int i;` to `volatile int i;`. The loop's compare variable can stay non-volatile so IDO uses the increment-result register directly without an extra reload.

**Diagnostic signal:** if your build produces a loop body that's exactly `(2 * iter_count - 2)` instructions shorter than expected, and the missing instructions are `lw N(sp)` and `sw N(sp)` pairs in the loop body, this is the volatile-loop-counter pattern.

**Companion gotchas:**
- `volatile` on the COMPARE variable (`while (i < N)`) doesn't help — it forces an extra reload that target may not have.
- Frame size grows by 8 bytes for the volatile slot. If target has frame `0x8`, that matches a single volatile + ra-save (no other locals). Larger frames need additional locals.
- `feedback_ido_volatile_unused_local_forces_local_slot_spill.md` is the analogous pattern for arg-preservation; this memo is the loop-counter variant.

---

---

<a id="feedback-ido-volatile-preserve-redundant-io"></a>
## Use `volatile T *arg` to prevent IDO from fusing two `sb`/`sw` stores to the same address

_When the target asm has two distinct stores to the same address (e.g. `sb $t9, 0(a0); sb $t0, 0(a0)` where the second value is derived from the first), plain C emits ONE store because IDO fuses `*a0 = val; *a0 = val | 0x40;` into just the final write. Declaring the arg as `volatile T *a0` forces IDO to honor both stores._

**Rule:** If the target asm has:
```
lbu $tN, 0($a0)
andi $tM, $tN, <mask>
ori  $tP, $tM, <set>
sb   $tM, 0($a0)        ; first store
sb   $tP, 0($a0)        ; second store — same address, different value
```

…the original source had TWO writes to the same address. IDO -O2 will collapse two back-to-back writes to a non-volatile pointer into one final write. To preserve both:

```c
void f(volatile unsigned char *a0) {     /* NOTE: volatile on the PARAM */
    unsigned int val = *a0;
    val &= 0xFF7F;
    *a0 = val;            /* store 1 — preserved because a0 is volatile */
    *a0 = val | 0x40;     /* store 2 */
}
```

Without the `volatile`, IDO sees the first store as dead (overwritten before any read) and emits only the second.

**Gotcha:** if `a0` is passed to another function, cast it: `other_func((void*)a0)`. IDO cfe will complain about `volatile` qualifier loss otherwise, or add the qualifier to an incompatible signature.

**Related:** this is a variant of the general "volatile forces store" trick, but applied to a parameter rather than a local. Using volatile on a LOCAL forces it to spill to stack (undesirable for register-level matching). Using volatile on a POINTER target affects only stores/loads through that pointer, not the pointer itself.

**Caveat:** this gives the two stores but doesn't fix register allocation. If the target picks specific temp registers (e.g. `$t9`, `$t0`) that the general allocator doesn't, you may still land at 97–99 % and need NON_MATCHING. The memory `feedback_ido_v0_reuse_via_locals.md` covers the broader register-allocation levers.

**Origin:** 2026-04-19 game_libs gl_func_0002A4D0. Without volatile: 91 % (one `sb` instead of two). With volatile on the param: 97.67 % (both `sb` but registers $v0/$t6 vs target $t9/$t0). Wrapped as NON_MATCHING at 97.67 %.

---

---

<a id="feedback-ido-volatile-unused-local-forces-local-slot-spill"></a>
## `volatile int saved_arg = aN;` forces IDO to spill aN to a LOCAL stack slot instead of the caller's outgoing-arg slot

_When target has `sw $aN, 0x24(sp)` (local-slot offset) but your IDO build emits `sw $aN, 0xBC(sp)` (caller's outgoing-arg slot at sp+frame_size+slot), the difference is whether IDO treats the saved arg as "live local" or "dead-eliminated and only kept for caller-slot ABI requirement". Adding `volatile` to the local declaration prevents dead-elimination — IDO emits the local-slot store at the C-source-declared offset._

**Pattern (verified 2026-05-02 on `gl_func_0003F880`):**

Target asm:
```
addiu sp, sp, -184
sw    ra, 20(sp)
sw    a0, 184(sp)        ; caller's a0 slot (frame top)
addiu t6, zero, 0x2A
sw    a1, 36(sp)         ; ← LOCAL-slot store, sp+0x24
sw    t6, 24(sp)
jal   gl_func
addiu a0, sp, 24
```

**Wrong C** (caller-slot store):
```c
void gl_func_0003F880(int a0, int a1) {
    char buf[0x90];
    int saved_a1;
    int pad[2];
    int local;
    saved_a1 = a1;     // never read — IDO dead-eliminates the local-slot store
    local = 0x2A;
    gl_func_00000000(&local);
    (void)buf;
    (void)pad;
    (void)saved_a1;    // (void) doesn't count as "use" for IDO
}
```
IDO emits `sw $a1, 0xBC(sp)` (caller's a1 slot, frame_size+4) instead of `sw $a1, 0x24(sp)`. 99.92 % cap.

**Fix** (volatile forces local-slot store):
```c
void gl_func_0003F880(int a0, int a1) {
    char buf[0x90];
    volatile int saved_a1;     // ← volatile keyword
    int pad[2];
    int local;
    saved_a1 = a1;             // IDO MUST emit the store — volatile is observable
    local = 0x2A;
    gl_func_00000000(&local);
    (void)buf;
    (void)pad;
}
```
IDO emits `sw $a1, 0x24(sp)` — the actual local slot at the offset determined by the surrounding `buf[0x90] + saved_a1 + pad[2] + local` layout. Exact match.

**Why this works:**

`(void)saved_a1` is a no-op cast — IDO sees no observable effect, dead-eliminates the local-slot store, but still spills $a1 to the caller's outgoing-arg slot (the standard "arg-save before jal" ABI behavior — see `feedback_ido_unused_arg_save.md`). So you get a SPILL, but to the wrong slot.

`volatile` makes the assignment observable. IDO can't dead-eliminate it. It emits `sw $a1, OFFSET(sp)` where OFFSET is the local-slot offset determined by the variable layout. The previously-redundant caller-slot spill collapses into this one local-slot spill.

**How to apply:**

When NM diff shows ONE wrong store of an arg ($a0/$a1/$a2/$a3) at the caller's outgoing-arg slot, and target has the SAME arg stored at a local slot:

1. Look for `int saved_aN` (or similar) in the C body that's never read.
2. Add `volatile` to its declaration.
3. Make sure the assignment IS the only write (no later overwrites).
4. The `(void)` is no longer needed — `volatile` keeps the local alive on its own.

**Generalizes:** any "extra store target wants to a local slot, IDO won't emit because variable is dead". Same fix applies to non-arg locals if they're spillable temps that target preserves.

**Anti-pattern:** Don't `int *p = &saved_a1;` — taking the address grows the frame by 8 bytes (alters slot offsets for all downstream locals). Keep it as a plain `volatile int`.

**Pointer-typed volatile DOES NOT work — use int cast instead** (added 2026-05-06 from func_0000553C work):

When the arg you're trying to spill is a POINTER (`int *arg0`), the obvious form is broken:
```c
volatile int *arg0_save = arg0;  // NO-OP — IDO drops the read
```
IDO -O2 sees that `*arg0_save` is the same as `arg0` (both live in $a0), proves the spill is dead, and drops it. The `volatile` doesn't save it because the compiler can elide the volatile READ when the value is already in a register (the volatile rule technically only protects against re-ordering, not against this kind of CSE-from-arg-reg).

Use int-cast volatile instead:
```c
volatile int saved_a0 = (int)arg0;            // OK — forces local-slot sw
... func(..., (int*)saved_a0, ...);           // OK — keeps the use site
```
The int-cast severs the relationship between `saved_a0` and `arg0` from the compiler's perspective; it can't prove the spill is dead because the cast might be observable. Verified: forces `sw a0, 0x1c(sp)` per the int's stack offset (88.40% → 89.80% on func_0000553C).

**One more caveat from the same work:** Don't separate the cast into an intermediate `reloaded` local — that REGRESSES (89.80% → 84.20% in the test case). The `(int*)saved_a0` cast must stay inline at the use site for the reload to schedule correctly.

**`char pad[N]` to grow frame when local-slot collides with caller-arg-slot** (added 2026-05-06 from func_0000553C):

If your `volatile int saved_aN` ends up at the SAME stack offset as the implicit caller-arg-slot save (which happens when the natural frame size is small enough that the local lands at sp+frame_size = caller's $aN slot), IDO collapses both writes into ONE store. Target may have BOTH writes (one at sp+0x28 = caller-arg-slot, one at sp+0x1C = local). To get both, add `char pad[N]` (N=8 typical) to grow the frame so the local moves to a different offset.

Verified: func_0000553C frame -0x20 → -0x28 via `char pad[8]`, promoting 88.40% → 89.88%. The pad is consumed by frame-size accounting; no extra access insns emitted.

**Caveat: pad alone does NOT grow the frame** (verified 2026-05-06 on game_uso_func_00003A28): IDO -O2 dead-eliminates the unused `char pad[N]` and frame stays at its natural size. The pad-grows-frame trick requires a PAIRED live local — typically the `volatile int saved_aN` from the parent recipe. The volatile is what keeps the frame "anchored" at the larger size; the pad just shifts WHERE the volatile spill lands relative to other slots. If your function has no arg-spill candidate to volatile-ize (no caller-arg-slot save needed), the pad won't help — you need a different lever.

**Related:** `feedback_ido_unused_arg_save.md` (unused arg gets caller-slot spill), `feedback_ido_volatile_buf_pointer_indirect.md` (volatile buf forces pointer-indirect addressing).

---

---

<a id="feedback-ido-write-only-volatile-keeps-frame-without-deadload"></a>
## Write-only `volatile int dummy = aN;` (no read) keeps an 8-byte stack frame allocated WITHOUT emitting the dead-load artifact of `(void)dummy;`

_When the only lever you have to keep IDO -O2 from collapsing an 8-byte stack frame is a `volatile int dummy;`, the default `(void)dummy;` use-site emits a trailing `lw zero, OFFSET(sp)` dead-load that shows up as an extra mismatching insn. Replace `(void)dummy;` with a write-only `dummy = aN;` (assign any in-scope value) — volatile-write keeps the slot anchored (frame stays -8) but emits no read. Verified 2026-05-14 on `gl_func_0006AF0C` (game_libs_post.c): swapping `(void)dummy;` for `dummy = a0_unused;` dropped built insn count 16→14 (matches target's 14) and promoted 79.28% → 86.78% (+7.50pp)._

**Pattern:**

```c
void f(int a0_unused, ...) {
    volatile int dummy;
    /* ... body that needs an 8-byte frame ... */
    dummy = a0_unused;   /* OR any other in-scope int — keeps slot alive without reading */
}
```

The volatile-WRITE is observable, so IDO can't DCE the slot allocation. But there's no volatile-READ, so no trailing `lw zero, OFF(sp)` is emitted. Net codegen cost is ONE store at the assignment site (`sw aN, OFF(sp)` in a delay slot, typically) — versus the original 2-insn cost of read+write with `(void)dummy;` (volatile-write at top + volatile-read at bottom).

**Why `(void)dummy;` reads (and `dummy = x;` doesn't):**

Per C11 6.7.3, accessing a volatile object is observable. `(void)dummy` is a read access (compiler must emit a `lw`), so IDO emits a load that DOES NOTHING with the value (hence `lw zero, OFF(sp)` — discards into $zero). `dummy = x` is a write access; the compiler emits a store but no load. Both keep the local slot alive against DCE.

**When to use this vs the read form:**

- Use `(void)dummy;` (read-form) when target asm shows a trailing `lw zero, OFF(sp)` near the epilogue — the dead-load is what target HAS and you need to emit it.
- Use `dummy = x;` (write-only-form) when target shows NO such trailing load and you just need the frame-allocation effect.

**Anti-pattern:** Don't initialize the volatile at decl (`volatile int dummy = 0;`) — that's a write of a constant, which IDO might emit as `sw zero, OFF(sp)` (different opcode than the `sw aN, OFF(sp)` you may have wanted) or hoist around the function body in unpredictable ways. Declare unitialized, then assign in body at the point you want the spill.

**Related:** `feedback-ido-volatile-saved-arg-forces-local-slot-spill` (write-form's broader cousin: spill an arg to a specific local slot), `feedback-ido-volatile-loop-counter-for-stack-iter` (volatile to force stack-counter loop), `feedback-ido-file-context-affects-frame-size` (when even this lever can't close an 8-byte frame gap).

---

---

<a id="feedback-ido-reuse-arg-after-null-test-for-sreg-iterator"></a>
## Reuse an arg as a later loop iterator only AFTER a separate null-test temp to get `lw v0` + delay-slot `$s0 = v0`

_When target first preserves `a0` in `$s0`, later loads `node = s0->next` into `$v0`, tests it, and copies `$v0` into `$s0` in the branch delay slot, write the C with a separate null-test temp and only then reuse the arg variable as the iterator. Verified 2026-05-16 on `func_000086C0` (bootup_uso.c): 84.94% -> 99.70% from the iterator shape, then 100% after applying the existing inline-function-pointer `$t9` recipe._

**Target shape:**

```asm
or    s0, a0, zero
...
lw    v0, 0x34(s0)
beq   v0, zero, end
or    s0, v0, zero
```

**C shape:**

```c
node = *(char **)(arg0 + 0x34);
if (node != 0) {
    arg0 = node;
    do {
        ...
        arg0 = *(char **)(arg0 + 0x84);
    } while (arg0 != 0);
}
```

The failed extremes are instructive:

- `node` as the only iterator keeps the loop clean but leaves the original `arg0` in a caller-slot spill instead of `$s0`.
- `arg0 = *(arg0 + off); while (arg0 != 0)` puts the load directly into `$s0`, losing the target's `$v0` load plus branch-delay copy.

The split temp is the lever: it gives IDO one pseudo for the null test (`v0`) and then lets the reassigned arg pseudo take over `$s0` for the loop body.

**Pair with:** `feedback-ido-indirect-call-t9` when the loop calls a callback loaded from the node's object; naming the callback local can leave the match stuck at 99.70%.

---

<a id="feedback-ido-sreg-priority-first-assignment-not-decl-order"></a>
## $s0 priority follows FIRST-ASSIGNMENT order in the function body, NOT declaration order

_When two locals compete for $s0 (typical final-mile cap when fuzzy is 95-99%), IDO -O2's allocator picks the one assigned FIRST in the body — declaration order alone does NOT flip the allocation. The for-loop's init clause `for (i = 0; ...)` runs AFTER any earlier explicit body assignments, so it doesn't beat them for priority._

**Pattern (verified 2026-05-14 on `gl_func_0004ED0C`):**

C source where iter gets $s0:
```c
void f(T *self) {
    int *iter = self;     /* assigned at decl */
    int i;                /* declared but not yet assigned */
    int count = self->count;
    for (i = 0; i < count; i++) {  /* i assigned here */
        ... iter[k] ...
    }
}
```

Built: `or s0, a0, zero` (s0 = iter), `or s1, zero, zero` (s1 = i) — wrong.

C source where i gets $s0 (move i's assignment EARLIER in body):
```c
void f(T *self) {
    int *iter;
    int i;
    int count;
    i = 0;            /* ← first body assignment */
    iter = self;       /* second */
    count = self->count;
    for (; i < count; i++) {
        ... iter[k] ...
    }
}
```

Built: `or s0, zero, zero` (s0 = i), `or s1, a0, zero` (s1 = iter) — matches target.

**Doesn't help (verified):**
- Just swapping `int i;` and `int *iter;` declarations: NO change in $s0 allocation.
- Adding `register` keyword: NO change.

**Why it works:** IDO -O2's $s-reg allocator weights live ranges by their first-write point in the linearized body. The for-loop init is emitted AFTER any preceding explicit assignments, so a body-prefix assignment beats the for-init for "first to need $s reg".

**When to apply:**
- Fuzzy is 95-99% on a function with both a counter and a pointer competing for $s0.
- Diff shows `$s0` and `$s1` swapped between two locals.
- Target's prologue `or s0, ...` order tells you which local should be in $s0.

**Verified 2026-05-14 on `gl_func_0004ED0C`:** 96.07% → 97.68% (+1.6pp final-mile).

**Refinement — source-order of multiple `=0` inits controls EMIT ORDER of the `or sX, zero, zero` insns** (2026-05-27, gl_func_0000A130 byte-exact 25/25):

If two locals BOTH initialized to 0 compete (e.g. `int i = 0; int count = 0;`), the first-assignment-order lever above picks which one gets $s0. BUT the C source order of the two `=0` statements ALSO controls the emit order of the corresponding `or sX, zero, zero` insns. When target's prologue has `or s2, zero, zero; or s0, zero, zero` (s2 init BEFORE s0), the C must write `count = 0; i = 0;` (count first) — even though i goes to s0 (allocno-priority based on use-count), the init insn for s2 is emitted FIRST per source order.

Two-step lever recipe:
1. Pull the for-init `i = 0` OUT of the for-statement and place it before the for-loop. This wins $s0 for i (matching target).
2. Reorder the two assignments by source order so the `or sX, zero, zero` insns emit in the target's order.

C source for gl_func_0000A130 (cracked):
```c
int gl_func_0000A130(char *a0) {
    int i, count;
    char *p;
    count = 0;        /* emits `or s2, zero, zero` first */
    i = 0;            /* emits `or s0, zero, zero` second; i wins $s0 by allocno */
    p = a0 + 0x18;
    for (; i != 24; i += 8) {
        if (gl_func_00000000(p) != 0) count++;
        p += 8;
    }
    return count;
}
```
Bytes 25/25. Previous comment claimed "decl-order swap REGRESSES" — true for DECL order; the source-assignment-order swap is the working lever.

**Narrow generalization (2026-05-27 probes negative):** the two-step lever applies cleanly to FLAT-loop functions with EXACTLY 2 init-to-0 vars (e.g. counter + index). It does NOT apply to:
- Functions with 3+ init-to-0 vars where one needs to thread through a bnel-delay (gl_func_0000B310, 92.93% — IDO's `or v0, s2, 0` delay-slot insertion is a separate cap).
- Nested-loop functions with both inner/outer index vars (game_libs_func_0005DFE4, 95.26%, 12-register cascade).
- Dispatchers with bit-flag tests (game_libs_func_00034CC8, 89.75%).
- Multi-args-args dispatchers with > 3 a-reg moves (game_uso_func_00007ACC, 90.08%).

Recognize: if the diff is purely 2 swapped `or sX, zero, zero` insns at the prologue, this lever cracks. Anything broader is a different cap class.

**Placement matters when there's a LEADING function call:** if the function body starts with a `func();` call BEFORE any non-trivial body, the `i = 0;` first-assignment must come AFTER that call, NOT before. Pre-call placement caused a regression on gl_func_0002D064 (89.47% → 87.67%, -1.8pp); post-call placement gave +2.35pp (89.47% → 91.82%). Reasoning: the leading call kills caller-save registers, and IDO re-evaluates allocator weights post-call. Placing `i = 0;` PRE-call assigns it to a transient that's killed; POST-call assigns it to a callee-save slot.

```c
void f(T *self) {
    int i, *iter;
    func_X();        /* ← leading call */
    i = 0;            /* ← AFTER call: gets $s0 */
    iter = self;      /* ← second body-assignment */
    ... body ...
    for (; i < count; i++) { ... }
}
```

Verified 2026-05-14 on gl_func_0002D064 (final mile: 91.82% → 100% combined with store-statement-order matching).

---

---

<a id="feedback-ido-drop-redundant-early-return-before-for-loop"></a>
## Drop redundant `if (count <= 0) return;` before a for-loop — IDO emits BOTH branch checks (blezl-likely + blez), doubling the test code

_When the C body has both an explicit early-return and a for-loop whose initial test handles the same condition, IDO -O2 emits both checks: the early-return as `blezl` (branch-likely) with a delay-slot reload, AND the for-loop's initial test as a plain `blez`. The for-loop's natural `i < count` already returns when count is 0 or negative — so the explicit early-return is structurally redundant._

**Pattern (verified 2026-05-14 on `gl_func_0004ED0C`):**

Wrong (caps at 88-89%):
```c
void f(T *self) {
    int i;
    int count = self->count;
    if (count <= 0) return;          // ← redundant
    for (i = 0; i < count; i++) {
        ...
    }
}
```

Built emits:
```
lw   v0, count(a0)
... 
blezl v0, .L_end                ; early-return (branch-likely)
lw   ra, ...                     ; DS (annulled if not taken)
blez  v0, .L_end_again            ; for-loop start (plain blez!)
or    s1, zero, zero              ; DS: i = 0
... loop body ...
```

Two near-identical branch tests in a row is the diagnostic signal.

Right (matches single-blez target):
```c
void f(T *self) {
    int i;
    int count = self->count;
    for (i = 0; i < count; i++) {
        ...
    }
}
```

Built emits a single `blez` matching target's shape.

**How to spot in the wild:**
- Target's pre-loop has ONE `blez tN, .end` followed by the loop's first body insn.
- Your built has TWO branches — `blezl` (likely) + `blez` — for what should be one early-test.
- The C wrap has both an `if (count <= 0) return;` AND a `for (...; i < count; ...)`.

**Fix:** delete the explicit early-return. The for-loop handles count <= 0 naturally.

**Verified 2026-05-14 on `gl_func_0004ED0C`** (game_libs_post.c): combining this fix with the inline-method-ptr-for-$t9 recipe pushed 88.57% → 96.07% (+7.5pp).

**Doesn't apply when** the early-return path runs DIFFERENT cleanup or has a different return value than the for-loop's natural exit. Only the "for-loop already handles it" case is redundant.

---

---

<a id="feedback-ido-bne-ds-preserves-result-for-next-arg"></a>
## Diagnostic: regular bne's DS holding `or aM, vN, zero` is preserving the result as the NEXT call's argument — your wrap is missing an arg

_When you see this pattern in target asm, the C source you've written is ALMOST certainly under-arging the next call:_

```
jal    func
... DS (load some arg) ...
bne    v0, $zero, .L_next_call    ; result-zero check
or     a1, v0, $zero               ; DS — preserves v0 (= func result) into a1
.L_zero_arm:                       ; if v0 == 0
...
.L_next_call:                      ; if v0 != 0
lui    a0, ...                     ; setup next call's arg-a0
addiu  a0, a0, ...
jal    next_func                   ; ← takes a1 (= preserved result)!
```

The `or a1, v0, zero` in a REGULAR (non-likely) bne's DS executes regardless of the branch outcome — but the value is only USED on the taken path (where `.L_next_call` reads a1 as the function's second argument). On the not-taken path (v0 == 0), a1 is set but `.L_zero_arm` doesn't use it (dead store).

**Diagnostic rule:** any `or aM, $vN, $zero` in a bne's DS preserves $vN (= jal result) into $aM for a subsequent jal on the taken path. Re-read the C: the next call needs the result as an explicit arg.

**Recipe:**

```c
int r = func(arg);
if (r == 0) {
    /* zero-arm */
} else {
    next_func(other_arg, r, original_input);   /* ← r is the new middle arg */
}
```

**The error mode this fixes:** the natural-looking C is

```c
if (func(arg) == 0) {  /* result discarded — only sign-tested */
    /* zero-arm */
} else {
    next_func(other_arg, original_input);   /* ← MISSING arg */
}
```

Without naming the result, the C body reads as a simple test-and-discard. IDO has no signal that the result is needed downstream. The wrap fuzzy% sits in the 80s and won't budge.

**Verified 2026-05-14 on `gl_func_00021EA8`** (game_libs_post.c): 87.5% → 100% by adding `int r0 = func(...)` and passing it as the middle arg to the next call. Same recipe applied to both call-pair branches in the function (4 calls total, 2 pairs).

**Diagnostic also applies to vtable indirect-call dispatchers** with preceding `or aM, sN, zero` (preserving an $sN saved-arg into $aM for the call). Same family-pattern, different source: instead of `or aM, vN, zero` (preserving call-result), it's `or aM, sN, zero` (preserving callee-save reg). IMPORTANT: read the function's prologue `or sN, aM, zero` insns FIRST to know which input arg landed in which $sN — the wrong $sN→$aM mapping leads to passing the wrong variable. Verified 2026-05-14 on `gl_func_00038C04`: 99.81% → 100% by switching the 2nd arg of `((void(*)(int,int**))vt[0x3C/4])(off+self, X)` from `self` to `state` after re-reading that target's prologue had `or s0, a1, zero` (s0=state) and `or s1, a0, zero` (s1=self), so the `or a1, s0, zero` before the jalr was preserving STATE.

**Related:** `feedback-ido-arg-save-to-sreg-in-bne-delay` (IDO schedules `or sN, aN, zero` into bne DS — that's a SAVE to s-reg, not result-preserve to a-reg). The diagnostic differs by which register class is the destination of the `or`: a-reg = next-call-arg preserve; s-reg = callee-save copy.

---

---

<a id="feedback-ido-short-of-int-vs-direct-short-load"></a>
## Short-of-int extraction emits the WRONG halfword address — use `*(short*)((char*)p + OFF)` not `(short)p[OFF/4]`

_When target asm has `lh rT, OFFSET(rS)` reading a 16-bit halfword at a specific byte offset inside a struct, the natural-looking C `(short)struct[OFFSET/4]` does NOT match. IDO -O2 emits `lh rT, OFFSET+2(rS)` — the LOW half of the 32-bit word at OFFSET (MIPS is big-endian, so low half = bytes [+2, +3] of the word). The same trap applies to unsigned-short extraction from int pointers: `(unsigned short)*int_ptr` emits `lhu +2(p)`, not `lhu 0(p) + andi`._

**Pattern (verified 2026-05-14 on `gl_func_00038C04`):**

C source `(short)vtable[0x38/4]` (assuming `int *vtable`):
- Reads `*(int*)((char*)vtable + 0x38)` as an int word
- Casts to short — keeps only the LOW 16 bits
- IDO emits: `lh rT, 0x3A(rS)` — directly loads the low half from the word at 0x38
- Big-endian shifts the byte offset by +2 to address the low half

C source `*(short*)((char*)vtable + 0x38)`:
- Reads halfword at byte offset 0x38 directly
- IDO emits: `lh rT, 0x38(rS)` — direct halfword load at the stated offset

**Companion trap for unsigned-short:**

C source `(unsigned short)*int_ptr`:
- IDO emits: `lhu rT, 2(int_ptr)` (low-half byte offset)

C source `*int_ptr & 0xFFFF`:
- IDO emits: `lw rT, 0(int_ptr); andi rT, rT, 0xFFFF` (full word + mask)

**Diagnostic — read target's lh/lhu offset literally:**
- `lh rT, OFF(rS)` where OFF % 4 == 2 → cast-of-int form: `(short)p[OFF/4 - 0]` (if `lh` at `OFF+2`, the source field is the int at `OFF`)
- `lh rT, OFF(rS)` where OFF % 4 == 0 → direct halfword form: `*(short*)((char*)p + OFF)`

The OFF mod 4 == 2 case is misleading because it LOOKS like a halfword field at the low-half byte offset; the source actually treats it as an int and casts.

**Verified 2026-05-14 on `gl_func_00038C04`:** the wrap had `(short)vtable[0x38/4]` (emitting `lh +0x3A`) where target needed `*(short*)((char*)vtable + 0x38)` (emitting `lh +0x38`). Combined with the `(unsigned short)*p` → `*p & 0xFFFF` fix, pushed null fuzzy (scoring artifact from the wrong-offset lh) → 95.92%.

**Second confirmation 2026-05-14 on `gl_func_0004ED0C`:** identical trap with `(short)vtable[0x8/4]` (emitting `lh +0xA`) → `*(short*)((char*)vtable + 0x8)` (emitting `lh +0x8`). Single byte fix, fuzzy delta only +0.04pp because the dominant remaining diffs are register-cascade caps; but the C body is now semantically correct on the lh insn.

**The trap is contagious in vtable-dispatch loops** — wherever a function does `((fn_ptr_t)vt[N/4])((short)vt[M/4] + base)`, both the cast-of-int AND the offset-divided-by-4 indexing combine to silently produce the wrong-offset lh. Audit candidates by searching for `(short)\w+\[\w+/4\]` patterns; replace systematically with `*(short*)((char*)x + OFF)`.

**Related:** `feedback-ido-andi-mask-bytewidth-depends-on-c-form` (sibling concern: byte-encoded immediates depend on C form even when semantic value is identical).

---

---

<a id="feedback-ido-andi-mask-bytewidth-depends-on-c-form"></a>
## `x & ~K` emits `andi rT,rS,0xFFFF-K`; `x & EXPLICIT_MASK` emits `andi rT,rS,EXPLICIT_MASK` — choose the C form that matches target's literal

_For 8-bit-stored values, `*p = *p & ~2;` and `*p = *p & 0xFD;` produce functionally-identical results (clear bit 1 of the low 8 bits, since the store is 8-bit `sb`). But IDO encodes the `andi` instruction with a DIFFERENT 16-bit immediate depending on the C form, and the resulting byte differs even though semantic behavior matches._

**Pattern (verified 2026-05-14 on `gl_func_0002D064`):**

C source `*(char*)(a0 + 0) = *(char*)(a0 + 0) & ~2;` → IDO emits:
```
lbu  rT, 0(rS)
andi rU, rT, 0xFFFD       ; 0x31cffffd
sb   rU, 0(rS)
```

C source `*(char*)(a0 + 0) = *(char*)(a0 + 0) & 0xFD;` → IDO emits:
```
lbu  rT, 0(rS)
andi rU, rT, 0xFD         ; 0x31cf00fd
sb   rU, 0(rS)
```

Both expressions clear bit 1 of the low 8 bits, but the immediate stored in the `andi` instruction differs. The first form uses the C complement operator (`~2` = `0xFFFFFFFD` as signed int), which IDO truncates to the low 16 bits = `0xFFFD`. The second uses the explicit narrow mask, which IDO uses directly = `0xFD`.

**How to apply:**

- If target asm shows `andi rT,rS,0xFFFD` (or any `andi 0xFFF<x>` pattern with the complement form): use `& ~K` in C, where `K` is the bit being cleared.
- If target asm shows `andi rT,rS,0x00FD` (or any narrow mask form): use the explicit literal `& 0xFD`.
- Identify which form by looking at the upper 8 bits of the andi immediate. `0xFF<x>` → complement form. `0x00<x>` → explicit literal form.

**Why it matters:** even when both forms are semantically equivalent (e.g., for 8-bit stores), they emit different opcode bytes (0x31cf**FFFD** vs 0x31cf**00FD**). A byte-exact match requires choosing the form that matches target's encoding.

**Same class as:** `feedback-ido-magic-arg-via-symbol-not-literal` (lui+addiu vs lui+ori for `0xKKKKKKKK` constants), `feedback-ido-split-or-constant` (when to combine vs split a constant in C to match `lui+or+ori` vs `lui+addiu`). All three are "same effective value, different opcode encoding, source-form-dependent" patterns.

**Caveat — `~K` doesn't always emit `andi`** (verified 2026-05-15 on `gl_func_0002D2F4`): when `~K` evaluates to a value whose upper 16 bits aren't sign-consistent with the lower 16 (e.g., `~0x80` = `0xFFFFFF7F`), IDO emits a 3-insn sequence: `addiu temp, $zero, -129; and rT, rS, temp` (load-32-bit-then-AND) instead of a 1-insn `andi rT, rS, 0xFF7F`. Use the EXPLICIT 16-bit-fitting constant `0xFF7F` to force the andi-immediate form. The `~K` form only works cleanly when `K <= 0xFF` AND the bit-K position is in the LOW byte; for larger K or bit positions in the second byte, prefer the explicit narrow constant.

**When `~K` DOES emit andi-with-FFXX (2026-05-27, `gl_func_00024B94`):** for `*(char*)p &= ~0x0C` where K=0x0C is small and the operand is `char`, IDO emits `andi rT, rS, 0xFFF3` (single insn). The explicit-literal form `*(char*)p &= 0xF3` emits `andi rT, rS, 0x00F3` instead. BOTH are semantically identical for a byte store (sb truncates), but the BYTE ENCODING differs (`3109FFF3` vs `310900F3`). When target uses the `0xFFFx`-immediate form, you MUST write the C as `~MASK` not as `LOW_BYTE_MASK` to match. Recognize: the lower 16 bits of `~0x0C` = `0xFFF3` fit andi's immediate (zero-extended), so IDO uses the 1-insn andi path. The 3-insn `addiu+and` materialization only kicks in when the constant CANNOT fit in 16 bits as andi-immediate (i.e., the value > 0xFFFF in absolute terms). Pick the C form to match target's chosen encoding:
- target uses `andi 0x00F3`: write `*(char*)p &= 0xF3`
- target uses `andi 0xFFF3`: write `*(char*)p &= ~0x0C`

---

---

<a id="feedback-ido-volatile-int-array-low-pad-grows-frame-and-pushes-buf-up"></a>
## `volatile int low_pad[N];` declared BEFORE a `float buf[M]` grows the frame by 4N bytes AND pushes buf to a higher stack offset

_When the target has `float buf` at sp+0xK and built emits it at sp+0xK-8 (or sp+0xK-16), the local-array layout differs by a fixed gap. Inserting a `volatile int low_pad[N];` declared BEFORE buf, with `low_pad[i] = 0;` writes in the body, grows the frame by 4*N bytes and forces buf to be placed ABOVE low_pad in the stack. Verified 2026-05-14 on `gl_func_00039A9C`: `volatile int low_pad[2]; low_pad[0]=0; low_pad[1]=0;` before `float buf[3]` grew the frame from -0x30 to -0x38 and moved buf from sp+0x24 to sp+0x28 (matching target's sp+0x28). Sibling `sp_arg` also moved from sp+0x20 to sp+0x34, matching target._

**Tradeoff (why this is partial, not promote-to-100):** the N volatile writes appear as `sw zero, K(sp)` instructions at the top of the function, contributing to a fuzzy% regression even when the structural layout becomes correct. On 39A9C this was 99.61% (baseline) → 77.96% (with 4-element low_pad to fully match target -0x40 frame). Net: layout fix WORSE than original because the extra stores outweigh the offset-correction gains.

**When to use:**
- The buf-offset gap is exactly 4*N bytes and you have a downstream INSN_PATCH path planned to elide the N volatile-store insns.
- You're debugging WHICH lever controls IDO's local-array placement (this confirms it's the "volatile-scalar-before-array" ordering rule).
- Initial pass to confirm the structural cap class (file-context-affects-frame-size vs genuinely C-controllable).

**Why volatile-scalar pushes arrays up:** IDO -O2's stack-slot allocator places volatile scalars at LOW offsets in declaration order (they need slot pinning for the volatile-write semantic), then arrays go ABOVE them at higher offsets. Non-volatile scalars get DCE'd if unused (no `(void)` cast needed for elimination of `int pad1, pad2;`). The `volatile` keyword + observable write is the key to pinning a low-offset slot.

**Anti-pattern: don't use volatile arrays AFTER buf** — they get placed at the TOP of locals (highest offset), pushing buf DOWN, which is the OPPOSITE direction. Verified 2026-05-14 on 39B0C — `volatile int pad1, pad2;` declared AFTER buf went to sp+0x28..0x2F and buf stayed at sp+0x1C.

**Addressing-mode coupling (2026-05-27, gl_func_00037D48 negative):** swapping the declaration order of `int tmp[3]` and `float fbuf[3]` ALSO changes which addressing-mode IDO picks for the stores. Original order (tmp first) produces `addiu v1, sp, X; sw via v1` (pointer-based stores), needed for the int→float ping-pong shape. Reversing the decl (fbuf first) flips IDO to `sw via sp+off` (direct), breaking the shape entirely (regressed 23/24 → 12/24). Recognize: decl-order changes don't ONLY affect slot positions; they can also flip addressing-mode choices that other parts of the function depend on. If the function uses a pointer-based access pattern (`addiu rN, sp, X; sw/lw via rN`), don't reorder declarations across the pointer scope.

**Compare to:** `feedback-ido-file-context-affects-frame-size` (when the buf-offset gap isn't C-controllable AT ALL — different .c file context produces the gap). The low_pad recipe works on 39A9C because the frame-shape gap IS reachable from C; the file-context cap is for cases where it isn't.

---

---

<a id="feedback-ido-o0-value-return-extra-branch"></a>
## Value-returning -O0 functions emit an extra return-branch this toolchain can't fold — likely a systematic cap

**Observed 2026-05-29.** A value-returning function compiled at `-O0` with this toolchain (decompals `ido-static-recomp` 7.1) ends with TWO branches to the epilogue: the `return`'s explicit `b epilogue` PLUS the function-body's `b +1` end-of-block marker. Many original `1080` `-O0` targets have only ONE (`lw v0, <slot>; b +1; nop; epilogue` — the return value loaded, then a single dead `b +1`, falling through to the epilogue). So for value-returning `-O0` functions the build is reliably **+1 insn (an extra `b; nop`)** vs the target.

```
target:  lw v0, 0x28(sp);  b +1;  nop;  <epilogue>          # 1 branch
mine:    lw v0, 0x28(sp);  b ep;  nop;  b +1;  nop;  <ep>   # 2 branches (extra b;nop)
```

**Verified** the extra branch is independent of: combined-vs-separate local init, comma-expression `return (store, val)`, a union/scalar alias for the returned element, and `-g`/`-g1`/`-g2`/`-g3` (all `-O0` variants emit 2; `-O1` emits 0). Minimal repro: `int f(int*a,int n){int s=0,i; for(i=0;i<n;i++) s|=g(a[i]); return s;}` builds 2 branches; the analogous original target has 1. The **void** `-O0` functions match fine (no `lw v0` → just the single end-marker) — which is why every landed `-O0` match (accessors, `mgrproc_uso_func_000009A8`, `_00000504`) is void.

**How to apply:** if an `-O0` Yay0-USO target is **value-returning** and your build is exactly 1 insn long with an extra `b; nop` before the epilogue, it's this cap — leave it `INCLUDE_ASM`. Confirmed on `mgrproc_uso_func_00000A14` (got to 50 vs 48 insns via the union-alias trick for `buf[0]` direct-load, but the value-return branch is the irreducible residual). Suspected IDO patch-level codegen divergence vs the game's compiler; no C construct found to fold it. (If a value-returning `-O0` function is ever matched, revisit this.)

---

<a id="feedback-ido-float-call-result-preserved-in-f20"></a>
## Float function-return used in an expression is preserved in callee-saved $f20 — target uses $f0 directly (toolchain cap)

**Observed 2026-05-29.** When a function returning `float` is called and its result is used in a following FP expression, this toolchain (decompals `ido-static-recomp` 7.1) emits `mov.s $f20, $f0` (+ `sdc1/ldc1 $f20` save/restore) to preserve the return in a **callee-saved** FP register before the next operand, even when the next operand is just a load that can't clobber `$f0`. Many `1080` targets keep the value in `$f0` and use it directly:

```
target:  jal rng; lui at; lwc1 f4,0xN(at);  mul.s f6,f0,f4;  trunc.w.s; mfc1   # f0 direct, no f20
mine:    jal rng; mov.s f20,f0; lui; lwc1 f4; mul.s f6,f4,f20; trunc.w.s; mfc1  # f0->f20 (+ save/restore)
```

Minimal repro: `int mf(void){ return (int)(g() * *(float*)&D); }` (g returns float) emits the `mov.s $f20,$f0` + `sdc1/ldc1 $f20`. No statement-splitting, operand-order, or local-vs-call ordering avoids it. Suspected IDO patch-level FP-temp-allocation divergence vs the game's compiler. **Treat float-returning-call expressions as a likely cap** when the target has no `$f20` save and uses `$f0` directly. Confirmed blocking on `mgrproc_uso_func_000005D0` (random-ID float-RNG loop; also value-returning calls feed the `mul.s`). Companion to [value-returning -O0 extra-branch](#feedback-ido-o0-value-return-extra-branch) — both are systematic toolchain codegen divergences, not C-fixable.

---

<a id="feedback-ido-o0-dead-reassign-forces-s-reg-materialize"></a>
## -O0: a dead reassignment of a `register` var reproduces a stray `lui sN; addiu sN` symbol-materialize

**From `mgrproc_uso_func_00000504` (2026-05-29).** Some `-O0` targets contain a stray full address-materialize of a data symbol (`lui sN, %hi(D); addiu sN, %lo(D)`) into a callee-saved register whose result is never read — a "dead" address computation (e.g. left over from source that took `&D` but the later use re-materializes it). Because `-O0` does no dead-code elimination, you reproduce it by **reassigning an existing `register` variable to that address as a dead statement**: `register int v3; ... /* real uses of v3 */; v3 = (int)&D_00000000;` emits `lui s0; addiu s0, %lo` even though `v3` is dead afterward. Reusing the SAME `register` var (rather than a second one) keeps it in `s0` (a second `register` var would take `s1`). Pair with a direct int-symbol read (`extern int D; if (D == K)`) for the `$at`-fused `lui; lw %lo` sentinel load (vs `*(int*)&D` which materializes), and let `bake-data-relocs.py` bake the `%lo` into the Yay0 blob. Took `func_00000504` to byte-exact.

---

<a id="feedback-o0-cluster-split-with-layout-shim"></a>
## -O0-cluster split mid-file requires a paired -O2 layout shim, not just the -O0 file

_When a -O0 cluster sits MID-file (not at start or end), splitting it out needs THREE files: predecessor (truncated), the -O0 cluster file, AND a successor "layout shim" (-O2 INCLUDE_ASMs only) holding everything between the cluster and the next existing split boundary. Skipping the shim leaves a hole that breaks the linker layout and can't be papered over by TRUNCATE_TEXT alone._

**The 3-file recipe (verified 2026-05-02 on bootup_uso 0xF390..0xF6C4 cluster):**

Setting: a -O2 file (`bootup_uso.c`, originally truncated to 0xF76C) contains a contiguous run of -O0 wrappers at offsets 0xF390..0xF430 (3 functions), followed by 7 -O2 functions at 0xF434..0xF6C4 (all at 100% as INCLUDE_ASM), followed by an existing -O0 split at 0xF7F4. The 3 -O0 wrappers cap at 60-67% under -O2; need to be split into a -O0 sub-file.

**Wrong approach (single split):**
1. Truncate `bootup_uso.c.o` to `0xF390` (drop the entire 0xF390..0xF76C tail).
2. Add `bootup_uso_o0_F390.c.o` after it in the linker script.
3. Skip the 0xF434..0xF6C4 functions because "they were already at 100%."

This breaks the layout: the -O0 file ends at 0xF430 + alignment, then `bootup_uso_o0_F7F4.c.o` would start at the wrong offset because the 0x338 bytes of 0xF434..0xF76C functions are gone.

**Right approach (3-file split):**
1. Create `src/<seg>/<seg>_o0_<addr>.c` with the -O0 wrappers, build with `OPT_FLAGS := -O0`, `TRUNCATE_TEXT := <cluster_size>`.
2. Create `src/<seg>/<seg>_<next_addr>.c` (LAYOUT SHIM) with INCLUDE_ASMs for all functions between cluster end and the next existing split boundary. Build with default `-O2`, `TRUNCATE_TEXT := <shim_size>`.
3. Truncate the predecessor `<seg>.c.o` to the cluster start address.
4. Add BOTH new files to the linker script in order, between predecessor and the next existing -O0 split.
5. Add both to `objdiff.json`.

The shim file is mandatory even though all its functions are already at 100% — its `.o` provides the bytes between cluster and next split.

**Per-function levers needed inside the -O0 file (per feedback_ido_o0_register_and_inline.md):**
- `register T *p = &SYMBOL;` to force the $s0-saved-frame + `or aN, s0, zero` indirection that -O0 emits when the source has a register variable. Without this, -O0 doesn't bother saving s0 for a single use.
- 1-arg passthrough wrappers (`f(a0) { callee(a0); }`) match trivially at -O0 — the spill+reload + b+1 pattern just falls out.
- Cross-function data refs (`.L<addr>` from splat) need `extern char D_<ADDR>;` in the C plus `D_<ADDR> = 0x<ADDR>;` in `undefined_syms_auto.txt`. The C extern name is up to you; `undefined_syms_auto.txt` defines the address.

**Payoff:** 3 functions (F390, F3D4, F404) jumped from 60.65% / 66.67% / 66.67% NM-wraps to 100% exact matches in one tick. The infrastructure work (3-file split + Makefile + linker + objdiff config + undefined_syms) is ~30 lines of glue across 5 files but lands a permanent +3 to the project.

**When to apply:** any time you see a contiguous run of 2+ small -O0 wrappers (`b +1; nop` dead-branch + spill+reload) inside a -O2 file. Single-wrapper splits aren't worth the 3-file overhead; 3+ wrappers definitely are. The dividing line is "is the linker-layout adjustment per match worse than a permuter run?" — for -O0 wrappers, layout adjust wins because permuter can't introduce -O0 patterns.

**Anti-pattern:** moving ONLY the -O0 functions and TRUNCATE_TEXTing the predecessor without a shim — break the layout, downstream functions shift, half the segment regresses.

**Don't forget:** after `make expected RUN_CC_CHECK=0`, the two new `expected/src/<seg>/<newfile>.c.o` baselines show as untracked. They MUST be committed alongside the source split — without them, the land script refuses ("current worktree has tracked changes") and any fresh `make expected` run will produce them as untracked again. `git add expected/...c.o` for both new files in the same commit (or a follow-up).

**The -O0 bit set/clear template (verified 2026-05-02 on bootup_uso F434, F4CC, F564, F5BC, F614, F66C — six matches in one follow-up tick).** Extremely common -O0 wrapper shape:

```
27BDFFE8           addiu sp, -0x18 (or -0x10 for 1-block)
24850018           addiu a1, a0, 0x18    ; offset to bit-flag field
00A03025           or a2, a1, zero       ; p2 = p1
240700XX           addiu a3, zero, 0/1   ; set flag (compile-time constant)
10E00007           beqz a3, .Lclear      ; if !set goto clear
00000000           nop
00C04025           or t0, a2, zero       ; reload p2 into t0
8D0E0000           lw t6, 0(t0)
35CF000X           ori t7, t6, MASK      ; *p |= MASK
AD0F0000           sw t7, 0(t0)
10000006           b .Lend
00000000           nop
.Lclear:
00C04025           or t0, a2, zero       ; reload p2
8D180000           lw t8, 0(t0)
2401FFFX           addiu at, zero, ~MASK
0301C824           and t9, t8, at        ; *p &= ~MASK
AD190000           sw t9, 0(t0)
.Lend:
b/return
```

The matching C source needs FOUR register locals to force the a1/a2/a3 + per-branch-t0-reload pattern:

```c
void f(int *a0) {
    register int *p1, *p2;
    register int set;
    register int *t;             /* CRUCIAL — t = p2 inside each branch */
    p1 = (int*)((char*)a0 + 0x18);
    p2 = p1;
    set = 0;                     /* or 1 */
    if (set) { t = p2; *t = *t | MASK; }
    else     { t = p2; *t = *t & ~MASK; }
}
```

Why each lever matters:
- `register int *p1, *p2;` — gives a1/a2 (input arg slots) for the two pointer copies. Without `register`, IDO stack-spills them into sp+N.
- `register int set;` — gives a3 for the const flag.
- `register int *t; t = p2;` inside each branch — produces the `or t0, a2, zero` reload before each lw/sw. Without `t`, IDO uses `lw t6, 0(a2)` directly (no reload).
- `*t = *t | MASK; *t = *t & ~MASK;` — the explicit `*t = *t OP X` form (vs `*t |= X`) emits the `lw + ori + sw` triple cleanly. Compound-assign would still match in this case but the explicit form is more readable.

**Two-block variant** (e.g. F434/F4CC): just write the same recipe TWICE in sequence with two different MASK values — IDO doesn't share `p1/p2/set` across blocks at -O0, so re-init both:

```c
p1 = (int*)((char*)a0 + 0x18); p2 = p1; set = X;
if (set) { t = p2; *t = *t | 4; } else { t = p2; *t = *t & ~4; }

p1 = (int*)((char*)a0 + 0x18); p2 = p1; set = X;
if (set) { t = p2; *t = *t | 8; } else { t = p2; *t = *t & ~8; }
```

**Search heuristic for finding more of these:** in any -O0 cluster, look for `0xAFA40018; 0x...3025; 0x240700[01]; 0x10E0...` ([sw a0,sp+18] + [or a2,a1,0] + [li a3,0/1] + [beqz a3]) at the start of a 0x58 or 0x98 function. That's the fingerprint. Each match is ~2 minutes of work once the template is in hand.

---

---

<a id="feedback-o0-file-split-objdiff-json-step"></a>
## New -O0 .c file split needs FOUR config touches; objdiff.json is the easy-to-miss one

_When carving an -O0 function out of its parent .c into a dedicated `<seg>_o0_<offset>.c` file, you need (1) Makefile per-file `OPT_FLAGS := -O0` and `TRUNCATE_TEXT`, (2) tenshoe.ld entry, (3) source split itself, AND (4) objdiff.json unit entry. Skipping #4 leaves the function with no `fuzzy_match_percent` (null) — looks like the build is broken when it isn't._

**Trigger:** you split a function out of its segment's main `.c` file into a new `<seg>_o0_<NNN>.c` file because the function is compiled at -O0 (different from the segment's default -O2). The build links fine, but `objdiff-cli report generate` shows the function with no `fuzzy_match_percent` field — the unit isn't being scored.

**Recipe (1080 Snowboarding flavor, all four steps):**

1. **Source split:** create `src/<seg>/<seg>_o0_<offset>.c` containing the function. The TRUNCATE_TEXT value below = the symbol's size (in bytes, hex). Pattern from `arcproc_uso_o0_50.c` and `arcproc_uso_o0_12C.c`.
2. **Makefile** (after the existing per-file overrides, around line 30):
   ```makefile
   build/src/<seg>/<seg>_o0_<offset>.c.o: OPT_FLAGS := -O0
   build/src/<seg>/<seg>_o0_<offset>.c.o: TRUNCATE_TEXT := <symbol_hex_size>
   ```
3. **tenshoe.ld** (in the `<seg>` segment block, in the right order between the parent .c.o and any tail .c.o):
   ```ld
   build/src/<seg>/<seg>_o0_<offset>.c.o(.text);
   ```
4. **objdiff.json** (insert a unit entry next to the existing `<seg>` units, with `-O0` in `c_flags`):
   ```json
   {
     "name": "src/<seg>/<seg>_o0_<offset>",
     "target_path": "expected/src/<seg>/<seg>_o0_<offset>.c.o",
     "base_path": "build/src/<seg>/<seg>_o0_<offset>.c.o",
     "metadata": {
       "source_path": "src/<seg>/<seg>_o0_<offset>.c",
       "progress_categories": ["<seg>"]
     },
     "scratch": {
       "platform": "n64",
       "compiler": "ido7.1",
       "c_flags": "-O0 -G 0 -mips2 -32 -non_shared -Xcpluscomm -Wab,-r4300_mul"
     }
   }
   ```

**Why #4 matters:** without the objdiff.json entry, `objdiff-cli report` doesn't know the new .o is a separate unit. The function's symbol still appears in `report.json` (because objdiff finds symbols across all units), but it's listed under the OLD parent unit (e.g., `arcproc_uso_tail1`) — which references the OLD `expected/.../arcproc_uso_tail1.c.o` (with the function's INCLUDE_ASM bytes). The new `build/.../<seg>_o0_<offset>.c.o` has the function but no `target_path` to compare against, so `fuzzy_match_percent` stays null.

**How to detect:** `python3 -c "import json; r=json.load(open('report.json')); ..."` for the function shows `'fuzzy_match_percent'` missing entirely (not 0.0). That's the smoking gun for "objdiff isn't scoring this unit."

**Verification after fixing all four:** the function should appear under its NEW unit name with a real percentage:
```
src/arcproc_uso/arcproc_uso_o0_12C {'name': 'arcproc_uso_func_0000012C', 'size': '112', 'fuzzy_match_percent': 85.71429, ...}
```

**Bonus -O0 cap:** for `if(==) return 1; return 0;` shape, IDO -O0 emits an extra `b zero,zero,+1; nop` between the second `return` path and the epilogue (the implicit "end of function falls through to epilogue" goto). Caps at ~85.7% (24/28 for a 28-insn function). Same shape as `arcproc_uso_func_000000B4`. Tried swap-arms and explicit-else — both regress, neither flips. Don't grind further; commit as NM.

**Extended 2026-05-05 (failed variants for the `if return / return` shape, -O0):** the actual cap pattern is the JOIN-POINT branch — IDO -O0 emits THREE branches total (if-arm exit + else-arm exit + dead trailer) when the if-arm has an explicit early `return X`. Expected shape has only TWO branches (if-arm direct-to-epilogue + dead trailer). Tested 4 more variants on `arcproc_uso_func_0000012C` (current 92.86 % drift):
- (a) Explicit `else { return 0; }` — adds 4th branch (worse).
- (b) `register int rv; if (...) rv=1; else rv=0; return rv;` — `register` keyword DOES place rv in $s, but the if/else still emits a join-point + return-branch + trailer (same 3 branches).
- (c) Goto-zero-path (`if (cond) goto zero_path; return 1; zero_path: return 0;`) — adds extra `b zero_path` from else fall-through (worse).
- (d) `register int rv; rv=0; if (cond) rv=1; return rv;` — same 3 branches (the rv-init creates a 0-arm join-point).

**Conclusion:** IDO -O0's "early-return-in-if-arm" pattern always produces a join-point + dead trailer regardless of else-arm shape. The expected pattern (no join-point, if-arm branches direct-to-epilogue, else-arm has the dead trailer) requires dataflow normalization IDO -O0 doesn't perform. INSN_PATCH-blocked because the cap is +8 bytes (2 extra insns) — post-cc tools can shrink (PROLOGUE_STEALS) or overwrite (INSN_PATCH) but can't grow. Settle for ~92.86 % NM cap on this shape family.

**Related:**
- `feedback_uso_accessor_o0_variant.md` — accessor templates that need -O0 file split.
- `feedback_objdiff_null_percent_means_not_tracked.md` — the broader rule for null %.
- `feedback_non_aligned_o_split.md` — TRUNCATE_TEXT mechanics for non-16-aligned splits.

---

---

<a id="feedback-ido-o0-loop-stack-reload-signal"></a>
## Loop reloads ALL locals from sp every iteration = -O0 codegen signal

_When a function's loop body starts with `lw tA, X(sp); lw tB, Y(sp); lw tC, Z(sp)` for variables that have no `volatile` or address-taken reason, it's almost certainly -O0 compiled. -O2 keeps loop-carried values in registers (only ra + callee-saves spill)._

**Detection signal:** before writing C, scan the target's loop body. If the FIRST 3 instructions inside the loop are `lw` from sp-relative offsets that MATCH the function's own prologue stack-stores, the function is -O0. Don't grind -O2 C variants — they cap at single-digit %.

**Example (gl_func_00071864, 16-bit byte-sum checksum, 23 insns):**

```asm
27BDFFF0  addiu $sp, $sp, -0x10
AFA00008  sw $zero, 0x8($sp)     ; sp[0x8] = 0 (accum spill)
AFA40004  sw $a0, 0x4($sp)       ; sp[0x4] = p (arg spill)
18A00010  blez $a1, exit
AFA0000C  sw $zero, 0xC($sp)     ; (delay) sp[0xC] = 0 (i spill)
                                  ; --- loop top ---
8FAF0004  lw $t7, 0x4($sp)       ; reload p
8FAE0008  lw $t6, 0x8($sp)       ; reload accum
8FAB000C  lw $t3, 0xC($sp)       ; reload i
...
```

Straightforward C body:

```c
unsigned short f(unsigned char *p, int n) {
    int i;
    int accum = 0;
    for (i = 0; i < n; i++) accum = (accum + p[i]) & 0xFFFF;
    return (unsigned short)accum;
}
```

At -O2 produces 5.4% match (target's stack-heavy loop vs C-emit's register loop). No amount of permutation rescues this — the cap is the optimization level itself.

**Resolution paths:**

1. **File-split to OPT_FLAGS=-O0** — carve the function (or its cluster) into a dedicated `.c` file with per-file `OPT_FLAGS := -O0` in the Makefile + corresponding tenshoe.ld + objdiff.json entries (per `feedback_o0_file_split_objdiff_json_step.md`). Worthwhile only if the function or its callees are also -O0.
2. **Accept INCLUDE_ASM** — for one-off -O0 stragglers in an -O2 file, the file-split overhead exceeds the value. Document the detection signal inline and move on.

**Why this happens:** small ROM-init / checksum / boot-path functions are often compiled at -O0 for debugging predictability — register pressure is low, debugger-friendly, and the perf impact is one-time-init. The N64 boot path and game_libs init code have ~50 such functions in 1080 Snowboarding alone.

**Distinguish from -O2 stack-heavy patterns:** -O2 DOES spill to stack when (a) `volatile` qualifier present, (b) variable's address taken (`&x` somewhere), or (c) register pressure forces spill. Those don't trigger this signal because the spills are TARGETED (one variable, not all locals). The -O0 signature is uniform: every local lives on stack, every read is sp-relative.

---

---

<a id="feedback-o0-int-reader-template-variant"></a>
## -O0 variant of the int-reader accessor template — 19 insns / 0x4C bytes vs the standard -O2 template's 16 insns / 0x40 bytes

_When scanning USO accessor templates, also check 0x4C-byte / 19-instruction variants — these are -O0 compiles of the SAME body. Byte signature: identical entry (`addiu sp,-0x20; sw a0,0x20; sw ra,0x14; lui+addiu a0,&D; addiu a1,sp,0x18; addiu a2,$0,4`), then UNFILLED `jal func_00000000; nop` delay slot, then chained-deref `addiu tN,sp,0x18; lw tM,0(tN); lw tK,0x20(sp); sw tM,0(tK)`, then dead BB-marker `b +1; nop`, then standard epilogue. C body identical to standard template; only differs by per-file OPT_FLAGS. Promotes byte-for-byte at -O0 standalone._

**The two int-reader template variants** (both have identical C body):

```c
void f(int *dst) {
    int buf[2];
    gl_func_00000000(&D_00000000, buf, 4);
    *dst = buf[0];
}
```

Compile at **-O2** (standard template, 16 insns, 0x40):
```
27BDFFE0 addiu sp,-0x20
AFA40020 sw a0,0x20(sp)
AFBF0014 sw ra,0x14(sp)
3C040000 lui a0,...
24840000 addiu a0,a0,...        # &D_00000000
27A50018 addiu a1,sp,0x18
0C000000 jal func_00000000
24060004  addiu a2,$0,4         # delay slot — FILLED
8FAE0018 lw t6,0x18(sp)         # buf[0]
8FAF0020 lw t7,0x20(sp)         # dst
ADEE0000 sw t6,0(t7)            # *dst = buf[0]
8FBF0014 lw ra,0x14(sp)
27BD0020 addiu sp,+0x20
03E00008 jr ra
00000000 nop
```

Compile at **-O0** (19 insns, 0x4C):
```
27BDFFE0 addiu sp,-0x20
AFBF0014 sw ra,0x14(sp)         # NOTE: ra saved BEFORE a0 (-O0 order)
AFA40020 sw a0,0x20(sp)
3C040000 lui a0,...
24840000 addiu a0,a0,...
27A50018 addiu a1,sp,0x18
24060004 addiu a2,$0,4          # SEPARATE insn, before jal (not in delay slot)
0C000000 jal func_00000000
00000000  nop                    # delay slot — UNFILLED
27AE0018 addiu t6,sp,0x18       # &buf — chained deref via tmp reg
8DCF0000 lw t7,0(t6)             # buf[0]
8FB80020 lw t8,0x20(sp)          # dst
AF0F0000 sw t7,0(t8)             # *dst = buf[0]
10000001 b +1                    # dead BB-marker
00000000  nop
8FBF0014 lw ra,0x14(sp)
27BD0020 addiu sp,+0x20
03E00008 jr ra
00000000 nop
```

**Distinguishing markers for the -O0 variant** (vs -O2):
- Size 0x4C (19 insns) vs 0x40 (16 insns) — biggest tell
- Unfilled `jal; nop` delay slot
- Three chained registers (t6→t7→t8) for buf-deref instead of direct `lw t6, OFF(sp)`
- Dead `b +1; nop` BB-marker before epilogue
- ra-save comes BEFORE a0-save in prologue (vs -O2 which spills a0 first)

**Verified cases (2026-05-04)**:
- `gl_func_00008944` (int reader -O0): 0x4C target, standalone -O0 compile byte-identical.
- `gl_func_000089F4` (float reader -O0): 0x4C target, standalone -O0 compile byte-identical (lwc1 $f4 / swc1 $f4 in place of lw/sw at the deref step). Confirms the speculation that float / Vec3 / Quad4 readers also have -O0 0x4C variants.
- File split required to actually land — game_libs had no -O0 sub-files at the time.

**How to apply**:
- When the source=4 scan ("untouched USO accessor templates") yields NOTHING at the standard 0x40-byte signature, try grepping for 0x4C-byte int readers — these are -O0 variants in otherwise-O2 files, often skipped because they "don't look like the template".
- The C body is identical. Only the wrap doc + Makefile OPT_FLAGS override differ.
- Float variant verified 2026-05-04 (gl_func_000089F4). Vec3 / Quad4 -O0 variants still untested — but expect same shape with the chained deref using lwc1+swc1 (Vec3) or 4-field copy (Quad4) at the deref step.

**Related**:
- `feedback_uso_accessor_template_reuse.md` — original 4 -O2 templates
- `feedback_uso_byte_identical_clones_beyond_accessors.md` — byte-clones beyond simple accessors
- `feedback_o0_cluster_split_with_layout_shim.md` — how to do the file split

---

---

## IDO -O2 -g3 doesn't disable MID-BODY branch-likely — only fills `jr ra` delay slots

_The `-O2 -g3` recipe (above) unfills the terminal `jr ra` delay slot, but it does NOT disable IDO's mid-body branch-likely emission. For functions whose target asm has UNFILLED nop-delays on conditional branches (`bne t6, zero, L; nop` instead of `beql t6, zero, L; <body-insn>`), `-O2 -g3` is NOT a fix._

**Test matrix for `if(cond)return0; ...body... return val;` shape (run on func_00011D78, 15-insn target with frameless `bne+nop` shape):**

| Flag combo | Insns | Frame | Branch shape | Notes |
|------------|------:|-------|--------------|-------|
| -O0        | 23 | yes | `beq+nop` to shared epilogue | Way too verbose, classic -O0 spills |
| -O1        | 17 | yes | `beq+nop` + sw/lw spills | Frame from spill-restore |
| -O2        | 12 | no  | `beql+lw(slot)` | Standard fast emit, FILLED slot |
| -O2 -g     | 18 | yes | `bne+nop` + multi-beq epilogue | uopt warning ("use -g3"), dead epilogue chain |
| **-O2 -g3** | **12** | **no** | **`bnel+mtc1(slot)`** | **Same as -O2 (scheduler still fills)** |

None match the target's 15-insn frameless `bne+nop` shape with a dead `jr ra; nop` pair acting as alignment/fall-through fill.

**Conclusion:** Target was probably compiled with a non-standard IDO flag combo (perhaps `-Wab,-noreorder` or hand-edited asm pre-link), OR the source has a structural quirk (a third unreachable code path) the standard flag matrix can't reproduce.

**Diagnostic signal:** target asm has `bne/beq <reg>, zero, L; nop` (unfilled mid-body) AND a dead `jr ra; nop` pair between body's natural return and a branch-target label. Build at any standard -O level emits `beql/bnel` with a filled delay slot. The structural delta is +3 insns, blocking INSN_PATCH (insertions not supported).

**Workaround if needed:** accept partial NM wrap, or split the function to its own `.c` file with custom POST_COMPILE script (see `kernel_056` precedent in 1080's Makefile, where a Python e_flags rewrite is bolted on after cc).

Documented 2026-05-05 while grinding func_00011D78 (capped at 40% fuzzy from this exact issue). Same shape blocker for cluster siblings func_00011C70/CA4/DBC.

---

<a id="feedback-ido-branch-likely-consolidates-explicit-ifelse"></a>
## IDO -O2 collapses explicit `if (early-return) else (compute)` 12-insn shape into 11-insn shared-tail via `beql`

_When target has an explicit if/else with two distinct `jr ra` blocks (one for `return 0` early-out, one for the compute-and-return path) at 12 instructions total, IDO -O2 consolidates them into 11 instructions via a `beql + lw $v0, ... [delay-likely]` shared-tail: branch-likely cancels the lw on the early-return arm. The C body is structurally correct but emits 1 fewer insn than target._

**Diagnostic signal:**
- Target: 12 insns / 0x30, two `jr ra` blocks, an `or v0, zero, zero` between them.
- Built (any natural C `if (cond) return 0; return *p;`): 11 insns / 0x2C, single `beql` with `lw $v0, ...` in the delay-likely slot, only one `jr ra`.
- The 50200004 opcode (`beql $at, $zero, +1`) with an `lw` in the next slot is the smoking gun — IDO scheduler's branch-likely path-merge.

**Why it caps:**
- INSN_PATCH can rewrite bytes but not change function size — and the 1-insn delta blocks it.
- SUFFIX_BYTES=0x4 (add trailing nop) brings size to 0x30 but the byte ORDER is still wrong; you'd need to INSN_PATCH most of the function to reorder, which defeats the purpose.
- 8 source variants × 4 -O levels (verified on `func_00011D40`, 2026-05-04 + 2026-05-05): no natural C suppresses this consolidation.

**Possible escapes (untested):**
- File-split to `-O1` to disable scheduler — but `-O1` produces a filled `jr ra` delay that target doesn't have.
- Force an artificial side-effect between the two return paths (volatile read?) so IDO can't merge them.
- POST_COMPILE script to rewrite the consolidated bytes back into target's shape (kernel_056 precedent).

**Companion / sibling caps:**
- `feedback-ido-branch-likely-arm-choice` (which path becomes the branch-likely)
- `feedback-ido-empty-body-do-while-emits-branch-likely` (related scheduler optimization)
- `feedback-ido-bnel-tail-merge-register-restore` (similar tail-merge pattern but on register restore)

Verified 2026-05-05 on `func_00011D40` in bootup_uso_tail3a (capped at structural-cap class). Class signature: short function with `if (early-return-0) return *ptr;` shape and target has 12-insn explicit if/else.

---

## IDO -O2 constant-folder ignores `(char*)` cast — `*(T*)((char*)(P+N) + M)` folds to `*(T*)(P+N+M)`

_When trying to force IDO to emit `addiu vN, P, N; lwc1 fX, M(vN)` (split addressing) instead of single `lwc1 fX, N+M(P)`, the natural-looking C dodge `*(float*)((char*)(P + N) + M)` fails — IDO -O2's constant-fold pass discards type info from intermediate `(char*)` casts and treats the whole expression as `*(float*)(P + N + M)`. Same .o bytes as the simpler form._

**Rule:** if `N + M` fits in a 16-bit signed offset (typical for struct field accesses up to ~0x7FFF), IDO will fold ANY combination of:

```c
*(T*)((char*)(P + N) + M)        // explicit cast + N + M
*(T*)((char*)P + N + M)          // single cast, all-additive
*(T*)(P + N + M)                 // no cast, P is char*
T *t = (T*)(P + N); val = t[M/sizeof(T)];   // typed temp
char *t = P + N; val = *(T*)(t + M);         // untyped temp, single use
```

→ all produce identical `lwc1 fX, (N+M)(reg(P))`.

**What forces non-folding (untested but candidate paths):**

- `volatile char *t = P + N;` then `*(T*)(t + M)` — volatile guarantees materialization.
- `register char *t = P + N;` (untested) — register class may force the addiu.
- A `struct {char pad[N]; T val;} *s = (struct ...*)P; access via s->val` — gives IDO type-shape evidence the pad+field structure is intentional. Untested.
- Multiple uses of the same intermediate — if `t = P + N` is dereferenced 2+ times, IDO may keep it materialized rather than folding.

**Detection signal:** target asm has `addiu vX, base, N` then `lwc1/lw fY/tZ, M(vX)` (split), but your C produces `lwc1/lw fY/tZ, N+M(base)` (folded). The mathematical addresses are identical; only the addressing mode differs. Found while grinding `game_uso_func_00007448` (capped at 70.97% from this exact gap, 2026-05-05).

---

## IDO preserves explicit 2-test if/else-if; combined `(v != K)` collapses both arms

_When target asm shows two separate `bne/beq` tests for what looks like one logical condition (e.g. `if (v == 0) X; else if (v == 2) skip; else X;`), do NOT simplify the C to `if (v != 2) X;`. Even though both forms are semantically equivalent ("execute X unless v == 2"), IDO emits them differently: the explicit 2-test form keeps both branches with separate jal sites; the simplified form collapses to one branch + one jal. To match the target's bytes, write the C as the original 2-test._

**Pattern in target asm:**

```
bne $v0, $zero, .skip_first    # if v != 0, skip first call
nop
jal call(...)                  # v == 0: call
b .merge
addiu $at, $zero, 2
.skip_first:
beq $v0, $at, .merge           # if v == 2, skip second call
nop
jal call(...)                  # v != 2 (and v != 0): call
.merge:
```

Two separate `jal` sites with identical args, gated by `v == 0` (do) and `v == 2` (skip).

**C source — what NOT to write (single-test, semantically equivalent but different bytes):**

```c
if (v != 2) {
    call(...);
}
```

This compiles to ONE branch (`bne $v0, $at, .skip; nop; jal call; .skip:`) and ONE jal — collapsing the asm's 2-arm dispatch into a single test.

**C source — match the asm's structure:**

```c
if (v == 0) {
    call(...);
} else if (v != 2) {
    call(...);
}
```

This preserves the 2-jal dispatch.

**Why:** IDO -O2's optimizer is conservative about merging arithmetically-equivalent conditional branches when the bodies have side effects (function calls). It honors the source-level `if (v == 0) ... else if (...)` structure literally, even when the simplification `(v != 2) → (v == 0 || v != 2)` would produce shorter code. Likely a side effect of the `if-conversion` pass running before constant-folding on conditional values.

**Verified 2026-05-05** on `mgrproc_uso_func_00001324`: switching from `if (v != 2) call();` to `if (v == 0) call(); else if (v != 2) call();` dropped diffs from 28/41 to 8/41 (80.5% byte match, remaining diffs are pure register-pick).

**Detection signal:** target asm has 2 `jal SAME_FUNC` calls with identical args, gated by 2 separate compare-branch sequences with the SAME variable. C body that uses a single combined predicate produces only 1 jal.

---

<a id="feedback-ido-o2-loop-array-strength-reduction"></a>
## IDO -O2 strength-reduces `array[idx]` in nested inner loops into cached-pointer-post-increment — not flippable from standard C

_When the inner loop reads `array[idx]` and increments idx every iter, IDO -O2 strength-reduces this into a cached pointer (`s_reg = array + idx_initial`) that's post-incremented per iter, replacing per-iter `addu base, idx; lbu val, 0(base)` with `lbu val, 0(s_reg); addiu s_reg, s_reg, 1`. If the target asm has the NON-strength-reduced form (re-adds base+idx each iter), no standard C variant defeats this — `v = idx; *(array+v); idx = v+1`, `register int idx`, and explicit pointer-cast variants all either no-op or REGRESS the diff. Verified 2026-05-06 on `gl_func_00055B44` (60-insn nested loop, 86.58% capped). Regress example: `v = byte_idx; ...; byte_idx = v+1` drove diffs from 60 → 75 lines._

**Detection signal**: target's inner loop has `move v0,sN; addu tM,sK,v0; lbu/lw val,0(tM); addiu sN,sN,1` (4 insns per byte read) where built has `lbu/lw val,0(sM); addiu sM,sM,1` (2 insns, sM is the cached pointer). The 2-insn deficit per inner iter is the SR signature.

**Why this isn't C-controllable**: IDO's strength reduction runs after register allocation in the optimizer pipeline. It detects loop induction variables purely from the data-flow graph — source-level expression structure (`a[i]` vs `*(a+i)` vs cached `v = i; *(a+v)`) all reduce to the same DFG and trigger SR identically. The DFG would need an extra dependency to PREVENT SR, but adding one (e.g., `volatile`) typically introduces other costly diffs (stack roundtrips, frame-size shifts) that regress the score elsewhere.

**Promotion paths for SR-blocked functions**:
- decomp-permuter (random shape variants might find a non-SR-able pattern by accident)
- per-symbol INSN_PATCH for the SR-shifted insns (~4 insns per inner-loop iter × outer iters, but in the .o the bytes are just the static body — so 2-3 patches not Nx)
- Defer until SR-suppression knob is added to the matching workflow (none exists today)


---

<a id="feedback-ido-want-two-iv-use-single-counter-index"></a>
## When the TARGET has two induction vars (counter + strength-reduced pointer), write ONE counter IV and index — don't declare an explicit pointer

The productive inverse of the SR-blocked case above. Many small game_libs loops compile to **two** induction variables: a counter `i` in `$s0` (steps by the element stride, compared to a `li $sN, BOUND`) and a data pointer in `$s1` post-incremented every iter. The natural decompile — declaring an explicit `float *p = src; ... *p; p++` alongside `for (i = 0; ...)` — gets this **wrong twice**: (1) `p = src` is the first-referenced pseudo so `p` grabs `$s0` (the swap), and (2) even after fixing the swap by assigning `i = 0` before `p = src`, a residual preheader schedule diff appears (the `move $s0,zero` for `i=0` fills the `lui→addiu` latency gap of the loop-invariant address, whereas the target keeps `lui+addiu` adjacent).

**Fix both at once: delete the explicit pointer and index the source array by the counter** — `(double)*(float*)((char*)src + i)` (or `src[i/stride]`). Now `i` is the *sole source-level* induction variable, referenced in BOTH the loop test and the address computation, so it out-prioritizes everything for `$s0`; GCC's strength reduction then *manufactures* the auxiliary data pointer into `$s1` exactly as the target does, and the preheader schedule falls into place because the derived IV's setup is ordered by the optimizer, not by your source statement order. Verified 2026-05-24 on `gl_func_0005C784` (98.8% → byte-exact): explicit-`p` form stuck at 2 preheader diffs through three orderings; single-counter-index form hit 0 diffs immediately. Pairs with the `$s0↔$s1` first-assigned-pseudo lever (`gl_func_0004C288`) — try the index form FIRST for any counter+pointer loop, since it subsumes the swap fix.

---

<a id="feedback-ido-two-explicit-ivs-counter-first"></a>
## When the target has a trip counter + a SEPARATE advancing pointer (both real $s-regs), write TWO explicit IVs, init the counter first, use comma-`for`

The **complement** of the single-counter-index recipe above, and the crack for a class previously mis-filed as an "induction-var cap." Some loops keep BOTH a trip counter AND a separate advancing pointer in distinct $s-regs — the pointer is advanced by `addiu ptr,STRIDE` in the branch-delay slot and is NOT re-derived from the counter each iteration:

```
# target outer loop tail
addiu   s4,s4,1          # trip counter += 1
bne     s4,s7,<top>      # compare to LIMIT (li s7,4)
addiu   s5,s5,16         # row pointer += stride (delay slot)
```

For THIS shape, both `a1[row*4+col]` indexing and `p = a1 + row*4` lose — IDO strength-reduces them to a single by-stride counter (`li s7,64; addiu s4,16`), which is the documented near-miss. The fix is to write **two explicit IVs** and apply two levers:

1. **Init the counter before the pointer.** `for (i = 0, q = base; ...)` — the counter's pseudo is born first, so it wins the LOWER $s-reg (counter→s4/s0, pointer→s5/s1). The recorded "a separate advancing `p` (p+=4) only swaps the s4/s5 roles" failure was caused by initing the pointer first (`q = base; for (i = 0; ...)`), which gives the pointer the lower reg.
2. **Use the comma-init `for` form** `for (i = 0, q = base; i != N; i++, q++)`. This reorders the prologue so the loop-invariant address `addiu`s schedule *before* the var-init moves — cracking the final scheduler-tie diffs (the same prologue-schedule residual that the single-counter-index recipe dodges by construction).

Nests cleanly: inner `for (col = 0, p = rowp; col != 16; col += 4, p++)` (byte counter + float pointer), outer `for (row = 0, rowp = a1; row != 4; row++, rowp += 4)` (trip counter + row-base pointer that strides 4 floats = 16 bytes). Verified byte-exact 2026-05-29 on **gl_func_0005C6C4** (4x4 float-matrix printer, 48 insns), which had been documented as a 99.96% induction-var cap with two failed attempts on record.

**Decision rule** when a near-miss bottoms out on a counter/stride diff: look at the TARGET's loop tail. If it shows a trip counter (`addiu cnt,1; bne cnt,SMALL_LIMIT`) **plus** a separate `addiu ptr,STRIDE`, it is NOT a cap — apply this two-explicit-IV recipe. Only if the target shows a single fully-unrolled body with a by-N element counter and no separate pointer is it the genuine auto-unroll cap ([feedback-ido-unroll-element-vs-trip-counter](#feedback-ido-unroll-element-vs-trip-counter), e.g. gl_func_0005BDC0).

---

<a id="feedback-ido-o0-byte-masked-stack-vars-are-unsigned-char"></a>
## -O0 body-tuning: a stack var masked to 0xFF each iteration is `unsigned char` (sb/lbu), not int

When reverse-engineering an **-O0** function body for an -O0 file split, match the stack-slot WIDTH first. At -O0 every local is a stack slot reloaded on each use, so the load/store width is visible: `sb`/`lbu` to a byte slot = `unsigned char`; `sh`/`lhu` = `unsigned short`; `sw`/`lw` = `int`. A loop accumulator that the algorithm masks to `& 0xFF` every iteration is stored as a **byte** in the target → declare it `unsigned char` (and drop the explicit `& 0xFF`, since the `sb` store truncates). Verified 2026-05-25 on `gl_func_00070194` (CRC-5): `int out` → 184 bytes vs target 176; `unsigned char out` → 180 (1 insn off). **Caveats that did NOT help (regressed):** splitting one expression into separate `out<<=1; out|=bit; out^=tmp;` statements (more reloads, 188); `unsigned char` *return type* (184). The stubborn residual on this one is the -O0 RETURN structure: the target emits `(x & 0x1f) & 0xff` via temp+move pairs with an interleaved sp-restore and no double-`b epilogue`, while `return x & 0x1F` (int return) emits an in-place `andi` + a redundant double branch — an -O0 return-codegen idiom still being reverse-engineered. General lesson: -O0 carves are NOT just plumbing; each body needs per-function -O0 codegen tuning (stack-slot widths, intermediate-store order, return idiom) before the carve pays off.

---

<a id="feedback-ido-inline-call-arg-ptr-vs-named-local-treg"></a>
## Inline a computed pointer into the call (no named local) to keep it in the $t-sequence instead of $v0

When a computed pointer is passed as a (stack-spilled) call argument, declaring it as a **named local** (`char *p = base + idx*K; f(..., p, ...)`) makes IDO assign it `$v0` (a free caller-save return reg), which then cascades the *next* temp (e.g. a constant arg) down a register too. If the target instead continues the natural temp sequence (`...t6/t7/t8/$t9`), **inline the expression directly into the call**: `f(..., base + idx*K, ...)`. With no named local, IDO allocates the addu result as the next temp (`$t9` after `$t8`), matching the target, and the cascade resolves. Verified 2026-05-24 on `timproc_uso_b5_func_0000CCC8`: named `char *p` → `addu $v0` + `li $t9` (4 register diffs); inlined → `addu $t9` + `li $t0` (0 real diffs). This is the **complement** to the usual "use a named local to force a value into $s/$v" advice — for call-arg pointers you often want the *opposite* (inline to stay in $t). Cracked a regalloc "cap" that had previously been forced with the now-banned INSN_PATCH, so re-test ex-INSN_PATCH regallocs with this lever (see `project_1080_ex_insn_patch_regrind_vein`).

**Ex-INSN_PATCH triage (2026-05-24): most are GENUINE caps, not cracks.** Swept the ex-INSN_PATCH functions in game_libs.c, mgrproc_uso, timproc_uso_b1/b5, n64proc_uso, h2hproc_uso — INSN_PATCH was used precisely because the residual diff is a genuine cap, so the hit rate for legitimate-lever cracks is LOW. Read the INSN_PATCH comment's stated *reason* and triage before grinding: only **regalloc-via-named-local** ("idx chain in v0...", "addu base-first v0 vs t-sequence") cracks via this inline-p / fully-array-indexed lever. The others do NOT crack with current levers: **FP-operand-order** ("$f6/$f8 reg-swap", `add.s`/`mul.s` fs/ft canonicalized regardless of C operand order — `game_libs_func_000086A0`, `gl_func_0000871C`), **caller-set $v0/$v1** ("rewrites a1/a2 to v0/v1" — `gl_func_00008674`), **instruction-scheduling order** (`addiu` vs `lui` / `move` vs `sw` swaps — `mgrproc_uso_func_000011A4`), **branch-likely structure** (`bnel` vs `beq`-chain — `mgrproc_uso_func_000014F4`), and size-mismatch (structural). Several USO ex-INSN_PATCH cracks are also reloc-blind-gated (episode only after spimdisasm migration) even when the C is made correct.

---

<a id="feedback-ido-o32-int-a0-float-f12-cap"></a>
## o32 ABI CAP: a function receiving int in $a0 AND float in $f12 simultaneously is not C-reachable

Recognition: target prologue uses an incoming integer arg from `$a0` (e.g. `andi a0,a0,0xff`) AND an incoming float arg from `$f12` (e.g. `mfc1 a1,$f12` / `swc1 $f12,N(sp)` / `cvt`/`mul.s` on `$f12`) — both in the same function. Under the **o32** ABI (`-32`), floating-point and integer arguments **share** the four argument slots, so you can never get this combination from a C prototype:

- `f(int a0, float a2)` → a0 in `$a0`, a2 in **`$a1`** (a 2nd-position float *after* an int goes to the integer register, NOT `$f12`/`$f14`).
- `f(float a2, int a0)` → a2 in **`$f12`**, but a0 in **`$a1`** (the float reserved slot 0, pushing the int to slot 1).

Neither yields int-`$a0` + float-`$f12`. That independent allocation (FP args in `$f12`/`$f14` regardless of preceding int args) is the **n32/n64** convention, which `-32` does not use. Verified 2026-05-24 by standalone-compiling both signatures (see `gl_func_0002DF68`, a 1-diff near-miss whose only diff is our stack-roundtrip `sw a1` vs the target's `mfc1 a1,$f12`). This is the float sibling of the caller-set-integer-register cap (`feedback_caller_set_int_reg_cap_1080_game_libs`). **Detect and leave INCLUDE_ASM** — no C signature reproduces it. (The target was likely built from a different ABI/hand-written, or the caller sets `$f12` directly.)

---

<a id="feedback-ido-rtl-operand-eval-pointer-reg"></a>
## GCC 2.7.2 evaluates binary-operator operands right-to-left — swap commutative operands to control pointer-IV register assignment

When a loop computes `dst[i] = a[i] OP b[i]` over two input arrays, GCC strength-reduces `a[i]` and `b[i]` into pointer induction variables and assigns them temp registers in **creation order**. Creation order follows **evaluation order, which is right-to-left** in GCC 2.7.2: the *right* operand `b[i]` is evaluated first, so b's pointer IV is created first and grabs the lower free temp register (e.g. `$v1`), while a's lands in the next ($a3).

So the natural decompile `dst[i] = a[i] + b[i]` puts **b→$v1, a→$a3**. If the target asm instead has **a→$v1, b→$a3** (a loaded into `$f4` first, i.e. as the first `add.s` operand), flip the source to `dst[i] = b[i] + a[i]`. For a commutative op (`+`, `*`) this is identical in value AND emits the same `add.s $f8,$f4,$f6` bytes (a stays the first FP operand because it's now evaluated first into `$f4`) — only the pointer-register assignment changes. Verified 2026-05-24 on `gl_func_0005E030` (Matrix4-add): `a[i]+b[i]` gave a→$a3 (7 diffs), `b[i]+a[i]` gave a→$v1 (5 diffs, register swap eliminated).

**Caveat — non-commutative ops:** for `-` and `/` the operand order is semantically fixed (`a-b ≠ b-a`), so this lever is unavailable. The sibling `gl_func_0005E0B4` (Matrix4-**sub**, byte-identical to E030 mod `add.s`→`sub.s`) therefore can't use the swap and needs a different register-allocation lever. (Both also share an unsolved +8-byte below-buf frame-size cap — see that function's wrap comment.)

---

<a id="feedback-ido-decrement-arg-not-local-for-counter-loop"></a>
## Decrement the ARG directly (`count--`) not a local copy (`cp--`) when target's loop counter lives in the arg register

_When target asm has the args-preserved-as-locals shape (one `move localReg, argReg` at entry, then per-iter `addiu argReg, argReg, -1`), the C source should decrement the ARG-NAMED param (`count--`) — not introduce a local copy and decrement THAT (`cp = count; cp--`). IDO -O2 maps the explicit `count--` to per-iter `addiu argReg,argReg,-1` (matching target). When you decrement `cp` instead, IDO promotes `cp` to a free $aN/$vN scratch and decrements that, then has to MOVE `count` to a different reg too — net result is more moves, not fewer. Verified 2026-05-06 on func_80000598: `cp--; rem = cp` → 29 diff lines (15 insns); `count--; rem = count` → 10 diff lines (15 insns). Same insn count, very different reg layout._

**The pattern**:

Target asm:
```
move    localReg, argReg     # save copy at entry
beqz    argReg, end
addiu   argReg, argReg, -1   # decrement arg directly (delay slot)
.loop:
  ...
  bnez  argReg, .loop
  addiu argReg, argReg, -1   # decrement arg per iter
```

C source — what NOT to write:
```c
void f(u8* src, u8* dst, s32 count) {
    s32 cp = count;
    if (count == 0) return;
    cp--;
    do {
        s32 rem = cp;
        ...
        cp--;
    } while (rem != 0);
}
```

C source — match the target:
```c
void f(u8* src, u8* dst, s32 count) {
    s32 cp = count;          /* keep the local — its value is the saved copy */
    if (count == 0) return;
    count--;                  /* decrement the arg directly */
    do {
        s32 rem = count;      /* read live arg, not local copy */
        ...
        count--;
    } while (rem != 0);
    (void)cp;                 /* live for prologue copy emit */
}
```

**Why**: the arg parameter has its OWN register slot (a0/a1/a2/a3) that's already live and stable. Decrementing it in-place doesn't require a separate destination register; IDO emits the natural `addiu aN,aN,-1`. Decrementing a local instead asks IDO to allocate a scratch, copy arg→scratch (or use the local copy you already made), then decrement the scratch. The arithmetic is identical but the regalloc footprint is worse.

**Detection**: target's loop has `addiu aN, aN, -1` (the arg register is being modified). Built has `addiu vN, vN, -1` or similar (a scratch register is being modified).

**Caveat**: this is opposite to the usual "don't mutate args" guidance. For decomp purposes, `count--` is correct when target shows arg-mutation; resist the lint instinct.


## `volatile int off = K;` to defeat constant-fold of `&D + K` produces WORSE codegen, not target's `addiu+lw0` form

_When target has `lui rX, 0; addiu rX, rX, K; lw rY, 0(rX); lw rZ, 4(rX)` (offset materialized into the base register, lw uses 0/4 offset), the natural C `int *t = (int*)((char*)&D + K); v1=t[0]; v2=t[1];` triggers IDO's constant-folder and emits `lui rX, 0; addiu rX, rX, 0; lw rY, K(rX); lw rZ, K+4(rX)` (offset folded into the lw). Adding `volatile int off = K; t = &D + off;` to defeat the fold produces `addiu rT, zero, K; sw rT, OFF(sp); ... lw rB, OFF(sp); lui rA; addiu rA, rA, 0; addu rC, rB, rA; lw 0(rC); lw 4(rC)` — the volatile is preserved (immediate stored to and reloaded from stack) and the addu materializes the runtime sum, but the resulting shape is structurally different from target's literal addiu+0-offset form. Worse: frame grows for the volatile spill slot._

**Rule**: don't try volatile-offset to defeat IDO's `&SYMBOL + literal` constant fold. The fold is structural for symbol-relative addresses with literal offsets, and the only escape (volatile) introduces stack spills + runtime adds. If target's emit really requires the addiu+lw0 form, the function is C-unflippable; document it as a structural cap and INCLUDE_ASM-tautology it.

**Verified 2026-05-06 on game_uso_func_00010E2C** (1080 Snowboarding spine wrap family). Cap stays at 87.38% with 4 attempts (`register int *t`, `register volatile int *t`, `*t++ / *t`, block-scope `extern int(int, ...)`, and now `volatile int off`). All structural; no C-level path forward.


## In-place arg mutate `if (cond) a0 = N;` produces the `bnez at, skip; nop; li aN, N` pre-call shape — named-local `int v;` form regresses massively

_When target has a conditional 2nd-arg setup before a jal (`bnez at, skip; nop; li a1, N; .skip: jal; <delay sets a0>`), the natural `int v; if (cond) v = N; else v = a0; jal(..., v);` form regresses sharply (~36 % vs target's shape) because IDO inserts an extra `move a2, a1` shuffle for the named local. Mutating the existing arg in-place — `if (cond) a0 = N;` then `jal(..., a0)` — produces the target shape directly and lands at ~94 %._

**Pattern (target):**
```
slti  at, a1, K            ; condition
bnez  at, .skip            ; skip the override if condition
nop                        ; delay
li    a1, N                ; override arg
.skip:
jal   gl_func
lui   a0, ...              ; delay (1st arg setup)
```

**Wrong C** (named local, ~36 %):
```c
int v;
gl_func(0xF0000000, a0);
if (a0 >= K) { v = N; } else { v = a0; }
gl_func(0xF0000000, v);
```
Built emits an extra `b skip; li v, N` pair plus `move a1, v` shuffle — 4 extra insns vs target.

**Right C** (in-place mutate, ~94 %):
```c
gl_func(0xF0000000, a0);
if (a0 >= K) {
    a0 = N;
}
gl_func(0xF0000000, a0);
```
Built emits `bnez at, skip; nop; li a1, N; .skip: jal` directly — same shape as target.

**Why:** the same-arg slot (here `a0`/`a1` after the move) is already live and register-stable. Mutating it via `aN = N` puts the override directly into the call's arg-register, no additional move needed. Introducing a named local forces IDO to allocate a scratch, write both branches' values into it, then move the scratch into the arg register before the call.

**Detection**: target has the bnez+nop+li shape; the `nop` in the bnez-delay is the load-bearing signal that "the delay slot wasn't used to fill another insn from the override path" — meaning the override IS unconditional in path 2 (no else needed). When you see this, write `if (cond) arg = N;` (no else, no named local).

**Verified 2026-05-06 on gl_func_0002D6C8** (1080 Snowboarding game_libs, 17/18 = 94 % byte-exact; only diff is a trailing `move a2, a0` dead-code that IDO emits but no C reaches). Same recipe as `feedback-ido-decrement-arg-in-place` extended from loop-counter to conditional-arg-override use.

**Related:** `feedback-ido-decrement-arg-in-place` (decrement-in-place sister recipe), `feedback-ido-bnel-dispatch-modify-c-mask-return` (extends to multi-case sparse dispatch).

**COUNTER-CASE — in-place arg reassignment backfires when the target keeps the arg SPILLED-to-home (verified 2026-05-29, gl_func_00069688):** the in-place levers above assume the arg should stay register-resident. The opposite shape exists: a constructor stores an arg early (`sw a1, home`), reloads it for one mid-function field store (`lw t7, home; sw t7, self->X`), then near the tail reloads it AGAIN into a now-DEAD callee-saved reg (the one that held a different arg whose live range just ended — e.g. `lw s1, home; addiu s1, s1, 0x70`) and increments in-place to form a derived pointer. Here the arg is NEVER held in a register across the whole body — it round-trips through its home slot. Writing `arg += 0x70;` to mimic the in-place `addiu` makes IDO promote the arg to a *fresh* saved reg ($s2) held live start-to-finish (extra save + the early store becomes `sw s2,...` instead of `lw t7,home; sw t7,...`) — wrong allocation, regressed 87%→83% reg-blind. Keeping a plain `char *p = arg + 0x70;` local is closer (87%) but spills `p` to its own slot rather than reusing the dead arg's reg (the allocator-internal reuse is not C-reachable). **Lesson: in-place reassignment forces register-residency; if the target spills-and-reloads the arg through its home slot, don't force it — the dead-reg-reuse-for-reloaded-arg pattern is an allocator decision you can't drive from C.**

<a id="feedback-ido-cse-bust-via-distinct-externs"></a>
## Defeat IDO -O2 cross-USO-placeholder CSE by declaring two DISTINCT externs both aliased to the same address

_When a function accesses `D_00000000` (or any cross-USO placeholder) at multiple sites and the target asm uses TWO separate `lui` instructions (one per access) instead of CSE-folding both into a shared base register, declare each access via a distinct C extern name. Add aliases for both to `undefined_syms_auto.txt` mapping to the same `0x00000000`. Runtime relocation collapses them back to the same address; compile-time CSE sees them as distinct symbols and emits separate `lui`s._

**Generalizes to N sites + frees a callee-saved reg (verified 2026-05-29, gl_func_00054A14):** when the SAME constant address is passed as an arg to N successive calls and the target re-materializes `lui;addiu` for EACH call (no CSE), a single `&D_00000000` makes IDO CSE it into a callee-saved reg held across all the calls — which ALSO steals an `$s` reg, so the function's real arg gets bumped to a second `$s` (extra save + bigger frame, wrong allocation). Declaring N DISTINCT externs (`D_x_o0..o(N-1) = 0x0`), one per call site, defeats the CSE → IDO re-materializes `lui;addiu` per call AND no longer needs a callee-saved reg for the address, freeing `$s0` for the genuine arg and matching the target's single-`$s` allocation. Took gl_func_00054A14 (7-call settings binder) 66% → 97.78% (combined with a float-typed call alias for the single-precision stack args). The byte result is honest: each distinct extern resolves to `0x0`, so each emits the exact `lui 0; addiu 0` the target has.

### Symptom

Two-extern target asm:
```
lui  $at, 0           ; %hi(D_X) — store base
lui  $a1, 0           ; %hi(D_Y) — array load base (separate reg!)
sw   $a0, 0($at)
lw   $a1, 0(...)
```

But IDO -O2 with single extern emits CSE'd:
```
lui  $v0, 0           ; %hi(D)
addiu $v0, $v0, 0     ; reuse $v0 as shared base for BOTH the store and the array load
sw   $a0, 0($v0)
lw   ..., (a2*4)($v0)
```

### Why CSE happens

Both accesses compile to the same C-level address (`&D_00000000`). IDO -O2's common-subexpression-elimination materializes the address ONCE in `$v0`+`addiu` form, then reuses across both call sites. The `volatile int*` cast does NOT defeat this CSE (it only changes load-store-elimination, not address-materialization-CSE).

### Fix

In the C body, declare two distinct externs:
```c
extern int D_2D710_store;   /* the store target */
extern int D_2D710_load;    /* the array-load base */

void gl_func_0002D710(int a0, int unused_a1, int a2) {
    D_2D710_store = a0;
    gl_func_00000000(0x41010000, ((int*)&D_2D710_load)[a2], a2);
}
```

In `undefined_syms_auto.txt` (or `symbol_addrs.txt`), add aliases mapping both to the same address as the original placeholder:
```
D_2D710_store = 0x00000000;
D_2D710_load  = 0x00000000;
```

The compiler sees two distinct symbols (one per `extern` declaration), so CSE doesn't fold their address loads. The linker resolves both to `0x00000000` (the cross-USO runtime-relocated placeholder), so the final ROM bytes are identical to a single-extern resolution.

### Verified

`gl_func_0002D710` (game_libs, 2026-05-06): single-extern wrap caps at 1/15 word match (one shared `lui+addiu` for both write and read). Splitting into `D_2D710_store` + `D_2D710_load` promoted to 14/15 — every instruction matches except the unused-arg-save residual at offset 0x4 (separate cap, see `feedback-ido-unused-arg-save`).

### Naming convention

Use `D_<funcaddr>_<purpose>` per existing 1080 convention (e.g., `D_44F4_iter0`, `D_44F4_typtag`). Keep names function-scoped — don't reuse a `D_2D710_*` placeholder in another function unless they truly share state, since at link-time they're distinguishable symbols.

### When NOT to use

Only reach for the split when the target's asm clearly uses TWO separate scratch registers for what would be the same C-level address. If the target uses a single shared base (like IDO's natural CSE'd output), forcing a split via 2 externs would REGRESS the match.

### Scope limit: ISOLATED loads only, NOT entangled multi-ref webs (2026-05-28)

The lever works cleanly when the to-split load is relatively ISOLATED — `gl_func_00039C8C` (2026-05-28): a 102-insn fn that loads `&D_0+0x1A80` once for a bounds-arg while `&D_0` is otherwise a stable entry-`$s0` base; one distinct extern (`D_39C8C_max`) for just that load → 99.0%→100% (408B byte-exact), no collateral.

But it BACKFIRES on functions that reference `&D_00000000` at MANY sites sharing one base. `timproc_uso_b5_func_000079A4` (2026-05-28): 3 `&D_0` refs (0x34 gate / 0x1D0 fade / 0xA4+slot array) all CSE'd onto one base. Splitting just the 0x1D0 fade load into a distinct extern shattered the shared-base CSE web and reshuffled the WHOLE allocation → 98.32%→75-diff regression (+2 insns). Rule of thumb: count the `&D_0` (or placeholder) reference sites first. 1-2 isolated sites → safe. 3+ sites sharing a base → the split cascades; leave it as the natural CSE cap.

---

<a id="feedback-ido-fp-immediate-cse-not-bustable"></a>
## FP-IMMEDIATE-constant CSE (e.g. 1.0f into two `$f` regs) is NOT bustable from C — distinct from symbol-address CSE

The distinct-externs lever above works because a symbol ADDRESS is materialized via `lui`/`addiu` of a named symbol — give it two names, two materializations. An **immediate FP constant** (`1.0f` via `lui at,0x3f80; mtc1 at,$fN`) has NO symbol handle, so there's no way to make IDO emit two materializations from C.

**Symptom** (`gl_func_0002DF98`, 2026-05-28, struct-init writing 1.0f to three fields 0x54/0x58/0x5C): target keeps 1.0f in TWO fp regs —
```
lui  at, 0x3f80
mtc1 at, $f2        ; 1.0f copy A
mtc1 at, $f4        ; 1.0f copy B  (extra insn)
...
swc1 $f2, 0x54(a0)
swc1 $f2, 0x58(a0)
swc1 $f4, 0x5C(a0)  ; third store uses the SECOND reg
```
IDO's natural emit CSE-folds the immediate into ONE reg and stores it to all three (1 insn shorter — `swc1 $f2, 0x5C(a0)`).

**Why C can't reproduce it:**
- `float last = 1.0f; ... store last` → IDO value-numbering proves `last == 1.0f literal`, merges them back to one reg (regression, no extra insn).
- `volatile float last = 1.0f;` → forces a STACK roundtrip (`swc1 $f0,N(sp); lwc1 $f4,N(sp)`), not the target's `mtc1` immediate — wrong shape.
- Loading from a distinct float extern → emits `lwc1 from memory`, not `mtc1` immediate.

There is no C construct that makes IDO materialize the SAME immediate FP constant into two registers via two `mtc1`s. The target shape arises from original source where two distinct fp pseudos both happened to be 1.0f and stayed simultaneously live; value-numbering in our single-expression C always unifies them. **Treat 1-insn "+mtc1 duplicate-FP-constant" diffs as permanent NM caps — don't grind.**

---

<a id="feedback-ido-extern-vs-literal-pointer-encoding-cap"></a>
## `&extern_symbol` vs `(int*)0xNNNN` literal: lui+addiu vs lui+ori — SOLVED 2026-05-24 by `&D_00000000 + offset` (the body below is the obsolete "cap" analysis)

**SOLVED (2026-05-24, supersedes the entire cap analysis below).** When the target has `lui+addiu` and expected/.o has the bytes INLINE (no relocs), the fix is to address through the **DEFINED** base symbol `D_00000000` (at USO offset 0) plus the byte offset, NOT an UNDEFINED `&gl_ref_NNNN` extern:
```c
(char *)&D_00000000 + 0xNNNNN     /* asm-processor RESOLVES this reloc INLINE -> lui+addiu, no reloc, matches expected */
&gl_ref_0003F020                  /* UNDEFINED extern -> lui+addiu WITH R_MIPS_HI16/LO16 relocs -> expected lacks them -> mismatch */
(int*)0x0003F020                  /* literal -> lui+ori (wrong opcode) */
```
The key: `D_00000000` is a **defined** symbol (offset 0), so asm-processor bakes `%hi/%lo(D+0xNNNNN)` into the instruction bytes (inline, no reloc), exactly matching the reloc-blind expected/.o. An undefined extern can't be resolved, so its reloc survives and mismatches. Cracked `gl_func_00061E58` byte-exact (was the ~65% example in this very entry) — change `&gl_ref_0003F020`→`(char*)&D_00000000 + 0x3F020`, `&gl_ref_00022038`→`+ 0x22038`. **This is the same lever as `feedback-return-const-lui-addiu-vs-lui-ori` / `feedback-ido-magic-arg-via-symbol-not-literal`; it applies to lui+addiu-with-inline-expected (grep `&gl_ref_` in src/).** Caveats:
- **-O2 only**: at -O0 the `+offset` materializes the base separately (3 insns, no $at-fold) — leave -O0 functions as-is.
- **Cleanest for call-arg-only uses** (the symbol passed straight to a call, like 61E58). When `&gl_ref` is used in a STORE (`*(int*)&gl_ref = x`), arithmetic, or alongside a prologue `sw ra`, the inline materialization interacts with surrounding scheduling/regalloc and the reloc-fix leaves a SECONDARY cap (e.g. gl_func_0004D05C: reloc fixed 80→99% but a 2-byte `sw ra`/`lui a0` in-tree prologue swap remains; gl_func_000671E4: the store-address materialization reschedules ~6 insns). Verify in-tree (NOT standalone — these show false convergence) and accept the secondary cap when it appears.
- **The lever needs the SAME relocs in expected/.o — does NOT work when expected is raw-`.word` with the address baked NO-reloc.** Whether asm-processor bakes `&D_00000000+off` inline (no reloc) or leaves an `R_MIPS_HI16/LO16` against `D_00000000` depends on whether `D_00000000` is *defined* in the TU being assembled — in most game_libs files it's `extern int D_00000000;` (UNDEFINED), so the reloc **survives** just like `&gl_ref`. 61E58 worked because its expected/.o *also* carries those D relocs (reloc-aware compare matches reloc↔reloc). For a function whose expected/.o was disassembled from raw USO `.word`s (the address baked with **no** reloc table — typical of a `return <address>` leaf), there is NO C symbol form that reproduces "baked + zero relocs": both `&gl_ref` and `&D+off` add surviving relocs the expected lacks, and the land's reloc-aware `byte_verify` rejects them (e.g. `game_libs_func_000666FC`, `return 0x41310` → fuzzy 33.3% on its 3 insns). **Before attempting: `objdump -dr expected/build/.../<file>.c.o` and look at the target insns — if there is no `R_MIPS_HI16/LO16` reloc there, this lever cannot help; it's a genuine literal-baked cap, leave it INCLUDE_ASM.**
- **`objdump -d` (no `-r`) shows the baked value even when a reloc survives → a `-d`-only byte compare gives a FALSE 0-diff.** A surviving `lui rX,0x4`/`addiu …,0x1310` disassembles identically to the inline-baked expected, so a plain `objdump -d` raw-byte diff reports "0 diffs" while the `.o`s actually differ by 2 reloc entries. ALWAYS verify these address-materializing functions with `objdump -dr` (relocs shown) or the land script's reloc-aware `byte_verify` — never `-d` alone.

---
_OBSOLETE ANALYSIS (kept for archaeology — concluded "cap", now wrong):_
_When the target ROM has a constant pointer materialised via `lui rX, HI16; addiu rX, rX, LO16(signed-extending)` BUT expected/.o has NO relocation entries (bytes are inline), neither natural C form reaches the exact byte sequence:_

- **`extern T sym;` declared in `undefined_syms_auto.txt`** → IDO emits `lui+addiu` (correct shape) BUT also emits `R_MIPS_HI16` / `R_MIPS_LO16` relocations against `sym`. Result at .o level: `lui rX, 0; addiu rX, rX, 0` + reloc table entries. Linker resolves at link-time to the right bytes.
- **`(int*)0x0003F020` literal cast** → IDO emits `lui+ori` (different shape!) with no relocations. Bytes inline as `lui rX, 0x3; ori rX, rX, 0xF020`. Same value but different encoding from the addiu pair.

**Mismatch at .o-level:** if expected/.o has `lui 0x4; addiu -0xFE0` (sign-extending negative offset → 0x40000 − 0xFE0 = 0x3F020) inlined without relocations, then:
- The `&extern` form gives matching `lui+addiu` shape but with relocations expected lacks.
- The literal-cast form gives `lui+ori` (wrong instruction).

**Verified 2026-05-06 on `gl_func_00061E58`** (1080 game_libs). 17-insn function with 3 lui+addiu pairs targeting `0x3F020` and `0x22038`. With `&gl_ref_0003F020` extern, built has correct mnemonic shape but extra reloc entries. With `(int*)0x0003F020` literal, built has `lui+ori` instead of `lui+addiu`. Neither reaches expected/.o byte-equality. Cap stays at ~65%.

**Why expected has no relocs**: the original ROM was built from C using a typed-symbol pattern (likely `extern T D_3F020;` with a different declaration shape OR a #define that produced inline bytes via assembler-level constant). The post-cc-recipe SUFFIX_BYTES/INSN_PATCH pipeline COULD inject the exact bytes, but that's invasive for a small wrapper.

**Practical rule**:
- Use `&gl_ref_NNNNNNNN` form per `feedback-game-libs-jal-targets` for ROM-correctness — the linker resolves and the ROM matches.
- Accept ~60-70% NM cap for these functions when expected/.o has bytes inlined without relocations.
- Don't grind the literal-cast form expecting it to fix encoding; it switches `addiu` → `ori`, which is a worse mismatch.

**Related:**
- `feedback-game-libs-jal-targets` (in N64_FORENSICS.md) — the gl_ref recipe for absolute-symbol externs.
- `feedback-ido-type-split-unique-extern-breaks-cse` — doesn't help here; CSE isn't the issue.

---

<a id="feedback-ido-lui-lw-hoisted-above-prologue"></a>
## IDO -O2 may emit a leading `lui Tn, 0; lw Tn, K(Tn)` global-pointer load BEFORE the sp-adjust prologue — C source that triggers this isn't reachable from straightforward `extern *p = &D[K];` patterns

_When target asm shows the function starting with 2 instructions that load a global pointer (lui+lw with a relocation against the data segment) and ONLY THEN does the prologue (`addiu $sp, -N; sw $ra, K($sp)`), IDO has hoisted the global-load above the stack-adjust. Standard C bodies always produce prologue-first emit, so this manifests as a 2-insn schedule difference that doesn't byte-match._

**Symptom:**

Target:
```
lui $t6, 0
lw  $t6, 0x548($t6)    ; reloc → &D + 0x548
addiu $sp, $sp, -0x40
sw  $ra, 0x14($sp)
lw  $a1, 0($t6)         ; first body load
... function body ...
```

Your build (any straightforward C):
```
addiu $sp, $sp, -0x40
sw  $ra, 0x14($sp)
lui $t6, 0
lw  $t6, 0x548($t6)
lw  $a1, 0($t6)
... function body ...
```

Same instructions, different order. Your output is +0 bytes (same total) but words 0/1 swap with words 2/3, so byte-exact fails.

**Why this happens:** IDO -O2's instruction scheduler can hoist a register-temp-load (using only caller-save $t-regs) above the prologue when:
- The load result is used immediately after the prologue.
- The hoisted insns don't depend on $sp.
- Putting them before the prologue avoids a pipeline stall on the first body instruction.

This is an aggressive scheduling pass that runs after the normal codegen — the C source determines what insns exist, not their relative order vs the prologue.

**Why C can't reach it:** The compiler's prologue-emission pass produces stack-adjust + saves first, and the scheduler operates on the post-prologue insn stream. There's no C-level trigger that says "schedule this global-load before the prologue." `register T *p asm("$t6") = ...;` isn't supported by IDO 7.1 (per `feedback_ido_no_gcc_register_asm.md`).

**Verified case (2026-05-07):** `game_uso_func_00006F38` in 1080. Target leads with `lui $t6, 0; lw $t6, 0x548($t6)` before the prologue. Standalone IDO -O2 of the equivalent C body emits prologue first, lui+lw second — same insn count (28 → 30 if I added the dead spills, but the schedule itself is unflippable). Documented as NM-cap.

**How to apply:** when target shows lui+lw before prologue with the lui's hi16 reloc-resolved against `&D_<seg>` and the body uses the loaded register immediately, this is the unflippable-schedule cap. Wrap NM with the structural decode; don't grind register-allocation knobs (the cap is scheduler-level, not regalloc-level). If post-cc-recipe promotion becomes possible (e.g., via a 2-insn-swap script that doesn't disturb relocations), this is a candidate.

**Companion:** `docs/POST_CC_RECIPES.md` — the existing PROLOGUE_STEALS recipe handles the OPPOSITE case (predecessor's tail bleeds INTO this function's prologue) but doesn't apply here (the lui+lw is logically OUR function's, just scheduled differently).

---

<a id="feedback-ido-block-reorder-not-source-flippable"></a>
## Confirmed-not-a-lever: swapping if-then-else (or goto) BLOCK ORDER in C source does NOT flip IDO -O2's emit order — the reorder is destination-shape-driven, not source-flippable

_When two basic blocks of similar size dispatch via `if (key == K0) goto k0; if (key == K1) goto k1;` and IDO emits them in non-source order in the .o, swapping source order is a no-op: IDO consistently picks the same emit order based on RTL-level shape heuristics, regardless of which arm is written first._

**Setup:** function with `goto k0` and `goto k1` arms in source order k0 → k1. IDO emits k1 first (offset 0x39C) and k0 second (0x3D8). Source clearly has k0 first; emit clearly has k1 first.

**Hypothesis tested:** swap source order to k1 → k0. If IDO's reorder is "always-flip-source-order," the swapped source should produce k0-first emit. If reorder is "always-emit-k1-first" (intrinsic to the blocks themselves), swapping source has no effect.

**Result (verified 2026-05-07 on `n64proc_uso_func_0000035C`):** IDO emits k1 first regardless of source order. Both source orderings produce structurally-identical .o output with k1 emitted first. Confirms the reorder operates on RTL post-front-end and is independent of C's textual block order.

**How to apply:** when target's k0/k1 blocks are emitted in non-source order and your build emits them in the OPPOSITE-of-target order, do NOT spend cycles on source-block-swap variants. The cap is at IDO's RTL reorder pass (analogous to GCC's `reorg.c`), not reachable from C-source-form variation. Move on to other levers (per-call unique externs, INSN_PATCH for byte-replacement, or accept the cap as documented).

**Companion confirmed-not-a-lever entries (this function class):**
- decl-source-order is decoupled from `$s` pseudo-numbering (variant 6 of same function)
- block-scope of locals does NOT shorten RTL live range (variant 23)
- type narrowing (`short` vs `int`) is a no-op for `$s` priority when value used as int downstream (variant 25)
- `-g0`/`-g2`/`-g3` flags don't shift `$s` allocation in IDO -O2 (variant 26)

---

<a id="feedback-ido-volatile-local-frame-placement"></a>
## `volatile int x;` in IDO -O2 lands at TOP of stack frame (sp+frame_size-4), not bottom — using it to force a dead-store at sp+0x4 grows the frame by 8 bytes

_When you need IDO to emit a dead-store at a SPECIFIC low frame offset (e.g., sp+0x4) to match a target's IDO -O2 emit, declaring `volatile int x; x = val;` does NOT place x there. IDO's local-allocator puts volatile locals at the high end of the frame (sp+frame_size-4), forcing the frame to grow by 8 bytes (16-byte alignment)._

**Symptom:** target has frame 0x18 with a dead `sw a1, 0x4(sp)` in a delay slot (~14 insns). C body with `volatile int x; x = arg0;` reproduces the dead-store and the right insn count (14) but lands x at sp+0x1C with frame 0x20 — same shape, wrong offset, +8 bytes too big.

**Why:** IDO's stack allocator processes locals top-down (from sp+frame_size-4 toward sp). The first volatile gets the highest slot. To force x to sp+0x4 you'd need to allocate other locals ABOVE it, but those locals would themselves consume the high slots, leaving x at the bottom only after the frame is enlarged enough.

**What also doesn't work:**
- `char buf[8]; *(volatile int*)(buf+4) = val;` — the volatile-cast forces IDO to compute the base register via `addiu tN, sp, frame_offset`, adding an extra insn before the store. Wrong shape.
- Reordering decls — IDO's allocator priority is data-flow-derived, not source-order.

**Net:** if target's dead-store lives at a low offset (sp+0x4..0x10) inside an existing-frame's local space WITHOUT growing the frame, that combination is unreachable from C. The store can be reproduced (right shape, right count), but only at TOP-of-frame slots which add 8 bytes.

**Verified case (2026-05-07):** `func_00005068` in 1080-bootup_uso. 14-insn 2-call helper with target dead-store at sp+0x4 in jal delay slot. 6 documented variant attempts; volatile + buf-cast both produce the right insn count but wrong offset/frame. Cap confirmed.

**How to apply:** when target has a "dead store at low frame offset within minimal frame," skip the volatile-local approach. Either accept the cap (NM-wrap at insn-count parity) or use post-cc INSN_PATCH if the build is in shift-tolerant byte-replacement scope (per `docs/POST_CC_RECIPES.md`).

---

<a id="feedback-ido-brace-block-scope-saves-stack-frame-bytes"></a>
## Brace-block scope for short-lived named locals keeps stack frame at the natural size; function-scope declaration grows it by 8 bytes

_When you introduce named locals to flip IDO's register pick (the `feedback-ido-v0-reuse-via-locals` / `feedback-ido-inline-keeps-t-regs` lever), declaring them at FUNCTION scope tells IDO's allocator to reserve dedicated stack slots even if those slots are never written. Wrapping the declaration in a brace-block `{ int *p_a = ...; ... }` keeps the frame at its natural size — IDO reuses existing slots once the brace-block exits._

**Setup:** target function has frame 0x28 with intermediate `lw v1, X(v0); lw a2, Y(v0); lw a0, 0x800(v1); lw t6, 0x800(a2)` pattern (uses $v1/$a2 for the intermediate ptr loads). Naive C with inline expressions emits $t6/$t7 for the intermediates — wrong regs.

**The lever (well-documented):** introduce named local pointers `int *p_a = (int*)v0[X/4]; int *p_b = (int*)v0[Y/4];` to make IDO pick $v1/$a2.

**The trap:** declaring them at function scope grows the frame from 0x28 to 0x30 — 8 bytes too many. IDO reserves slots for the named locals even though the values only live within a few insns.

**The fix:** wrap the named locals in a brace-block:
```c
v0 = ...;
{
    int *p_a = (int*)v0[X/4];
    int *p_b = (int*)v0[Y/4];
    n0 = p_a[0x800/4];
    n1 = p_b[0x800/4];
}
gl_func(n0, ...);
```

The brace-block tells IDO the locals' lifetime ends at the closing brace, so the slots can be reused for other spills (or not allocated at all if the values fit in registers). Frame stays at 0x28.

**Verified case (2026-05-07):** `mgrproc_uso_func_00001AD0` (1080 mgrproc_uso). Function-scope `int *p_a, *p_b` → frame 0x30, match 98.88%. Brace-block-scope same locals → frame 0x28, match 99.09%. Same register-pick win in both variants ($v1/$a2 for intermediates), only the frame size differs.

**Caveat — does NOT shorten RTL live range:** an entry in `feedback-ido-block-reorder-not-source-flippable` notes "block-scope of locals does NOT shorten RTL live range" — that's about REGISTER pressure (the named local still gets a dedicated $s register as if it lived the whole function). The brace-block lever applies SPECIFICALLY to STACK frame sizing, not register liveness. Both findings can be true simultaneously.

**How to apply:** when introducing named locals to flip IDO's register pick AND the target's frame size is smaller than your build's:
1. First check whether the diff is +8 bytes of frame (look at `addiu sp, sp, -SIZE` immediates).
2. If yes, wrap the locals in a brace-block. Often gets the last 0.2-0.5pp.
3. If the frame size is correct but reg pick is still wrong, the issue isn't the brace-block — it's the named-local form itself (try `register int *p_a = ...` per `feedback-ido-register.md`, or revert to inline form).

**Does NOT generalize to volatile-spill locals** (verified 2026-05-07 on `func_0000553C`): the brace-block trick is scope-specific. For register-flip locals (this entry), the value's lifetime ends at the assignment to the consumer (`n0 = p_a[...]`) so the brace-block is safe. For volatile-spill locals (`feedback-ido-volatile-unused-local-forces-local-slot-spill`), the spill must remain LIVE across the subsequent call — wrapping in a brace-block kills the spill at the closing brace and IDO drops the `sw aN, local_slot(sp)` store. Net: brace-block-saves-frame applies to "named local that gets dereferenced before the next jal," NOT to "volatile that triggers a defensive caller-spill across a jal." The two mechanisms have opposite scope requirements.

---

<a id="feedback-ido-extern-addr-non-null-fold-defeats-runtime-null-check"></a>
## IDO -O2 folds `&extern == 0` to FALSE — defeats null-check arms in C bodies that mirror cross-USO unbound-symbol asm

_When the target asm has a runtime null-check like `bnez v1, target` where v1 was set up via `lui rX, 0; addiu v1, rX, 0` (cross-USO data placeholder), the natural C body `int *v1 = (int*)&D_00000000; if (v1 == 0) { alloc(...); } else { ... }` doesn't reproduce — IDO -O2 sees `&D_00000000` as a compile-time non-null symbol address and folds the null-check, eliding the entire alloc arm._

**Why this happens:** `&SYM` for any extern is a fixed address from the compiler's view. Even if the linker eventually resolves SYM to 0 (cross-USO unbound symbol, or a deliberately-zeroed alias in `undefined_syms_auto.txt`), the compiler doesn't know that — it treats `&SYM` as "some non-null pointer" and constant-folds `&SYM == 0` to FALSE. The taken-arm code is dead from IDO's perspective.

**Symptom:** standalone IDO emit is N insns shorter than target. Inspecting the diff shows the conditional alloc/init branch is entirely missing; only the always-executed tail (the post-merge zero-stores) remains.

**Levers to defeat the fold:**

1. **Load v1 via a runtime indirection**: declare a separate `extern int *D_globalptr;` and load `v1 = D_globalptr;`. Now v1 is a value loaded from memory at runtime, not an address-of symbol — IDO can't fold the null-check.
2. **`volatile` indirection**: `volatile int **pp = (volatile int**)&D_PTR_HOLDER; v1 = *pp;` — the volatile read is unfoldable. Useful when the target asm has both `lui+lw` (load via pointer) and the conditional check.
3. **Function call to obscure the value**: if there's any plausible accessor in the codebase (`get_X_ptr()`), use it — function returns are opaque to constant folding.

**Common case where this matters:** lazy-init / memoized allocators. The asm has `if (g_cached == 0) { g_cached = alloc(N); } use(g_cached);` patterns where `g_cached` is a global pointer placeholder. The natural `g_cached = &D_PTR_NULL;` C form gets folded; needs to come through a `volatile int *` indirection.

**Verified 2026-05-08** on `gl_func_0005165C` (1080-agent-e). Predecessor's stolen-prologue tail set `v1 = &SOME_GLOBAL`, and the body had `if (v1 == 0) alloc(4); *v1 = 0; D[0]=0; D[4]=0;`. Standalone -O2 of the natural C body collapsed to 7 insns (only the trailing zero-stores), vs target's 14. NM-wrap kept the partial — lever fix not pursued; documented for future tightening.

**Companion:** `feedback-ido-cse-bust-via-distinct-externs` (different problem: defeating CSE between two `&D_00000000` accesses by declaring distinct externs).

---

<a id="feedback-ido-magic-arg-via-symbol-not-literal"></a>
## Pass magic-numeric arg via `&gl_ref_<addr>` symbol — IDO emits `lui+addiu` only for symbol refs, not raw int literals (which emit `lui+ori`)

_When the target asm has `lui aN, HI; addiu aN, aN, LO` materializing a magic 32-bit constant 0xNNNNNNNN as a call argument, the C source MUST use a symbol reference (`&gl_ref_<addr>`), NOT the raw integer literal._

**Why:** IDO 7.1 picks the lui-pair shape based on the operand's nature, not its numeric value:

- Raw int literal (`0x2B3B8`): emitted as `lui aN, 0x2; ori aN, aN, 0xB3B8` (literal high half, no sign-extension).
- Symbol address (`&gl_ref_0002B3B8`): emitted as `lui aN, %hi; addiu aN, aN, %lo` (relocations the linker fills with sign-corrected halves: HI = (addr+0x8000)>>16, LO = signed 16-bit).

Both compute the same final address, but the BYTE PATTERN differs (`0x34a5...` ori vs `0x24a5...` addiu).

**Recipe:**

```c
extern char gl_ref_0002B3B8;   /* declare as char to avoid type collisions */
gl_func_X(arg, &gl_ref_0002B3B8, ...);
```

In `undefined_syms_auto.txt`:

```
gl_ref_0002B3B8 = 0x0002B3B8;
```

The linker resolves the R_MIPS_HI16/LO16 relocations to address 0x0002B3B8, producing `lui aN, 0x3; addiu aN, aN, -19528` (`= +0xB3B8` as signed) → bytes `0x3c050003 0x24a5b3b8`. Byte-exact match against expected/.o.

**Naive byte-compare gotcha:** `mips-linux-gnu-objdump -d build/<file>.c.o` shows the unresolved relocation slots as `lui 0; addiu 0` (bytes `0x3c050000 0x24a50000`), making the function look 2-insn off vs expected/.o. This is normal — expected/.o is built from `.s` files with hardcoded resolved bytes (no relocations). Verify against `build/tenshoe.elf` (linked output, post-relocation) instead, OR rely on objdiff (which is reloc-aware).

**Verified 2026-05-08** on `gl_func_000682F8` — 3-arg helper call `gl_func_0001CA10(self+0x14, &gl_ref_0002B3B8, self)` matches byte-exact in linked ELF; `build/<file>.c.o` shows the expected reloc-stub mismatch in raw `objdump -d`.

**Further confirmations 2026-05-14:**
- `gl_func_000545BC` (game_libs_post.c): the magic constant `0x2107C` passed to a 2-arg call. `&gl_ref_0002107C` lever pushed 81.40% → 100% (combined with the goto-end recipe; the lui+addiu fix is the +1.4pp final-mile component). EXACT MATCH.
- `game_libs_func_0004D0E4` (game_libs_post.c): the magic constant `0x3EB00` stored at a struct field. `&gl_ref_0003EB00` lever pushed 70.37% → 72.44% (+2.07pp).
- `func_000086C0` (bootup_uso.c): alt-entry call to `func_0000027C + 0x18`. `&gl_ref_00000294` lever pushed 81.76% → 84.93% (+3.17pp; collapsed 4-insn materialize-then-adjust to 3-insn lui+jal+adjusted-addiu(DS)).
- `func_0000B49C` (bootup_uso.c): alt-entry call to `func_00008A40 + 0x18`. `&gl_ref_00008A58` lever pushed 65.58% → 68.48% (+2.90pp).

The recipe is high-yield for any unmatched function where built emits `lui+ori` (or `lui+addiu+addiu`) for a constant or alt-entry pointer that target encodes as `lui+addiu` (or `lui+adjusted-addiu(DS)`).

**Variant — segment-base + offset (USO / relocatable code, no new symbol required):** In game_libs / USO segments where `D_00000000` is the segment-base extern, you can write `(char*)&D_00000000 + 0xN` instead of declaring a new `gl_ref_<addr>` and editing `undefined_syms_auto.txt`. IDO emits the same `lui %hi(D_00000000+0xN); addiu %lo(D_00000000+0xN)` pair (signed-corrected) — the linker resolves D_00000000=0 plus addend 0xN, yielding the same bytes as a fresh `gl_ref_0000N` symbol. Verified 2026-05-15 on `gl_func_0000B868` (call#2 3rd arg = 0xD4E0 → `(char*)&D_00000000 + 0xD4E0`; promoted 40% → 100% mnemonic). Cleaner for one-off magic constants; use the named-`gl_ref_<addr>` form when the same magic appears in many call sites (one extern declaration vs N inline casts).

### Variant — also applies to ALT-ENTRY tail calls (`func_X + offset` pointer arithmetic)

The recipe extends beyond magic integer constants. When a C body has a tail call like `func_00000000((char*)func_0000027C + 0x18);` (calling into an alt-entry / mid-function jump target), IDO emits the FULL 4-insn materialization-then-adjust sequence:

```
lui    a0, %hi(func_0000027C)       ; materialize symbol base
addiu  a0, a0, %lo(func_0000027C)   ; complete the symbol
jal    callee
addiu  a0, a0, 0x18                  ; (DS) add the offset
```

Target asm has the cleaner 3-insn `lui + jal + adjusted-addiu(DS)` form:
```
lui    a0, %hi(func_0000027C+0x18)
jal    callee
addiu  a0, a0, %lo(func_0000027C+0x18)   ; (DS, with the +0x18 folded in)
```

Same recipe applies — declare a NEW symbol at the resolved offset:

```
gl_ref_00000294 = 0x00000294;        ; in undefined_syms_auto.txt
                                      ; (0x294 = 0x27C + 0x18)
```

```c
extern char gl_ref_00000294;
func_00000000(&gl_ref_00000294);     /* was: func_00000000((char*)func_0000027C + 0x18); */
```

IDO emits the 3-insn form. Verified 2026-05-14 on `func_000086C0` (1080 bootup_uso): 81.76% → 84.93% (+3.17pp).

**When to use this variant:**
- Target has a tail call to an interior offset of another function (alt-entry).
- Built emits an extra `addiu aN, aN, %lo(symbol)` before the jal compared to expected.
- The symbol-ref recipe collapses the 4-insn form into target's 3-insn form.

**Companion:** `feedback-ido-split-or-constant` covers the inverse case (forcing `lui+or+ori` via a split-OR shape when the target asm has `or` operations on the constant).

---

<a id="feedback-ido-div-substitution-necessary-but-regalloc-shifts"></a>
## Replacing literal `1024` with `(x<<10)/x` DOES emit the sll+div+mflo sequence at IDO -O2 (memory-load operand defeats SR), but added locals can shift register allocation enough to net-zero fuzzy%

_When target asm has `sll tN, sM, 10; div 0, tN, sM; mflo sP; bnez sM, +2; nop; break 7` (a self-canceling `(x<<10)/x = 1024` sequence with div-by-zero trap), replacing the literal `1024` in the C body with the equivalent `(x<<10)/x` expression IS recognized — IDO -O2 doesn't strength-reduce when the operand comes from a memory load (no compile-time visibility). However, declaring the result as a new local (or substituting inline) introduces extra register pressure: frame size can grow (e.g., 0x58→0x60), and $s-reg assignments shift across the function. The div pattern alone is "necessary-but-not-sufficient" — to land net-positive fuzzy%, the divided value must also be assigned the same $s-reg slot as the target._

**Why the div is preserved:** IDO's strength reduction needs to see both operands at compile time to fold `(x<<10)/x → 1024`. When `x` is a value loaded from memory (`lw t6, off(sN)` then `t6<<10/t6`), the optimizer can't statically prove `t6 != 0` — so it preserves the full `sll+div+mflo+break-on-zero` sequence including the div-by-zero trap. This is identical reasoning to `feedback-ido-o2-loop-array-strength-reduction`: SR needs DFG-level visibility.

**Why fuzzy% can stay flat or regress:** the substitution adds 1-2 intermediate locals. Even if you don't declare them as named C variables, IDO's register allocator sees the new `mflo sP` result as a value that must live until consumed by the next instruction. Three things shift:
1. **Frame size** — if the function was at the boundary of needing one more $s-reg saved, the new live range pushes it over (8-byte frame growth).
2. **$s-reg pick** — IDO's allocator reassigns $s0/$s1/...$s8 to balance the new live range. Even if total $s-regs unchanged, the slot-to-variable mapping flips.
3. **Multu/multiply downstream** — if the divided value is consumed by `multu v0, sN`, the `sN` choice depends on which $s-reg the mflo landed in.

Result: even when the div sequence itself is byte-correct, the surrounding code has 4-8 lines of register-name diff (s0 vs s1, s4 vs s3, etc.). Net fuzzy% delta = 0.

**Verified case (2026-05-07):** `gui_func_00000B58` (1080 gui_uso). Replacing literal `1024` in two `gl_func_00000000` arg slots with `(s3<<10)/s3` and `(g2<<10)/g2`:
- Built emit: full `sll+div+mflo+break` sequence in both spots (matches asm shape).
- Frame: 0x58 → 0x60 (+8 bytes).
- Reg shifts: $s0↔$s1, $s3↔$s4, $s5↔$s8 in built vs expected.
- Diff lines: ~80 → ~80 (no improvement).
- Fuzzy: 36.12% → 36.12%.

**How to apply:** when target has a `(x<<N)/x = 2^N` div sequence and your build emits the literal:
1. The substitution is a NECESSARY ingredient — write it.
2. But check the frame size and $s-reg assignments BEFORE concluding the change helps. If frame grew or $s-regs shifted, the substitution won't land fuzzy% gains alone.
3. Pair with explicit local-variable scoping (brace-block per `feedback-ido-brace-block-scope-saves-stack-frame-bytes`) to keep the frame size constant.
4. If after both fixes the $s-reg slot is still wrong, the gap is likely deeper register-pressure analysis (use `cc1 -dg` to inspect the .greg dump per the skill's "Debugging register allocation" notes).

**Don't do it the other direction:** don't substitute literal `1024` for `(x<<10)/x` when target uses the literal — IDO will emit `li t, 0x400` and the div sequence won't appear. The div pattern signals the substitution is needed; the literal pattern signals it isn't.

---

<a id="feedback-ido-inline-symbol-arith-vs-base-local"></a>
## Inline `&D_X + N` everywhere (not via a `base` local) — lets IDO use $at-fused `lui at; sw 0(at)` stores instead of 2-insn $v1 materialization

_For multiple stores like `*(int*)(base + 0xN) = 0` where `base = &D_X`, declaring `base` as a local forces IDO -O2 to materialize the symbol in $v1 (`lui v1; addiu v1, v1, 0; sw $0, 0xN(v1)` — 3 insns per store). Inlining `(char*)&D_X + 0xN` at every site lets IDO use the $at-fused store pattern (`lui at, %hi(D_X+0xN); sw $0, %lo(D_X+0xN)(at)` — 2 insns per store)._

**The shape difference (target vs `base` local form):**

| C body | Emit per `*(int*)(... + 0xN) = 0` store |
|---|---|
| `*(int*)((char*)&D_X + 0xN) = 0;` (inline) | `lui at, %hi(D_X+0xN); sw $0, %lo(D_X+0xN)(at)` — 2 insns |
| `char *base = &D_X; *(int*)(base + 0xN) = 0;` | `lui v1, %hi(D_X); addiu v1, v1, %lo(D_X); sw $0, 0xN(v1)` — 3 insns (base materialized once but emitted at first use) |

The 1-insn savings per store compounds when the function has multiple constant-address writes.

**Why this happens:** `$at` is the assembler-temporary register; MIPS reserves it for instruction expansions like `la sym` → `lui at, %hi(sym); ori at, at, %lo(sym)`. IDO -O2 will emit `lui at; sw $0, %lo(SYM)(at)` directly when the store target is a pre-resolved symbol with known address. When you introduce a `base` local variable, IDO has to materialize the symbol in a callee-saved register (since `base` might be live across calls), and `$at` is no longer available for the per-store fold.

**Verified case (2026-05-14):** `gl_func_00021EA8`, a 38-insn 4-call gated cleanup pair with 5 `*(int*)(base + offset) = 0` stores. Initial NM-wrap C body used `char *base = (char*)&D_00000000;` and got 68%. Refactoring to inline `(char*)&D_00000000 + offset` at every site brought 86.7% (+18.7pp). No other changes.

**Counter-intuitive vs "factor common subexpressions":** the usual C-style refactor is to extract a common base into a local — and for non-constant addresses or hot loops this is correct. But for **constant-address stores specifically**, IDO's optimizer prefers the inlined form because `$at` is reservable per-instruction whereas `$v1` (or any caller-save register) has to be re-allocated across the function.

**When to apply:** function has 2+ stores to constant addresses sharing a base symbol AND fuzzy is below 90%. Try the inline form first; if fuzzy improves, keep it.

**When NOT to apply:** the address is NOT a compile-time constant (e.g., `base = arg0 + 0x100;` then store via `base[N]`). In that case the local IS needed — there's no symbol for `$at` to fuse against.

---

<a id="feedback-ido-epilogue-no-move-v0-implies-void-return"></a>
## Asm epilogue with no `move v0, ...` before `jr ra` indicates void return — match the C signature

_When the target's epilogue is `lw ra, X(sp); addiu sp, sp, +N; jr ra; nop` with NO `move v0, ...` (or `or v0, ..., zero`) immediately before `jr ra`, the function returns `void`. C bodies declared as `T *fn(...)` with `return X;` will emit a spurious `move v0, X` that doesn't appear in target._

**The diagnostic — look at the last 4 insns before `jr ra`:**

| Asm tail | Inferred return type |
|----------|---------------------|
| `lw ra, X(sp); addiu sp, +N; jr ra; nop` | `void` |
| `lw ra, X(sp); addiu sp, +N; jr ra; <reg-set>` (delay-slot fill) | `void` (delay-slot is incidental) |
| `... move v0, X; lw ra, ...; addiu sp, +N; jr ra; nop` | non-void (returns whatever's in X) |
| `lw ra, X(sp); addiu sp, +N; jr ra; or v0, X, $0` (delay) | non-void (returns X via delay-slot move) |

The key signal is whether `$v0` (or `$f0` for float-returning fns) is explicitly set in or near the epilogue. If not, the function returns void and any prior $v0 value just leaks out.

**Why this matters for fuzzy%:** declaring `void *fn()` with `return X;` emits `move v0, X` (or `or v0, X, $0`) before the epilogue. If the target's tail doesn't have that instruction, you've added a spurious insn. Each spurious instruction misaligns surrounding asm, cascading into ~0.2-0.5pp fuzzy loss per spurious insn at this scale.

**The C-source fix:**
```c
/* Before: */
void *fn(int *a0) {
    /* ... body ... */
    return a0;
}
/* After: */
void fn(int *a0) {
    /* ... body ... */
    /* no return statement */
}
```

If the function had multiple `return X;` paths (e.g. early-exit "return 0" branches), all of them need to drop the value. Use `goto end;` and `(void)var;` at the end if the variable was load-bearing for documentation purposes.

**Caveat — function MIGHT actually return something via $v0 leaking from prior computation.** Some functions have NO explicit `move v0` in the epilogue but DO return a value — whatever happened to be computed last. This is hard to distinguish from "returns void" without seeing call sites. If the function has internal callers that USE the return value, the C signature is non-void; if no callers exist (USO loader-called) or callers ignore the return, void is safe.

**Verified case (2026-05-07):** `game_uso_func_00001DDC` (1080 game_uso). 383-insn function with 19.64% NM-wrap. Asm epilogue is `swc1 f8, 52(a2); lw ra, 20(sp); addiu sp, +384; jr ra; nop` — no `move v0`. Built with `void *fn(...)` + `return a0` was emitting `move v0, a1`. Changed to `void fn(...)` and dropped the return: 19.64% → 19.90% (+0.26pp). No internal callers, so signature change is safe.

**How to apply:** when grinding an NM-wrap that's been stuck at low fuzzy%, compare the epilogue tail. If the build has `move v0` and expected doesn't, drop the return value.


---

<a id="feedback-ido-symbol-offset-runtime-cannot-fold"></a>
## IDO can't fold `&SYM + 0xCONST + runtime` into 3-insn lui/addiu/addu — always factors constant onto runtime side (4 insns)

_Inverse of `feedback-ido-offset-in-instruction-vs-reloc`: that entry is about loads (`lw $reg, OFF($at)`) where the offset goes into the instruction. This entry is about pure address computation when both a symbol+constant AND a runtime expression are added together. IDO ALWAYS factors as `(D) + (0xCONST + runtime)` (4 insns: lui-D, addiu-of-CONST-on-runtime, addiu-D-lo16, addu) instead of expected `(D + 0xCONST) + runtime` (3 insns: lui-of-(D+CONST), addiu-of-(D+CONST), addu). No combination of paren grouping, intermediate temp, array-index expression, int-cast, or operand reordering coerces it. Confirmed across 5 expression shapes 2026-05-08 on `timproc_uso_b5_func_0000CCC8`._

**Symptom:**
```c
gl_func(..., &D_00000000[0x1C0 + idx * 24], ...);
// or:        (char*)&D_00000000 + 0x1C0 + idx*24
// or:        ((int)&D_00000000 + 0x1C0) + idx*24
// or:        char *base = &D_00000000[0x1C0]; base + idx*24
```

**Expected (3 insns for the addr calc):**
```
lui   $t8, hi(D + 0x1C0)         ; HI16 reloc on D, in-insn imm baked = 0
addiu $t8, $t8, lo(D + 0x1C0)    ; LO16 reloc on D, in-insn imm baked = 0x1C0
addu  $t9, $runtime, $t8         ; merge with runtime
```

**IDO emits (4 insns):**
```
lui   $t9, 0                     ; HI16 reloc on D, addend 0
addiu $t8, $runtime, 0x1C0       ; constant 0x1C0 baked onto RUNTIME side
addiu $t9, $t9, 0                ; LO16 reloc on D, addend 0
addu  $t0, $t8, $t9              ; merge
```

**Workaround recipe (untried — needs link-side coordination):**
1. Declare a per-offset extern: `extern char D_000001C0;` (or whatever offset).
2. Add to `undefined_syms_auto.txt`: `D_000001C0 = 0x000001C0;`
3. Use `&D_000001C0 + runtime` in C — IDO emits `lui hi(D_at_OFF); addiu lo(D_at_OFF); addu` (3 insns) with HI16/LO16 relocs against the new symbol.
4. Add INSN_PATCH for the addiu's lo16: `funcName=0x2C:0x271801C0` (the literal post-link bytes).
5. The post-cc patcher writes the literal bytes; OBJCOPY -O binary --only-section=.text strips relocs, exposing the patched bytes.

**Why the workaround:** with the new symbol, IDO emits the lui+addiu pair against the offset symbol (HI16/LO16 = 0/0 in-instruction with relocs), then INSN_PATCH overwrites with the literal `0x271801C0` post-cc. Note: USO segments extract via `$(OBJCOPY) -O binary --only-section=.text` from the .c.o (pre-link), so .o relocs are NOT applied to the extracted bytes. Without INSN_PATCH, extracted .text would have imm=0 even though linked .text would have imm=0x1C0.

**Why other obvious approaches don't work:**
- `(char*)0x1C0 + runtime` — IDO emits no lui at all (0x1C0 fits in 16 bits as addiu imm), wrong shape.
- `extern char D_000001C0` WITHOUT INSN_PATCH — link succeeds, but extracted .text bytes have imm=0 (relocs not applied during OBJCOPY).
- Just adding INSN_PATCH on top of `&D + 0x1C0` C — my emit is 4 insns (one too many); INSN_PATCH replaces words but doesn't shorten the function.

**Companion entries:**
- `feedback-ido-offset-in-instruction-vs-reloc` — the load-side analog (offset goes IN-instruction for `lw $reg, OFF($at)`).
- `feedback-ido-d-cse-deep-uses-share-base` — related D-base CSE behavior across multiple uses.

**How to apply:**
- For NM grinds where my emit is exactly 1 insn longer than expected and the diff is around `&D_00000000 + 0xN + runtime`, this is the cause. NM-wrap and document, OR apply the per-offset-extern + INSN_PATCH recipe if landing this function is high-priority.


---

<a id="feedback-ido-v1-base-materialization-via-second-inline-deref"></a>
## Force IDO to materialize `&D` in `$v1` (lui+addiu pair) by combining named-local-for-first-deref with inline-second-deref of same offset

_When target asm shows `lui $v1, hi(D); addiu $v1, $v1, 0; lw $v0, OFF($v1); ...; lw $a0, OFF($v1)` — i.e. shared base-register `$v1` reused across two loads of D[OFF] separated by intervening insns/calls — the C shape that produces this is: assign the FIRST deref to a named local (forces $v0 for the loaded value), then INLINE the SECOND deref inside a function-argument expression (forces base reuse rather than re-luiing). Combines `feedback-ido-v0-reuse-via-locals` and `feedback-ido-offset-in-instruction-vs-reloc` patterns._

**Recipe (gl_func_00006E78, 1080 Snowboarding, 2026-05-08, 26-insn exact match):**
```c
int *p;
p = *(int**)((char*)&D_00000000 + 0x138);   // first deref → named local p (gets $v0)
p[0xB4/4] = 0;                              // store via $v0
gl_func_00000000(*(int*)((char*)&D_00000000 + 0x138), 0);  // second deref INLINE inside arg
```

Produces:
```
lui   $v1, 0
addiu $v1, $v1, 0           ; $v1 = &D_00000000 (materialized base)
lw    $v0, 0x138($v1)        ; $v0 = D[0x138] (named local 'p')
move  $a1, $zero
sw    $zero, 0xB4($v0)       ; store via $v0
jal   gl_func_00000000
lw    $a0, 0x138($v1)        ; (delay slot) reload via shared $v1
```

**Why both knobs are needed:**
- Named local `p` alone: IDO would still pick lui+lw (collapsed, offset baked into lw) because `&D` is only visible as a one-shot reference in the assignment.
- Inline second deref alone: IDO would emit a fresh lui+lw for the second access (no base sharing).
- COMBINED: IDO sees `&D + 0x138` referenced TWICE (first via the named-local assignment, second inside the call arg). To efficiently emit both, it materializes `&D` in `$v1` (lui+addiu) and reuses the base for both offset-loads. Named local locks $v0 for the first lw's destination; the second lw goes to $a0 (the call's arg slot) via the same base register.

**Anti-pattern (does NOT work):**
```c
int *p = *(int**)((char*)&D_00000000 + 0x138);
p[0xB4/4] = 0;
gl_func_00000000(p, 0);                     // ← passes p (already loaded), not D[0x138] reload
```
This would emit only ONE load of D[0x138], so no base sharing pattern. The call passes $v0 (= p) directly. Wrong shape if target reloads.

**How to apply:**
- When target asm shows TWO lw instructions of `OFF($base)` with the SAME offset and same base register, separated by a call/store, the source code accesses `D[OFF]` twice. Use the named-local-for-first-deref + inline-second-deref shape.
- The second lw being in a `jal` delay slot is normal — IDO's scheduler hoists the reload there since the call needs $a0 set.

## Lift unconditional loop-counter init OUT of the if-body to claim the branch's delay slot — leaves the result-init before the branch

**Why this matters:** When you have `result = sum;` followed by `if (len) { i = 0; loop; }`, IDO's reorg.c will fill the `beq len, 0` delay slot with the immediately-preceding `or v1, a0, 0` (= result = sum), placing the result-copy AFTER the branch. If target asm shows `or v1, a0, 0` BEFORE the branch and `or v0, 0, 0` (= i = 0) IN the delay slot, the lever is to lift `i = 0` OUT of the if-body so it sits unconditionally before the branch. With both `result = sum` and `i = 0` available as delay-slot candidates, IDO picks the loop counter (semantically free since `i` is unused when `len == 0`) and leaves `result = sum` exactly where target wants it.

**Asm pattern that prompts this rewrite:**
```
or v1, a0, 0       ; result = sum (BEFORE branch)
beq a2, 0, +N      ; if (len == 0)
or v0, 0, 0        ; delay slot: i = 0
or a0, a1, 0       ; bufptr = buf
.loop:
lbu t6, 0(a0)
addiu v0, v0, 1
sltu at, v0, a2
addiu a0, a0, 1
bne  at, 0, .loop
addu v1, v1, t6
```

**Wrong C (cap at 81-90% — produces `beq` first, `or v1` in delay slot):**
```c
int f(int sum, unsigned char *buf, unsigned int len) {
    int result = sum;
    int i;
    if (len != 0) {
        i = 0;            // i declared here but only init'd inside if
        do { result += buf[i]; i++; } while (i < len);
    }
    return result;
}
```

**Right C (matches exact — `or v1` before `beq`, `or v0=0` in delay slot):**
```c
int f(int sum, unsigned char *buf, unsigned int len) {
    int result = sum;
    unsigned int i = 0;   // <-- unconditional init
    if (len != 0) {
        do { result += buf[i]; i++; } while (i < len);
    }
    return result;
}
```

**The mechanism:** IDO's delay-slot filler (reorg.c) scans both the immediately-preceding instruction and unconditional fall-through path candidates. With `i = 0` lifted to before the branch, both `or v1, a0, 0` (preceding) and `or v0, 0, 0` (also preceding now, since both inits are unconditional) are candidates. Reorg picks `or v0` for the slot — likely because moving `or v0` is cheaper (it's a constant-source, no register-dependency on `a0` being preserved across the branch). The result is `or v1` stays put and `or v0` enters the delay slot.

**When this lever applies:** any `result = X; if (cond) { i = 0; loop; }` pattern where target shows the result-init BEFORE the branch but built emits it IN the delay slot. The fix is mechanical: move ALL inits that survive both branches OUT of the conditional, declaring them unconditionally at the function's top.

**When it doesn't apply:** if `i = 0` semantically MUST be inside the if (e.g., `i` reads a different value when `len == 0`), or if the unconditional init introduces extra clean-up insns elsewhere, this rewrite won't work.

**Generalizes the prior "no C-level lever" cap-confirmation pattern.** Many NM-wrap caps from earlier 1080 work labeled "delay slot scheduler put X first, can't force Y" can potentially be broken by moving the second-candidate's init out of its guard scope. Check before declaring a function "cap-confirmed" — try lifting one init.

**Counter-case (2026-05-08): the lever REGRESSES heavily on functions that don't fit the pattern.** Tested on `game_uso_func_0000F49C` (90.40% NM-wrap, 30-insn state-init): tried lifting `int *sub = a0->0xB4;` out of an if-block. Result: regressed from 90.40% to 74.53% (-15.87pp). IDO -O2 promoted `sub` to a longer-lived value and shifted register allocations across the dispatch — the lifted load wasn't placed in the delay slot the lever predicted; it was hoisted and held in a register, causing other shuffles.

**Diagnostic for whether the lever applies:**
- Loop-counter / accumulator shape where the second-candidate init (`i = 0`) is naturally USE-ONCE and can be a free delay-slot fill. → Try the lever.
- Dispatch / state-init shape where the lifted local has multiple uses POST-conditional (e.g., `sub[0xA18] = 1` then `gl_func(...)` later). → DON'T lift; the local will get $s-promoted and regress codegen.

In short: the lever works when the lifted-init's value is consumed in a delay slot and never again; it backfires when the lifted-init's value lives across a call.

## Dead `extern` declarations (uncalled, only-referenced-in-comments) CAN shift IDO -O2 register allocation

**Why this matters:** A truly-uncalled `extern void func();` at file scope contributes a symbol to IDO's translation-unit symbol table even when no C statement references it. Removing such a dead decl can shift register allocation in nearby functions enough to bump fuzzy%, even though the function being graded never had a reference to the dead symbol.

**Diagnostic signal:** A function's NM-wrap has been stable at the same fuzzy% across multiple iterations, AND the source file contains `extern` declarations whose only references are in `/* ... */` comments (e.g., a removed stub call's leftover decl).

**Verified case (2026-05-08):** `game_uso_func_00001DDC` (1528-byte spine function, NM-wrap at 17.16%). Source had `extern void *gl_func_TODO_00001DDC(int *scratch, int *a2);` left over from a 2026-05-07 stub-call removal. The decl was not referenced by any C statement (only in comments). Removing the line bumped fuzzy% to 17.52% (+0.36pp = ~5 insns shifted). The function being graded does NOT call `gl_func_TODO_00001DDC`; the change was via IDO's global register allocator's symbol-table accounting.

**Why IDO behaves this way (speculation, unverified):** IDO -O2's register allocator reads the full TU symbol table at compile time. Dead externs contribute to allocno enumeration ordering or cost computation. Removing them shifts the global register-priority calculation enough to nudge a few `lw`/`sw` allocations onto different `$t`/`$s` registers. The effect is small (sub-1pp) but real.

**How to apply:**
1. After a stub-call removal, ALWAYS audit and remove the corresponding `extern` decl too.
2. Before grinding fine-grained register-allocation knobs on a stuck NM-wrap, grep the source file for `extern` decls that are referenced only in comments — remove them as a free baseline-improvement.
3. Don't expect dramatic gains (this is sub-1pp); use it as a "free pre-grind cleanup" not a primary lever.

**Doesn't apply when:** the extern is referenced by ANY active C code (even if the call site is in a different function within the same file). It only nudges codegen when the symbol is genuinely dead in the TU.


---

<a id="feedback-ido-o0-accessor-template-extra-b1-nop-tail"></a>
## Standard accessor templates at -O0 produce 3 extra insns (`b +1; nop` dead tail jump) vs the -O2 form

_When you see what LOOKS like the standard Quad4/Vec3/int/float-reader template (`Quad4 buf; gl_func_0(&D, &buf, N); *dst = buf;`) in asm but the function has 3 EXTRA insns (`b +1; nop` between the last copy-store and the epilogue), the function is compiled at -O0, not -O2. The same C body matches at both opt levels — pick the right OPT_FLAGS for the file._

**Symptom (verified 2026-05-08, gl_func_00008990 in game_libs_o0_8944.c):**

Asm has standard Quad4-reader shape:
```
addiu sp, -0x28; sw ra; sw a0, 0x28(sp)
lui+addiu a0, &D; addiu a1, sp, 0x18; li a2, 0x10
jal gl_func_0; nop                       ; (jal+nop instead of jal+li)
lw t6, 0x28(sp); addiu t7, sp, 0x18
[4 lw/sw pairs copying 16 bytes]
b +1; nop                                ; ← these 3 extra insns
lw ra; addiu sp; jr ra; nop
```

vs the -O2 form (gl_func_0000975C):
```
addiu sp, -0x28; sw a0, 0x28(sp); sw ra
lui+addiu a0, &D; addiu a1, sp, 0x18; jal; li a2, 0x10  ; jal+li in delay
addiu t7, sp, 0x18; [4 lw/sw pairs interleaved with t6 reload]
lw ra; addiu sp; jr ra; nop                 ; no b +1; nop tail
```

**Identifying -O0 vs -O2 placement in the .o:**

Check the symbol's expected/.o location:
```bash
for u in expected/src/SEG/*.c.o; do
    sym=$(mips-linux-gnu-objdump -t "$u" 2>/dev/null | grep "FUNC_NAME ")
    [ -n "$sym" ] && echo "=== $u ===" && echo "$sym"
done
```

If `expected/.../SEG_o0_NNNN.c.o` is the host (not just `SEG.c.o`), the function is in an -O0 file.

**Recipe:**

1. Identify whether the function is in an -O0 file via `objdump -t` on expected/.o.
2. Write the standard accessor template body unchanged.
3. Place the void func in the SAME -O0 file (the file's Makefile rule has `OPT_FLAGS := -O0`, so building the new void body uses -O0 automatically).
4. The `b +1; nop` tail emerges from -O0's conservative scheduling — DON'T try to add manual `__asm__` to inject it; it's a natural artifact.

**How to apply:**

- For game_libs accessor templates near offsets 0x8944, 0x949C, etc. (1080's known -O0 cluster files), automatically use -O0 and the standard template.
- For OTHER segments where you see the `b +1; nop` tail in asm, check the Makefile for an existing -O0 file in that segment; if one exists, the function probably belongs there.

**Companion:**
- `feedback-ido-o0-cluster-split-with-layout-shim.md` — file-split workflow when -O0 cluster is needed but doesn't yet exist.
- `feedback-uso-accessor-template-reuse.md` — same templates work across all USOs at -O2.


---

<a id="feedback-ido-arg-type-signedness-shifts-allocno-order"></a>
## Parameter type signedness affects allocno priority — `int` vs `unsigned int` shifts register-allocation order downstream

_When the function signature has `int aN` vs `unsigned int aN`, IDO -O2's allocator assigns DIFFERENT register names to downstream temps even when the inner expression CASTS the value to unsigned (e.g. `(unsigned int)a1 >> 16`). Both produce identical instruction count and shift opcode (srl), but the register-name chain shifts by one position. Use whichever type makes the chain align with target asm's register names — the cast-to-unsigned-inside-the-expression is enough to get the desired srl encoding regardless of the signature type._

**Symptom (verified 2026-05-08, gl_func_00068730 exact match):**

C with `unsigned int a1` parameter:
```c
int gl_func_00068730(int *a0, unsigned int a1) {
    gl_func_00000000(a0, a1);
    int *row = (int*)((char*)a0[0x30/4] + ((a1 >> 16) << 4));
    int *subtable = (int*)row[1];
    return subtable[a1 & 0xFFFF];
}
```
Emits:
```
lw a0, 4(v1)        ← uses a0
andi t0, a1
sll  t1, t0, 2
addu t2, a0, t1
lw   v0, 0(t2)
```

Same code with `int a1` parameter (and explicit cast on the shift):
```c
int gl_func_00068730(int *a0, int a1) {
    gl_func_00000000(a0, a1);
    int *row = (int*)((char*)a0[0x30/4] + (((unsigned int)a1 >> 16) << 4));
    return ((int*)row[1])[a1 & 0xFFFF];
}
```
Emits:
```
lw   t0, 4(v1)        ← uses t0 (NOT a0)
andi t1, a1
sll  t2, t1, 2
addu t3, t0, t2
lw   v0, 0(t3)
```

**Why:** IDO's allocno priority calculation treats `int` and `unsigned int` parameters as distinct pseudo classes even when the dataflow is identical. The post-call lookup chain's allocno-numbering shifts by one when a1's signature type changes, which cascades through every subsequent register assignment.

The shift instruction itself is unaffected — `(unsigned int)a1 >> 16` produces `srl` regardless of a1's declared type, because the cast forces unsigned shift semantics at the expression level.

**How to apply:**

When matching a function with a signed-arg-but-srl-shift idiom, try BOTH `int aN` and `unsigned int aN` for the parameter type. The shift will still be `srl` thanks to the inline cast, but the surrounding register names may flip into alignment with target asm.

**Companion:**
- `feedback-ido-narrow-arg-promotion.md` — `short`/`u8` arg signatures changing emit shape (different mechanism, same flavor of "param type matters more than you'd expect").
- `feedback-ido-v0-reuse-via-locals.md` — named locals shifting register picks toward $v0.

## Anti-lever: untyped-path re-fetch via named local does NOT defeat IDO -O2 struct-field CSE — it regresses regalloc

**Why this matters:** When target asm has TWO `lw OFFSET(base)` loads of the same struct field into DIFFERENT scratch registers (e.g., dlp loaded twice as $v1 and $t7), and your struct-typed C body emits ONE load (CSE'd by IDO), the natural lever is to introduce a second access via an untyped path: `T *p2 = *(T**)((char*)X + N); use(p2);`. **This regresses fuzzy% in practice.**

**Tested twice (both regressed):**
- `gui_uso_func_00003B14` (2026-05-08, gui_uso DL builder): 98.89% → 96.11% (-2.78pp).
- `gl_func_00010068` (2026-05-08, game_uso 6-call dispatcher): 79.13% → 74.17% (-5.0pp).

**Why it fails:** Adding a named-local pointer (`T *p2 = ...`) promotes the local to $s through IDO's global allocator. The expected 2-emit `lw` pattern doesn't materialize because IDO sees two distinct access paths but allocates one as $s (longer live range), shifting other regalloc decisions across the entire function body. Net: worse than the original CSE'd version.

**What does work for "force re-load" patterns (per other entries):** Don't introduce a new named local. Either:
- Inline the second access at the use site without a binding (`((T*)*(int*)((char*)X + N))->field`).
- Use `volatile` qualifier on the source pointer (forces re-load semantically, but changes types).
- Permuter run — let it find a non-obvious ordering that triggers the 2-emit.

**Don't try the named-local lever again. The CSE behavior is fundamental to IDO -O2's allocator and the obvious workaround is wrong.**

---

<a id="feedback-ido-arg-alias-doubles-s-reg-when-used-across-calls"></a>
## Drop the `int *s2 = a0;` alias when `a0` is deeply used across calls — alias forces IDO to allocate TWO distinct $s regs

_When the function body uses `a0` BOTH as a struct-field-base across multiple jal calls AND as a passed-through arg to inner calls, an explicit `int *s2 = a0;` C-level alias makes IDO allocate one $s register for the named alias AND a second $s for `a0`'s preserved value. Result: +1 spill save, +2 setup insns (`sw $sN, OFF(sp)` + `or $sN, a0, $0` for the second copy), and a trailing reload from the wrong-name register near the loop end._

**Symptom:** target spills 4 saved regs (`s0, s1, s2, ra`); built spills 5 (`s0, s1, s2, s3, ra`) with an extra `or s3, a0, $0` after the s2-alias setup. The post-loop reload at the bnel-likely's neighbor uses `s3` not `s2`.

**Why it happens:** IDO's global allocator sees two distinct allocnos — one for the C-named alias `s2` and one for the function arg `a0` — and assigns different hardware registers because:
- The alias is live across all calls (used inline in the loop body).
- `a0` is also live across all calls (because it's passed unchanged into the inner jal — it's NOT just dataflow-equivalent to the alias; it has its own use point).
- IDO does NOT prove these are the same value at register-allocation time (despite RTL would-canonicalize at higher opt levels in modern compilers).

**Counter-example for the older "alias DCE" claim:** `feedback-ido-3save-vs-2save-arg-preserve` (line ~220 of this doc) says `int *p = a0;` is DCE'd at -O2. That claim is true ONLY when the alias is used at a single site (or its uses can be merged with a's natural uses). Once both names are referenced across multiple call sites in different argument positions, IDO keeps both as separate pseudos.

**Recipe:** drop the alias and use `a0` directly throughout the function body:

```c
// BAD — IDO allocates s2 (alias) AND s3 (a0) — 5 saved regs total
void f(int *a0, int a1) {
    int *s2 = a0;
    s2[X] = call(...);
    while (...) {
        call(s2[Y], s2);   // s2 used both as base AND as arg
    }
}

// GOOD — IDO allocates only s2 (= a0) — 4 saved regs total
void f(int *a0, int a1) {
    a0[X] = call(...);
    while (...) {
        call(a0[Y], a0);   // a0 used both as base AND as arg
    }
}
```

**How to apply:** when the target shows `sw sN, OFF(sp)` count = M but your built shows M+1 saves, AND you have `int *s2 = a0;` (or similar arg-rename alias) at function start, AND the body uses both the alias name and references arg-base structures via its fields, drop the alias. The fix is one rename, no logic change.

**Verified 2026-05-08** on `gl_func_00068524` (game_libs alloc-and-init constructor): 88.72% → 100% via this + the loop entry-test type fix (`if (count != 0) { do {...} while ((u32)i < (u32)count); }` instead of `for (i=0; i<count; ...)` — see `feedback-ido-...` for unsigned-loop pattern).

---

<a id="feedback-ido-file-context-affects-frame-size"></a>
## Identical C body in different .c files can emit DIFFERENT frame sizes — file-context affects IDO's spill-slot allocator

_Three siblings of an alloc-and-link constructor family share IDENTICAL C source (same volatile-ptr-to-arg lever, same control flow, same cross-call shape). One matches at 100 %; the other two land at ~89 % with an 8-byte-smaller frame (0x20 vs target's 0x28). Same OPT_FLAGS, same compiler, same body — only the surrounding .c file differs._

**Symptom (2026-05-08, three-function family):**

| Function | File | Body | Result |
|----------|------|------|--------|
| `eddproc_uso_func_000003BC` | `src/eddproc_uso/eddproc_uso.c` | volatile-ptr lever | **100 %** (frame 0x28) |
| `arcproc_uso_func_00002334` | `src/arcproc_uso/arcproc_uso_tail1.c` | volatile-ptr lever | **89.08 %** (frame 0x20) |
| `mgrproc_uso_func_00003358` | `src/mgrproc_uso/mgrproc_uso.c` | volatile-ptr lever | **89.08 %** (frame 0x20) |

The C body in all three is character-for-character identical (or comparable to within trivial whitespace):

```c
void *func(int *arg0) {
    int *p, *head;
    volatile int **p_arg0 = (volatile int**)&arg0;
    p = (int*)gl_func_00000000(0x40);
    if (p != 0) {
        gl_func_00000000(p);
        *(int*)((char*)p + 0x28) = (int)&D_00000000;
        *(int*)((char*)p + 0x3C) = 0;
    }
    head = (int*)((int*)*p_arg0)[0x10];
    if (head != 0) { /* link */ }
    return p;
}
```

eddproc emits frame 0x28; arcproc and mgrproc emit frame 0x20. Frame-size mismatch cascades into ~9-instruction byte-level diff (spill/reload offsets shifted 4 bytes lower).

**Why it likely happens:** IDO's allocator uses pseudo-numbering and live-range analysis that depend on the global pseudo state in the compilation unit. When other functions in the same .c file declare locals that perturb the allocator's tiebreakers (e.g., shared-pseudo numbering, weight-priority ties), the same C body's allocation outcomes shift.

eddproc_uso.c is a small file (handful of functions); arcproc_uso_tail1.c and mgrproc_uso.c are large multi-function files with many other functions (some with PROLOGUE_STEALS / INSN_PATCH / SUFFIX_BYTES post-cc patches applied). The hypothesis: more sibling functions = more pseudos in the global allocator = different ordering = different allocation.

**What does NOT close the gap:**
- Adding `int pad;` or `int pad[2];` (frame grows by 8 bytes total, not just shifts the spill area)
- `volatile int slot18_pad;` (same; volatile occupies a slot that grows the frame)
- Reordering local declarations
- The volatile-ptr-to-arg lever IS already applied (without it the gap is wider)

**Diagnostic:** when target shape includes a sibling matched in a DIFFERENT .c file at 100 %, copy that exact C body verbatim into the current file. If you still cap at the 8-byte frame diff, this is the file-context cap. NM-wrap and document; further C-level grinding won't close it.

**Workaround (untested but plausible):** move the function to a smaller, lower-pseudo-pressure .c file, the way fragment-merge moves work cross-file. Doable via per-`.o` linker-script slot juggling but expensive (per `feedback-cross-file-fragment-unblock-via-move-then-merge`) — probably only worth it for hot functions.

---

<a id="feedback-ido-arg-addr-via-volatile-ptr-forces-caller-spill"></a>
## Force caller-slot spill of a USED arg via `volatile T *p = &argN;`

_When target has a leading `sw aN, frame_size+offsetN(sp)` writing an arg into ITS caller-slot for an arg that's actively USED in the body — so the unused-arg-save pattern (`feedback-ido-unused-arg-save`) doesn't apply — declare `volatile T *p = &argN;` (or `volatile T *const p = &argN;`) at the top of the function. IDO -O2 must materialize argN to its caller-slot at sp+frame_size+offsetN, since the address escapes through a volatile-qualified pointer and DCE can't prove the spill is dead._

**Why it works:** plain `int *p = &a1;` followed by an unused `p` is DCE'd by IDO -O2 — the address-take is elided and no spill happens. With `volatile`, IDO conservatively assumes the pointer's value may be observed externally (volatile acts as an opaque barrier in IDO's optimizer), so the address-take must be honored, which forces the spill of argN to its addressable home (the caller-slot at sp+frame_size+offsetN).

**The required boilerplate:**
```c
void *func(int *a0, int a1) {
    volatile int *p = &a1;   /* forces sw a1, 0x14(sp) — the caller-slot spill */
    /* ... function body uses a1 normally ... */
    (void)p;                  /* suppress unused-warning; p is otherwise unread */
    return ...;
}
```

The `volatile` qualifier is on the POINTEE type, not on `p`. The cast tells IDO "the value at *p may be observed by external code" — but since p itself is never written through, the only effect is that &a1 must produce a real address.

**When the target shape this fixes appears:**
- A leading `sw aN, frame_size+offsetN(sp)` (caller's slot for argN) where:
  - frame_size is the function's own stack adjust
  - offsetN = 4*N (a0=0, a1=4, a2=8, a3=0xC)
- The arg IS used in the body (so `feedback-ido-unused-arg-save` doesn't apply)
- No other obvious reason for the spill (no varargs, no struct-by-value)

**Verified 2026-05-08** on `gl_func_0003EA98` (linked-list lookup-by-key, 18 insns):
- target: `sw a1, 0x14(sp)` at offset 0x04 (frame=0x10, a1's caller-slot at sp+0x14)
- before: built had no equivalent emit; wrap capped at 82.89% fuzzy
- after: `volatile int *p = &a1;` produces the exact `sw a1, 0x14(sp)`; promoted to 100%

**Compatible with:** the volatile-local trick for spilling values onto the OWN-FRAME stack (`volatile int key = a1;` inside scope) — both can coexist in the same function. The volatile-pointer-to-arg controls the CALLER-SLOT spill; the volatile-local controls the OWN-FRAME spill.

**Sub-rule — declaration order vs other locals:** when the function has another stack-resident local (e.g. `int tmp;` taken by address as `&tmp`), the volatile-pointer's *implicit* stack slot competes with that local's slot. IDO assigns the EARLIER-DECLARED local the HIGHER stack offset. Get the order wrong and the `addiu rN, sp, OFFSET` for `&local` mismatches by 4 bytes. Verified 2026-05-08 on `mgrproc_uso_func_000032F8`: with `volatile char **p = &dst; int tmp;` produced `addiu a0, sp, 24` (tmp at sp+0x18); with `int tmp; volatile char **p = &dst;` produced `addiu a0, sp, 28` (tmp at sp+0x1C, matching target). Rule of thumb: declare the addressed-local FIRST, then the volatile-pointer.

**Anti-pattern — volatile-arg can't reach frame=0x20 via volatile-int-spill alone.** When target has BOTH `sw aN, 0x20(sp)` (caller-slot at frame=0x20) AND `sw vM, 0x18(sp)` (mid-function spill at sp+0x18), and the function has no other locals, the natural attempt is `volatile int *vparg = &aN; volatile int spill;` to grow frame for both reservations. This fails: the volatile-int-spill grows frame too aggressively (commonly 0x28 or 0x30 instead of 0x20), and re-ordering the two declarations doesn't get the spill to land at sp+0x18. Verified 2026-05-08 on `gl_func_000688F8` (3 ordering variants tested, all overshoot or land spill at sp+0x1C). The volatile-arg recipe requires frame to grow via NON-volatile locals (e.g. an addressed `int tmp;`, a typed-struct stack local) — the volatile-int-spill is too coarse a frame-growth lever to coexist with it.

**Multi-arg variant (composes cleanly):** when target spills MULTIPLE args to their caller slots (`sw a0, frame_size+0(sp); sw a1, frame_size+4(sp); ...`), apply the recipe once per arg with distinct local pointer names. They compose without interference — both vp0/vp1 are DCE'd as locals; only the &arg-take effects survive, so frame stays minimum:
```c
void func(int *a0, int a1) {
    volatile int **vp0 = (volatile int **)&a0;   /* sw a0, frame_size+0 */
    volatile int  *vp1 = (volatile int  *)&a1;   /* sw a1, frame_size+4 */
    /* body uses a0/a1 normally; reloads happen via lw rN, frame_size+offset(sp) */
    (void)vp0; (void)vp1;
}
```
Verified 2026-05-08 on `gl_func_00028FCC` (13-insn 1-call function): both `sw a0, 0x18(sp)` and `sw a1, 0x1C(sp)` produced from natural C body once both volatile-pointer-decls are in place. Frame stays at 0x18 (minimum for ra-save).

**Don't use this** when the target's spill is at a DIFFERENT offset than the arg's natural caller-slot — that means a different mechanism is producing it (e.g., `feedback-ido-precall-arg-spill-unreachable` for outgoing-arg defensive spills). This recipe specifically generates "the arg's own caller-slot."

**Inverse non-recipe (does NOT work):** the symmetric form `volatile T *p = (volatile T *)alloc()` to spill a *return value* through a stack slot is NOT equivalent. In the arg-recipe, `&argN` is a stable lvalue that must be honored; in the return-value form, `(volatile T*)alloc()` casts a non-lvalue v0 to a volatile-pointer-typed local — the local pointer itself isn't volatile, only the pointee. IDO sees `p = (read v0); deref-of-p` as plain pointer reuse, optimizes the local away, and emits no spill. Verified 2026-05-08 on `gl_func_000688F8`: tried `volatile int *spill = (volatile int*)alloc(0x20); p = (int*)spill;` to force `sw v0, 0x18(sp); lw a1, 0x18(sp)` — produced 24-insn frame-0x18 with no spill (0pp). To force a return-value spill you need a stack-resident `volatile T slot;` lvalue and then `slot = alloc(...); p = slot;` — but the address-take grows frame past the typical target (per the existing `*(volatile int*)&q_alloc = q_alloc` case at frame 0x28).

---

<a id="feedback-ido-volatile-local-scoped-to-if-block-flips-early-exit-shape"></a>
## Place `volatile int local = arg;` INSIDE the if-non-zero block to flip early-exit from `bnel-likely+delay-load` to `beqz+nop`

_Common shape: the function does an early-exit `if (cond) return X;`, then a do-while loop reading some stack-spilled local. When the volatile spill of the loop-local is declared at FUNCTION TOP (before the early-exit), IDO -O2's scheduler hoists the first-iter `lw local, OFFSET(sp)` into the early-exit branch's delay slot, emitting `bnel cond, $0, +N` (branch-likely with delay-load) instead of the target's `beqz cond, +N; nop`. Scoping the volatile decl INSIDE the if-non-zero block pushes the spill AFTER the branch, removing IDO's hoist opportunity and producing the target shape._

**The pattern:**
```c
/* GOOD — volatile decl is scoped INSIDE the if-non-zero block.
 * IDO can't hoist the spill or its reload into the branch delay. */
void *f(struct *list_owner, int key) {
    volatile int *p = &key;            /* caller-slot spill (separate trick) */
    int *node = list_owner->head;
    if (node != 0) {
        volatile int kspill = key;     /* OWN-FRAME spill — scoped HERE */
        do {
            if (node->key == kspill) return node;
            node = node->next;
        } while (node != 0);
    }
    (void)p;
    return 0;
}

/* BAD — volatile decl at function top.
 * IDO hoists the first-iter `lw t6, kspill_offset(sp)` into the
 * `if (node != 0)` branch's delay slot, emitting bnel-likely. */
void *f_bad(struct *list_owner, int key) {
    volatile int kspill = key;          /* spill happens before branch — hoistable */
    int *node = list_owner->head;
    if (node != 0) {
        do { ... } while (node != 0);
    }
    return 0;
}
```

**Why this matters:** for early-exit + loop patterns, IDO's `reorg.c` looks at the instruction immediately after the branch (in the fall-through path) and tries to fill the delay slot with it as a likely-delay candidate. If that instruction is `lw` from a stack slot that was just-spilled, it's a perfect candidate — IDO converts the branch to branch-likely + uses the lw as the delay slot. The result mismatches target.

**Diagnostic:** target shows `beqz/bnez Reg, +N; nop` (regular branch with explicit nop), built shows `bnel/beql Reg, $0, +N; lw/something(delay-likely)` for the same control transfer. The instruction count is the same; only the branch type and delay-slot occupancy differ.

**Verified 2026-05-08** on `gl_func_0003EA98` (same function as the volatile-pointer-to-arg trick): scoping `volatile int key = a1;` to the if-block flipped the early-exit from bnel-likely to beqz+nop, contributing to the 82.89% → 100% promotion.

**Generalizes to:** any do-while/while loop with an early-exit guard that reads an own-frame spill on the first iteration. The fix is purely scope-based — no logic change needed.

---

<a id="feedback-ido-extern-char-vs-extern-fn-folds-lo-offset"></a>
## `extern char SYM;` (data-decl) folds a `+const` offset into the `%lo` immediate; `extern T SYM(void);` (function-decl) forces a separate `%hi+%lo` pair

_When target asm has `lui at, %hi(SYM); sw vN, 0xK(at)` (single lui + sw with the constant offset folded into the store immediate, single reloc pair), the C source's `extern` declaration of SYM matters: data-decls fold, function-decls don't._

**Symptom:** target stores via `*(int*)(&SYM + 0xK) = val` should produce one `lui at` + one `sw vN, 0xK(at)` (12 insns total in a typical leaf wrapper). With `extern T SYM(void);` (function-decl), IDO emits a SEPARATE `lui+addiu` pair to materialize `&SYM` in a register, THEN computes `+0xK` via a separate `addiu+sw`, expanding the function from 12 → 13-14 insns. With `extern char SYM;` (data-decl), the constant offset is folded into the `%lo` immediate of the sw, producing the compact form that matches target.

**The fix:**
```c
/* WRONG — produces 13-14 insns, separate %hi+%lo for &SYM, +0xK in addiu */
extern int SYM(void);
*(int*)((char*)&SYM + 0xK) = val;

/* RIGHT — produces 12 insns, %lo(SYM+0xK) folded into sw immediate */
extern char SYM;
*(int*)(&SYM + 0xK) = val;
```

**Why it works:** IDO treats function symbols as "needing absolute address materialization" — the address-take of a function forces a real register-resident pointer (since calling indirectly through it would need it). Data symbols can be referenced relative to the symbol with arbitrary `%lo` immediates, so `&char_SYM + 0xK` becomes a single reloc pair `R_MIPS_HI16 SYM` + `R_MIPS_LO16 SYM` with imm=0xK on the sw.

**Verified 2026-05-08** on `func_0000E9FC` (12-insn bootup_uso wrapper): the existing wrap had `extern int func_00000008(void); *(int*)((char*)&func_00000008 + 0x20) = ...` and the doc-comment claimed this was unreproducible (13-insn growth). Switching to `extern char func_00000008; *(int*)(&func_00000008 + 0x20) = ...` produced the splat-folded compact form, dropping the diff count from 3 to 2 (cap class NM-86 → NM-83). Remaining diff is the unrelated prologue lui/sw scheduling swap.

<a id="feedback-ido-volatile-const-bind-catastrophic-regression"></a>
## Don't wrap a single constant store as `volatile int target = K; *p = target;` to defeat hoist — catastrophic regression

_When IDO hoists a constant load (e.g., `addiu t1, $0, 0x2D0`) above the body branch where target keeps it inside, the obvious lever is to bind the constant via `volatile int target = K;` so the spill/reload prevents hoisting. **Don't.** The volatile spill+reload adds ≥3 insns AND shifts $s register allocation across every variable whose live range crosses the volatile, often catastrophically (verified 2026-05-08 on `h2hproc_uso_func_00001204`: 90.86% → 35.63%, -55pp)._

The issue isn't just the 3 added insns — it's that volatile-spill creates a stack-resident value with a long live range, which bumps every other allocno's priority calculation in IDO's allocator (`docs/gcc-2.7.2/global.c` priority formula). Re-allocations cascade across the whole function.

**Cheaper alternatives for hoist defeat (in order of disruption):**
1. Reorder the C statements so the constant assignment is in a different basic block from the branch's live values.
2. Use `__asm__("")` if IDO accepts it (often does in -O2 mode) as a scheduling barrier.
3. Use INSN_PATCH to reshape the bytes post-cc.

**When `volatile int local = K;` IS appropriate:** for stack-resident loop counters where target shows per-iter `lw/addiu/sw` from a fixed sp+N slot (`feedback-ido-volatile-loop-counter-for-stack-iter`). The volatile is the POINT in that case — you want the spill+reload behavior. Distinct from this anti-pattern where you only want hoist defeat.

**Mirror anti-pattern — REMOVING a local to shrink frame size (verified 2026-05-08 on `titproc_uso_func_00000C54`):** the inverse lever — dropping a working `int count;` local to free its 8-byte slot and shrink frame from 0x48 to 0x40 to match target — also cascades catastrophically. Removed `int count;` and inlined the volatile read into the if-body: frame DID shrink to 0x40 (matches target), but fuzzy regressed 89.32% → 5.02% (-84pp). Freeing the slot caused IDO to reshuffle $s-reg assignments across the whole function (~208 insn diffs from the original ~24). Same root cause as the additive case: any change to a long-lived stack-resident value shifts every other allocno's priority. **General rule for late-tier (>80% fuzzy) matching:** don't add or remove $s-resident locals to fix frame-size deltas; use INSN_PATCH or pad-array-of-correct-size (`feedback-ido-buf-array-alignment`) instead — both keep $s allocation stable.

**When this matters:** USO functions where the original ROM stores into a fixed offset relative to another in-segment symbol (e.g., a "function table" or "metadata block" that lives just past the function's own code). The splat-folded reloc form is the "natural" emit for the symbol+const-offset pattern; getting it requires the data-decl form even when the named symbol is logically a function.

---

<a id="feedback-ido-void-cast-arg-spill"></a>
## `(void)a; (void)b; (void)c;` after the call forces IDO to spill ALL incoming args to caller's outgoing-arg-shadow

_For a forwarder shape where the called function takes ONE arg (a single computed pointer/symbol-offset) but the function still needs to spill its own incoming `$a0/$a1/$a2` to the caller's outgoing-arg-shadow (sp+0x18 / 0x1C / 0x20 in a -0x18 frame), `(void)a; (void)b; (void)c;` after the call is the smallest C lever that makes IDO -O2 emit those stores. It does NOT register-shift them as call args, and it does NOT add register copies — just the three stores in the natural order._

**Origin:** 2026-05-08, `gl_func_0004D224` (game_libs USO). Target asm:

```
27BDFFE8  addiu $sp, $sp, -0x18
AFA40018  sw    $a0, 0x18($sp)   ; spill incoming $a0 to caller's arg0 slot
AFBF0014  sw    $ra, 0x14($sp)
3C040002  lui   $a0, 0x0002      ; HI=0x2 (reloc HI16, &D + 0x201D8)
AFA5001C  sw    $a1, 0x1C($sp)   ; spill incoming $a1 to caller's arg1 slot
AFA60020  sw    $a2, 0x20($sp)   ; spill incoming $a2 to caller's arg2 slot
0C000000  jal   gl_func_00000000
248401D8  addiu $a0, $a0, 0x01D8 ; LO=0x1D8 (reloc LO16)
8FBF0014  lw    $ra, 0x14($sp)
27BD0018  addiu $sp, $sp, 0x18
03E00008  jr    $ra
00000000   nop
```

The natural-shape attempts each fail differently:

1. `f(a,b,c) { callee(&D, a, b, c); }` — IDO marshals as 4-arg call: `or $a3,$a2,$0; or $a2,$a1,$0; or $a1,$a0,$0; lui $a0`. No stack spill. Diff: 4 wrong moves vs 3 wrong stores in expected.
2. `f(a,b,c) { callee(&D); }` — args a/b/c are dead, IDO drops the spills. Diff: 3 missing stores.
3. `f(int a, ...) { callee(&D); }` — varargs prologue spills $a1, $a2, $a3 (NOT $a0). Wrong slots.
4. `f(int a, int b, int c, ...) { callee(&D); }` — varargs spills only $a3 from named-arg position 3. Wrong slot count.
5. `(void)a; (void)b; (void)c;` AFTER the call — exact match.

**Why this works:**

`(void)x` is a no-op cast that the C front-end accepts as "x has been read". IDO -O2's emit treats the read as caller-side ABI-observable: the arg must be reachable from the caller's frame for any down-call hypothetically reading it. Because the function ALSO calls `gl_func_00000000` between the prologue and the casts, IDO conservatively spills `$a0/$a1/$a2` to the caller's outgoing-arg-shadow slots BEFORE the call — which is exactly the varargs-prologue layout.

The casts after the call are key. Putting them BEFORE the call collapses to "args dead before call" and IDO drops the spills. The order is:

```c
void gl_func_0004D224(int a, int b, int c) {
    gl_func_00000000((char*)&D_00000000 + 0x201D8);  // call FIRST
    (void)a; (void)b; (void)c;                       // marker AFTER
}
```

**How to apply:**

When NM diff shows TARGET spills 2+ incoming args to the caller's outgoing-arg-shadow (offsets at frame_size, frame_size+4, frame_size+8 — i.e. `0x18, 0x1C, 0x20` for a `-0x18` frame), and the called function takes a different/single arg:

1. Write the call as the natural single-arg shape: `callee(&D + offset)`.
2. After the call, append `(void)a; (void)b; ...` for each incoming arg you want spilled.
3. The spills emit in the order of the casts and at the natural caller-shadow offsets.

**Generalizes:** any forwarder where target preserves incoming arg-regs across a call to a downstream callee with a different arg count. Sister to `feedback_ido_volatile_unused_local_forces_local_slot_spill.md` but for the caller's-shadow slots, and cleaner when you need 2+ spills (one `(void)x` per arg vs one `volatile int saved_x = x` per arg).

**Anti-pattern:** Don't combine with `volatile int` — that lands one in a local slot, conflicting with the caller-shadow target. Use ONE technique consistently.

**Anti-pattern 2:** Don't put the casts BEFORE the call — `(void)a; gl_func_0(&D); (void)b;` won't emit `$b`'s spill before the call either; both must come after. (Verified during the gl_func_0004D224 grind: tried before-call, the spill collapsed.)

**Anti-pattern 3 — SCOPE LIMIT, arg already body-used:** The recipe ONLY works when the arg has NO body-level use (it's truly "unused" except for the conditional preservation across the call). If the arg is read inside the body (e.g. `if (cond) callee(arg[0x20])`), adding `(void)arg;` after widens the arg's live range across the whole function and IDO -O2 promotes it from `$aN` to a `$s-reg`, churning $s-allocation everywhere. Verified 2026-05-17 on `gl_func_0005B68C` (95% → 73% regression — a0 was used inside the if-block as `a0[0x20]`, then trailing `(void)a0` promoted a0 to $s0 cascading the whole function). Recipe scope: forwarder shape where args are passed through OR completely unused, not partial-use shapes.

**Related:** `feedback_ido_volatile_unused_local_forces_local_slot_spill.md` (single-arg local-slot spill via `volatile int saved`). `feedback_ido_unused_arg_save.md` (background on caller-shadow vs local-slot spill).


---

<a id="feedback-ido-preload-field-into-local-forces-load-before-clobber"></a>
## Pre-load arg field into named local to force field-load BEFORE `&D` materialization clobbers the arg-register

_When a wrapper does `func(&D_X, arg->field, ...)` and the target asm shows `lw aN, 0xK(a0)` BEFORE `lui a0, %hi(D_X)`, but the obvious C `func(&D_X, arg->field, 0)` emits the clobber-then-reload-via-spill shape (+1 insn vs target), the fix is to assign the field to a named local FIRST: `int val = arg->field; func(&D_X, val, 0);`. The sequence point forces IDO to evaluate the load before setting up the call args. **2026-05-10 verified on gl_func_00054668: 75.62 % → byte-exact, 4-call wrapper unblocked.** Prior cap doc said "no clear C-level lever to force IDO to evaluate field-load before address materialization" — the lever IS the named local._

**Pattern in the target asm:**

```
sw $a0, 0x18($sp)         ; spill a0 to caller-slot (because it'll be reloaded)
lw $a1, 0xC($a0)          ; ← load arg->field via ORIGINAL a0 (still holds arg ptr)
lui $a0, %hi(D_X)         ; ← THEN clobber a0 with the address materialization
addiu $a0, $a0, %lo(D_X)
jal func
move $a2, $zero           ; (delay slot)
lw $a0, 0x18($sp)          ; reload a0 from spill for subsequent calls
```

The C that produces this:

```c
void wrapper(int *arg) {
    int val = arg->field;          /* ← named local; evaluation point before call */
    func(&D_X, val, 0);
    func((char*)arg + 0x2C, 0);
    func(&D_X);
    func(arg);
}
```

The C that does NOT produce this (and costs +1 insn):

```c
void wrapper(int *arg) {
    func(&D_X, arg->field, 0);     /* IDO clobbers a0 first, then reloads via $t6 to do the field load */
    ...
}
```

**Why it works:** IDO -O2's call-arg evaluator processes args left-to-right when materializing into argument registers. With `arg->field` inline, IDO can choose to materialize the LITERAL constants (`&D_X` for $a0) first, then read the field through a spill-reload of $a0. The named-local form forces the field load BEFORE any arg-register setup begins — at the assignment statement, where IDO must commit `val` to a register or stack slot.

**Diagnostic asm-shape to recognize this cap:**
- Target asm has multiple `func()` calls passing `arg` (the function parameter) as $a0
- ONE of the calls passes `arg->field_K` as a later argument
- That call's prologue has `lw $a1, K($a0)` BEFORE `lui $a0, %hi(D_X)` (loads via original a0)
- Caller-slot spill `sw $a0, frame_size+0x0($sp)` happens at function entry

**When the pre-load form does NOT help:**
- If the field load uses a register that's NOT the soon-to-be-clobbered arg register (e.g., field comes from a different struct, accessed via a different base), no clobber happens — IDO already gets the order right.
- If there's only ONE call (no later reload of arg needed), IDO doesn't spill arg and the order doesn't matter.

**Cross-reference:** `feedback-ido-arg-addr-via-volatile-ptr-forces-caller-spill` (companion recipe — also forces caller-slot use, but for the spill itself, not the load order). `feedback-ido-arg-spill-via-trailing-void-casts` (different evaluation-order recipe for unused args).

---

<a id="feedback-ido-inline-deref-doesnt-transfer-zero-vs-offset"></a>
## Inline-deref CSE-defeat recipe does NOT transfer from zero-deref (`*a1`) to offset-deref (`orig->field_40`) patterns

_When the inline-`*a1`-at-every-site recipe (`feedback-ido-inline-deref-vs-cache-flips-vN-tN`) lands exact-match on a function with `*(int**)a1` zero-deref pattern, the obvious move is to apply it to a sibling function with `orig->field_40` (= offset-deref) shape. **It regresses badly** — IDO emits MORE instructions, not fewer, and the regalloc cascade is unchanged._

**Origin:** 2026-05-08, after `game_libs_func_0004D39C` (DLL-insert with `*a1` zero-deref) landed via the inline form (cached `int *head = *a1` → 17 insns, 3/17 match; inline `*a1` everywhere → 18 insns, 18/18 byte-exact). Tried the same recipe on `gl_func_000088B4`, which is structurally identical (alloc-init + DLL-insert) but the head pointer is at `orig->field_40` (offset 0x40 from `orig`, not zero). Result: cached form 14/36, inline form 3/38 (regressed by 11 matches AND added 2 instructions). Reverted.

**Why the recipes diverge:**

The zero-deref `*a1` reads through register `$a1` directly: `lw $tN, 0($a1)`. Each inline use is a self-contained 1-insn load with $a1 as the base. IDO's CSE elimination is opportunistic — when the value of `*a1` is needed in 4 sites, the cached form makes IDO retain `$tN` across the function (1 reload), the inline form makes IDO emit 4 fresh `lw $tN, 0($a1)` (because $a1 is a parameter, naturally lives in $a1 the whole function). The fresh-load form forces a particular regalloc shape for the EARLIER pseudos, which happens to match target.

The offset-deref `orig->field_40` requires `lw $tN, 0x40($orig)` for the BASE load (to get the head ptr), THEN `lw $tM, OFF($tN)` to access fields. Each inline use becomes 2 insns (re-deref the base + access field) — DOUBLES the load count vs the cached `existing = orig->field_40` form. IDO's regalloc cascades through these extra loads in a way that NO LONGER matches target. The "fresh-load" trick that helped the zero-deref case is the OPPOSITE of helpful here — target's pattern uses the CACHED base ptr (in $tN holding `orig->field_40`), and inline-deref makes that holder live longer than IDO's allocator wants.

**Diagnostic — when the recipe is at risk of NOT transferring:**

1. Inspect the deref offset. If the target's first deref is at offset 0 (zero-deref via `*ptr`), the inline recipe usually transfers across siblings.
2. If the target's first deref is at non-zero offset (`ptr->field_N`, where N > 0 in the originating struct), the cached form is more likely to match — DON'T inline-eliminate the cached local.
3. Asm signal: target's first BASE-load is `lw $tN, OFF($a0)` where OFF != 0 → cached form. Target's first BASE-load is `lw $tN, 0($a0)` → either form may apply, try inline first.

**How to apply (when porting a recipe between siblings):**

Before applying the inline recipe to a new function, check the asm:
- Target uses `lw $tN, 0($a0)` then `lw $tM, OFF($tN)` chain → inline-deref of `*a0` likely works.
- Target uses `lw $tN, OFF($a0)` (single load, base-with-offset) then `lw $tM, OFF2($tN)` → cached form (`existing = arg->field`) likely required. Inline-deref will regress.

**Sibling-port doctrine update:** `feedback-port-matched-sibling-c-before-trusting-frame-regalloc-cap-claim` (in MATCHING_WORKFLOW.md) says "try the matched sibling's C body verbatim before believing a cap claim." This entry is the corollary: **the sibling's C body is conditional on the access pattern being zero-deref vs offset-deref**. Verify by inspecting the target's first base-load offset before porting. If they differ, the port WILL fail in the way described.

**Related:**
- `feedback-ido-inline-deref-vs-cache-flips-vN-tN` (the original recipe, zero-deref case).
- `feedback-ido-inline-deref-v0` (single-use inline-deref for $v0 vs $tN).
- `feedback-port-matched-sibling-c-before-trusting-frame-regalloc-cap-claim` (sibling-port doctrine).


<a id="feedback-ido-o0-return-cond-emits-sltu-xori-not-beq"></a>
## At IDO -O0, `return cond;` emits sltu+xori coercion — `if (cond) return 1; return 0;` emits the canonical beq-conditional shape

_Boolean-coerced single-return forms regress significantly at -O0 vs the explicit if-then-else early-return. Matching code that uses `beq + 1/0 immediates` won't reach via `return *a0 == 0;` because IDO -O0 always emits the boolean-cast sequence (sltu+xori or sltiu+xori) instead of pulling the comparison up into the branch._

**Symptom (verified 2026-05-08, `arcproc_uso_func_0000012C`):** existing 92.86% NM-wrap with `if (*a0 == 0) return 1; return 0;` was tightened to `return *a0 == 0;` hoping a single-return shape would eliminate the trailing dead `b +1; nop`. Instead fuzzy regressed to 77.68% (-15pp). Inspecting the .o:

- **`if (cond) return 1; return 0;`** (target shape) → `lw v0, 0(s0); beq v0, zero, .L1; nop; addiu v0, zero, 1; b .end; nop; .L1: addiu v0, zero, 0; b .end; nop`
- **`return cond;`** → `lw v0, 0(s0); sltu v0, zero, v0; xori v0, v0, 1` (no branch — pure dataflow)

At -O0, IDO doesn't do branch-folding optimization. The single-return form materializes a 0/1 boolean via sltu+xori and writes it to $v0; the explicit-branch form keeps a branch + immediate-load shape. Both produce same observable result, but only the explicit form matches asm that uses beq.

**Why future-you should know this:** the natural cleanup instinct ("rewrite `if (X) return 1; return 0;` as `return X;`") is correct at -O2 but **catastrophically wrong at -O0**. When grinding a -O0 file:

- If target asm has `beq <var>, $zero, .L; ...; addiu $v0, $zero, 1; b .end; ...; addiu $v0, $zero, 0` — keep the if-then-else early-return shape.
- Don't reach for the boolean-coerced `return cond;` form unless the target shows `sltu/sltiu + xori` directly.

**Distinct from `feedback-ido-o0-load-order-not-expression-driven`:** that entry covers field-load order at -O0; this one is about return-statement shape lowering at -O0. Both reflect IDO -O0's lack of dataflow normalization, but the levers are different.

**How to apply:** when picking a -O0 NM-wrap to grind, BEFORE rewriting any `if/return` chain into a single-return: check whether target asm has `beq` or `sltu` for the comparison. If `beq`, keep the explicit-branch form; if `sltu`, the single-return form may be needed.

---

<a id="feedback-ido-init-locals-after-call-avoids-spill"></a>
## Initialize pointer/end locals AFTER the function call to avoid stack spill across it

_When loop-internal pointers (src, end, dst) only need to live POST-call, declaring them uninitialized at top of function then initializing AFTER the gl_func call keeps them in caller-save $t/$v registers without a stack slot. Initializing them BEFORE the call (the natural C shape) forces IDO to spill across the call since the locals must survive. Verified 2026-05-13 on game_uso_func_0000C12C: 0 % → 81.27 % with this single change._

**The natural-but-suboptimal C:**

```c
void f(int *a0) {
    int buf[16];
    int *src = buf;       /* init BEFORE call — IDO must spill across */
    int *end = buf + 15;
    gl_func(&D, buf, 0x40);
    do {
        *a0++ = *src++; ...
    } while (src != end);
}
```

IDO -O2 sees `src` and `end` are live across the `gl_func` call, so it spills them to local stack slots (frame grows by 8 bytes, plus the spill/reload bytecode at the call site).

**The matching C:**

```c
void f(int *a0) {
    int buf[16];
    int *src;             /* declared, NOT initialized */
    int *end;
    gl_func(&D, buf, 0x40);
    /* init AFTER the call — live range is post-call only */
    src = buf;
    end = buf + 15;
    do {
        *a0++ = *src++; ...
    } while (src != end);
}
```

Now `src` and `end` are only live from their init point onward (no live-range across the call), so IDO uses caller-save $t-regs and emits no spill.

**Why it works:** IDO's liveness analysis sees the assignment-after-call form as creating fresh pseudos whose live ranges start post-call. These pseudos can be allocated to any caller-save register (since the caller-save expectation is the call destroys them). The pre-call init form has the pseudos live FROM declaration THROUGH the call, requiring callee-save ($s) or stack spill.

**When this lever applies:**
- The local's value depends only on stack array addresses (buf, buf + N) or other compile-time values that don't need the call's result.
- The local is dead BEFORE the call (just hasn't been declared yet) and live AFTER.
- The natural C "init at declaration" form lives across the call.

**When it does NOT help:**
- If the local's value depends on the call's return value or output buffer, you can't init it before the call anyway.
- If the local is used both before AND after the call, splitting init points loses the benefit.

**Companion patterns:**
- `feedback-ido-v0-reuse-via-locals` — named locals get $v0/$v1; inline derefs get $t-regs.
- `feedback-ido-brace-block-scope-saves-stack-frame-bytes` — wrap named locals in `{ ... }` to limit lifetime.
- `feedback-ido-arg-addr-via-volatile-ptr-forces-caller-spill` — opposite direction (force caller-slot spill of an arg).

<a id="feedback-ido-double-deref-fills-jal-delay-slot"></a>
## Reference `*ptr` twice in the C source when target loads it twice across a jal — IDO scheduler picks the second load to fill the jal delay slot

**Symptom:** target asm shows two `lw <tN>, 0(a2)` loads of the same pointer dereference: the first early, the second immediately before a jal whose delay slot is the **store** of the second-loaded value to a stack local. Example from `gl_func_0003F2B8`:

```
lw  t6, 0(a2)         # first load of *a2
addiu t7, $0, 1
sw  t7, 0x60(sp)
sw  t6, 0x64(sp)
lw  t8, 0(a2)         # SECOND load of *a2 (could've been kept in t6)
addiu a0, sp, 0x20
jal func
sw  t8, 0x70(sp)      # delay slot: store the second-loaded value
```

**Pitfall:** caching `*a2` in one local (`int t = *a2; b64 = t; b70 = t;`) produces a single-load form with the jal's delay slot filled by something else (or unfilled). The byte sequence diverges.

**Fix:** write two source-level dereferences:

```c
void gl_func_0003F2B8(int *a0, int a1, int *a2) {
    int b18;
    char b20[0x40];
    int b60_0, b60_1, pad6c, b70;
    b60_0 = 1;
    b60_1 = *a2;          // first read
    func_00000000(b20, a1);
    b70 = *a2;            // second read — IDO loads it pre-jal and stores in delay slot
    b18 = 12;
    func_00000000(&b18);
}
```

**Why it works:** IDO's scheduler treats each source-level `*a2` as an independent load. The pre-jal expression `b70 = *a2;` (re-derefs immediately before the call) gets lowered to `lw <reg>, 0(a2); sw <reg>, b70_off(sp)`. The scheduler then moves the `sw` into the jal's delay slot, leaving the `lw` immediately before. A cached local would only get one `lw` and the scheduler can't manufacture a second one.

**Detection signal:** target has TWO loads of the same offset off the same base register, separated by a few unrelated instructions, with the SECOND load's destination feeding a `sw` in the next jal's delay slot. Verified 2026-05-15 on `gl_func_0003F2B8` — landed 100% via duplicate-deref + pass-a1 + a missing `*(int**)&buf[0x50] = a2` data store. (Earlier read of `sw a2, 0x68(sp)` as a "local-slot a2 spill" was wrong — that's a buf[0x50] DATA store of a2 as a pointer field. Whether `sw aN, OFFSET(sp)` is a register spill or data store is determined by the offset's position relative to buf base vs frame size: offsets at `frame + 0..0xC` are caller-slot spills; offsets inside the buf range are data writes.)

<a id="feedback-ido-wrapper-buf-size-drives-frame-size"></a>
## "Caller-slot arg-spill cap" in stack-buf wrapper family is a frame-size cap — `char buf[N]` size drives IDO's frame allocation

**Symptom:** small wrapper that builds a stack buffer and calls one or two helpers with `&buf[0x08]` / `&buf[0]`-style args. Decompiles to ~98–99 % fuzzy with a diff that looks like an "extra arg spill":

```
mine offset 0x08: sw a0, 0x78(sp)       expected: sw a0, 0xB8(sp)
mine offset 0x20: sw a2, 0x80(sp)       expected: sw a2, 0xC0(sp)
mine offset 0x54: addiu sp, sp, 0x78    expected: addiu sp, sp, 0xB8
```

The labels look like "unused-arg-spill cap family" because target spills `a0`/`a2` to caller slots and you spill them too — just at smaller offsets. Easy to misdiagnose as a register-allocation cap.

**Root cause:** target's `sw a0, 0xB8(sp)` writes to OUR sp+0xB8, which equals CALLER's sp+0 (the caller's $a0 slot). The offset 0xB8 = our frame size. Target chose a frame of 0xB8; your `char buf[0x60]` produced a frame of 0x78. Same spill, different offset.

**Fix:** size the buffer so IDO allocates the same frame as target. If target frame is 0xB8 and your current frame is 0x78, grow `buf` by 0x40:

```c
void gl_func_0003F044(int *a0, int a1, float *a2) {
    char buf[0xA0];   // sized to drive frame to -0xB8 (not 0x60 → -0x78)
    *(int*)&buf[0x00] = 0x32;
    *(int*)&buf[0x48] = (int)a2;
    func_00000000(&buf[0x08], a1);
    *(float*)&buf[0x4C] = a2[0];
    /* ... */
    func_00000000(&buf[0x00]);
    (void)a0;
}
```

**Detection signal:** diff is 4–7 mismatches, all of the form "same opcode, offset differs by a constant K" — and K equals (target_frame − built_frame). Compute the delta, grow buf by that amount.

**Why this matters:** before discovering this lever, multiple wrappers in the gl_func_0003Fxxx family were committed as 83–93 % NM wraps with "unused-arg-spill cap" framing (gl_func_0003F2B8, gl_func_0003F350). Verified 2026-05-15 on `gl_func_0003F044`: char buf[0x60] → 99.79 % (5 frame-offset diffs); char buf[0xA0] → 100 % byte-exact.

**Doesn't fully unlock siblings, though.** Retrying `gl_func_0003F2B8` (char buf[0x58] → 0x98) bumped 83.4 → 83.6 % only. Frame now matches target's -0xB8, but a separate cap remains: target's `sw a2, 0x68(sp)` is a LOCAL-slot spill of `a2` (not a caller-slot store). My emit doesn't produce it because the body uses `*a2` only before the call — IDO doesn't see a reason to preserve. Forcing the local spill likely needs a `register int *a2` hint or a body rewrite that commits `a2` to a callee-preserved register. **The buf-size lever fixes ALL frame-offset diffs (caller-slot stores, sp adjustments, epilogue) but does NOT fix local-slot spills.**

**Companion patterns:** `feedback-ido-o2-lowest-spill-slot` (related: IDO picks lowest spill slot when frame has unused space). The "grow buf" lever is a different angle on the same allocation behavior.

<a id="feedback-ido-pass-unused-arg-to-suppress-caller-slot-spill"></a>
## Suppress the "unused-arg caller-slot spill" by passing the unused arg to one of the func calls (even when the call doesn't visibly need it)

**Symptom:** small wrapper with K&R-style arg signature (`f(a0, a1, a2, a3)`) where some args are "unused" (not referenced in the body). Target asm spills only the FIRST arg (`sw a0, frame(sp)`) to its caller slot; your emit spills MORE (e.g. `sw a1, frame+4(sp)` too). Diff is +1 insn, "extra unused-arg spill."

```
mine offset 0x10: sw a1, 0xBC(sp)   <-- extra
target offset 0x10: sw a2, 0x60(sp) (data write into buf, not spill)
```

The naive C uses `(void)a1;` or just leaves a1 unmentioned — both cause IDO to spill a1 to caller slot.

**Fix:** pass the unused arg as an argument to one of the existing helper calls in the body, even if the called function doesn't conceptually need it:

```c
void gl_func_0003F008(int a0, int a1, int a2, int a3) {
    char buf[0xA0];
    *(int*)&buf[0x48] = a2;
    *(int*)&buf[0x4C] = a3;
    func_00000000(&buf[0x08], a1);   // <-- pass a1 here, even though target asm
                                       //     shows no $a1 setup before this jal
    *(int*)&buf[0x00] = 0x18;
    func_00000000(&buf[0x00]);
}
```

**Why it works:** `$a1` already holds the caller-passed value through the function entry (it's the second arg register; no instruction has clobbered it). When the C source says `func(buf, a1)`, IDO recognizes a1 is USED for the call, suppresses the K&R-style caller-slot spill — AND skips the `or a1, a1, $0` setup insn because $a1 already has the right value. Net effect: target's lean shape, no extra spill, no extra setup.

**When to apply:** the wrapper-family wraps in 1080 that say "extra `sw a1, 0xBC(sp)` (unused a1 arg)" — gl_func_0003F0A4, 0003F0E8, 0003F158, 0003F198, 0003EFC4, 0003EF2C, 0003EF78, and others. Pick the call that's nearest the K&R-spilled-arg's position in the calling convention; whichever call already gets target's $aN-passed-naturally pattern is the one to add the arg to.

**Promoted gl_func_0003F008 from 92.5 % NM → 100 % byte-exact** on 2026-05-15. Likely promotes most of the family.

**Caveat:** only works for args target also keeps in registers (caller passed them, no intermediate clobber). If the arg has been clobbered before the call where you want to pass it, IDO has to reload it — which may add insns elsewhere.


---

<a id="feedback-ido-no-addiu-into-jal-delay-when-store-via-base-precedes"></a>
## IDO -O2 won't put `addiu aN, aN, K` (func-arg setup) into a jal-delay slot when a store via the SAME base precedes the call

_When a function does `*a0_offset_K = v; func(&a0[L], ...);` IDO -O2 emits `sw v, K(a0); addiu a0, a0, L*4; sw a1, off(sp); jal func; sw arg, off(sp) [delay]`. The `addiu a0` is left as a standalone instruction BEFORE the jal, not filled into the delay slot. Target asm sometimes has the addiu in the delay slot (`jal func; addiu a0, a0, L*4 [delay]`), saving one insn — but IDO's scheduler treats the preceding store-via-a0 as a true dependency on the original $a0 value, so it can't sink the addiu past it._

**Symptom:** built has +1 insn vs target on a function with shape "store via base; func(base+K, ...)". Example: gl_func_0003E904 (built 26 vs target 25 insns). All other diffs at the same offset are just downstream insn-shift artifacts.

**C-level levers tested (2026-05-16, gl_func_0003E904):**
- Compute `int *p = a0 + L*4;` as a local before any stores, then `func(p, ...)` — IDO emits the addiu earlier (a0 is now dead) but the delay slot still gets filled with a spill, not the addiu.
- Reorder the store to AFTER the func call — changes semantics (the callee may rely on the store; can't blindly move).
- Use `(char*)a0 + L` vs `&a0[L/4]` — same emit.

**Verdict:** structural cap; no clean C lever. The `addiu` stays as a standalone insn, locking the function at -1 insn over target. INSN_PATCH is blocked by the size delta (it can only overwrite, not insert/delete).

**Workaround:** none currently. If a permuter run finds a fold where the store can be reordered without breaking the callee's contract, it would unlock; otherwise accept the NM cap.

**Related:** `feedback-insn-patch-size-diff-blocked` (POST_CC_RECIPES.md) — same root cause, different surface.

---

<a id="feedback-ido-branch-likely-needs-distinct-test-and-delay-base-regs"></a>
## Annulled `bnel`/`beql` requires test-reg ≠ delay-slot-load base-reg; the enabler is IDO double-reloading a spilled pointer param

_GCC 2.7.2 / IDO reorg fills a branch-likely's annulled delay slot with the
branch TARGET's first instruction. It will only do this (emit `bnel`/`beql`
instead of plain `bne`/`beq`) when the delay-slot instruction is safe to
execute speculatively — in particular when the **branch's test register is
different from the base register of the load it pulls into the delay**._

**Target shape:**
```
lw   t8, 0x24(sp)        ; reload spilled param a3  -> t8
lw   t9, 0x24(sp)        ; reload SAME spilled a3   -> t9  (second reload!)
bnel t8, zero, .copy     ; test t8
lw   t1, 0(t9)           ; delay-likely: first copy load, base t9 (≠ t8)
```
The two `lw … 0x24(sp)` of the same spilled parameter into **two distinct
registers** is what makes test-reg (t8) ≠ delay-load-base (t9), which is
the precondition for reorg to annul.

**Why C can't force it:** natural C reloads the spilled param **once** and
uses that one register for both the null test and the dereference, so
test-reg == load-base and reorg falls back to a plain `bne` + separate
load → the function comes out **exactly 1 instruction short**. The
double-reload is an IDO register-allocator/reorg artifact tied to the
spilled-parameter liveness across an intervening call; it is NOT reachable
by C expression restructuring at a given frame shape.

**Verified ineffective levers (2026-05-16, `gl_func_0003D7F8`):**
- `#feedback-ido-bnel-arm-swap` (EQUAL case in the `if` arm) — already in
  that shape, still plain `bne`.
- pointer-local `int *p = a3;` then deref via `p` — IDO CSEs `p` back to
  the single `a3` reload, no change.

**Path forward:** (a) permuter on the near-match body (randomizes spill /
register choices until the t8≠t9 split + branch-likely appears); or
(b) force SAME-LEN first (introduce a second, distinct spilled local for
the deref base so the param's home slot is loaded twice), then INSN_PATCH
the `bne`→`bnel` opcode + the delay-slot load + register renames — all
same-length word overwrites (jal orphan-relocs auto-stripped). Don't keep
grinding C control-flow shapes; this residual is regalloc-bound.

---

<a id="feedback-isolated-vs-full-tu-o2-divergence"></a>
## Isolated-compile vs full-TU IDO -O2 codegen can diverge for the same function — always verify against the full `make` build

_IDO 7.1's -O2 optimizer is translation-unit-context-dependent. The same
function body, same flags, can produce two different instruction shapes
depending on whether it is compiled alone or as part of the full source
file. This breaks the common "test the C in isolation, eyeball the asm"
shortcut: an isolated test can look byte-perfect while the real build is
sub-80%._

**Concrete case (2026-05-16, `game_libs_func_0003D9E4`, 12-insn list walk):**

Compiled IN ISOLATION with the EXACT project flags:
```
cc -c -G 0 -non_shared -Xcpluscomm -Wab,-r4300_mul -O2 -mips2 -32 \
   -I include -I src -DNON_MATCHING -o /tmp/f.o /tmp/f.c
```
→ 12 insns, plain `beq`/`bne`, `nop` delay slots — target shape
byte-for-byte except ONE register (counter in `$v0`; target reuses the
dead `$a0` param).

The full-TU `make non_matching_objects` build of `game_libs_post.c`
(asm-processor phase-1 output verified textually identical to the
source for this function) → 17 insns, `beql`/`bnel`, loop rotation,
**3.75% fuzzy**. Same C. Same flags. Same -O2.

**Why:** IDO's RTL optimizer / reorg makes decisions influenced by
whole-TU state (function ordering, accumulated optimizer context), not
purely the single function. A small isolated TU and a multi-thousand-line
TU can land in different optimization states for the identical function.

**Implications / how to apply:**
- ALWAYS score against `build/.../<file>.c.o` (objdiff / the project's
  byte_verify), NEVER an isolated `cc` of the extracted function. An
  isolated test is a useful *sanity check that the logic is right*, but
  it is NOT proof the build matches.
- If isolated == target but full build diverges: the C **logic is
  correct** — stop re-deriving control flow. The residual is a
  TU-context optimizer artifact. Escalate to the permuter, or search for
  a loop/branch form that survives the full-TU optimizer to the target
  shape (different break/continue placement, counter-register recycling,
  goto vs structured).
- This is a distinct class from "wrong C shape." Diagnose by extracting
  the function from the asm-processor phase-1 output and cc'ing it alone
  with the exact flags: if that hits the target shape, you have this
  divergence, not a logic bug.

---

<a id="feedback-ido-inline-arg-deref-defeats-cse-emit-multiple-lw"></a>
## Inline `aN[OFFSET]` at each use (vs caching in a local) to force IDO to emit the same `lw` twice — matches target's redundant-reload shape

_When built has one `lw` for `a0[K]` cached into a local, but target has TWO+ `lw a0,K(a0)` (target's C source apparently inlines the deref at each use, breaking IDO's CSE), refactor the C body to inline `aN[K]` at every use instead of caching into a local. IDO will re-emit the lw at each reference. This is the reverse of the usual "cache for clarity" idiom — for byte-match grinding, the wasted memory reads ARE the match._

**Symptom:** built is 1+ insns SHORT vs target, and the missing insns look like duplicate `lw aN, K(aN)` for the same struct field.

**Recipe:**
```c
// REGRESSES (caches → 1 lw):
int *p = (int*)a0[0x240/4];
p[0x144/4] = toggled;
vtable = (int*)p[0x28/4];
... (int)p ...

// FIXES (inlines → 3 lw's of 0x240 in target's pattern):
((int*)a0[0x240/4])[0x144/4] = toggled;
vtable = (int*)((int*)a0[0x240/4])[0x28/4];
... (int)a0[0x240/4] ...
```

**Why it works:** the original target source apparently didn't cache (perhaps the dev preferred inline style, OR a non-aliased volatile-like access semantics required separate loads). IDO -O2's CSE doesn't fold separate-statement loads of the same struct field across statements — each inline `a0[K]` becomes its own `lw`.

**Verified 2026-05-16 on `gl_func_00046B64`:** 85% NM → exact via inline-the-deref + 12-insn INSN_PATCH for the leftover register-rename diffs. The inline change alone took 23 insns → 24 insns (matching target's count). Cap on the wrap doc was "needs INSN_PATCH for final register-rename"; the actual blocker was the missing inline-vs-cached lw, NOT the register names.

**When to apply:** built is exactly N insns short, AND the missing N insns are duplicate `lw` for the same struct field that built loaded once into a local. Don't apply when the cached local has a NON-trivial computation — inlining duplicates compute too.

**When NOT to apply (verified 2026-05-16 on `timproc_uso_b1_func_00001908`):** built is N insns short BUT the missing insns are STRUCTURAL register-shuffles around a cached pointer (target keeps `self` in `$a3` from one spill-reload, my emit reloads per-use into `$a0`). Inlining the deref REGRESSED by losing 1 more insn (86.60% → 85.96%, 172B/43 → 168B/42). Diagnostic: look at the missing insns in the diff — if they're `lw self,sp+0xN; lw sub,K(self)` PAIRS, this recipe applies; if they're `lw sub,K(self)` only (self already cached in an unchanged reg), inlining doesn't help and may hurt by collapsing the cached form.

**Complementary recipe:** `feedback-unique-extern-neutral-when-clobber-forces-reload` (PATTERNS.md) covers the &D-extern case where unique-externs force separate reloads. This entry covers arg-pointer field-deref CSE-defeat via inline.

---

<a id="feedback-ido-named-float-const-pins-fp-reg-across-body"></a>
## `float four = 4.0f;` named local pins the FP constant to one $fN across multiple uses

_For functions that use a non-zero FP literal (e.g. 4.0f, 2.0f, 58.0f) multiple times, declaring `float NAME = LITERAL;` as a named local pins the constant in a single $fN register across all uses. Without the named local, IDO -O2 may re-materialize the constant (`lui at, IMM; mtc1 at, $fN`) at each use site, doubling the setup overhead. With the named local, single setup + register reuse — matches target's emit when target was compiled with the same pattern._

**Symptom:** built has extra `lui at, 0xXXXX; mtc1 at, $fN` pairs around each FP-literal use; target has single setup near the top and reuses $fN.

**Recipe (verified 2026-05-16 by parallel agent on `game_libs_func_000086A0`, by me on `gl_func_0000871C`):**
```c
void f(int *a0) {
    float four = 4.0f;      /* pin $f4 = 4.0f */
    float f550 = *(float*)((char*)a0 + 0x550);
    if (f550 < four) { ... }                       /* uses $f4 */
    ...
    *(float*)((char*)a0 + 0x550) = -(f550 / four); /* reuses $f4 */
}
```

**Why it works:** unlike the `register int one = 1;` case (which constant-folds away per the documented "register honored narrowly" rule), FP literals require lui+mtc1 setup that's expensive to duplicate. IDO -O2 treats the named float local as a hint to allocate one $f-reg and reuse rather than CSE'ing the literal into per-use materialization. Effective for 2+ uses of the same constant.

**Doesn't apply when:**
- Single-use constant (no CSE benefit, named local just adds noise).
- Constant is 0.0f (target may use `mtc1 $0, $fN` differently — see `feedback-ido-f2-intermediate-unreproducible` for the 0.0f-specific traps). Verified 2026-05-17 on `game_libs_func_00064124`: target has $f2=0.0f (bulk zeros) AND $f4=0.0f (delay-slot store) as DISTINCT regs. `float zero2 = 0.0f;` named local with single-use at the $f4 site does NOT split the CSE — IDO still folds the named zero into the same reg as literal 0.0f stores. The lever is asymmetric: lui+mtc1-LITERAL setup CAN be pinned via name; mtc1-$0 setup CAN'T (no shared setup to amortize).
- Target re-materializes the constant per use (the inverse: drop the named local then).

**Complementary to** `feedback-ido-shared-base-via-deferred-assign-and-named-locals` (PATTERNS.md): same lever shape (named local → CSE), applied to FP literals rather than &D-base.

---

<a id="feedback-ido-bitfield-setter-two-statement-split-for-redundant-sw"></a>
## Bitfield setter `*a0 = (*a0 & ~M) | (V << N);` emits ONE sw; target's two-sw shape needs split into two statements

_When target asm has TWO `sw rX, 0(a0)` writes (a cleared-mask intermediate followed by the OR'd final value) for what is logically a bitfield setter, the natural single-expression form emits only ONE `sw` (built shorter by 4 bytes / 1 insn). Split the single expression into TWO statements: clear-then-set. IDO honors the sequence points and emits the intermediate store._

**Symptom:** built `.o` for a setter is 4 bytes / 1 insn shorter than `expected/.o`. The missing insn is a `sw rX, 0(aN)` that writes the cleared-mask intermediate. Target's body looks like:

```mips
lw    $t6, 0($a0)        ; load *a0
li    $at, ~M            ; mask
andi  $t9, $a1, K        ; new bits in low position
and   $t7, $t6, $at      ; cleared = *a0 & ~M
sw    $t7, 0($a0)        ; INTERMEDIATE STORE — the one your build is missing
or    $t0, $t7, $t9      ; final = cleared | new
jr    $ra
sw    $t0, 0($a0)        ; FINAL STORE
```

**Don't write:**
```c
void setter(int *a0, int a1) {
    *a0 = (*a0 & ~M) | ((a1 & K) << N);   /* emits ONE sw */
}
```

**Do write:**
```c
void setter(int *a0, int a1) {
    *a0 = *a0 & ~M;                 /* emits intermediate sw */
    *a0 = *a0 | ((a1 & K) << N);    /* emits final sw */
}
```

**Why:** the C `=` operator is a sequence point; two assignments to `*a0` force two stores. IDO -O2 does NOT fuse them across statements even when the second's RHS only adds bits (it has no proof the intermediate value isn't observable from another thread / signal handler / aliased pointer). The single-expression form gives IDO one assignment to compile, so one store.

**Where this shows up:** bitfield-accessor patterns generated by IDA / Ghidra reverse engineering — splat-mis-bundled getter/setter pairs at the tail of larger functions (the gl_func_0000A7B4 family). Once you spot one setter needing the split, the whole accessor cluster likely needs it.

**Verified 2026-05-17 on:** game_libs_func_0000A884 (bits 0..1), A8B4 (bits 2..4), A938 (bits 6..9), A96C (bits 10..13). 4/4 setters needed the split. Their paired getters (A878, A8A4, A928, A95C) matched exactly with single-expression `(*a0 >> N) & M` — only the setters need the split.

**Doesn't apply when:** the setter writes only the cleared value (no OR) or only the new value (no clear) — those are single-store patterns by construction. Only the clear-AND-set composite needs the split.

---

<a id="feedback-ido-leaf-beqz-fallthrough-into-next-func"></a>
## Leaf with `beqz $tN, +K` branching past function end into next function's `jr ra` body — tail-fallthrough caps INCLUDE_ASM-only

_Pattern: a leaf getter where the false-condition branch lands PAST the function's own `jr ra` insn, falling through into the immediately-following function's body. The fall-through provides the return for the false case; the true case is handled by the function's own jr ra. Cannot be reproduced from any tested C form — IDO has no lever to emit a function that intentionally relies on linker layout placing a specific neighbor after it. INCLUDE_ASM-cap._

**Symptom:** an 8-insn leaf body whose `beqz` offset targets the FIRST insn of the next function (not a label within itself):

```mips
glabel get_bit5
    lw    $t6, 0($a0)
    or    $v0, $0, $0         ; preemptive return = 0
    sra   $t7, $t6, 5
    andi  $t8, $t7, 1
    beqz  $t8, +3              ; branch to +0x10 past function end
    nop                         ; delay slot (always executed)
    jr    $ra                   ; true path: return 0x20 via DS
    li    $v0, 0x20             ; DS of jr ra

glabel next_func                ; immediately follows
    jr    $ra                   ; ← beqz's target lands HERE
    nop
```

If `($t8 == 0)`: beqz branches to `next_func`'s `jr ra; nop` — returns with v0=0 (preserved from the `or v0,0,0` preset).
If `($t8 != 0)`: falls through to `jr ra; li v0, 0x20` — returns with v0=0x20.

**Why C can't reproduce:** the function is 8 insns. The "false path" of the conditional doesn't return from this function — it returns from the LINKER-ADJACENT function. No C-level lever asks IDO to emit a function shorter than it needs (truncated `jr ra` short by relying on the next symbol's body to supply one). Even SUFFIX_BYTES doesn't fit: the missing `jr ra; nop` IS the next function — duplicating it here would make the next function 0-byte.

**Action:** keep `INCLUDE_ASM` for the leaf, decode the neighbor (almost always `void f(void){}` — the empty function whose body is the fallthrough target). Document the dependency in the leaf's comment so a future split-into-its-own-.c doesn't break it (re-ordering would invalidate the fallthrough).

**Identified 2026-05-17 on:** game_libs_func_0000A8D8 (8-insn bit-5 getter), where next function game_libs_func_0000A8F8 IS the empty `void f(void){}` whose `jr ra; nop` is the fallthrough's return.

**Cousin patterns:** `feedback-ido-fabs-dead-mov` (unreachable insns from branch-likely artifacts) — but that's intra-function dead code, recoverable via `fabsf()`. The tail-fallthrough is inter-function and not recoverable.

---

<a id="feedback-intervening-call-forces-reload-vs-cse-cap"></a>
## Same-base multi-deref: an intervening `jal` forces a natural reload (exact-able); NO call → IDO CSEs the base (reload-CSE cap)

_Predictive heuristic for which small split-off / fresh functions are
worth pushing to byte-exact vs which will plateau on the reload-not-CSE
residual (the EE84/DDC0/120C family)._

When a function dereferences the **same base** twice (e.g. `a0->0x6A8`
read for two separate sub-objects), the target asm reloads it (`lw t6,
N(a0)` … `lw t9, N(a0)`):

- **If there is an intervening `jal`** between the two uses, IDO -O2
  *must* reload (the call clobbers caller-saved regs / the value can't
  live across it) — so natural C (`func(a0->X); func(a0->X);`) emits the
  two reloads and **matches**. These are exact-able; prioritize them.
  Verified 2026-05-17 `timproc_uso_b3_func_00001184` — byte-exact
  unconditional-C land (0→100%, +0.02% completion), the C had a `jal`
  between the two `a0->0x6A8` derefs.
- **If there is NO call** between the uses (pure load/op/store, e.g.
  `(a0->0x6A8->0x6C)->0x18 |= 4; (a0->0x6A8->0x94)->0x18 |= 4;`), IDO
  -O2 **CSEs** the base into one `lw` while the target reloads → build
  is N insns short, no C expression form defeats it (cast, re-deref,
  explicit locals all CSE back). This is the documented reload-not-CSE
  cap — verified `timproc_uso_b3_func_0000120C`/`000011D4` (2-short),
  same family as EE84 `a0->0xB4` / DDC0. Keep INCLUDE_ASM + decode
  comment; don't grind.

**Triage rule:** before investing a tick toward exact on a small
fresh/split function with a repeated base deref, check for an
intervening `jal`. Has-call → go for the byte-exact unconditional-C
land. No-call same-base-multi-deref → expect the reload-CSE cap, record
the decode and move on.

**Land mechanics reminder:** the exact-able case must be **unconditional
C** (NOT `#ifdef NON_MATCHING / #else INCLUDE_ASM`). With the #else
INCLUDE_ASM wrap the real build path is INCLUDE_ASM and build/.o ==
expected/.o is the *tautology trap*, not a match (see the build-path
guard in docs/POST_CC_RECIPES.md#feedback-insn-patch-screen-by-opmismatch-count).
Convert to unconditional C, then byte_verify build/.o vs expected/.o
(reloc-aware) before episode + land.

### feedback-ido-signed-mod-break-pair

**Pattern:** A signed `%` or `/` whose divisor is not a compile-time
known-nonzero constant (e.g. loaded from memory) lowers in IDO -O2 to
the full trapping sequence:

```
div   $zero, $dividend, $divisor
mfhi  $r            # (% ; mflo for /)
bnez  $divisor, +2  # skip the next trap if divisor != 0
nop
break 7             # divide-by-zero trap
addiu $at, $zero, -1
bne   $divisor, $at, +2   # skip overflow trap unless divisor == -1
lui   $at, 0x8000
bne   $dividend, $at, +2  # ... and dividend == INT_MIN (0x80000000)
nop
break 6             # signed INT_MIN / -1 overflow trap
```

**Why it can't be removed from C:** `break 7` (÷0) and `break 6`
(INT_MIN/−1 overflow — a result MIPS hardware cannot represent) are
part of IDO's *signed* integer division lowering, not an optimizer
artifact. IDO only elides them when it can prove the divisor is a
nonzero constant at compile time. Any `int x % n` / `int x / n` with
`n` coming from a `lw` keeps the entire guard pair. This is distinct
from the strength-reduction `(x<<10)/x` case
(`#feedback-ido-div-strength-reduction-needs-dfg-visibility`): there
only `break 7` appears because the divisor equals the shifted dividend
(never INT_MIN-vs-−1); the `% n` ring-index case emits BOTH.

**Implications for matching:**
- A plain-C ring buffer `idx = (first + count) % max;` (the classic
  inlined `osSendMesg` body) will reproduce the `div+mfhi+break 7`
  but is otherwise exact — it caps just below 100 only by the guard
  shape, which is *already what the target has*, so it usually MATCHES.
  Don't "fix" the breaks; the target libultra code has them too.
- If the target uses `divu` + only `break 7` (no `break 6`), the
  original operands were `unsigned` — make the C operands `u32`.
- If the target has NEITHER break (bare `div;mflo`), the divisor was a
  known constant there — use a literal, or it's a different routine.
- Only reach for post-cc INSN_PATCH if the target genuinely lacks a
  guard your signed C must emit (rare).

Verified 2026-05-17 on `func_800044CC` (1080 kernel, libultra
PI-event callback with an inlined `osSendMesg` ring-index `%`).

## Leaf load-hoist above an aliasing store — don't cache the first deref in a named local
<a name="feedback-ido-leaf-load-hoist-no-named-temp"></a>

**Symptom.** A tiny no-frame leaf's target asm hoists a load above a
preceding store that *could* alias it, and uses two transient temp
registers for two reads of the same `aN[k]`:

```
lw   $t6, 4($a1)      ; load a1[1]   -- HOISTED above the next store
sw   $a1, 0($a0)      ; a0[0] = a1
sw   $t6, 4($a0)      ; a0[1] = t6
lw   $t7, 4($a1)      ; load a1[1] AGAIN (different reg, no CSE)
sw   $a0, 0($t7)      ; (a1[1])[0] = a0
sw   $a0, 4($a1)      ; a1[1] = a0   (jr delay slot)
```

**Two traps:**

1. **Program-order C keeps the store first.** `a0[0]=(int)a1;
   a0[1]=a1[1];` emits `sw a1,0(a0); lw t6,4(a1); sw t6,4(a0)` — IDO
   will *not* reorder a load above an aliasing store it can't prove
   disjoint (both `int*`). 6/7 words, only the first two swapped.
2. **A named temp fixes the order but breaks regalloc + CSE.**
   `int t=a1[1]; a0[0]=a1; a0[1]=t; ((int*)a1[1])[0]=a0;` puts the
   load first, but the named local lands in `$v0` (not `$t6`), and the
   later `a1[1]` deref is CSE'd back to `t` → only **one** load instead
   of the target's two.

**Fix.** Write the load-bearing statement FIRST, no named temp, and
leave the later access as a fresh bare deref so it does not CSE:

```c
void f(int *a0, int *a1) {
    a0[1] = a1[1];                 /* lw t6,4(a1); (stores reorder) */
    a0[0] = (int)a1;
    ((int *)a1[1])[0] = (int)a0;   /* fresh deref -> 2nd lw into t7 */
    a1[1] = (int)a0;
}
```

IDO -O2 then: schedules `lw t6,4(a1)` first (the RHS of stmt 1),
**swaps the two independent `a0` stores** into target order
(`sw a1,0(a0)` before `sw t6,4(a0)`), reloads `a1[1]` into `$t7`
(no CSE across the intervening `a0` stores — conservative aliasing),
and drops the final `a1[1]=a0` into the `jr` delay slot. Byte-exact.

**Why it works.** The hoist the scheduler *won't* do across a store
(trap 1) it *will* do when the load is the first statement's own RHS
(nothing to hoist past). The two same-base stores `0(a0)`/`4(a0)` are
provably disjoint so the scheduler is free to put them in either
order — it picks the target's. Transient subexpressions get the
caller-save `$t` temps IDO uses for scratch; a named local enters the
priority allocator and grabs `$v0`.

**Generalizes:** any small leaf where the target double-loads `aN[k]`
into distinct `$t` regs around stores to a *different* aliasing-class
base — express both reads as bare derefs in the order that puts the
first load ahead of the first conflicting store; never introduce a
local to "hold" it. Sibling of
`#feedback-ido-double-deref-fills-jal-delay-slot` (same no-CSE
double-deref principle, jal-delay-slot variant). Verified 2026-05-18
on `game_libs_func_000664D4` (1080 game_libs, byte-exact 7/7).

## Generic `&D_00000000 + 0xK` folds field offsets to absolute loads — use a distinct relocated symbol when the target holds a base register
<a name="feedback-ido-generic-reloc-base-folds-vs-distinct-symbol"></a>

**Symptom.** Target accesses many fields of one fixed (reloc'd)
object through a single held base — the base is computed once
(`lui;addiu`), spilled (`sw base, 0xNN(sp)`), and reloaded
`lw tA, 0xNN(sp); lw tB, OFF(tA)` (base+offset) before every field:

```
lui  t6, 4
addiu t6, t6, 0x1710        ; base = seg + 0x41710
sw   t6, 0x1C(sp)           ; spill the base
...
lw   t7, 0x1C(sp)           ; reload base
lw   t8, 0x10(t7)           ; base->0x10   (base+offset)
...
lw   t9, 0x1C(sp); lw ..,0x18(t9)  ; base->0x18
```

**Trap.** Writing the object as `char *obj = (char*)&D_00000000 +
0x41710;` and then `*(int*)(obj + 0x10)`, `*(int*)(obj + 0x18)`, …
makes IDO -O2 treat each `&D_00000000 + 0x41710 + fieldoff` as one
manifest constant and emit a **separate absolute `lui;lw`** per field
(`lui a0,4; lw a0,0x1720(a0)` for +0x10, etc.). No base register is
ever held; the function is several insns shorter and the frame is
smaller (no spill slot). This is the *generic-base* symbol
(`D_00000000` = segment base 0) being foldable at every use.

**Fix.** Give the object its own **distinct relocated symbol** so the
address needs a real HI/LO reloc pair and IDO must materialize it once
into a register (then field offsets stay immediates → base+offset,
matching the target's held-base shape):

```c
extern int D_00041710;            /* distinct seg-offset symbol */
int *obj = &D_00041710;
... obj[4] ...  obj[6] ...        /* base+offset, one held base */
```

**Prerequisite.** `D_00041710` must exist in the segment symbol
table — add it to `undefined_syms_auto.txt` (or the splat config) at
the correct VRAM/offset first, or the reference is an unresolved-
symbol link error (`ERR=1`). Until that plumbing exists, NM-wrap with
the real C body (the logic is correct; only the addressing mode is
off) and defer the symbol work.

**Rule of thumb.** Generic `&D_00000000 + 0xK` is fine when the target
itself uses absolute `lui;lw` per access (the common case). The moment
the target holds ONE base across many field accesses (spilled or in an
$s reg), switch to a distinct symbol — the generic form structurally
cannot produce a held base. Seen 2026-05-18 on `gl_func_0006A304`
(1080 game_libs USO pointer-relocation fixup driver).

## IDO -O2 2x-unrolls a known-small-trip loop — non-unrolled target with li-constant bound is likely an un-suppressible-from-C cap
<a name="feedback-ido-unrolls-known-small-trip-loop"></a>

**Symptom.** Target has a single tight loop body ending
`addiu iv,iv,K; bne iv,tN,.Lbody` where `tN` is a `li`-loaded
constant (e.g. `li t0,6`), ~28 insns. Your C-emit is ~2x larger
(e.g. 76 vs 51) and `build/non_matching/.../X.c.o` disassembly shows
**two full copies of the loop body per loop pass** plus a residual
(two `addiu iv` and the `bne` after the second copy).

**Cause.** IDO -O2 computed the static trip count (`iv: 0,K,2K…`
with a constant bound → N iterations) and unrolled the loop 2x.
This happens for **both** `for (i=0;i!=N;i+=K)` and
`do { } while (iv != N)` — the loop FORM is irrelevant; only the
*statically-known trip count* matters. Restructuring for↔do-while
does NOT help (verified).

**Why the target isn't unrolled.** It was compiled such that IDO did
NOT unroll, yet its bound is a baked `li 6`. Two possibilities:
(a) the original source's bound is a runtime/opaque value (defeats
trip-count analysis → no unroll) that merely *happens* to be 6 at
the relevant call/inline site — but then the asm would not show a
flat `li 6` unless it was constant-propagated; (b) IDO's unroll
cost-heuristic declined for that exact body shape (body
size/complexity over threshold). Neither is reliably reproducible
from clean C while keeping the `li N` bound: making the bound opaque
(`volatile`, a memory load, a noinline helper return) changes other
codegen and usually still mismatches.

**Verdict.** No robust C-level lever to suppress IDO's
small-known-trip 2x-unroll. Treat as an IDO-loop-unroll cap: keep
the correct algorithm NM-wrapped, document it, move on. Do NOT keep
grinding loop-form variants — for/while/do-while/pointer-walk all
unroll identically when the trip count is statically derivable.

**Diagnostic recipe.** Build `build/non_matching/src/<seg>/<unit>.c.o`
(compiles the `#ifdef NON_MATCHING` body with `-DNON_MATCHING`),
`objdump -d` the symbol, and count loop-body repetitions. If body
appears 2x with two increment insns per pass → this cap. This is the
fast way to distinguish "loop unroll" from "regalloc/scheduling"
(the latter has the right insn count, wrong registers/order).
Verified 2026-05-18 on `game_libs_func_00054144` (game_libs
triangle-centroid; 3-trip ×2-unroll → 76 vs target 51).

## Reuse the parameter as the object (not a fresh local) — IDO arg-saves to the caller slot, keeping the minimal frame
<a name="feedback-ido-reuse-param-as-object-caller-slot-spill"></a>

**Context.** "alloc-or-given" constructor shape: an object that is
either the caller-supplied pointer or a freshly `alloc()`'d one, then
passed through ≥1 `jal` (init/register) and returned.

**Symptom.** C is byte-exact in structure (same insn count, right
ops/branches) but every spill offset is shifted and the prologue/
epilogue differ by a constant: e.g. `addiu sp,sp,-0x20` vs target
`-0x18`, `sw a2,0x1C(sp)` vs `sw a2,0x18(sp)`, `addiu sp,sp,0x20` vs
`+0x18`. A coherent +8-byte frame delta, N spill words off by the
same constant.

**Cause.** Writing the object as a FRESH local —
`int obj; obj=a0; if(a0==0) obj=alloc(N); …` — makes IDO allocate an
IN-FRAME stack slot for `obj` (it's a distinct pseudo that lives
across the jal). That grows the frame by 8 (slot + alignment) and
pushes every other spill down.

**Fix.** Assign back into the PARAMETER and use it as the object:

```c
int f(int a0) {
    if (a0 == 0) { a0 = alloc(N); if (a0 == 0) goto end; }
    cb(a0, …);            /* a0 survives the jal */
    … use a0 …
end:
    return a0;
}
```

IDO then spills the live arg via its **arg-save-to-caller-slot**
convention — `sw a0, <framesize>(sp)` into the caller's argument
slot ABOVE the frame — instead of carving an in-frame local. The
frame stays minimal and the spill offsets match the target.

**When to reach for it.** The only residual diffs are the
prologue/epilogue `addiu sp` pair plus a handful of spill `sw/lw`
words all off by the same constant, AND the spilled value is
derived from a parameter. This is the C-level lever for that exact
cap (no INSN_PATCH needed). Combine with the ternary-alloc
goto-end single-epilogue idiom
(`#feedback-ido-alloc-or-passthrough-ternary`) and inlining call
results (no named `int r` for `r=cb(); if(r)…` → fold into the
target var) to remove other in-frame locals.

Verified 2026-05-18 on `game_libs_post.c gl_func_00041524`
(alloc-or-given constructor): a fresh `int obj` capped at 6
frame-size diffs (frame 0x20 vs 0x18); switching to in-place `a0`
reuse → **byte-exact 32/32, pure C, no post-cc recipe**. Decoded
from a bare "Multi-pass decode pending" stub in one focused
multi-pass session (36→34→32/7→32/6→MATCH).

## Drop the extra "working register" param — IDO routes the spill to the SOURCE param's home slot, not the working register's home slot
<a name="feedback-ido-drop-working-reg-param-spill-follows-source-pseudo"></a>

**Context.** A finer-grained sibling of the param-reuse lever
above (`#feedback-ido-reuse-param-as-object-caller-slot-spill`).
Same family — alloc-or-given with the resource passed through ≥1
`jal` — but the symptom is sharper: **frame size is already
correct, only the offset of a single spill word is off by 4**.

**Symptom.** 24/24 insns byte-exact except one pair:
`sw $a1, 0x1C(sp)` / `lw $a1, 0x1C(sp)` (our build) vs target
`sw $a1, 0x18(sp)` / `lw $a1, 0x18(sp)`. Frame is `-0x18`, ra at
`0x14`, all branches/ops/registers identical. Permuter-immune
(its scorer normalises sp-relative offsets, so it reports score 0
on a pure spill-slot swap — do NOT log an episode off a permuter
zero without a raw byte-compare).

**Cause.** Even when IDO routes the working pseudo through a
caller's home slot (the lever above), the *which slot* depends on
the SOURCE pseudo, not on the current working register.

When the function is written:

```c
int f(int a0, int a1) {       /* 2-param, a1 is the "working" param */
    a1 = a0;                  /* copy param a0 into param a1 */
    if (a0 == 0) {
        a1 = alloc(N);
        …
    }
    /* a1 spilled across the next jal */
}
```

IDO assigns the working pseudo to `$a1` (the natural place — both
the home for param-2 and a free arg-reg) and spills to `a1`'s home
slot `0x1C`. The *value* spilled lives in `$a1` and the *pseudo*
spilled is the one declared as `a1`.

When the function is written:

```c
int f(int a0) {               /* 1-param, reuse a0 */
    if (a0 == 0) {
        a0 = alloc(N);
        …
    }
    /* a0-pseudo, currently in $a1 after the param→a1 copy,
       is spilled across the next jal */
}
```

IDO STILL copies `$a0 → $a1` and uses `$a1` as the working register
(same `or a1,a0,$0` insn — the register allocator's choice doesn't
change). But the spill target is `a0`'s home slot `0x18`, not
`a1`'s `0x1C`, because the live pseudo descends from the `a0`
parameter — IDO tracks the spill against the source pseudo's home.

**Fix.** Drop the extra working-register param. Use the single
`a0` param and reassign back into it:

```c
int f(int a0) {
    int v1;
    if (a0 == 0) {
        a0 = alloc(N);
        if (a0 == 0) goto end;
    }
    v1 = a0;
    if (a0 == 0) {            /* dead block — IDO can't prove !=0 */
        v1 = alloc(N);
        if (v1 == 0) goto skip_store;
    }
    *(int*)v1 = 0;
skip_store:
    *(int*)a0 = TAG;
end:
    return a0;
}
```

Keep `goto end;` (not `return 0;`) — `return 0;` adds an explicit
`or v0, $0, $0` (set v0 to 0) plus a forward branch to the
epilogue, costing 2 insns over the natural `beq v0, $0, epilogue`
shape.

**Counter-trap.** A fresh-local 1-arg form does NOT crack this
spill:

```c
int f(int a0) {
    int r = a0;               /* fresh local, NOT param-reuse */
    if (a0 == 0) { r = alloc(N); … }
    …
}
```

This bumps the frame to `-0x20` and puts the working pseudo in
`$v1` (different registers entirely — spill at `0x18` but
everything else shifts). Both legs of the lever are required: 1-arg
**and** reuse the param directly.

**When to reach for it.** Only residual is a single spill `sw/lw`
pair at the working register's home (e.g. `0x1C` for `$a1`,
`0x20` for `$a2`) that the target places at a lower arg-home slot
(`$a0`'s `0x18`). Earlier docs may report "permuter-immune
spill-slot offset cap" — that's this lever. Verified 2026-05-27
on `gl_func_00037FAC` (24 insns, prior 99.92% / spill at 0x1C →
byte-exact at 0x18). Generalizes directly to `gl_func_00066514`
(same shape with the working pseudo in `$a2`; 3-param form spills
at `0x20`, 1-param `a0`-reuse should spill at `0x18`).

**Corollary — transcribe m2c's `||`/`&&` short-circuit + sentinel comparison VERBATIM; don't "clean it up" (verified 2026-05-29, gl_func_000628EC / gl_func_000519A4).** When m2c renders a nested alloc-bail as a comma/short-circuit monster like `if ((s != (void*)-0x110) || (a1 = s+0x110, v1 = alloc(4,a1), v1 != 0)) && ((a0 = v1, v1 != 0) || (a0 = alloc(4,a1), a0 != 0))) *a0 = 0;`, write it as-is. The `s != (void*)-0x110` is m2c's view of a null-check on `&s->field_110` (the address `s + 0x110`), and IDO genuinely emits the dead alloc(4) blocks because it can't fold `base+const != 0`. Rewriting it to the "obvious" `p = (int*)(s+0x110); if (p != 0) *p = 0;` lets IDO PROVE `p != 0` and deletes both dead blocks → frame shrinks, instruction count drops (~10 insns short), and the whole tail mis-aligns. On gl_func_000628EC the verbatim form jumped the match 26%→52% and restored the exact 80-insn count. So for the nested-alloc-with-dead-blocks family: faithful comma-operator transcription beats clean nested-`if` whenever the target keeps the unreachable alloc legs.

## Append+overflow: hold `n = count+1` in a named temp; don't reload the just-stored counter for the bound test
<a name="feedback-ido-append-overflow-count-temp"></a>

**Shape.** Recurring game_libs record-append tail:

```
n = self->[K] + 1;
self->[K] = n;
if (!((unsigned)n < (unsigned)cap)) cb_assert(&D + STR);
return self->[K] - 1;
```

Target asm: `lw v0,K(a0); addiu v0,v0,1; sltu at,v0,a1;
... sw v0,K(a0); ...; lw v0,K(s0); ... addiu v0,v0,-1` — the
**count+1** value stays in `$v0` and feeds BOTH the `sltu` (bound
test) and the `sw` (store back); the return path reloads `self->[K]`
into `$v0` again and subtracts 1.

**Trap.** Writing it without the temp —
`self->[K] = self->[K] + 1; if (!((unsigned)self->[K] < cap)) …;` —
makes IDO emit a *fresh load* of `self->[K]` for the test. Because
the field-store reloads earlier in the function already consume the
low scratch regs, that reloaded value lands in `$v1`/`$t7`, not the
target's `$v0`. Result: same instruction count, ~7 register-only
diffs clustered at the tail (`8C8F0044` vs `8C820044`, `25E3…` vs
`2442…`, `0065082B` vs `0045082B`, …).

**Fix.** Introduce the explicit temp and reuse it:

```c
int n = self[K/4] + 1;
self[K/4] = n;
if (!((unsigned int)n < (unsigned int)cap)) gl_func_00000000(&D + STR);
return self[K/4] - 1;     /* genuine reload → v0, -1, jr-delay */
```

`n` pins count+1 to `$v0` for the sltu+sw; the `return` line's
`self[K/4]` is a real second load (target reloads too — `lw v0`
in the epilogue, `addiu v0,v0,-1` in the `jr ra` delay slot).
Pure-C, no post-cc recipe.

**Companion idiom.** The 4 (or N) field stores preceding this tail
reload `self->[K]` and `self->[base]` *per store* (no cached
slot/idx) — keep them as uncached
`*(short*)(self[base/4] + self[K/4]*8 + OFF) = val;` so IDO
re-emits the `lw;lw;sll;addu` per field (matches the target's
un-CSE'd per-store address recompute).

Verified 2026-05-19 byte-exact on `gl_func_000503A4` (game_libs
4×u16 record-append, 40/40, 6-arg with 2 stack args). Same family:
`gl_func_00044CE8` and other append+assert functions.

## Indexed double-deref accessor (`return base[idx*4+K]->[J]`) — all-$t-temporary target is a register-allocation cap from C

<a name="feedback-ido-indexed-double-deref-allt-cap"></a>

**Shape.** Tiny leaf accessor that chains two indexed pointer loads, no named result:

```
return *(int*)(*(int*)((char*)a0[B/4] + (a0[I/4] << 2) + 0x40) + (a0[J/4] << 2) + 0x3C);
```

Target asm keeps EVERY intermediate (the input loads, the shifts, the
addus, the inner deref) in `$t` temporaries — e.g. `lw $t7,I(a0);
lw $t6,B(a0); lw $t1,J(a0); sll $t8,$t7,2; addu $t9,$t6,$t8;
lw $t0,0x40($t9); sll $t2,$t1,2; addu $t3,$t0,$t2; jr ra;
lw $v0,0x3C($t3)`.

**SOLVED 2026-05-23 — this was NOT a cap; it's the addu operand-order lever.**
The mistake was (a) using named locals and (b) writing the address as
`base + idx*4`. Two fixes together crack it:
1. **Fully inline — no named locals.** A named `int i`/`int *base`/`int j`
   gets `$v0/$a1/$a2`; inlining keeps everything in `$t` temporaries.
2. **Write the scaled index FIRST in each addu: `idx*4 + base`, not
   `base + idx*4`.** For a LOADED base (`*(int*)(a0+B)`), IDO makes the
   C-second operand the addu `rs`, so `idx*4 + base` emits `addu rd, base,
   idx*4` (base as rs) — the target's order. `base + idx*4` emits the
   reversed (capped) order.

Matching form (8C1C):
```c
return *(int*)(*(int*)(*(int*)((char*)a0+0x3C4)*4 + *(int*)((char*)a0+0x40C) + 0x40) + 0x6C);
```
Verified byte-exact 2026-05-23 on the whole family that was previously
NM-wrapped as "permuter-class": `timproc_uso_b5_func_00008C1C/_00008AD4/
_00008A38/_00008A64/_00008A90`. No INSN_PATCH needed.

**Param base — the `(int)a0` cast is the trap, not the operand order.** For a
PARAMETER base, `(int)a0 + idx*4` (int-cast) forces index-first, BUT pointer
arithmetic with the param written first — `(char*)a0 + idx*4 + K` — emits
base-first and matches. `game_libs_func_00067358` (`return *(int*)((char*)a0 +
a1*4 + 0x13C8)`) verified byte-exact this way 2026-05-23 (it had been deferred
only because the earlier attempt used the `(int)a0` cast). So: always use
`(char*)param + idx*4` pointer-arith, never `(int)param + idx*4`.

**The SHARED-address sub-case → 1-insn INSN_PATCH, not a cap.** When the same
`p = a0+idx*4` feeds both a load and a store (`*(p+K1)=*(p+K2)`), IDO
materializes ONE addu and emits it index-first (`addu v0,t7,a0`) regardless of
C operand order — the `base + idx*4` ↔ `idx*4 + base` lever does NOT flip it
here (confirmed across `&a0[idx]`, `(char*)a0+idx*4`, `idx*4+(char*)a0`,
`(idx<<2)+(char*)a0` — all index-first). BUT every other byte matches, so the
operand-order is a commutative 1-insn diff: keep the natural C body (`int *p =
&a0[idx]; *(p+K1)=*(p+K2);`) and INSN_PATCH the single addu to base-first
(`func=0x8:0x008F1021`). `timproc_uso_b5_func_00008ABC` promoted byte-exact this
way 2026-05-23 (1/6, well under the ≤half episode-fidelity bar). So the shared-
address shape is NOT a permanent cap — it's a guaranteed 1-insn patch.

## A no-dependency constant store gets hoisted into a load-delay gap — write it LAST in source order
<a name="feedback-ido-zero-store-write-last-to-prevent-hoist"></a>

**Shape.** A small accessor copies several loaded fields into the object and also writes a constant:

```c
obj->A = g->x;   obj->B = g->y;   obj->C = g->z;   obj->K = 0;
```

**Trap.** A constant store like `obj->K = 0` (`sw $zero, K(obj)`) has no value
dependency, so IDO's scheduler is free to hoist it up to fill a load-delay
gap between two dependent `lw`s. If you write it before the last field copy,
it lands *earlier* than the target (which emits it just before the
jr-delay-slot store).

**Fix.** Write the constant store as the LAST statement of the function. With
nothing after it but the implicit return, IDO keeps it at the end (the final
real store before the jr-delay store).

Verified byte-exact 2026-05-22 on `timproc_uso_b5_func_0000A928` (copies
`(*(D+0x134))->0x84/0x80/0x8C` into `a0->0x2C/0x30/0x34` plus `a0->0x3C=0`):
writing `a0->0x3C=0` third emitted it at insn 8 (hoisted into the gap after a
`lw`); writing it last emitted it at insn 11, matching the target.

## jr-epilogue double-store: delay-pick + emit-order + temp-reg# all couple to source order (some target combos unreachable)
<a name="feedback-ido-jr-epilogue-double-store-coupling-cap"></a>

**Shape.** A no-frame leaf does exactly two *independent* stores of
differently-computed values, then `jr $ra`:

```c
*(int*)(a0 + 0x1F4) = 1;          /* value 1   */
*(char**)(a0 + 0xE0) = a0 + 0x60; /* value a0+0x60 */
```

**Trap.** Three things are all locked to source order and cannot be tuned
independently:
1. **temp-reg number** follows the order each store's *value* is computed
   (first-computed value → lower temp, e.g. `$t6`);
2. **emit order** of the two `sw`s;
3. **which store fills the jr delay slot** — IDO consistently puts the
   *first*-source store into the delay slot, emitting the second one first.

So if the target shows `li t6,1; addiu t7,a0,0x60; sw t6,0x1F4; jr; sw t7,0xE0`
— i.e. value `1`→`$t6` (computed first) AND the `0xE0` store in the delay slot
— it's **unreachable from C**: getting `0xE0` into the delay requires it to be
the first source store, which forces `a0+0x60`→`$t6` (wrong reg); getting
`1`→`$t6` requires the `0x1F4` store first, which puts `0x1F4` (not `0xE0`) in
the delay. The (delay-store, reg-number) pair the target wants is the one
combination source order can't produce. Five variants (natural, swapped,
explicit-temp-decoupled both ways, inline-address) all confirmed.

**How to apply.** Recognize a 5-insn `compute;compute;sw;jr;sw` leaf where the
target's delay-slot store uses the *second*-computed value AND the
first-computed value lands in the lower temp. NM-wrap/defer; don't grind. This
is the jr-epilogue analogue of the jal-delay `feedback-ido-swap-stores-for-jal-delay-fill`
recipe — but unlike the jal case (where you *can* pick the delay store by
swapping source order), the jr case couples the reg# too, so the swap that
fixes the delay store breaks the reg. Verified 2026-05-23 on
`game_libs_func_000478D8`. The clean siblings in the same sweep DID match
(`0001D754`/`0001D858` gbi builders, `00067AA0` field-zero, `0002A9A4` getc).

## getc-style post-increment: deref `**a0` (not a named pointer local) keeps the pointer in $a1, and lbu must precede the addiu
<a name="feedback-ido-getc-deref-form-keeps-a1"></a>

**Shape.** `unsigned char c = *(*pp)++;` — read a byte, post-increment the
caller's pointer. Target:

```
lw   a1, 0(a0)      # p = *pp
lbu  v0, 0(a1)      # c = *p   (BEFORE the increment)
addiu t6, a1, 1     # p+1
jr   ra
sw   t6, 0(a0)      # *pp = p+1  (delay slot)
```

**Fix.** Write it with the double-deref `**a0` form and read-before-write:

```c
unsigned char f(unsigned char **a0) {
    unsigned char v = **a0;   /* lbu first */
    *a0 = *a0 + 1;            /* increment + store-in-delay */
    return v;
}
```

**Trap.** A named pointer local — `unsigned char *p = *a0; v = *p; *a0 = p+1;`
— allocates the loaded pointer to `$v1` (not `$a1`) and reorders to
`addiu;sw;lbu(delay)` (increment first, byte-read in the delay slot), which is
the wrong shape. The `**a0` double-deref keeps the pointer in `$a1` and forces
the `lbu` to precede the `addiu`. Verified byte-exact 2026-05-23 on
`game_libs_func_0002A9A4`.

## Commutative compare (`beq`/`bne`) operand order: don't cast the parameter — casting flips which operand becomes `rs`
<a name="feedback-ido-beq-operand-order-param-cast"></a>

For a loop/guard comparing a loaded pointer-local against a parameter
(`while (p != a0)` / `if (p != a0)`), `beq`/`bne` is commutative so either
register order is semantically equal but **byte-different**. IDO's operand
choice is driven by the parameter's declared type, NOT by source operand order:

- **Param at its natural type, no cast** → the loaded value `p` (in `$v0`) is
  `rs`: `beq $v0, $a0`. This matches targets whose first compare instruction
  loads a field and tests it directly.
- **Param cast at the compare** (`p != (int*)a0`, or declaring it `int **a0` and
  casting) → the *parameter* becomes `rs`: `beq $a0, $v0` — reversed bytes.

Flipping source order (`a0 != p` vs `p != a0`) does **not** change it; only the
cast does.

**How to apply.** If the target's `beq`/`bne` has the freshly-loaded value as
`rs`, declare the parameter at the type that lets you compare WITHOUT a cast.
Verified byte-exact 2026-05-23 on `game_libs_func_0005B73C` (circular-list
counter): `int *a0` + `p != a0` matched; `int **a0` + `p != (int*)a0` missed by
operand order only. Pairs with the do-while strlen form
(`if(*p) do{p++;}while(*p)` emits the `lbu 1(reg)` look-ahead that `while(*++p)`
does not) — both verified the same day on the loop-leaf vein.

**Does NOT generalize to `addu` (scaled-index pointer arith).** For
`base + idx*4` (`addu v0, base, index`), the cast lever flips the *operand order*
the same way — `(char*)a0 + idx*4` gives base-first `addu v0,a0,t7`, while the
`int *` shared-base form (`&a0[idx]`, `a0+idx`) gives index-first `addu v0,t7,a0`
— BUT the cast simultaneously couples the register allocation: the char* form
moves the index to `$v0` and the result pointer to `$v1`, whereas the target
wants index→`$t6`/result→`$v0`. So unlike `beq` (where the cast is a clean
lever), for `addu` the base-first order and the correct temp-reg numbering are
mutually exclusive — it's a genuine cap. Verified 2026-05-23 on
`timproc_uso_b5_func_00008ABC` (6-insn `a0[idx]` copy, 1 operand-order diff, all
4 cast/shared-base forms tried). Don't burn a tick trying the cast lever on an
`addu`-operand-order wrap.

## Indirect call: inline the call expression to get $t9 (not a named fn-ptr local → $v0)
<a name="feedback-ido-indirect-call-inline-for-t9"></a>

When a function calls through a pointer, IDO emits the computed-call register
`$t9` (`lw $t9, off(base); jalr $t9`). But if you stage the pointer in a named
local first, the local gets a normal allocno register (`$v0`) and you get
`lw $v0; jalr $v0` — a 2-insn register mismatch.

```c
/* MISMATCH — fn gets $v0 */
void f(int *a0) { void (*fn)(void) = (void(*)(void))a0[1]; fn(); }
/* MATCH — inline call uses $t9 */
void f(int *a0) { ((void (*)(void))a0[1])(); }
```

Inline the cast-and-call as a single expression. Verified byte-exact
2026-05-22 on `gl_func_00069C94` (9-insn indirect-call thunk):
named-local form emitted `lw $v0,4(a0); jalr $v0`; inline form emitted
`lw $t9,4(a0); jalr $t9` matching the target.

## Two-flag dispatch: `if (A<0 || B<0)` emits bltz-then + bgez-else (not && of >=0)
<a name="feedback-ido-or-of-negatives-bltz-bgez"></a>

When a function branches on two sign-bit flag tests and calls one of two
callees, match the asm `bltz tA, THEN; bgez tB, ELSE` with an **OR of the
negative tests**, putting the THEN callee first:

```c
/* asm: bltz t6, then;  bgez t7, else;  then: A();  else: B(); */
if ((v0 << 12) < 0 || (v0 << 8) < 0) { A(); } else { B(); }
```

The short-circuit `||` makes the first test a `bltz` that jumps INTO the
then-block (taken = condition true), and the second a `bgez` that jumps to
the else-block (taken = NOT the second negative). Writing the logically-
equivalent `if ((v0<<12)>=0 && (v0<<8)>=0) B(); else A();` instead emits TWO
`bltz` (both branching to the else/A block) — wrong branch offset AND an
inverted second test (`bltz` where the target has `bgez`). Verified byte-exact
2026-05-22 on `gl_func_00056FF4` (bit19||bit23 flag dispatch): the `||`-of-
negatives form matched 18/18; the `&&` form had 2 diffs.

<a id="feedback-ido-targeted-volatile-keeps-dead-store"></a>
## Reproduce a target's DEAD store via a TARGETED volatile cast on just that one store

Some 1080 game_libs functions write a field TWICE with no read between, leaving the first store dead:

```
lw    t2, 0x40(a0)        ; idx = a0->0x40
addiu t3, t2, 1           ; t3 = idx + 1
sw    t3, 0x40(a0)        ; a0->0x40 = idx+1     <- DEAD (overwritten next)
andi  t5, t3, 0xF         ; t5 = (idx+1) & 0xF   (uses the REGISTER t3, not a reload)
sw    t5, 0x40(a0)        ; a0->0x40 = (idx+1)&0xF
```

The natural C is `int t = a0->0x40 + 1; a0->0x40 = t; a0->0x40 = t & 0xF;` — but IDO -O2 **dead-store-eliminates** the first `a0->0x40 = t` (the field is overwritten with no intervening read), emitting one store. Result: 1 insn short, and every later branch offset shifts.

**Fix — cast ONLY the dead store's lvalue to volatile:**
```c
int t = a0[0x40/4] + 1;
((volatile int *)a0)[0x40/4] = t;   // volatile store: cannot be DCE'd -> emitted
a0[0x40/4] = t & 0xF;                // normal store (the live one)
```
A volatile store has identical encoding to a plain `sw`, so the bytes match; volatile only blocks the dead-store elimination.

**Do NOT make the whole pointer volatile** (`volatile int *a0`): that forces EVERY `a0[...]` access to a fresh, un-CSE'd load, adding many extra loads and reordering the merge — it over-applied to 22 diffs on gl_func_00031784 (vs the targeted cast's 0 structural diffs). The single-store cast is surgical; the whole-pointer qualifier is a sledgehammer.

**Origin:** 2026-05-23, game_libs_func_00031784 (ring-buffer push state machine). Targeted volatile took it 26→27 insns (correct length); 5 residual register-renumber insns in the increment block were INSN_PATCHed → byte-exact, reloc-free, episode logged. (Cf. the related but distinct volatile levers: caller-slot spill via `volatile T *p=&arg`, N-fold reload via `volatile T **`, scoped-volatile early-exit shape.)

---

<a id="feedback-ido-multiuse-nonpow2-mult-shares-multu"></a>
## Multi-use non-power-of-2 constant multiply → IDO shares `li N`+`multu`; single-use strength-reduces to shifts

For a stride/size like `*6` (`*3`, `*12`, …), IDO -O2 strength-reduces a SINGLE
use to shifts (e.g. `x*6` → `sll t,x,2; subu t,t,x; sll t,t,1`). But when the
SAME constant multiply appears 2-3+ times in one function, IDO instead
materializes the constant once (`li a3, 6`) and emits `multu x,a3; mflo t` per
use (sharing the `a3` constant). If the target was compiled to inline the shift
sequences per-use (no shared `multu`), the multi-use C cannot reproduce it —
neither plain `x*6`, explicit `(x*4-x)<<1`, nor struct/array indexing
(`((Struct6*)p)[i]`) avoids the shared-multu once there are 3 uses. This is a
codegen cap for such functions.

Verified 2026-05-23: `game_libs_func_0005318C` (single `a1*6`) matched
byte-exact with shifts, but its sibling `game_libs_func_0005313C` (three `*6`:
`a1*6` lookup + `idx*6` + `a1*6` epilogue) forced shared `li 6`+multu → NM-wrap
cap. Diagnostic: built `.o` shows `li <N>,<reg>` + `multu`/`mflo` where target
shows `sll/subu/sll`. No C lever found; the function stays NM (or needs a
flag/opt-level split if the original used a different setting).

---

<a id="feedback-ido-return-saved-var-trailing-reload"></a>
## Trailing `lw v0,saved(sp)` reload (Δ+1) = `return saved_var`; return the last call instead

A multi-call wrapper that saves an early result and returns it:

```c
int f(void *a0, void *a1) {
    int r = cb(1);     /* spilled to K(sp) */
    cb(a0, a1);
    cb(a0, a1);
    cb(r);             /* a0 = lw K(sp) in the jal delay slot */
    return r;          /* <-- adds a trailing `lw v0, K(sp)` reload */
}
```

emits one extra instruction vs the target (Δ+1, ~95%): the `return r` forces a
final `lw v0, K(sp)` because `r` was spilled (it's live across the calls). The
target has NO v0 reload before `addiu sp / jr ra` — it returns the **last call's**
result, which is already in `v0`. Fix:

```c
    return cb(r);      /* v0 already holds it — no reload, byte-exact */
```

Diagnostic: align built vs target; if the sole real diff is one extra
`lw v0,K(sp)` immediately before the epilogue, this is it. Verified 2026-05-23
`gl_func_00034C7C` (94.7→100, reloc-blind %-mover). Check the other Δ+1
count-mismatch near-misses for the same shape before reaching for a regalloc grind.

**Companion Δ-1 (built shorter): in-place pointer increment vs separate walk
pointer.** When a loop derefs+increments a pointer arg directly (`...*src...; src++;`)
but the target keeps the original arg in a saved reg and walks a COPY, built is
Δ-1. Add an explicit copy `p = src; ...*p...; p++;` → count matches, and what
remains is usually a clean `s0<->s1` swap (counter vs pointer) closeable by
`NON_MATCHING_INSN_PATCH` (register-field-only). The C copy is the count lever;
the twin closes the residual renumber. Verified 2026-05-23 `gl_func_0005C784`
(95.2→100; 32/33 Δ-1 → 33/33 with 6 register-field-only diffs → twin). Reloc-blind.

---

<a id="feedback-ido-float-div-pow2-strength-reduced-to-mul"></a>
## Float `/2^n` strength-reduced to `mul.s` by reciprocal — CRACKED 2026-05-24 by named-divisor at function scope (was INSN_PATCH-twin)

> **DEPRECATED-MENTIONS 2026-05-23.** This section mentions INSN_PATCH/PROLOGUE_STEALS; those mechanisms were REMOVED as match-faking — see `feedback_no_instruction_forcing_matches_policy`. Non-recipe content (recognition patterns, debug tips, byte-level analysis) is still useful; just don't treat any "→ INSN_PATCH" / "→ PROLOGUE_STEALS" advice as a fix.


> **DEPRECATED-FRAMING 2026-05-23.** The original recipe used a banned
> NON_MATCHING_INSN_PATCH twin; INSN_PATCH was removed as match-faking. The
> recognition pattern is still valid, but the CURRENT fix is the named-divisor
> at function scope (see `#feedback-ido-div-2-mul-fold-and-mtc1-load-delay-nops`):
> `float d = 1024.0f; ... x / d;` at function-scope (not in-loop) emits the
> target's `div.s` (lui 0x4480) instead of the reciprocal `mul.s` (lui 0x3a80).
> Verified gl_func_0005B848 landed 2026-05-24 via this lever. Historical text
> below.

`(float)v / 1024.0f` (loop-invariant power-of-2 divisor) → IDO -O2 hoists the
reciprocal `0x3a800000` (1/1024) and emits `mul.s $fd,$fs,$frecip`. Some targets
instead keep `div.s` by the literal `1024.0f` (`lui at,0x4480; mtc1; div.s`),
capping the C-body twin at ~98-99% on TWO words: the hoisted constant
(`lui ...,0x3a80` vs `0x4480`) and `mul.s` vs `div.s`. No clean C lever found to
suppress the strength reduction (writing `/1024.0f` already triggers it; a
`volatile` divisor adds a memory load the target doesn't have). BUT since
`1/1024` is exactly representable (2^-10), `x*(1/1024) == x/1024` bit-for-bit, so
forcing the target's two words via `NON_MATCHING_INSN_PATCH` (twin-only when the
default build is INCLUDE_ASM) was value-safe. Verified 2026-05-23 sibling pair
`gl_func_0005B764` / `gl_func_0005B848` (98.8-98.9→100, reloc-blind %-movers).

<a id="feedback-ido-stack-residency-plus-filled-slots-is-o1-not-o0"></a>
## Stack-residency + FILLED delay slots = -O1 register-pressure spill, NOT -O0 (un-reproducible cap)

**The trap:** `#feedback-ido-o0-loop-stack-reload-signal` says "loop reloads all
locals from sp every iteration ⇒ -O0." That signal is **necessary but not
sufficient.** Two distinct builds both reload locals from the stack:
1. **-O0** — every local on the stack, AND branch/jr delay slots **UNFILLED**
   (`b X; nop`, `jr ra; nop`, `beqz r,X; nop`). Existing project -O0 matches
   prove this: `gl_func_00008944` disassembles with `nop` in every fillable
   slot. Reproducible via `OPT_FLAGS := -O0` file-split.
2. **-O1 with original register pressure** — the optimizer spilled *some* locals
   (the ones under pressure) to the stack with reload-every-use, BUT kept others
   (e.g. a short-lived loop temp) in a register, AND the delay slots are **FILLED**
   (≈0-1 nops; the only nop is an un-fillable one like a `beqz` whose delay can't
   be safely filled). This is **not -O0**.

**Decisive test:** count `nop`s in the target and check whether a short-lived
local stays in a register.
- target nops ≈ 0-1 AND some local in a register ⇒ case 2 (-O1 pressure spill).
- target nops = "one per branch/jr" AND every local on stack ⇒ case 1 (-O0).

**Why case 2 is an un-reproducible cap with the project cc:** residency and
full delay-slot filling are mutually exclusive across the available flags.
- `-O1`/`-O2` (no `-g`): the scheduler **fills** delay slots, but the register
  allocator keeps the locals in registers (no residency) — wrong shape, wrong
  instruction count.
- `-O1`/`-O2` `-g1`/`-g2`: `-g` forces locals to the stack (debug residency),
  but **suppresses** full delay-slot filling — leaves multiple `nop`s the target
  doesn't have.
- `-g3` either register-allocates (`-O1 -g3`) or unrolls (`-O2 -g3`).

The original 1080 object got both because its *real* register pressure (from the
true source, which had whatever live ranges it had) spilled exactly those locals
at plain `-O1` while the assembler still filled slots. You can't recreate that
pressure from a minimal re-derived body, and:
- The **permuter cannot help** — it mutates C/AST; it cannot add assembler-level
  delay-slot filling, and from a `-g2` base (residency, unfilled) there is no
  C-level move that fills the slots.
- A **`volatile` base is structurally wrong** — volatile forces a reload on
  *every* read, but the target reuses a just-stored value for its final RMW
  (e.g. `out = out ^ tmp` reads the pre-store `(out|bit)&0xff` rather than
  reloading), which volatile forbids. So a volatile base always carries ≥1
  extra reload vs the target → can never reach score 0.

**Verdict:** keep `INCLUDE_ASM`; write a clean, readable NM body for
documentation. Verified 2026-05-25 on three game_libs_post functions that an
earlier session had queued as "-O0 carve candidates" but are actually this cap:
`gl_func_00070194` (44-insn CRC-5, heavy residency), `gl_func_000718C0`
(26-insn dual checksum, 0 nops), `gl_func_0003D914` (38-insn list walk, 0 nops).
The hand-derived C gets the frame, control flow (do-while, no top guard), and
instruction count exact, but the per-local spill decision and the filled slots
are not jointly reachable.

<a id="feedback-ido-o0-return-value-dead-double-b"></a>
## -O0 return-value functions emit a DEAD second `b epilogue` — toolchain-binary gap, not C-fixable

This is the definitive characterization of the "-O0 return-codegen idiom still
being reverse-engineered" hinted at under `#feedback-ido-stack-residency...` (the
`gl_func_00070194` note) and the per-function double-`b` residual seen on every
remaining -O0 **return-value** near-miss.

**Symptom.** A frame-having -O0 function ending in `return X;` compiles to:
```
lw    v0, off(sp)     # load return value
b     .epi            # the return's branch   <-- target has THIS one
nop
b     .epi            # DEAD closing-brace branch (unreachable)  <-- target lacks it
nop
.epi: lw ra ...; addiu sp ...; jr ra; nop
```
The 1080 ROM target has exactly ONE `b .epi`; our build emits TWO. The second is
unreachable (control already left via the first), so the built `.o` is +2 words
(8 bytes) long and every downstream offset shifts — the function never matches.

**Proven a TOOLCHAIN-BINARY codegen gap, NOT a C-structure issue.** The most
trivial possible return function reproduces it:
```c
extern int g();
int f(int *a0) { int x = a0[0]; g(); return x; }   /* -> double-b */
```
No source restructuring removes it (fall-through, explicit-else, `for`/`while`/
`do-while`, guard placement, early return, separate blocks — all still emit it).

**Full flag matrix (tested on IDO 7.1 AND 5.3, both identical):**

| flags | uncond `b` count | sp-reloads (caching?) |
|---|---|---|
| -O0, -O0 -g, -g1, -g2, -g3 | **2** | full (no caching) |
| -O1 -g, -O1 -g2 | **2** | full (no caching) |
| -O1 -g3, -O2, -O2 -g3 | 0 | cached (registers) |

The target needs **b=1 with full -O0 reloads** — a combination NO available
setting produces. Our cc gives either the dead double-`b` (every -O0/-O1-g
setting that preserves -O0's per-use stack reloads) or zero `b` with register
caching (every setting optimized enough to drop the dead branch also caches the
loads, which breaks the -O0 reload structure the target has).

**Why VOID -O0 functions are unaffected** (and DO land — e.g.
`gl_func_000093DC`, `gl_func_00008DAC`): with no `return`, the function emits a
single closing-brace `b .epi` that is LIVE (reachable, the only exit branch) and
present in both our build and the target. The divergence is specific to the
return's-branch + dead-closing-brace-branch pair.

**This blocks ALL -O0 return-value functions project-wide** — `func_00011B5C`
(bootup_uso_tail3a_mid.c), `arcproc_uso_func_0000012C`, `gl_func_000092F4`,
`gl_func_00008C3C`, and the rest of the o0 return-value near-misses. Do NOT
re-grind them from C; the residual is always this dead `b`.

**Not fixable within policy.** Stripping the dead branch post-cc would be
instruction-byte patching (match-faking, BANNED — see
`feedback_no_instruction_forcing_matches_policy`). The only legitimate fix is the
exact original 1080 IDO `cc` binary that elides the dead branch (our
ido-static-recomp 5.3/7.1 do not). That's a focused toolchain-acquisition task,
not a loop tick. Until then these are honest `INCLUDE_ASM`/NM caps. Verified
2026-05-25 (full matrix + trivial-repro on `func_00011B5C`).

<a name="feedback-ido-o0-local-offset-shift-not-c-reachable"></a>
## -O0 stack-offset +8 shift between mine and target: not C-reachable via decl reorder or pad locals

When an -O0 function residual is 4 stack-offset diffs where target's struct
locals are at sp+8 higher than mine but the **frame size is identical**, the
diffs are NOT shiftable from C source. The -O0 allocator's choice between
"padding below locals" vs "padding above locals" (between saved-regs and the
first local) is not driven by declaration order or type.

**Verified 2026-05-27 on `gl_func_00008A40`** (3 `register Vec3*` locals +
`Tri3i tmp` + `int pad_mid[2]` + `Tri3i raw` + `register float *src`, frame -0x58):

- Target: `tmp` at sp+0x34, `raw` at sp+0x48 (12-byte pad BELOW tmp).
- Mine (decl order tmp → pad_mid → raw): `tmp` at sp+0x2C, `raw` at sp+0x40
  (12-byte pad ABOVE raw). 4 diffs at @0x24/0x38/0x3c/0x5c.
- Swap raw and tmp decl order → still 4 diffs, just shifted differently.
- Add `Tri3i pad_low` as first local → frame grows -0x58→-0x68, 8 diffs
  (4 original + 4 from prologue/epilogue size).
- Add `long long pad_align` as first local → same as above, frame grows.

**Why no fix:** -O0 allocates locals in declaration order from a base offset,
with the choice of base (sp+0x28 vs sp+0x34) coming from the allocator's
internal selection, not visible to C. Any added local just grows the frame.

**How to apply:** for -O0 functions with 4 stack-offset diffs and identical
frame size to target, the structure is already correct — wrap NM at ~99.9 %
with a "[-O0 stack-layout cap]" label and move on. Don't grind decl-order
variants (already proven inert). This is the same cap class as register-rename
diffs in -O2: structurally indistinguishable at the C level. Distinct from
`feedback_ido_local_ordering.md` (which IS controllable for -O2 stack layout).

## Size +1 near-miss with an early `sw $aN` the target lacks: the placeholder call should PASS that arg, not be argless

A NM wrap one instruction too long (e.g. build 63 vs expected 62), where the
*build* has an extra `sw $a0, N(sp)` (an incoming-arg home) near the top that the
target does NOT have, often means a cross-USO placeholder call was written argless
(`gl_func_00000000()`) when the original PASSES the incoming arg through
(`gl_func_00000000(a0)`). When the arg is consumed by the call, IDO leaves it in
`$a0` and emits the `jal` directly; when the call takes no args, IDO has nothing to
do with the live incoming arg and homes it to the stack (the extra `sw`) — even if
the C never references it again. Fix: pass the arg the asm's first `jal` actually
uses (read the target — `$a0` at the first call site is usually the incoming arg
unchanged). Verified 2026-05-28 on gl_func_0005E190: `reloc1()` -> `reloc1(a0)`
dropped the spurious `sw a0` home, fixed the 63->62 size mismatch, and took it
98.26% -> 99.87%. This is a recurring fix in the size-mismatch near-miss vein
(K&R `gl_func_00000000()` placeholders make it easy to forget the passthrough arg);
docs/MATCHING_WORKFLOW.md notes that vein is the C-fixable one (vs same-size
allocator/operand caps).

## Size -1 near-miss (mine too SHORT) with a store-then-read of the same field: IDO CSE'd the reload — force it with a volatile read

The mirror of the size+1 / argless-placeholder recipe above. When a NM wrap is one
instruction too SHORT and the target has a `lw node, N(base)` reload that mine
lacks, look for a `base->N = X; ... node = base->N;` pattern in the C: IDO proves
`base->N == X` (the value just stored) and reuses X's register instead of reloading
from memory, dropping the `lw`. The target's original compile reloaded. Force the
reload by reading through a volatile-qualified pointer so IDO can't fold it:
`node = (int*)((volatile int*)base)[N/4];`. This is faithful (volatile read = a real
`lw`, the exact instruction the target emits) and not match-faking — the bytes come
from a genuine compile. Verified 2026-05-28 on gl_func_0003FF44: `self[0x10/4] =
handle; ... node = self[0x10/4];` CSE'd node==handle (-1 insn, 95.68%); the volatile
read restored the reload and the 38-insn size -> 98.18% (residual was then a pure
reg-assignment/frame-spill nuance). Companion to the size+1 argless-placeholder
recipe — together they cover much of the game_libs size-mismatch near-miss vein
(docs/MATCHING_WORKFLOW.md): +1 long = an arg needlessly homed (pass it); -1 short =
a reload CSE'd away (volatile it).

## Telling a FIXABLE size-mismatch near-miss from a CAP one (game_libs +/-1 vein triage)

After landing 3 game_libs +/-1 size-mismatch fixes (gl_func_0005E190, 0005C6C4,
0003FF44) and confirming ~8 others are caps (2026-05-28 sweep), the triage rule for
the extra/missing `sw aN` / `lw` signature:

FIXABLE (do the fix):
- **Extra `sw aN` (mine +1 long) AND the target's first `jal` USES aN** (aN is the
  incoming arg, unchanged, at the call site): the C wrote an argless placeholder
  `gl_func_00000000()` — pass aN. The arg is consumed by the call, not homed.
- **Missing `lw field` (mine -1 short) where `base->field = X` was just stored**:
  IDO CSE'd the reload with X's register. Force it with a volatile read
  `(int*)((volatile int*)base)[field/4]`.

CAP (leave NM, don't grind):
- **Extra/missing `sw aN` that is a DEAD spill filling a jal delay slot** — aN is
  homed to its shadow (sp+frame+N) AND spilled again to a low local slot, but aN is
  dead after the call (the code reloads OTHER args). IDO's delay-slot-filler chose
  the dead spill; `volatile int *p=&aN` produces the wrong (addiu+lw) form or no-op.
  (gl_func_0003EAE0, 0002DD58, 0003FA54.)
- **Unused-arg-save**: target saves an incoming arg the function never reads;
  asymmetric (saves a0 not a1, or vice versa). Not C-flippable. (0003F4F0, 0003F444.)
- **Duplicate float-const load** (target `mtc1 at,$fX; mtc1 at,$fY` — same const in
  two FP regs): IDO CSEs the const into one reg from C. (0002DF98.)
- **$s / FP register renumber** (s1<->s2, f4<->f12 swapped throughout): allocno-order
  artifact. (0002A55C, 0000D318.)
- **Constant-fold** (`+0xFF000000 - 1` folds to `+0xFEFFFFFF` lui+ori): robust against
  named/register/volatile locals. (0005AFD4.)
- **Force-register-copy** (target `or aN,a0,zero` preserving a0): IDO won't emit the
  copy from C, and GCC `register asm("$N")` is rejected by IDO cfe. (000671E4.)

Quick test: decode the target's first call site — if the extra-homed arg is a live
call argument there, it's the passthrough fix; if it's dead-after-call, it's a cap.

## Float passed into a callee's INT-register arg slot = raw-bits reinterpret (`*(int*)&f`), NOT a conversion

When a function forwards a float value into an argument position that the callee
takes as an INT register (a2/a3/stack, i.e. arg index >= the float that landed in
f12/f14), the asm loads it with a plain `lw` (raw 32-bit copy) — NOT `trunc.w.s` +
`mfc1`. That's a reinterpret of the float's bits, not a float->int conversion. In C,
pass `*(int*)&f` (or a union), declaring the callee param `int`. Passing the `float`
directly to an `int` param makes IDO emit the conversion (`trunc.w.s; mfc1`) — wrong
bytes + wrong size. Tell which from the target asm: `lw aN,off(sp)` feeding the call
= reinterpret; `lwc1 + trunc.w.s + mfc1` = genuine conversion.
Verified 2026-05-29 matching gl_func_0005C43C (9-arg float fn): `r2 = cb(a1, a2,
*(int*)&a4, *(int*)&a5)` — a4/a5 are floats (used as float in another call) but
forwarded as raw int-reg bits here. Companion facts for such multi-float-arg fns:
(1) the callee needs a float-typed alias (undefined_syms `gl_func_00000000_<suffix>
= 0x0` + `extern float alias(float,float,int,int)`) so f12/f14 stay single-precision
rather than K&R double-promoting (see #feedback-alias-extern-via-undefined-syms in
MATCHING_WORKFLOW); (2) a stray `int _pad;` may be needed to reserve the exact frame
slot (IDO's frame came out 8 bytes short without it).

<a id="feedback-ido-regalloc-renumber-matching-techniques"></a>
## Register-allocation-renumber caps: the matching toolkit (researched from OoT/sm64/mm IDO guides + permuter, 2026-05-29)

The hardest 1080 near-miss class: logic + instruction COUNT match, but a value
lands in a different register than the target, usually cascading (e.g. const `40`
in `$a2` vs target `$v1`, then every downstream `multu`/`addu`/`lw` shifts; or a
reloaded pointer in `$a3` vs `$t7`/`$t9`; or FP `$f4` vs `$f18` through a matrix
multiply). These are NOT operand-order (use the assignment-expr lever for those)
— the instructions are identical, only register NUMBERS differ. The permuter
FLOORS on them (random mutations don't systematically target "put X in $t7").
But they ARE solvable in principle — the original source structure colored
correctly. Toolkit, in priority order:

**1. IDO colors registers in a FIXED order, by first-USE / expression-list
position.** Integer order: `$v0,$v1,$a0,$a1,$a2,$a3,$t0,$t1,$t2,$t3,$t4,$t5`,
then spill. A candidate is colored when its value's FIRST USE appears (not its
declaration). So to flip a value from `$a2`→`$v1` (an earlier reg), make its
first use appear earlier relative to competing candidates, OR raise its priority
(more refs / shorter live range — Chow–Hennessy priority coloring). Reordering
DECLARATIONS alone often does nothing; reorder the STATEMENTS that first touch
the value. (Tested-negative on mgrproc_uso_func_00001594: swapping `idx*0x28`→
`0x28*idx` did NOT move the const's reg — operand order ≠ first-use order.)

**2. Dedup / GVN position drives the cascade.** IDO de-duplicates common
subexpressions, and the dedup'd expression moves to a different spot in the
expression list, shifting every downstream register number — exactly the
cascading-renumber symptom. Lever: deliberately DUPLICATE a loop-invariant
subexpression/constant (write it inline at multiple sites) so CSE folds it into a
different list position. Inverse: pull a CSE'd value into a named local to STOP
the fold.

**3. Live-range split around calls** (for "value kept in $a3, moved to $a0 via
`or a0,a3,zero`" vs "kept in $a0" caps): split the value's live range with an
intermediate assignment around the call so it must reload into a distinct temp.
Also `a = b + c;` → `a = b; a += c;` changes a value's register class.

**4. Permuter passes to drive MANUALLY (not just random mode).** The randomizer
has regalloc-targeted passes random mode only hits by luck: `perm_pad_var_decl`
(inserts unused vars to shift allocation), `perm_refer_to_var` (dummy `if(var){}`
— comment: "regalloc can act at a distance"), `perm_reorder_decls`,
`perm_duplicate_assignment`, `perm_temp_for_expr`. Wrap candidates in
`PERM_GENERAL(...)` / `PERM_RANDOMIZE(...)` macros in the C and run the permuter
in manual mode so it EXHAUSTIVELY tries combinations rather than random-walks.
(Plain random mode floored historically — that is NOT proof the function is
unmatchable; it's proof random didn't find it. Try manual PERM_ + the dump.)

**5. THE SYSTEMATIC DIAGNOSTIC — IDO's own regalloc dump — currently BLOCKED in
our toolchain (fixable).** `cc ... -Wo,-zdbug:6` dumps the priority-based-coloring
trace; `-Wo,-zdbug:5` dumps live ranges + the regalloc bit-vectors. This tells
you EXACTLY which candidate grabs the contested color first, so you target the
fix instead of blind-permuting. **BUT** all `-zdbug` levels currently crash our
static-recompiled IDO (it formatted floats via `ecvt(3)`, an `assert(0)` stub).
**UNLOCKED 2026-05-29** — implemented `wrapper_ecvt`/`wrapper_fcvt` in
`tools/ido-static-recomp/libc_impl.c` (via `snprintf("%.*e"/"%.*f")` parse →
scratch `INTBUF_ADDR` slice → `MEM_S8`/`MEM_S32`; ~110 lines) and rebuilt
(`cd tools/ido-static-recomp && make VERSION=7.1`). VERIFIED codegen-SAFE: ecvt
is only on the dump path, and all spot-checked matches (00003890, 73C0, 00003FAC,
F49C) still byte-match after the rebuild. **HOW TO USE THE DUMP:**
- `cc ... -Wo,-zdbug:6 -o x.o x.c` writes the trace to a file named **`uoptlist`
  in the CWD** (NOT stdout/stderr — that's why it looked empty). One function per
  invocation; for a whole-file build, build the file with the flag and the
  `uoptlist` contains every function's section (grep the function name).
- Format: a UCODE expression-list table (`index|bit kind op l r`; `isvar P =`
  param, `isop umpy/uadd/uilod/ustr =` ops) followed by `N: N assigned
  (unconstrained) R` lines = candidate→register coloring, plus live-range stats
  (`numlr`, `numlu`). The `assigned` lines tell you EXACTLY which candidate grabs
  the contested register and in what order — so you target the first-use/dedup/
  pad fix (techniques 1–3) instead of blind-permuting.
- NOTE: `tools/` is gitignored (per-machine build), so this `libc_impl.c` patch is
  LOCAL — re-apply via `scripts/patch-ido-ecvt-dump.py <libc_impl.c>` + rebuild
  (`make VERSION=7.1`) after a clean `tools/` checkout, or upstream it to
  decompals/ido-static-recomp. The rebuild relinks the shared cc; codegen is
  identical (ecvt is dump-path-only) so only the brief relink window matters.
- **SCOPE LIMIT (verified 2026-05-29, levels 1–99):** the `uopt -zdbug` dump shows
  the HIGH-LEVEL UCODE candidate coloring (`isvar`/`isop` list + `N: N assigned R`
  + live-range stats), but does NOT expose the FINAL hardware-register / spill-
  reload-temp assignment — that is chosen in the later **`ugen`** phase, which
  `uopt -zdbug` never prints. So the dump helps for true variable-coloring caps
  (a named live-range landing in a different reg, decided in uopt) but is NOT
  sufficient for the two caps probed: `timproc_uso_b1_func_00000DEC` (spilled ptr
  reloaded into `$a3` vs target `$t7`/`$t9` — a spill-reload-temp choice) and
  `mgrproc_uso_func_00001594` (literal `40` in `$a2` vs `$v1` — a constant is not
  a live-range candidate at all). For those, the contested register is picked
  downstream of the dump → fall back to the C-level levers (first-use reorder,
  CSE/dedup-shift, live-range split, pad-var) + permuter. Open follow-up: does
  `ugen` have its own debug dump exposing the final reg map? (not yet checked.)
  - **Third example (2026-05-30, `func_00007C74` bootup_uso) — spill-SLOT
    coalescing is also `ugen`-side, not in the dump.** This cap is the
    reuse-vs-abandon of a *dead* spill slot (mine reuses a0's freed `sp+0x18`
    for `link`; target abandons `0x18` and gives `link` a fresh `sp+0x20`,
    frame 0x20 vs 0x28). The dump DID surface the structure that drives it — 3
    spilled live ranges as `-ve save` candidates 23/24/25 in reg-alloc-prep,
    param a0 (cand 12) "split out 26", and the summary `rlods=3 rstrs=3
    numcalls=3` — but, exactly per the scope limit, it prints NO stack offset
    per candidate, so it can't tell you whether a freed slot gets coalesced.
    Net: the dump is a good *confirmation* tool for spill caps (it proves the
    spill count and which values spill, ruling out "missing pad" theories) but
    NOT a *crack* tool — the slot-packing decision is downstream. Dump-confirmed
    intractable; left NM.

**Honest limit:** the permuter README states there is no register-allocation-
specific randomizer and it "finds changes that improve regalloc by accident." When
two candidates have identical priority + live range, the order is a list-insertion
artifact reachable only by perturbing expression-list order (techniques 1–3). If
the dump shows that and 1–4 all fail, `#ifdef NON_MATCHING` is the correct outcome.

Sources: OoT `docs/guides/-O2 decompilation (for IDO 5.3).md` (register order, GVN
dedup, saved-reg rewrite, `-zdbug` levels); decomp-permuter README + `randomizer.py`
(PERM_ macros, passes); Chow & Hennessy, "Priority-Based Coloring Approach to
Register Allocation" (the algorithm IDO implements).

<a id="feedback-ido-unroll-trip-counter-representation"></a>
## IDO-unrolled loop residual trip-counter representation (count-groups vs count-elements) is NOT C-controllable

_When IDO -O2 auto-unrolls a simple `for(i=0;i<N;i++){ body(i); }` by factor K, it strength-reduces array accesses to pointers and emits a pure residual trip-counter (a register not used for addressing). That counter has two equivalent representations: count **elements** (`0, K, 2K, … < N`, increment `+K`) or count **groups** (`0 … N/K`, increment `+1`). The two are arithmetically identical (same iteration count) but produce DIFFERENT immediates in the bound-`addiu`/`li` and the increment-`addiu`. If the target picked the representation IDO doesn't pick for your source, you get a 2-instruction operand-immediate cap with the entire unrolled body otherwise byte-identical._

**Verified 2026-05-29 on `game_libs_func_0005BDC0`** (16-element reciprocal loop `dst[i] = 1.0f/src[i]`, IDO unrolls 4×). Target counts groups (`li $4,4`; `addiu $2,$2,1`; `bne $2,$4`); our build counts elements (`li $4,16`; `addiu $2,$2,4`). The 4 `div.s` + `swc1 -16/-12/-8/-4` body and both pointer `+16` increments match exactly — only the 2 counter immediates differ (99.92%).

**What was tried (all emit IDO's same element-scaled counter — `li 16`/`+4`):**
1. Natural `for(i=0;i<16;i++) dst[i]=1.0f/src[i];`
2. Manual grouped unroll: `for(i=0;i<4;i++){ dst[0..3]=…; src+=4; dst+=4; }`
3. Indexed grouped: `for(i=0;i<4;i++){ dst[i*4+0..3]=…; }`

IDO normalizes all three to the same internal loop, then re-unrolls 4× with its own element-scaled counter. The group-counter form the target used is an IDO loop-optimizer internal choice (possibly IDO-version- or surrounding-pressure-dependent), not reachable by reshaping the source loop.

**How to apply:** if an otherwise byte-identical IDO-unrolled loop differs ONLY in the bound + increment immediates of a pure trip-counter, recognize it as this representation cap and leave it NM — don't grind loop rewrites or the permuter.

**Related:**
- [final-add operand order in FPU reductions](#feedback-ido-fpu-reduction-operand-order) — sibling "byte-identical body, one encoding choice differs" cap.

<a id="feedback-ido-inline-cached-local-for-frame-shrink"></a>
## Inline a cached load-deref local into the loop body to drop its stack slot and shrink the frame

_Sibling lever to inline-everything (which targets GPR-renumber by forcing fresh-temp reloads at each use). This one targets FRAME-SIZE diffs: when a near-miss has a too-large frame by exactly an aligned slot's worth (+8 typical, since IDO usually rounds to 8) AND a cached `T x = *load_chain(...)` local that's used only inside a single loop, inlining the load chain at each loop use removes the local's stack slot. The frame shrinks; spill offsets for OTHER live values align down to the target's._

**Verified 2026-05-29 on `titproc_uso_func_00000418`** (33-insn FP selector). Original C cached `unsigned short mask = **(unsigned short**)((char*)&D_00000000 + 0x154);` then used `mask & (1 << index)` inside the do-while loop. Diff signature: frame size 40 vs target 32, spill `selected` at sp+28 vs target sp+24, plus matching sw/lw at the corresponding offsets — **6 diffs total**, all on the SAME 8-byte-frame-overhead root.

Fix: inline the two-level load into the loop body's condition:
```c
do {
    if ((**(unsigned short**)((char*)&D_00000000 + 0x154) & (1 << index)) != 0) {
        selected = index + 1;
    }
    index++;
} while (index != 8);
```
Result: frame 40 → 32, spill 28 → 24, 4 of 6 diffs closed. Residual 2 = a scheduler-decision order swap on independent instructions (`lw $5,24(sp)` vs `or $2,$0,$0`), not C-controllable.

**How to apply:** if a near-miss has a frame size that's exactly 8 bytes too large AND any cached load-deref-local-only-used-in-a-loop, inline it before touching anything else. Cheap, often-decisive. Doesn't fix GPR-renumber cascades (that's inline-everything's job).

**Limits:**
- Only works when the cached value is stable across loop iterations (no observable difference between caching and re-reading). If the underlying memory could change mid-loop, inlining IS semantically different — use a `volatile` re-read if you want both correctness and inlining.
- Doesn't help if the local is shared between multiple call sites outside the loop (the savings are exactly one stack slot — inlining into N sites costs N loads; the slot-drop has to be the dominant signal).
- Won't crack pure-scheduler residual diffs (final 2 diffs here are a register-init / stack-preload order swap independent of frame layout).

**Related:**
- [Inline a cached local-in-$v0 to force fresh-temp reload (GPR-renumber lever)](#feedback-ido-fp-commutative-operand-order-assignment-lever) — sibling lever for the register-cascade subclass.

<a id="feedback-ido-block-scope-cached-local-for-frame-shrink"></a>
## Block-scope a re-assigned cached local to drop its `$s` save and shrink the frame

_Sibling lever to inline-cached-local-for-frame-shrink. That one targets a frame +8 from a local's stack-slot overhead; this one targets a frame +8 from a local's `$s`-save+restore overhead._

The pattern: a function has a cached local like `int *root` re-assigned mid-function (the SAME expression on both sides — `root = *(int**)((char*)&D + 0x134);` at two points, between two segments of work). IDO sees one long-lived variable `root` with reads on both sides of intervening calls, so it promotes `root` to a callee-saved `$s` register (e.g. `$s0`). The cost: `sw $16, 24(sp)` + `lw $16, 24(sp)` at function boundaries → frame grows by 8 bytes versus a target that uses a temp register for each segment's `root` and reloads from memory between segments.

**Fix:** wrap each segment in its own block, declare `root` fresh inside each:
```c
gl_func_00000000(a0, a1);
{
    int *root = *(int**)((char*)&D_00000000 + 0x134);
    // segment 1's work using root
}
{
    int *root = *(int**)((char*)&D_00000000 + 0x134);
    // segment 2's work using root
}
```
Each block's `root` has a per-segment lifetime; IDO uses a temp register ($3-class) inside each block, the cross-call save/restore disappears, and the frame shrinks by 8.

**Verified 2026-05-29 on `h2hproc_uso_func_00000E04`** (slotC4+slotCC dual-channel processor, frame -56 → -48 matching target's -48, insn count 41 → 43 matching target's 43; 38 → 37 diffs).

**How to apply:** if a frame is +8 too large AND the C body has a cached local re-assigned mid-function with the same expression on each side, block-scope the local per segment. Cheap and decisive when the pattern matches.

**Limits:**
- Only works when the segments DON'T need to share the cached value (i.e., target also reloads). If the target keeps the value in a saved register across both segments, block-scoping would diverge from target.
- Doesn't fix the residual `&D_00000000`-in-`$s0` pattern: a target that ALSO caches the global base in a saved register requires keeping that base alive across calls. `char *D_base = (char*)&D_00000000;` hoist gets inline-folded; `register char *D_base` regresses the frame the other way. The base-in-$s0 residual is its own subclass.

**Related:**
- [Inline a cached load-deref local into the loop body](#feedback-ido-inline-cached-local-for-frame-shrink) — sibling lever for the stack-slot-overhead subclass.
