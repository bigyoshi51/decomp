# Agent brief: picking up 1080 decomp on a new machine

You are continuing an in-progress N64 decompilation. Read this before acting.
Everything durable is in git; this file is the operating manual for what is not
obvious from the code.

**State at handoff (2026-09-05):** 2355/3444 functions exact, 34.40% code bytes.
- Project repo `bigyoshi51/1080-decomp` main = `f75d7adad`
- Monorepo (this repo) `bigyoshi51/decomp` main = `cd32552`

---

## 1. First-run setup

```bash
git clone https://github.com/bigyoshi51/decomp.git            # tooling + docs + skills
git clone https://github.com/bigyoshi51/1080-decomp.git       # the project
```

Then, in order:

1. **ROM** — `baserom.z64` is gitignored and will never be in any repo (see §7).
   Place your own copy at `projects/1080 Snowboarding (USA)/baserom.z64`.
   It must be md5 `fa27089c425dbab99f19245c5c997613`, 16777216 bytes.
   Worktrees symlink to it; don't copy it 26 times.
2. **tools/** (gitignored) — run `bash scripts/bootstrap-1080-tools.sh`.
   It is idempotent and safe to rerun: downloads SHA-pinned IDO 5.3/7.1 and
   objdiff binaries, installs unprivileged MIPS binutils when the host lacks
   them, and shallow-clones `references/` + the permuter.
   **Caveat:** it installs *prebuilt* IDO. The `tools-patches/` ecvt patch (the
   `-Wo,-zdbug:6` regalloc dump) requires a *source* build of
   ido-static-recomp — if you need `./uoptlist`, build IDO from source and
   apply the patch there; the prebuilt binary cannot take it.
3. **Memory** — untar the memory bundle into
   `~/.claude/projects/<project-slug>/memory/`. 729 memos: user preferences,
   project state, and gotchas that are deliberately NOT in the repo.
4. **Worktrees** — `scripts/spin-up-agent.sh 1080` per parallel agent
   (auto-picks the next free letter, runs the `.agent-setup` recipe). Don't
   hand-roll the recipe.
5. **Build** — `make RUN_CC_CHECK=0 -j8` then
   `make non_matching_objects RUN_CC_CHECK=0 -j8`.

## 2. The gate — run this before every commit, no exceptions

```bash
make RUN_CC_CHECK=0 -j8 && cmp tenshoe.z64 baserom.z64   # MUST be byte-identical
make non_matching_objects RUN_CC_CHECK=0 -j8             # MUST exit 0 (retry once: transient donor race)
bash scripts/refresh-report.sh
```
Then diff the exact-set against `origin/main:report.json` and confirm **nothing
truly lost**. Restore `report.json` afterwards (`git checkout HEAD -- report.json`);
only the landing worktree commits it.

**Sentinels** — these must read 100.0 in every gate:
`gl_func_000551E0`, `gl_func_00055B10`, `gl_func_0000EBC8`, `gl_func_0000C5B0`,
`game_libs_func_00062F08`.

## 3. Landing ritual

Hand-analysis agents work on worktrees `agent-f/g/h` and never push. One
landing worktree (`agent-d`) collects:

```bash
cd projects/1080-agent-d                 # STANDALONE first command, never a cd-chain
git fetch origin && git checkout -B agent-d origin/main
git cherry-pick --abort 2>/dev/null      # stale sequencer states persist
git cherry-pick <hashes>                 # union-merge Makefile/undefined_syms conflicts
<run the §2 gate>
git add report.json && git commit -m "report.json: <wave summary>"
git push origin HEAD:main                # SEPARATE command — never chained to the gate
```

Read the gate output before pushing. Chaining the gate into the push has twice
masked a failure and pushed a regression.

## 4. Policy invariants

- **A match means the C compiles to the target bytes.** Instruction-byte
  patching (INSN_PATCH / PROLOGUE_STEALS / instruction-appending SUFFIX_BYTES)
  was removed as match-faking and must not come back. If C can't reach the
  bytes, leave it honestly `#ifdef NON_MATCHING`.
- **Episodes are for real exacts only** — the C on the build path producing the
  target bytes. An objdiff-100 NM wrap whose callees are placeholders stays a
  wrap with no episode; it would train on bytes the build never emits.
- **Never `replace_all`** on these sources. Textual twins across a TU exist; a
  blanket replace regressed a landed exact once. Edit per-site.
- Commit per function. Push every wave. No upstream PRs to third-party repos.

## 5. Clip management (the trap that bites)

Units with NM wraps carry `NON_MATCHING_TEXT_CLIP_KEEP_ALIGN` in the Makefile.
Growing an NM body pushes the unit's tail symbol past the clip and silently
truncates it — a sentinel drops to ~20-30% and looks like a regression.

- Re-probe the clip from the **post-splice** object, never a standalone compile.
- Rule: tail symbol's NM offset + its full expected size.
- A Makefile-only clip change does **not** rebuild the `.o`. `rm` it first, or
  you will gate against a stale object.
- Cherry-picking two commits that each advanced the clip can resolve to the
  intermediate value. Check the final clip after any multi-commit pick.

## 6. Landmines that cost real time

- **Stale-tree false losses.** If exacts you never touched appear "lost", your
  worktree predates a land. Re-checkout onto the new `origin/main` and re-gate.
  Don't chase it.
- **`disasm-func.py` without `--obj` shows the BUILD, not the target.** Multiple
  agents have "verified" a body against itself. Ground truth is always
  `expected/<unit>.o` at `st_value`, plus raw `.word` lists.
- **Prior cap notes are frequently fiction.** This session retracted a dozen
  "permanent cap" verdicts that were decode errors, splat boundary artifacts, or
  stale toolchain claims. Before grinding registers, size-check the build body
  against the target: a build/target instruction ratio well under 1.0 means
  missing logic, not an allocator tie.
- **Never pipe a `make` into `head`** — SIGPIPE kills the build mid-way and
  leaves a stale `.o`. Redirect to a log file.
- **`git remote -v` on the 1080 worktrees leaks an embedded PAT.** Use
  `git remote get-url origin | sed 's|://.*@|://|'` when displaying it.

## 7. Why the ROM is never committed

`baserom.z64` is copyrighted commercial game content. Every N64 decomp project
gitignores it deliberately: publishing it would expose the repo to takedown, and
binary blobs are effectively permanent in git history. Transfer your own copy
out-of-band. This is not negotiable and not worth re-litigating.

## 8. Where knowledge goes

- **Repo `docs/`** — any reusable technique, IDO quirk, or recipe. This is what
  non-Claude agents can read. `IDO_CODEGEN.md` (~250 entries), `PATTERNS.md`,
  `MATCHING_WORKFLOW.md`, `N64_FORENSICS.md`, `TOOLING_*.md`. Each has an Index
  at the top — skim it, jump to the entry, don't load whole files.
- **`~/.claude/.../memory/`** — per-conversation context only: user preferences,
  project-state-of-the-day, work-in-progress. Not technique.

## 9. Productive veins (as of handoff)

The filter that has been paying: **build/target instruction ratio**, not fuzzy %.
Ratio well under 1.0 = an under-decoded stub with missing logic; those yielded
+52pp, +79pp, and several 12%→90%+ rebuilds. Ratio at or above 1.0 = a genuine
register-allocation tie; leave it unless you have the regalloc dump.

Fuzzy % is **no signal of identity** — library functions have been found hiding
at 0.0% and 23%. On any anonymous function, spend two minutes checking
`references/libreultra`, Plauger libc, and gu/* by size and shape before
grinding. That check produced ~20 exact matches, several of which had been
written off as permanent caps.

**Live queue:**
- bootup `func_00011E00/ED4/FA8` triplet — needs the 10540-style -O0 carve;
  a body scoring 52/53 per function already exists in scratch
- `[50,60)` game_libs ratio tier: 521F8, 6D964, 959C, 6FBD8
- near-miss closers via the uopt regalloc dump: 56898 (99.8), 4118 (98.3),
  3AC5C (97.5), 2FB74 (97.0)
- 8FC8 loop counter-vs-pointer rank — probably a real cap; confirm with the dump

## 10. Resuming the loop

`/loop /decompile and think outside the box` — three hand-analysis agents on
worktrees f/g/h, results landed on agent-d per §3, pushed per wave.
