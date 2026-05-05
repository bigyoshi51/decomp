# Ido Codegen

> IDO 7.1 codegen quirks: how the compiler emits specific patterns, and what C-source shapes do or don't match a given asm.

_117 entries. Auto-generated from per-memo notes; content may be rough on first pass — light editing welcome._

## Quick reference by sub-topic

### branch likely / bnel

- [IDO emits the if-body's first store TWICE around a beql — once in delay slot (annulled on taken) + once at fall-through](#feedback-ido-beql-speculative-store-double-emit) — _For `if (cond) { dst = val; ... }` IDO -O2 emits `beql cond_reg, $0, end; sw val, dst_off(dst_reg)` in the delay slot AND ALSO `sw val, dst_off(dst_reg)` at the fall-through.
- [Asm `blez/blezl` vs `bne/beql` distinguishes `> 0` (signed) from `!= 0` (eq) source](#feedback-ido-blez-vs-bne-signed-compare) — When target asm uses `blez $rs, X` or `blezl $rs, X` for a conditional, the C source MUST be `if (val > 0)` (signed comparison), NOT `if (val != 0)`.
- [IDO `bnel` with value-in-delay-likely comes from C with the EQUAL case in the `if` arm](#feedback-ido-bnel-arm-swap) — When the target asm has `bnel $a, $b, .exit; or v0, zero, zero` (branch-likely with "set 0" in delay-likely) and the other path sets v0=1 via `b + addiu v0, zero, 1`, write the C with the `==` case inside the `if`, not…
- [bnel-likely with shared store-in-delay = `if (!cond) helper(); shared_store;`](#feedback-ido-bnel-shared-store-after-helper) — When asm shows `bnel ptr,zero,+N; sw <val>,off(reg) [delay-likely]; jal helper; ...; sw <val>,off(reg)` (same store on both paths), the C source is `if (cond == 0) helper(); store;` — the store happens both as…
- [IDO bnel tail-merging routes the false-path epilogue through the true-path's register-restore tail (cosmetic, ~99 % cap)](#feedback-ido-bnel-tail-merge-register-restore) — When the function body is `if (cond) { several jal calls }` and the true path ends with reload-args-then-jal patterns like `lw a0,0x18(sp); jal; lw a1,0x1C(sp)`, IDO sets the bnel branch target to the MIDDLE of those…
- [For float-predicate functions with conditional body, prefer positive-arm form to avoid branch-likely](#feedback-ido-branch-likely-arm-choice) — `if (!cond) return 0; body; return 1;` triggers IDO to emit `bc1tl`/`bnezl` (branch-likely).
- [IDO -O2 emits branch-likely for empty-body do-while loops; move call into the body to get plain branch + nop delay](#feedback-ido-empty-body-do-while-emits-branch-likely) — _`do { } while (func() & MASK)` (empty body, call in condition) compiles to beqzl/bnezl (branch-likely) with the call's lui hoisted into the annulled delay slot.
- [IDO -O2 sparse-case switch (case 0 + case 1) compiles to 3-arm beql dispatch with delay-slot pre-loads — unreachable from C if-else; switch is also rejected (.rodata jumptable)](#feedback-ido-sparse-switch-beql-preload-unreachable) — _When target asm shows `addiu $at,zero,1; beql v0,zero,caseA; <lw delay>; beql v0,$at,caseB; <lw delay>; b end; <lw ra delay>` (3-arm beql dispatch with each delay slot pre-loading the case body's first lw), this is a…
- [bc1fl with target=epilogue and `lw ra,X(sp)` in delay slot is a CONDITIONAL-CALL marker, not a clamp — the if-block guards a `jal` between here and the epilogue](#feedback-ido-bc1fl-skips-jal-to-epilogue) — _Diagnostic for misreading IDO -O2 trailing FP conditionals: when target's last bc1fl jumps to the epilogue with `lw ra,X(sp)` in the delay slot, it's NOT a clamp/store guard; it's `if (!cond) jal()` where the jal sits between the bc1fl and the epilogue. Decode the C as `if (cond_complement) func();`._

### FPU / float specifics

- [IDO -O2 folds `/2.0f` to `*0.5f` (different opcode); -mips2 schedules across mtc1 load-delays while -mips1 emits strict nops](#feedback-ido-div-2-mul-fold-and-mtc1-load-delay-nops) — _Two IDO codegen rules surfaced on bootup_uso func_000102A4. (1) `expr / 2.0f` compiles to `mul.s ..., 0.5f` (lui 0x3F000000, mtc1, mul.s) instead of `div.s ..., 2.0f` (lui 0x40000000, mtc1, div.s).
- [IDO -O2 emits double return into $f0+$f1 pair, not $f0+$f2 — kills "force $f2 via double-trick" theory](#feedback-ido-double-return-uses-f0-f1-not-f2) — For `double f(void){return 0;}`, IDO -O2 emits `mtc1 zero,$f1; mtc1 zero,$f0; jr ra; nop` — upper-half lands in $f1 (o32 paired-register convention), NOT $f2.
- [Function reads $f0 at entry without setting it — caller-context "implicit zero" pattern](#feedback-ido-f0-implicit-zero-at-entry) — Some IDO -O2 functions store $f0 (float return reg, NOT a standard arg) to memory at the start of the body.
- [IDO -O2 always folds `return 0.0f` paths through $f0 directly — `mtc1 $0, $f2; mov.s $f0, $f2` unreachable from C](#feedback-ido-f2-intermediate-unreproducible) — Target 4-insn leaves that return 0.0f via an intermediate ($fN != $f0) like `mtc1 $0,$f2; nop; jr $ra; mov.s $f0,$f2` cannot be reproduced from any tested IDO-O2 C body — literal, local var, volatile local (→stack…
- [IDO's fabs idiom leaves an unreachable `mov.s` at the merge point — branch-likely artifact unmatchable from C](#feedback-ido-fabs-dead-mov) — _IDO emits fabs as `bc1fl fall_taken; mov.s fDst, fSrc (taken=positive); b merge; neg.s fDst, fSrc (delay-always=negative); mov.s fDst, fSrc (fallthrough, unreachable); merge:`.
- [IDO -O2 final-add operand order in FPU reductions (`add.s fd, fs, ft`) follows source evaluation; can't easily flip without changing load order](#feedback-ido-fpu-reduction-operand-order) — _For dot products and chained FPU adds like `a[0]*b[0] + a[1]*b[1] + ... + a[n]*b[n]`, IDO emits the final reduction `add.s fd, fs, ft` with `fs` = running-sum register and `ft` = last-product register.
- [K&R-declared extern can't be called with float args under IDO (no way to get direct jal)](#feedback-ido-knr-float-call) — _In game_libs (1080), `gl_func_00000000` is declared as `extern int gl_func_00000000();` (K&R / no prototype).
- [Target asm with `mfc1 $aN, $f12` (float-bits-to-int-reg) is hard to reproduce from IDO C](#feedback-ido-mfc1-from-c) — When the target has a single `mfc1 aN, $f12` instruction converting a float arg's bits to an int register for passing as arg, IDO's C compiler emits a stack round-trip (swc1 + lw) instead — at least 14 C variants tried…
- [A SINGLE named float local in tight FPU code globally restructures IDO's entire FPU schedule — not just the immediate computation](#feedback-ido-named-float-local-globally-shifts-fpu-schedule) — _In tightly-scheduled FPU code (dot products, vector reductions), introducing ANY named `float` local — even just to name an intermediate sum — shifts IDO's FPU register allocation and instruction order across the WHOLE…
- [IDO -O2 needs named float locals to load-batch all loads before stores; inlined float derefs interleave load/store](#feedback-ido-named-float-locals-enable-load-batching) — When asm shows `lwc1 f14; lwc1 f12; lwc1 f2; lwc1 f0; swc1 f14; swc1 f12; swc1 f2; swc1 f0` (4 loads then 4 stores), the C source MUST have 4 named float locals.
- [O32 passes floats in $aN when preceded by a non-float arg — use `mtc1 aN, fM` reconstruction](#feedback-ido-o32-float-in-int-reg) — _When a function signature is `(int_like, float, ...)`, MIPS O32 passes the float in $a1 (the int register), not $f14.
- [o32 mixed-mode ABI — when first arg is int, a float second-arg passes in $a1 (int reg) not $f14, triggering `mtc1 $a1, $f12` at function entry](#feedback-ido-o32-mixed-mode-float-in-a1) — _o32 reserves $f12/$f14 for floats only when ALL leading args are floats.
- [IDO target `swc1 $f0, N(sp)` x4 at entry WITHOUT preceding `mtc1 $0, $f0` — $f0 inherited from caller](#feedback-ido-swc1-f0-without-mtc1) — Some functions store $f0 to multiple stack slots at entry (e.g. `swc1 $f0, 0x34..0x40(sp)` for a 4-float out-buffer) without any `mtc1 $0, $f0` to initialize $f0 first.

### argument / save register

- [IDO target's 3-save reg pattern (copy to free reg + stack spill + stack reload) for arg preservation isn't reachable from natural C](#feedback-ido-3save-vs-2save-arg-preserve) — _When target asm preserves an arg ($a0) across a jal via THREE moves — `or $aN_free, $a0, $zero` (copy to a free arg-reg) + `sw $aN_free, off(sp)` (spill the copy) + `lw $aN_free, off(sp)` (reload after call) — IDO -O2…
- [IDO bnel + delay-likely-move + fall-through alloc = "out = ptr ? ptr : alloc(N)" ternary](#feedback-ido-alloc-or-passthrough-ternary) — USO functions emit a 4-insn `bnel ptr,$0,+6 / move v1,ptr [delay-likely] / jal alloc / addiu a0,$0,N` pattern for the conditional-alloc ternary.
- [Pull `a0->field` into a named local when the same call overwrites $a0 with a new address](#feedback-ido-arg-deref-before-a0-overwrite) — For calls like `func(&SYM, *(int*)(a0 + N), 0)` where $a0 is about to be reassigned to &SYM, inlining the `*(int*)(a0+N)` deref makes IDO spill a0 early and reload via a fresh temp ($t6).
- [Function that never sets or spills a0 is forwarding caller's a0 to a callee](#feedback-ido-arg-passthrough) — If asm body shows a0 is never touched (no `sw a0, N(sp)`, no `or a0, ..., zero`, no `addiu a0, ..., N`) but a jal still uses it, the C takes a0 as a parameter and passes it through unchanged
- [IDO picks $a1 (not $a3) to save an arg across a jal — can't reliably flip from C](#feedback-ido-arg-save-reg-pick) — _When a function spills its incoming `a0` to survive a `jal`, IDO -O2 consistently allocates $a1 as the holding register: `or a1, a0, zero; sw a1, N(sp); ...jal...; lw a1, N(sp)`.
- [IDO schedules arg-save `or sN, aN, zero` into bne delay slot when an immediate `if (aN == 0)` test follows the prologue](#feedback-ido-arg-save-to-sreg-in-bne-delay) — When function body starts with `if (a0 == 0)` after prologue, IDO -O2 schedules `or s0, a0, zero` (the s-reg copy of a0) into the bne delay slot rather than into the inter-spill gap.
- [IDO -O2 hoists `move sN, aM` above adjacent jal when no data dependency; source order `jal; p = a0;` doesn't keep them in source order](#feedback-ido-hoists-save-reg-init-above-jal) — When you write `func(...); p = a0;` in C, IDO -O2 schedules the `move sN, aM` (the p=a0 emit) BEFORE the jal because there's no data dep.
- [Inlining intermediates into a fn-ptr call expression drops IDO's defensive arg-register spill](#feedback-ido-inline-fnptr-call-drops-arg-spill) — _When IDO -O2 spills caller-arg regs ($a1) defensively before an indirect call, factoring out the named local intermediates and inlining the deref chain INTO the call expression keeps the arg dead at the spill point —…
- [IDO emits extra `andi`/`sll+sra` for narrow (char/short) function parameters](#feedback-ido-narrow-arg-promotion) — Declaring a function arg as `char` or `short` makes IDO insert byte/halfword promotion at the prologue that breaks matching.
- [IDO does not CSE repeated immediate args at -O2](#feedback-ido-no-cse-arg-immediates) — Passing the same literal constant (e.g. 1) to multiple stack-arg slots and a register-arg in one call materializes a fresh `addiu rN, zero, K` per slot — no shared register
- [IDO pre-call outgoing-arg spills (`sw aN, N(sp)` before jal for args loaded from globals) are not C-reproducible for K&R callees](#feedback-ido-precall-arg-spill-unreachable) — _Some IDO-compiled functions emit extra `sw $a1, 4(sp); sw $a2, 8(sp)` stores IMMEDIATELY before a jal, saving the OUTGOING arg values (just loaded from global memory) into the caller's arg-save slots.
- [IDO -O2 empty `void f(int a0) {}` produces exactly `jr ra; sw a0, 0(sp)` — save-arg sentinels ARE matchable from C](#feedback-ido-save-arg-sentinel-empty-body) — _The 2-insn "save-arg-to-caller-shadow-space" sentinel (`jr ra; sw a0, 0(sp)`) — previously documented as non-C-expressible — IS matchable from IDO -O2 with the trivial C body `void f(int a0) { }`.
- [Fix IDO unused-a0 spill by passing a0 through to the jal callee](#feedback-ido-unused-arg-fix-pass-to-callee) — When a function has signature `void f(int a0, int *a1)` where a0 appears unused in the body but is a real (required) parameter to preserve a1's register assignment, IDO spills a0 to the caller's arg-save slot (extra `sw…
- [IDO spills unused `int a0` param to caller-slot sp+frame when function contains a jal](#feedback-ido-unused-arg-save) — _If the target asm has `sw a0, frame_size(sp)` at entry (into caller's arg-save slot) but you see no use of a0 later, declaring `void f(int a0) { ...jal... }` with an unused a0 parameter reproduces it — IDO -O2 does NOT…

### scheduling / delay slot

- [IDO folds prologue sw ra into early-return beq's delay slot](#feedback-ido-early-return-ra-delay-slot) — When `if (a0 == 0) return;` is the first statement, IDO moves the prologue `sw ra` into the beq's delay slot — write the C naturally and the scheduler handles it
- [IDO `-g3` disables delay-slot filling while keeping -O2 optimization — unfilled-`sw; jr; nop` IS matchable](#feedback-ido-g3-disables-delay-slot-fill) — _Compiling with `-O2 -g3` produces unfilled-delay-slot epilogues (`sw; jr ra; nop` instead of `sw; jr ra; sw(delay)`).
- [IDO -g does NOT suppress delay-slot fill (unlike KMC GCC -g2) — don't borrow the Glover technique](#feedback-ido-g-flag-does-not-suppress-delay-slot-fill) — _KMC GCC -g2 disables delay-slot reordering (per project_compiler_findings.md).
- [IDO -O1 target `lw $sN, spill(sp)` in jal delay slot — can't force via explicit C assignment](#feedback-ido-o1-delay-slot-s-reload) — rmon-style -O1 funcs spill arg `a0` to caller slot, then fill the first jal's delay slot with `lw $s0, SPILL(sp)` to promote msg into a callee-saved reg for later use.
- [Swap source order of two stores to let IDO's scheduler fill a jal delay slot with the SECOND-listed store](#feedback-ido-swap-stores-for-jal-delay-fill) — _When target asm has `sw $tA, OFFSET_X(a0); jal func; sw $tB, OFFSET_Y(a0)` (two consecutive stores with the second in the delay slot), write the C with the OTHER order: put the X-offset store SECOND in source.
- [IDO -O1: `register u32 v = expr & MASK; func(..., v);` produces andi-pre-jal pattern](#feedback-ido-o1-andi-pre-jal-via-register-u32-mask) — _When target has `andi tN,X,MASK; jal; or argReg,tN,zero` (3-insn mask-pre-jal vs natural delay-slot fold), use `register u32 v = expr & MASK; func(..., v);` block-local. The `& MASK` on the initializer (not the use) commits IDO to emitting the and pre-jal._

### $s register allocation

- [At IDO -O0, count target's `sw sN, ...` saves to set the EXACT number of `register T x;` declarations](#feedback-ido-o0-register-count-matches-target-s-saves-exactly) — _At -O0, IDO promotes register-typed locals to s0/s1/s2/... in declaration order.
- [IDO -O2 global s-register allocator is NOT driven by local declaration order](#feedback-ido-sreg-order-not-decl-driven) — _`feedback_ido_local_ordering.md` covers STACK OFFSETS (first-declared → highest sp offset).

### constant fold / immediate / CSE

- [IDO -O2 constant-folds the load-address even when the base is a register-declared local](#feedback-ido-constant-address-load-fold-inevitable) — _For `arg = *(int*)((char*)base + N)` where base = `&D_constant`, IDO emits a fresh `lui+lw` rather than `lw arg, N($base_reg)` even with `register` keyword.
- [IDO -O2 globally CSE's `&D_00000000` (and other large-extern bases) into a single $sN, breaking per-iter lui reloads in unrolled-loop matches](#feedback-ido-global-cse-extern-base-caps-unrolled-loops) — _When a function references the same large-extern symbol (`&D_00000000`, `&func_00000000`, etc.) at MANY sites, IDO -O2 caches the high half (lui+addiu) into a single saved register ($s3 typical) and reuses it across…
- [IDO load-CSE swap to flip $v0/$v1 regalloc](#feedback-ido-load-cse-swap-v0-v1) — Decl-order trick that flips IDO's $v0/$v1 assignment for a chained pointer-deref pair via CSE
- [Inlining `(*a0)` 3+ times instead of caching `p = *a0` flips IDO from $tN to $v1 for the int** spill-load](#feedback-ido-inline-deref-vs-cache-flips-vN-tN) — _When target keeps a `int**` arg in $v1 across post-call uses (multiple `lw tN, 0(v1)` reloads), explicit caching `p = *a0;` lets IDO pick a $t-reg instead. Inlining `(*a0)` at every use forces 3 separate reloads which IDO assigns via $v1._
- [Type-different unique externs (`int X` + `char Y`, both at addr 0) break IDO CSE between sibling lui+addiu in the same call](#feedback-ido-type-split-unique-extern-breaks-cse) — _When `func(p, *(int*)&D_X, &D_Y)` should emit TWO separate `lui+addiu` (target shape) but built emits ONE shared lui via CSE, declaring the externs with DIFFERENT types (one `int`, one `char`) prevents IDO from CSE-folding even when both link-resolve to address 0._
- [IDO -O2 auto-unrolls simple count-bounded pointer-chase loops 4x; also constant-folds `/ const` to `* recip`](#feedback-ido-o2-loop-unroll-and-constfold) — A bare `for (i=0; i<n; i++) p = p->next;` loop at IDO -O2 compiles to a Duff's-device-style 4x unrolled body with a remainder prologue.
- [IDO `register T x = const;` does NOT prevent constant-folding through reads of x](#feedback-ido-register-keyword-doesnt-block-constant-fold) — Declaring `register int one = 1;` in IDO -O2 does NOT pin `one` to a $s-register for all reads.
- [Split `x | 0x06000001` into `x |= 0x06000000; x |= 1;` to match `lui+or+ori` sequence](#feedback-ido-split-or-constant) — When the target asm has `lui at, HI; or a0, a0, at; ori a0, a0, LO` (three insts), don't combine the constant in C.

### loop / unroll

- [IDO -O2 if-guarded do-while defers register-only assignment past jal](#feedback-ido-if-guarded-do-while-defers-reg-move) — When a `p = a0;`-style register-only move is hoisted by IDO ahead of an unrelated jal (no data dep), wrapping the loop as `if (count > 0) { p = a0; do { ... } while (i < count); }` forces the move AFTER the count load…
- [IDO `while(1){}` always emits unreachable jr-ra epilogue + 2 alignment nops — caps short infinite-loop stubs](#feedback-ido-infinite-loop-unreachable-epilogue) — For functions whose target is a tight infinite-loop stub (`b .; nop; …nops; jr ra; nop`), IDO emits jr $ra at offset 0x20 with seven nops between (size 0x28).
- [IDO -O2 auto-unrolls do-while pointer-walks with subu/andi alignment guard regardless of bounds origin](#feedback-ido-pointer-walk-loop-unroll-guard-unflippable) — _For a do-while loop walking through memory clearing fields (`do { ptr += 4; ptr[-4]=ptr[-3]=ptr[-2]=ptr[-1]=0; } while (ptr != end);`), IDO -O2 emits TWO loops + a `subu/andi 0x3F` alignment guard.
- [IDO rewrites pointer-comparison sentinels as `s1 != magic - slot` in unrolled-loop bodies — recognize the pattern](#feedback-ido-sentinel-rewrite-in-unrolled-loops) — _When IDO encounters `if (s1 + slot != (char*)MAGIC)` inside an unrolled loop and MAGIC doesn't fit a 16-bit immediate, it rewrites the test as `if (s1 != (char*)(MAGIC - slot))` and emits `addiu $at, $zero, sentinel;…
- [`volatile s32 sp4;` forces IDO to keep a loop counter on the stack with per-iteration `lw/addiu/sw` instead of register-promoting it](#feedback-ido-volatile-loop-counter-for-stack-iter) — When target asm shows a loop body that reloads the counter from `N(sp)` each iteration (`lw rA, N(sp); ... addiu rB, rA, 1; sw rB, N(sp)`), the C source's loop counter must be `volatile` to prevent IDO from promoting it…

### char / int / signed / narrow

- [For multi-condition state checks, single boolean-return expression beats if-return chain by 70+ pp](#feedback-ido-boolean-return-xor-sltiu-chain) — When target uses `xor; sltiu; bne` chains for `(c1 || c2 || c3)` style checks (computing each condition as a 0/1 value, branching on non-zero to a shared exit), use `return c1 || c2 || c3;` in C — NOT `if (c1) return 1;…
- [IDO treats plain `char` as UNSIGNED by default — use `signed char` for `lb` opcodes](#feedback-ido-char-default-unsigned) — _Casting `(char)int_val` at IDO -O2 emits `lbu` (zero-extend), not `lb` (sign-extend).
- [Named `unsigned char c = *p;` forces $v0; inline `*p` in the comparison keeps the load in $t6](#feedback-ido-named-char-v0-vs-t6) — When the target has `lbu $t6, 0($sN)` for a char loaded from memory and compared immediately, declaring it as a local (`unsigned char c = *p`) forces IDO to allocate $v0 for the load instead.
- [IDO -O2 picks bgez vs srl+beqz for sign-test based on C form — `(unsigned)x>>31` forces 2-insn srl+beqz](#feedback-ido-sign-test-form-choice) — For `if (x < 0) {...}`, IDO -O2 emits the 1-insn `bgez x, .Lend` form (branch if non-negative, skipping the body).
- [`bgez v0; sra t, v0, 1; addiu at, v0, 1; sra t, at, 1` is IDO's signed `/2` lowering](#feedback-ido-signed-divide-2-idiom) — Signed-integer division by 2 in IDO doesn't become a single `sra`.

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
- [IDO -O3 produces byte-identical output to -O2 for single-file compiles — file-split with OPT_FLAGS=-O3 only adds value for inter-module (IPO) builds, which the per-.c.o pipeline doesn't use](#feedback-ido-o3-equals-o2-for-single-file-compile) — _When a function is stuck at -O2 codegen and you're considering file-split-with-OPT_FLAGS to try -O3, don't bother — IDO's -O3 differs from -O2 only in inter-module optimization (requires `cc -O3 -j ...`).
- [-O0-cluster split mid-file requires a paired -O2 layout shim, not just the -O0 file](#feedback-o0-cluster-split-with-layout-shim) — _When a -O0 cluster sits MID-file (not at start or end), splitting it out needs THREE files: predecessor (truncated), the -O0 cluster file, AND a successor "layout shim" (-O2 INCLUDE_ASMs only) holding everything…
- [New -O0 .c file split needs FOUR config touches; objdiff.json is the easy-to-miss one](#feedback-o0-file-split-objdiff-json-step) — _When carving an -O0 function out of its parent .c into a dedicated `<seg>_o0_<offset>.c` file, you need (1) Makefile per-file `OPT_FLAGS := -O0` and `TRUNCATE_TEXT`, (2) tenshoe.ld entry, (3) source split itself, AND…
- [-O0 variant of the int-reader accessor template — 19 insns / 0x4C bytes vs the standard -O2 template's 16 insns / 0x40 bytes](#feedback-o0-int-reader-template-variant) — _When scanning USO accessor templates, also check 0x4C-byte / 19-instruction variants — these are -O0 compiles of the SAME body.

### indirect / function pointer

- [Inline function-pointer call → IDO uses `jalr $t9`; naming as local → `$a1` or other](#feedback-ido-indirect-call-t9) — _For indirect calls via a struct member (`(*struct->callback)(args)`), keep the function-pointer EXPRESSION inline inside the call.
- [`volatile T buf[N]` forces IDO to emit `addiu tA, sp, off; lw tB, 0(tA)` (pointer-indirect load) instead of `lw tB, off(sp)` (direct sp-relative)](#feedback-ido-volatile-buf-pointer-indirect) — When the target asm uses `addiu tA, sp, off; lw tB, 0(tA)` (materialize stack address into a temp register, then load via the temp) instead of the standard direct `lw tB, off(sp)`, declaring the local buffer as…

### other

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
- [Use `goto end` for early-return from alloc-check; plain `return` emits extra branch](#feedback-ido-goto-epilogue) — _IDO compiles `return a0` from inside a nested if into `b + lw ra` redundancy, not a direct `beqz/bnez` to the epilogue.
- [IDO implicit decl conflicts with later explicit extern](#feedback-ido-implicit-decl-extern-conflict) — K&R-implicit `int func()` from a call BEFORE the explicit `extern void func()` declaration causes IDO cfe to error "Incompatible function return type"
- [IDO places locals first-declared-highest; add leading pad local to shift scratch slot down](#feedback-ido-local-ordering) — If your local `scratch` ends up at sp+0x1C but the target wants sp+0x18, declare an extra `int pad` BEFORE scratch.
- [`or v0, v1, zero` after jal = wrapper returning low word of callee's 64-bit return](#feedback-ido-long-long-v1-move) — In 1080 USO wrappers, the target `or v0, v1, zero` right before `jr ra` means the callee returns a `long long` and the wrapper returns only the low 32 bits.
- [IDO doesn't accept bare `__asm__("")` as a scheduling barrier](#feedback-ido-no-asm-barrier) — _The GCC trick of `__asm__("")` to force an instruction ordering barrier is NOT supported by IDO 7.1.
- [`&BASE + 0xOFFSET` vs `extern SYM_AT_OFFSET` produces different .o byte patterns even when addresses are equal](#feedback-ido-offset-in-instruction-vs-reloc) — _When target asm has `lw $reg, 0xNNN($at)` (offset baked into the instruction), write `*(int*)((char*)&BASE + 0xNNN)` in C — this emits `lw $reg, 0xNNN(...)` matching the target.
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
- [`void f(int a0, ...)` with empty body spills all 4 arg regs to caller slots](#feedback-ido-varargs-empty-body) — When target asm is `addiu sp, -8; sw a0, 8(sp); sw a1, 12(sp); sw a2, 16(sp); sw a3, 20(sp); jr ra; addiu sp, 8` — 4 consecutive spills of a0..a3 to caller's arg area, no jal, no other body — the original C was a…
- [Typed-varargs extern (`int f(int,int,...)`) does NOT force IDO -O2 caller-side stack-arg spills (sw a1,4(sp); sw a2,8(sp))](#feedback-ido-varargs-extern-doesnt-force-caller-spill) — _When target asm shows defensive `sw a1,4(sp); sw a2,8(sp)` spills around a jal but mine doesn't, the natural fix-attempt is to declare a unique-aliased extern with explicit varargs sig.
- [Use `void` return when target doesn't restore $v0 — int return forces IDO to spill v0 across calls](#feedback-ido-void-return-avoids-v0-spill) — When the asm doesn't have an explicit final `or v0, ...` epilogue insn AND v0 is consumed by an intermediate call (e.g. as $a2 arg in delay slot), the C should be `void` return, not `int`.
- [Use `volatile T *arg` to prevent IDO from fusing two `sb`/`sw` stores to the same address](#feedback-ido-volatile-preserve-redundant-io) — When the target asm has two distinct stores to the same address (e.g. `sb $t9, 0(a0); sb $t0, 0(a0)` where the second value is derived from the first), plain C emits ONE store because IDO fuses `*a0 = val; *a0 = val |…
- [`volatile int saved_arg = aN;` forces IDO to spill aN to a LOCAL stack slot instead of the caller's outgoing-arg slot](#feedback-ido-volatile-unused-local-forces-local-slot-spill) — _When target has `sw $aN, 0x24(sp)` (local-slot offset) but your IDO build emits `sw $aN, 0xBC(sp)` (caller's outgoing-arg slot at sp+frame_size+slot), the difference is whether IDO treats the saved arg as "live local"…


---

<a id="feedback-ido-3save-vs-2save-arg-preserve"></a>
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

**Related:** `feedback_ido_v0_reuse_via_locals.md` and `feedback_ido_inline_deref_v0.md` cover the broader "inline vs named local" axis for register allocation. This memory is the narrow case for commutative-op operand ordering in the encoding itself.

**Origin:** 2026-04-19 game_libs gl_func_00023B08. Inline `r + a1 * 16` → 99.33 % (only `addu` operand order off). Split `int offset = a1 << 4; r + offset` → 100 %.

**Addendum (2026-04-19, bootup_uso/func_00002774):** Array-indexing form `((T*)base)[i + offset]` gives `addu rd, base, idx` (BASE first), while the arithmetic form `*(T*)(base + i*sizeof(T) + offset*sizeof(T))` gives `addu rd, idx, base` (OFFSET first). Same semantic access, different operand order at the byte level.

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

When you see this pattern in target — especially with the `sw $vN; lw $vN` spill+reload of the shifted base across a jal — recognize it as the base-adjust trick. Skip the function or NM-wrap with a note. Don't try `int *p2 = (int*)(p + 0x2C);` from C — IDO will eliminate the alias.

**Related:** `feedback_ido_3save_vs_2save_arg_preserve.md` — similar "target uses an extra reg-shuffle that IDO won't reproduce."

---

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

**Related:**
- `feedback_ido_switch_rodata_jumptable.md` — base reference; this memo extends it with the matching idiom.
- `feedback_ido_branch_likely_arm_choice.md` — last-comparison bnel cap reasoning.
- `feedback_ido_goto_epilogue.md` — `goto end` to share epilogue (similar idiom).

---

---

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
because div.s is multi-cycle (~30 cycles) vs mul.s (~5 cycles). C
source has no lever to disable this — `/ 2.0f` and `* 0.5f` produce
identical bytes.

**Match path**: original ROM was built without this optimization (or
the compiler version differed). To hit byte-equivalence at runtime,
you'd need to either (a) compile this file with a different IDO option
that disables the fold, OR (b) accept it as a structural NM cap, OR
(c) `INSN_PATCH` the 3 affected insns (lui imm, no — but actually
INSN_PATCH would work here for the lui+mul opcode if we got the size
right).

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

<a id="feedback-ido-empty-body-do-while-emits-branch-likely"></a>
## IDO -O2 emits branch-likely for empty-body do-while loops; move call into the body to get plain branch + nop delay

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

**How to apply:** for FPU dot-product / vector-reduction leaves, expect a 1-instruction final-add operand-order cap if your output otherwise matches. Wrap NM at ~94 % and move on; don't grind variants — the load-order vs add-operand-order tradeoff is structural.

**Related:**
- `feedback_ido_v0_reuse_via_locals.md` — sibling case for integer register choice
- `feedback_ido_arg_save_to_sreg_in_bne_delay.md` — IDO instruction-scheduler caps from C

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

---

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

---

---

<a id="feedback-ido-goto-epilogue"></a>
## Use `goto end` for early-return from alloc-check; plain `return` emits extra branch

_IDO compiles `return a0` from inside a nested if into `b + lw ra` redundancy, not a direct `beqz/bnez` to the epilogue. A `goto end_label` at the sole `return` at the bottom produces the clean single-path branch that matches typical libgdl/libc code._

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

**Potential future workarounds (not tried):**
- Move the function to a SEPARATE .c file that doesn't include the K&R declaration, declares its own prototyped version of `gl_func_00000000`. Add to Makefile + linker script. Probably works but adds build complexity.
- Adopt a naming convention: `gl_func_00000000_ff = 0x0` in undefined_syms_auto.txt as an alias, then declare `extern void gl_func_00000000_ff(float, float);` and call that. Need to verify the linker resolves the alias correctly and that jal works.

**Origin:** 2026-04-19 game_libs gl_func_00067AC8. Tried 3 variants; all failed for the reasons above. Reverted to INCLUDE_ASM.

**Stack-arg variant (2026-05-02, game_uso_func_00000858, 8-arg constructor):**

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
- Conversely, if the target DOES have an `andi $aN, $aN, 0xff` or `sll+sra` right after the prologue, use `unsigned char`/`char`/`short` as appropriate — matching the asm.

**Origin:** hit 2026-04-18 on bootup_uso func_00000A50 and func_00000B14 (both `if (*a0) ((char*)*a0)[N] = a1;`). Target was 6 insts with a bare `sb`; `char a1` gave 8 insts (+andi +spill sw), `int a1 + (char)a1` matched exactly.

**Forwarding variant (2026-04-19 game_libs gl_func_000005A4):** when narrow args are FORWARDED to another callee (no local byte store), the target pattern is `sw $aN, off(sp)` (save word) followed by `lbu $rT, off+3(sp)` (read low byte of word — big-endian). This is exactly what `char`/`short` args produce when they survive a live range across a jal. In this case, DECLARE the args as `char`/`unsigned char`:

```c
void gl_func_000005A4(char *a0, char a1, char a2, char a3) {
    gl_func_00000000(a0 + 0xE4, &gl_ref_X, a1, a2, a3);
}
```

matches the `sw $aN, off(sp); lbu $rT, off+3(sp)` pattern for each narrow arg that's passed forward. Check the target: if you see `sw` + `lbu off+3` → narrow arg; if you see `andi $aN, 0xff` → also narrow but different codegen. If neither, use `int` + cast.

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

**Related:** `feedback_ido_no_gcc_register_asm.md` (IDO rejects `register T var asm("$N")`). `feedback_ido_register.md` (plain `register` keyword IS respected as an allocation hint). These three cover the main GCC-style pinning/barrier tricks that don't work in IDO.

**Origin:** 2026-04-19 game_libs gl_func_00026C6C. Tried `__asm__("")` to force a register copy for the `or a2, a1, zero` pattern — got `undefined reference to __asm__` at link time. Wrapped as NON_MATCHING (91 %).

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

---

---

<a id="feedback-ido-precall-arg-spill-unreachable"></a>
## IDO pre-call outgoing-arg spills (`sw aN, N(sp)` before jal for args loaded from globals) are not C-reproducible for K&R callees

_Some IDO-compiled functions emit extra `sw $a1, 4(sp); sw $a2, 8(sp)` stores IMMEDIATELY before a jal, saving the OUTGOING arg values (just loaded from global memory) into the caller's arg-save slots. When the callee is K&R (`extern int f();`) and the outgoing args are `*(int*)&D_XXX` reads, no C variant tried reproduces these spills — leaves a ~2-insn gap capping match at ~75-80%._

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

---

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

**Related:**
- `feedback_ido_switch_rodata_jumptable.md` — switch → .rodata jumptable, discarded by 1080 linker
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

**Origin:** 2026-04-20, bootup_uso/func_000020AC (array-append-pair to list at offsets 0xC0/0xC4 in a struct).

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

**How to apply:** when the target has unexplained `sw a0, FRAME(sp)` at entry and nothing that reads it back, your C needs an unused `int a0` parameter. Don't try to make the parameter "do something" — IDO spills it regardless.

**When not to apply:** if the target asm has NO `sw a0` or `sw a0` is followed by a clear `lw a0` later, then a0 genuinely IS used — write C that uses it.

**Origin:** 2026-04-18 game_libs 12-func cluster (prefix `addiu sp; sw a0; sw ra; lui a0; jal; addiu a0, a0`). Matched 7 plain + 1 return-1 variant + 3 address-literal variants with this pattern.

**Inverse caveat (2026-04-19 game_libs gl_func_0006270C):** if the target has `lw/use $a1` (second arg) but NO `sw a0` spill at entry AND a `jal` in the body, you CANNOT reproduce it with `void f(int a0, int *a1)` — IDO always spills unused a0 with a jal present. The target was likely either: (a) called with a non-standard convention that passes a single pointer via `$a1` instead of `$a0`, (b) had a different compiler/flags, or (c) uses some K&R declaration that IDO can't reproduce. Wrap as NON_MATCHING; don't grind. 91 % max.

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
| (more args — extrapolate: 3-arg would spill a0,a1,a2) |

The 2-spill case is clearly distinct from varargs: no `addiu sp, -8`, only 2 stores to caller arg slots, scheduler fills jr-ra delay slot with one of the sw instructions. Confirmed on `bootup_uso/func_0000EDC0` (2-arg empty).

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

**Related:** `feedback_ido_unused_arg_save.md` (unused arg gets caller-slot spill), `feedback_ido_volatile_buf_pointer_indirect.md` (volatile buf forces pointer-indirect addressing).

---

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
