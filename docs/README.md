# decomp/ documentation

Reference docs distilled from per-conversation feedback notes (~400 entries) collected during 1080 Snowboarding decompilation. They apply to any IDO-toolchain N64 decomp project, not just 1080 — keep them in mind when working on this or future projects.

| Doc | What it covers | When to consult |
|---|---|---|
| [IDO_CODEGEN.md](IDO_CODEGEN.md) | IDO 7.1 codegen quirks: how the compiler emits specific patterns, what C-source shapes do or don't match a given asm. | When you see a target asm idiom and need to know which C produces it. |
| [PATTERNS.md](PATTERNS.md) | Asm-shape pattern recipes: how to recognize an asm idiom and the C source that produces it. | When drafting C from asm — search for the pattern, find the recipe. |
| [MATCHING_WORKFLOW.md](MATCHING_WORKFLOW.md) | Operational recipes: NM wraps, fragment merging, objdiff scoring quirks, expected/ baseline care, file-split mechanics, build hygiene. | When a build / land / objdiff issue surfaces. |
| [POST_CC_RECIPES.md](POST_CC_RECIPES.md) | Last-resort byte-patch recipes: PROLOGUE_STEALS, INSN_PATCH, SUFFIX_BYTES, PREFIX_BYTES, TRUNCATE_TEXT. | When IDO codegen is correct but capped at 99% by allocation/scheduling. |
| [N64_FORENSICS.md](N64_FORENSICS.md) | N64-specific knowledge: RSP ucode, splat config, ROM layout, 1080 game-specific. | When investigating opaque blobs or game-specific structure. |
| [TOOLING_GIT.md](TOOLING_GIT.md) | Git, GitHub CLI, worktree, shell-state operational gotchas. | When git/gh actions misbehave. |
| [TOOLING_DECOMP.md](TOOLING_DECOMP.md) | Decompilation tooling specifics: m2c, Ghidra, the permuter, decomp.dev integration. | When picking or running a decomp tool. |

## How to use

Each doc has an Index at the top with one-line summaries. Skim the index, jump to the relevant section. Don't load whole docs into context — they're large reference files, not skill instructions.

The current contents are auto-generated from per-conversation notes; many entries are still rough on grammar / dedup. Edit freely as you encounter rough sections. Maintain the format: `## Title` heading + optional `_one-line summary_` + body.

## When to add a new entry

If you discover a non-obvious pattern, gotcha, or recipe that future agents would benefit from, add it to the relevant doc directly (no separate per-memo files). For agent-private context (user preferences, project-state-of-the-day), use the `~/.claude/projects/.../memory/` directory instead — those don't get checked in.

See `CLAUDE.md` (project orientation) for the broader project conventions.
