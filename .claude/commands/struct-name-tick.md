Run one tick of macro-based struct/global naming for the N64 decomp project. Each tick scans NM-wrap bodies for recurring offset patterns, picks one high-confidence candidate, defines a `#define` macro for it, replaces all qualifying call sites, builds to verify, and commits. Designed to run unsupervised in a loop.

## What this skill DOES

Each invocation produces ONE commit that:
- Adds a single `#define` macro to one source file
- Replaces 5+ instances of a raw offset access with the new macro
- Verifies via `make build/non_matching/<file>.c.o` that the NM build still compiles
- Commits with a message documenting the rename

## What this skill does NOT do

- Does NOT touch exact-matched C code (only `#ifdef NON_MATCHING` blocks)
- Does NOT introduce typed structs (that's a separate, supervised pass)
- Does NOT rename `gl_func_*` / `func_*` symbols (those are linker-resolved; renaming risks breaking callers)
- Does NOT change ROM bytes (the default build path is `INCLUDE_ASM`, unaffected)

The point is to build vocabulary safely. A wrong name is just bad documentation, easily reverted.

## Safety invariants

1. **Macros are defined inside `#ifdef NON_MATCHING ... #endif`** so default builds never see them. This eliminates name-collision risk in compiled code.
2. **Replacements happen ONLY inside `#ifdef NON_MATCHING` wrap bodies.** Exact-matched function bodies are off-limits.
3. **Build verification gate:** after edits, run `make RUN_CC_CHECK=0 build/non_matching/src/<seg>/<file>.c.o`. If it fails, **revert all edits and pick a different candidate**.
4. **One macro per commit.** Don't batch — keeps history bisectable.
5. **No global header pollution.** Define each macro local to the file where it's used.

## Workflow

### 1. Preflight

```bash
scripts/decomp-preflight.sh
```

This restores tracked files and warns about staleness. Don't skip — same gotchas apply as `/decompile`.

### 2. Scan for candidates

For 1080 Snowboarding (project `projects/1080-*`), candidates fall into two categories:

**Category A: D_00000000 + offset (global accessors)**

Pattern: `*(T*)((char*)&D_00000000 + 0xN)` or `*(T*)(&D_00000000 + 0xN)` where T is `int`, `int*`, `float`, etc.

```bash
# Inside an agent worktree (projects/1080-agent-X/):
python3 -c "
import re, glob, collections
candidates = collections.defaultdict(list)
for path in glob.glob('src/**/*.c', recursive=True):
    txt = open(path).read()
    # find each #ifdef NON_MATCHING ... #endif block
    blocks = re.findall(r'#ifdef NON_MATCHING(.*?)#(?:else|endif)', txt, re.DOTALL)
    for blk in blocks:
        for m in re.finditer(r'\\*\\(([^)]+)\\)\\s*\\(\\s*\\(char\\*\\)\\s*&D_00000000\\s*\\+\\s*0x([0-9A-Fa-f]+)\\s*\\)', blk):
            t = m.group(1).strip()
            off = int(m.group(2), 16)
            candidates[(t, off)].append(path)
# Rank
ranked = sorted(candidates.items(), key=lambda x: -len(x[1]))
for (t, off), paths in ranked[:20]:
    print(f'{len(paths):3d} uses  *({t})(D + 0x{off:04X})  in {len(set(paths))} files')
"
```

**Category B: arg-N + offset (struct-field accessors)**

Pattern: `*(T*)((char*)<argN> + 0xN)` where `<argN>` is a function parameter. Group by (segment, T, offset). Same scan but match `(char*)\s*<argname>` for the base.

This is harder to scan reliably because arg names vary; for the first version of the skill, focus on Category A only and add Category B in a follow-up tick.

**Verify candidates with strict stack-tracking, not regex:**

The non-greedy regex `r'#ifdef NON_MATCHING(.*?)#(?:else|endif)'` over-counts in files with wraps that contain `#else` inside a comment, OR in files where matches appear adjacent to but outside an `#ifdef NON_MATCHING` block. **Before committing to a candidate, re-verify per-file containment using a stack-walk over `#ifdef NON_MATCHING` / `#else` / `#endif` markers** to count only the matches strictly inside an NM block. A pilot run found 7 raw matches for an offset where only 4 were genuinely in-NM — the regex prefilter's count is a candidate floor, not a final figure.

### 3. Pick the next candidate

Filter the ranked list:
- **Skip if already named** — search the codebase for an existing `#define` whose body matches `*(T*)((char*)&D_00000000 + 0xN)`. If found, this offset is already named; move to the next.
- **Skip if uses < 5** — not enough evidence; wait for more wraps to accumulate.
- **Skip if uses span < 2 distinct .c files** — single-file repetition is often a copy-paste pattern, not a real shared semantic.

Pick the **top remaining candidate**. Don't re-roll within a single run.

### 4. Propose a name

Look at the access patterns in context to guess semantics. Conservative naming heuristics:

- Read in `<` or `>=` comparison against another value loaded from the same struct → likely `_count` or `_limit`
- Assigned only `0` and `1` → `_flag`
- Multiplied by a struct size in indexing → `_count` (loop counter)
- Always assigned a pointer (`= &D_X` or `= some_func()`) → `_ptr`
- Read into a temp that's then passed as `gl_func_00000000` arg → semantic depends on arg position

If no strong signal: name as `D_OFFSET_<HEX>` (purely positional, but with prefix to distinguish from raw refs). Don't try to be clever — a positional name is a placeholder for a future supervised rename.

**Naming convention:**
- All-uppercase, with a **segment prefix derived from the .c file's segment** to avoid cross-USO ambiguity. Each USO has its own runtime-relocated `D_00000000`, so offset `0x14C` in `timproc_uso_b1` and `mgrproc_uso` are different physical addresses with potentially different meanings — distinct names make this explicit.
  - `timproc_uso_b1` → `TIMB1_*` (e.g., `TIMB1_D_14C`)
  - `timproc_uso_b3` → `TIMB3_*`, `timproc_uso_b5` → `TIMB5_*`
  - `mgrproc_uso` → `MGR_*`, `arcproc_uso` → `ARC_*`, `eddproc_uso` → `EDD_*`
  - `titproc_uso` → `TIT_*`, `h2hproc_uso` → `H2H_*`, `n64proc_uso` → `N64_*`
  - `game_uso` → `GAME_*`, `game_libs` → `GL_*`, `gui_uso` → `GUI_*`
  - `bootup_uso` → `BOOT_*`, `boarder1_uso` → `BRDR1_*`, etc.
- Within the segment prefix, append the offset as hex if no semantic signal: `TIMB1_D_14C`. With a semantic signal: `TIMB1_LEVEL_INDEX`.
- Always all-uppercase (no naked lowercase names) to keep macros visually distinct from variables.
- For the macro form: `#define TIMB1_D_14C (*(int*)((char*)&D_00000000 + 0x14C))` (lvalue form so it works as both read and write target)

### 5. Choose where to define the macro

Locality matters. Define the macro at the **top of the single .c file** where it'll be used. If multiple files use it, define it in each (with `#ifdef`-guard against redefinition) OR pick the file with the most uses and put it there.

Wrap the `#define` block in:

```c
#ifdef NON_MATCHING
/* Macro definitions for NM-wrap bodies. Auto-managed by /struct-name-tick.
 * Default build never sees these — wrap bodies aren't compiled.
 */
#define D_GAME_LEVEL_INDEX (*(int*)((char*)&D_00000000 + 0x148))
#endif
```

If the file already has such a block (recognizable by the `Auto-managed by /struct-name-tick` comment), append the new `#define` to the existing block. Don't create duplicate blocks.

### 6. Replace call sites

For each NM-wrap occurrence of the raw access in the chosen scope:
- `*(int*)((char*)&D_00000000 + 0x148)` → `TIMB1_LEVEL_INDEX` (or whatever segment-prefixed name you chose)
- Both read and write contexts (the lvalue macro form supports both)

Replace ONLY inside `#ifdef NON_MATCHING ... #endif` blocks. NEVER touch code outside such blocks (those are exact-matched bodies; changing them would alter codegen).

**Skip substitutions inside `/* ... */` block comments and `//` line comments.** A pilot tick caught a substitution inside a wrap's doc-comment block (which described the raw asm semantics) — that's fine compilation-wise but defeats the comment's intent. Doc-comments often reference the raw offset to explain what the original asm does; replacing it with the macro hides that. Don't use a blunt `replace_all`. Either:
- Walk the source character-by-character with comment-tracking state and substitute only outside `/* */` and `//` regions, OR
- Match each occurrence individually with surrounding context, manually verify it's not inside a comment, then replace.

If a doc-comment incidentally gets the substitution and the comment was paraphrasing code (not asm), it's harmless and you can leave it. But if the comment was specifically documenting the raw access form, revert just that line.

### 7. Build-verification gate

```bash
make RUN_CC_CHECK=0 build/non_matching/src/<seg>/<file>.c.o
```

For every file you edited, the NM build must succeed. If ANY file's NM build fails:

```bash
git checkout -- src/  # revert all wrap edits
```

Then loop back to step 3 and pick a different candidate. Log the failure mode in the commit message of the next successful tick.

### 8. Verify the default build still passes

```bash
make RUN_CC_CHECK=0 build/src/<seg>/<file>.c.o
```

This MUST succeed (the default build produces ROM bytes; if it fails, revert immediately). Default builds shouldn't be affected by NM-only macro additions, but verify.

### 9. Commit

```bash
git add src/<seg>/<file>.c
git commit -m "Name D_00000000+0xN as <NAME> across <K> NM wraps

Heuristic: <one-line semantic guess>. Replaced <K> raw offset
references in <files...>. Macro defined under #ifdef NON_MATCHING
so default build is unchanged.

Auto-generated by /struct-name-tick."
```

Each tick is one commit. Don't batch.

### 10. (Optional) Refresh ledger

If `docs/audits/struct-naming-ledger.md` exists, append a row:

```
| <date> | D_GAME_LEVEL_INDEX | D_00000000 + 0x148 | int | 7 wraps | "level idx — passed to gl_func_X arg2" |
```

Future ticks read this to avoid re-naming. (If the ledger doesn't exist yet, don't create it on the first tick — wait until after a few macros land to see whether the auto-skip-by-grep logic is enough on its own.)

## Anti-patterns to catch yourself in

- **"This offset is used 8 times but I can't tell what it means, so I'll skip."** Wrong — that's exactly when a positional name like `D_OFFSET_148` is useful as a placeholder. Future ticks (or a supervised pass) can rename it once semantics are clearer. Naming `D_OFFSET_148` in 8 wraps is itself a documentation win even with the placeholder.
- **"Let me also clean up these adjacent offsets while I'm here."** No — one macro per commit. Do them as separate ticks.
- **"This macro should go in a shared header so other files can use it."** No — locality is part of the safety design. If a second file needs it, that's a future tick.
- **"This NM wrap is at 35% match; let me also re-grind the wrap body."** No — this skill is a naming pass, not a decompile pass. Run `/decompile` separately for that.

## Loop usage

```bash
/loop 10m /struct-name-tick
```

Each tick should produce one commit. If the candidate pool runs dry (fewer than 5 unnamed offsets with 5+ uses each), the tick should commit nothing and emit a short message — at that point the user can stop the loop or shift to manual struct typing.
