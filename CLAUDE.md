# decomp — agent orientation

> Read by Claude (`CLAUDE.md`) and by Codex / other agents (`AGENTS.md` is a symlink to this file). A handful of references below are Claude-specific (the `/decompile` skill, `~/.claude/projects/.../memory/` auto-memory) — Codex/other agents can ignore those and follow the script-level workflow (`scripts/decomp-preflight.sh`, `scripts/spin-up-agent.sh`, the project's `scripts/land-successful-decomp.sh`). Everything else applies regardless of which agent is driving.

This repo is a **multi-project N64 decompilation agent**. It wraps splat / asm-differ / m2c / IDO / GCC-KMC and layers an agent-driven workflow on top. Per-project work happens under `projects/<name>/`; the top-level code is cross-project infrastructure.

## Layout

- `main.py`, `decomp/` — Python CLI. Subcommands: `discover`, `info`, `m2c`, `diff`, `agent`, `export-episodes`, `log-exact-episode`. Invoke with `uv run python -m decomp.main <cmd>`.
- `projects/<game>/` — one decomp project per ROM. Has its own splat config, Makefile, `asm/`, `src/`, `episodes/`, `baserom.z64`.
- `projects/<game>-agent-<letter>/` — git worktrees for parallel Claude agents. Each on branch `agent-<letter>`. Never commit on `main` while an agent branch is active.
- `tools/` — downloaded third-party binaries (IDO, asm-processor, permuter, KMC GCC).
- `references/` — local clones of `libreultra`, `oot`, `papermario`. Grepped by `scripts/decomp-search` when matching libultra helpers.
- `scripts/decomp-search` — grep the reference clones. First thing to run when you recognize a `__os*` / `__rmon*` / libgcc helper.
- `scripts/spin-up-agent.sh` — `scripts/spin-up-agent.sh <project> [letter]` creates a parallel agent worktree at `projects/<prefix>-agent-<letter>/`, picking the next free letter and running the project's `.agent-setup` recipe (symlink toolchain, copy assets, etc.). Use this whenever a new agent worktree is needed; don't repeat the recipe by hand.
- `scripts/decomp-preflight.sh` — start-of-run hygiene + source roll. The `/decompile` skill calls this as its first action; restores tracked `report.json`, warns on parallel-agent merge artifacts, checks branch staleness, and prints `source=N`.
- `scripts/land-successful-decomp.sh` — per-project landing script. Rebases the agent branch onto `origin/main`, refuses to land unless `report.json` shows the function as exact + `episodes/<func>.json` exists, then fast-forwards main and pushes.
- `.claude/commands/` — skills. The main one is `/decompile` (daily driver). Siblings: `/merge-fragments`, `/split-fragments` (via script), `/setup-objdiff`, `/refine-splat`, `/new-project`, `/decompile-f3dex2`.
- `TRAINING_PLAN.md` — active design doc on how exact-match episodes feed into SFT / verifier-RL. Not a completed spec.

## Workflow entry points

- **Decompile one function:** invoke the `/decompile` skill (or run `/loop /decompile` to iterate). The skill handles project discovery, worktree selection, asm reading, matching, episode logging, and landing.
- **Spin up a parallel agent worktree:** `scripts/spin-up-agent.sh <project>` (auto-picks the next free `agent-<letter>`).
- **Add a new game:** `/new-project` skill.
- **Debug a stuck diff:** `objdiff-cli diff -u <unit> <func>` for mnemonic-level comparison; falls back to `objdump -M no-aliases` for exact-byte verification.
- **Research a technique:** see `docs/` (checked into the repo, accessible to all agents):
  - `docs/IDO_CODEGEN.md` — IDO 7.1 codegen quirks (~115 entries)
  - `docs/PATTERNS.md` — asm-shape pattern recipes (~145 entries)
  - `docs/MATCHING_WORKFLOW.md` — NM wraps, fragment merging, objdiff, expected/, build hygiene (~70 entries)
  - `docs/POST_CC_RECIPES.md` — PROLOGUE_STEALS, INSN_PATCH, SUFFIX_BYTES, PREFIX_BYTES (~20 entries)
  - `docs/N64_FORENSICS.md` — RSP ucode, splat config, 1080-specific
  - `docs/TOOLING_GIT.md` and `docs/TOOLING_DECOMP.md` — git/gh and m2c/Ghidra/permuter gotchas
  - Each doc has an Index at the top — skim, then jump to the relevant section. Don't load whole docs.
  - Claude-only: `~/.claude/projects/.../memory/` keeps per-conversation context (user preferences, project-state-of-the-day) that doesn't belong in the repo.

## Key conventions

- **Episodes are for exact matches only.** NON_MATCHING wraps don't get episodes — they'd train on wrong bytes.
- **NM wraps preserve the C, not `INCLUDE_ASM`.** Template: `#ifdef NON_MATCHING { body } #else INCLUDE_ASM(...); #endif`. Threshold ≥80 % match; below that keep plain INCLUDE_ASM.
- **Commit per-function, don't batch.** One match → one commit with its episode → land via script → push.
- **`report.json` is git-tracked but updated by the land script.** Before landing, `git checkout HEAD -- report.json` if your worktree has stomped it during local diffing.
- **asm-processor (IDO) / KMC GCC (Glover)** — per-project compiler. See each project's notes in the `/decompile` skill.

## Not in this repo

- No pre-built compilers committed — `tools/ido-static-recomp/` and `tools/gcc_2.7.2/` are built or downloaded per machine.
- No ROMs committed — `baserom.z64` files live in each project but are gitignored.
