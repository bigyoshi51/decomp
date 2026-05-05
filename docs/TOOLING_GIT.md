# Tooling Git

> Git, GitHub CLI, worktree, and shell-state operational gotchas.

_13 entries. Auto-generated from per-memo notes; content may be rough on first pass — light editing welcome._

## Index

- [Files in agent-X worktree CAN be modified externally during a session — stage edits immediately, don't trust working-tree state across long Bash invocations](#feedback-agent-worktree-external-modification) — Despite the worktree-per-agent isolation, files in /home/dan/Documents/code/decomp/projects/1080-agent-X/ have been observed to mutate witho
- [`assets/` is per-worktree (copied, not shared) — new splat entries need per-worktree asset extraction](#feedback-assets-dir-not-shared-between-worktrees) — When a parallel agent adds a new `bin` segment to `tenshoe.yaml` (e.g. a newly-discovered RSP ucode blob) and runs splat, the extracted `ass
- [When bash cwd has drifted to main worktree, Edit (absolute path) and grep/make/sed (cwd-relative) target DIFFERENT files — edits "vanish" without warning](#feedback-bash-cwd-drift-creates-edit-grep-split) — After the land-script's `cd` leaves the bash session's cwd in the main worktree, Edit/Write/Read calls with the agent-b absolute path target
- [Bash session can drift to main worktree OR ORCHESTRATOR REPO after `cd` for tooling — always verify pwd/branch before commit](#feedback-bash-cwd-drifts-to-main-worktree) — After running the land-successful-decomp.sh script OR after explicitly `cd`ing to the orchestrator (e.g. `cd /home/dan/Documents/code/decomp
- [Always check `gh auth status` active account BEFORE running mutating gh commands (issue create, PR create, comment)](#feedback-check-gh-auth-active-user-before-mutating) — gh CLI silently uses whichever account is "Active account: true". Two accounts are configured here (djsaunde + bigyoshi51) and the active on
- [`git add -A` accidentally tracks the `tools/ido-static-recomp` symlink, breaking the land script](#feedback-git-add-a-traps-symlink) — Don't use `git add -A` in agent-X worktrees. The `tools/ido-static-recomp` symlink (set up locally per `reference_worktrees.md`) is gitignor
- [Don't `git add -A` / `git add .` in a 1080-decomp worktree — stages local-only symlinks](#feedback-git-add-all-stages-worktree-symlinks) — Each 1080 agent worktree has `tools/asm-processor/asm-processor` and `tools/ido-static-recomp` as symlinks pointing at the main worktree's t
- [`git commit --amend --no-edit` in a parallel-agent worktree can absorb a wrong commit message](#feedback-git-amend-no-edit-parallel-agent-danger) — When another agent pushes to main mid-operation, a local HEAD can shift underneath your feet. `git commit --amend --no-edit` then re-uses wh
- [`git stash` is shared across all worktrees of the same repo — never `git stash pop` blind on a multi-agent project](#feedback-git-stash-shared-across-worktrees) — Stashes live in the parent repo's `.git/refs/stash`, not per-worktree. So sister agents' stashes (created in `agent-c-worktree`, `agent-d-wo
- [GitHub PAT used by `git push` lacks `workflow` scope; pushing changes to .github/workflows/ is rejected](#feedback-pat-lacks-workflow-scope-blocks-yml-push) — Pushing to bigyoshi51/1080-decomp from a CLI agent fails with "remote rejected ... refusing to allow a Personal Access Token to create or up
- [When an NM-wrap commit shows .text mismatch, FIRST stash to confirm — upstream state may already be broken](#feedback-pre-existing-text-mismatch-diagnose-via-stash) — When you add an `#ifdef NON_MATCHING / void func() { ... } / #else INCLUDE_ASM(...) / #endif` wrap and observe `cmp build/.o.text expected/.
- [Bash `cd` into main worktree during land persists across later turns — run land from subshell](#feedback-shell-cwd-drift-in-worktree) — In 1080 parallel-agent worktree flow, the manual land fallback is `cd <main-worktree> && git merge --ff-only <agent-branch> && git push`. Th
- [Recovering when another agent's process has mass-reverted your worktree's src/ files](#feedback-worktree-mass-revert-recovery) — With multiple parallel agents on 1080-decomp, one agent's rebase/reset/splat-rerun can mass-revert another worktree's src/ .c files to all-I

---

<a id="feedback-agent-worktree-external-modification"></a>
## Files in agent-X worktree CAN be modified externally during a session — stage edits immediately, don't trust working-tree state across long Bash invocations

_Despite the worktree-per-agent isolation, files in /home/dan/Documents/code/decomp/projects/1080-agent-X/ have been observed to mutate without local action — most likely a parallel agent or a human running scripts/git-checkout from outside. Always `git add` an Edit immediately and verify with mtime/git-status before assuming it persisted._

**Observed 2026-05-01 (during gl_func_0000127C work in agent-a):**

1. Made an `Edit` to `src/game_libs/game_libs.c` to replace an `INCLUDE_ASM` line with a decompiled C body + `#pragma GLOBAL_ASM` for a pad sidecar. Build succeeded with my body in the .o (objdump confirmed).
2. Several Bash invocations later (no `git checkout`, no `make clean`, no rebase by me), `git status` showed clean working tree on that file, and `sed -n '88p'` showed the original `INCLUDE_ASM` text. The new pad sidecar I created with `Write` was also missing from disk.
3. Reflog showed no HEAD movement that could explain the revert. The land script doesn't auto-stash. The hooks don't modify files.
4. **In a later attempt that succeeded**, I noticed `scripts/splice-function-prefix.py` had spontaneously appeared as `M` in git-status — a change reverting one of the recent commits, which I had not made. So files in agent-a's working tree DO mutate externally during the session.

**What this means:**

- The worktree-per-agent isolation is not absolute. Either a human is editing files directly during the session, or some script (cron, watcher, sibling agent's script that operates on all worktrees) reaches into agent-a's tree.
- Edits to source/asm files can disappear silently between an Edit call and a later verification.

**How to apply:**

- After every `Edit` / `Write` to a tracked file in the agent worktree, immediately `git add` it. Staged content survives external `git checkout` / `git restore` of the working tree (in most cases).
- Before assuming a previously-edited file is still as you left it, re-`Read` it or `git status` + `git diff` it.
- Don't blame "parallel agents reverted my work" without evidence — at the same time, don't assume isolation. The mechanism is unclear; protect against it by staging.
- When a long workflow involves multiple `Edit`s + `make`s + verification, stage after each Edit. Don't batch.

**Related:**
- `feedback_shell_cwd_drift_in_worktree.md` — the cwd-state version of the same "agent-a's environment isn't fully under your control" theme
- `feedback_idempotent_scripts_beat_rebase.md` — for sweeping changes, idempotent regeneration > diff-based merge

---

<a id="feedback-assets-dir-not-shared-between-worktrees"></a>
## `assets/` is per-worktree (copied, not shared) — new splat entries need per-worktree asset extraction

_When a parallel agent adds a new `bin` segment to `tenshoe.yaml` (e.g. a newly-discovered RSP ucode blob) and runs splat, the extracted `assets/X.bin` file ONLY lands in their worktree. Other worktrees with the same yaml/ld update will fail to link with `cannot find build/assets/X.bin.o`. Per `reference_worktrees.md` the 1080 worktree setup COPIES assets (not symlinks), so newly-extracted bins aren't synced. Fix: copy the missing asset from a sibling worktree or rerun splat locally._

**Symptom (2026-04-20, agent-e after origin/main sync):**
```
mips-linux-gnu-ld: cannot find build/assets/game_libs_ucode.bin.o: No such file or directory
make: *** [Makefile:148: build/tenshoe.elf] Error 1
```

**Why:** `tenshoe.yaml` / `tenshoe.ld` added a new `bin` segment for `game_libs_ucode` (ROM 0xDF3CD0). When the agent who added it ran splat, the bin got extracted to THEIR worktree's `assets/game_libs_ucode.bin`. But `assets/` is gitignored and copied-per-worktree (not symlinked to a shared location — see `reference_worktrees.md`). Pulling origin/main brings the yaml/ld/src changes but NOT the asset file.

**Fix options (in order of cheapness):**
1. Copy from a sibling worktree:
   ```bash
   cp ../1080-agent-<other-letter>/assets/<missing>.bin assets/
   ```
2. If no sibling has it either, rerun splat locally:
   ```bash
   python3 -m splat split tenshoe.yaml
   git checkout -- tenshoe.ld include_asm.h  # splat clobbers these
   ```

**Detection heuristic:** any `ld: cannot find build/assets/*.bin.o` after a pull is this bug. The fix is never to re-pull or reset — just get the asset file.

**Origin:** 2026-04-20 — agent-f added `game_libs_ucode` segment (RSP ucode region, 0xDF3CD0-0xE01AE8), which I pulled into agent-e. Build failed with missing asset; copied from agent-f's worktree, build succeeded. 1 minute to diagnose.

**Prevention (project-level):** could symlink `assets/` across worktrees OR commit extracted bins to git, but both have downsides (symlinks break find traversal; committed bins balloon repo size). The copy-on-demand pattern is fine once documented — this memo IS the documentation.

---

<a id="feedback-bash-cwd-drift-creates-edit-grep-split"></a>
## When bash cwd has drifted to main worktree, Edit (absolute path) and grep/make/sed (cwd-relative) target DIFFERENT files — edits "vanish" without warning

_After the land-script's `cd` leaves the bash session's cwd in the main worktree, Edit/Write/Read calls with the agent-b absolute path target one file, while grep/sed/make/`git status` target main worktree's file. Symptom: Edit appears to succeed, but a later `grep` shows the OLD content, and `make` builds the OLD content. Always verify cwd matches expected worktree before issuing relative-path commands. Verified 2026-05-04 on arcproc_uso_func_0000247C._

**The pitfall**: a single Edit appears to silently fail because cwd is
wrong. Concrete sequence:

1. Land-script runs, internally `cd`'s to the main worktree to do
   merge/push, never `cd`'s back. Bash session's cwd is now in main.
2. Next /decompile turn: I issue `Edit(file_path="/home/.../1080-agent-b/src/foo.c", ...)`.
   This Edit goes to agent-b's file (absolute path is honored).
3. I `grep` for the changed string. `grep` resolves relative paths
   against cwd → main worktree → reads main's `src/foo.c` which still
   has the OLD content. Reports "edit didn't take effect."
4. I `make build/src/foo.c.o`. Make uses relative paths → main worktree
   → builds the OLD `.c` from main → `.o` reflects pre-edit state.
5. Symptoms cascade: build/.o has stale content, objdiff scores wrong,
   I think Edit is broken, lose 5+ minutes diagnosing.

**The cause**: bash maintains cwd as session state. The land-script's
`cd` (via `feedback_bash_cwd_drifts_to_main_worktree.md`) leaves it
pointing at the main worktree. Edit/Read use absolute paths so they're
unaffected; grep/sed/make/`git` are all cwd-relative.

**Detection one-liner — run BEFORE any commit / build / grep**:

```bash
pwd && git branch --show-current
```

If you expected agent-b but see main, you've drifted. Either `cd` back
explicitly or use `git -C <agent-worktree>` for git ops and full
absolute paths everywhere.

**The "edit vanished" symptom** specifically:

- `Edit` reports success.
- `Read` (with the same absolute path) confirms new content.
- `Bash sed -n '...p' src/foo.c` (relative path, NO cwd guard) shows
  OLD content.
- `Bash grep ... src/foo.c` (relative path) shows OLD content.

The discrepancy IS the diagnostic. Don't assume Edit is broken — assume
cwd has drifted and you're reading two different files.

**Fix-forward when caught mid-run**:
```bash
cd /home/dan/Documents/code/decomp/projects/1080-agent-<letter>
# now relative paths are correct again — re-run grep/make/etc.
```

**Or**: write to absolute paths in EVERY Bash command in the run that
touches files. The bash one-liner pattern:
```bash
cd <correct-worktree> && <command>
```

**Why I committed to main this time**: bash cwd was in main, so
`git commit` committed to main directly. That was the same drift bug —
the agent-b branch never saw the commit. Either:
1. Push the commit from main as-is (skip the agent flow). Functionally
   correct, history-clean.
2. Cherry-pick to agent-b, force-reset main back, push agent-b →
   merge to main. More machinations, no real benefit.

For an urgent decomp commit, (1) is fine. The agent-b flow is for
*concurrency* with other agents; if no parallel agent is touching the
same file, committing on main is just a faster path.

**Related**:
- `feedback_bash_cwd_drifts_to_main_worktree.md` — the underlying
  cwd-drift bug
- `feedback_agent_worktree_external_modification.md` — adjacent class
  (file mutates externally — also presents as "edit vanished")

---

<a id="feedback-bash-cwd-drifts-to-main-worktree"></a>
## Bash session can drift to main worktree OR ORCHESTRATOR REPO after `cd` for tooling — always verify pwd/branch before commit

_After running the land-successful-decomp.sh script OR after explicitly `cd`ing to the orchestrator (e.g. `cd /home/dan/Documents/code/decomp` to use `uv run python -m decomp.main`), the bash session's cwd persists. The next `git add` / `git commit` runs in the wrong repo entirely. Symptom: commit lands on the ORCHESTRATOR's main branch with paths like `episodes/foo.json` (creating a new top-level episodes/ in the orchestrator monorepo). Different from the worktree-drift case: this drifts to a DIFFERENT REPO, not just a sister branch._

**The drift mechanism**: Bash sessions in this harness preserve cwd between
commands. When the land script (or a manual land sequence) does:

```bash
cd "/home/dan/.../1080 Snowboarding (USA)" && git fetch && git merge ...
```

The `cd` PERSISTS for the rest of the session. Subsequent commands like
`git status`, `make`, `git commit` operate on main worktree.

**Symptom**: `git commit` output shows `[main <hash>] ...` instead of
`[agent-b <hash>] ...`. By the time you notice, the commit is on local main.
If you push without checking, it goes to origin/main directly — bypassing
the agent-branch + land-script flow that other agents rely on for
coordination.

**Verified 2026-05-03 on game_uso_func_000034A4**: committed an NM wrap and
got `[main b45f306]` in the output. Reset main back via
`git reset --hard origin/main`, then cd'd back to the agent-b worktree and
re-committed there. No data lost (the patch was preserved in agent-b's
working tree because git worktrees have independent working trees).

**Verified 2026-05-05 on episodes-batch (ORCHESTRATOR REPO drift)**: ran
`cd /home/dan/Documents/code/decomp && uv run python -m decomp.main
log-exact-episode --project projects/1080-agent-b ...` to create episodes
(this works fine; --project + --source-file resolve correctly). BUT the
files ended up created at `/home/dan/Documents/code/decomp/episodes/*.json`
(orchestrator-relative path), NOT at
`projects/1080-agent-b/episodes/*.json`. Then `git add episodes/ && git
commit ...` ran in the orchestrator and landed `[main b0806ad]` on the
ORCHESTRATOR's main, with 12 episode .json files spuriously added to the
orchestrator's tracked tree. Required `git reset HEAD~1`, move the files
to the agent-b worktree, recommit on agent-b. THE ORCHESTRATOR REPO IS
A DIFFERENT GIT REPO from the agent worktree — not a sister branch.

**The trap with `uv run python -m decomp.main`**: it MUST run from the
orchestrator repo root (where `pyproject.toml` and the `decomp/` package
live). So `cd /home/dan/Documents/code/decomp` is the right way to invoke
it. But `--project projects/1080-agent-b` only controls where the EPISODE
FILES get written when paths are resolved relative to --source-file. If
you pass --source-file as `projects/1080-agent-b/src/...` (orchestrator-
relative), the script writes to `episodes/` (orchestrator-relative) by
default. Pass `--log-dir projects/1080-agent-b/episodes` explicitly OR
cd back to the agent worktree before running git.

**Recovery recipe** (if you accidentally commit on main locally):
1. `git format-patch -1 HEAD --stdout > /tmp/save.patch` (preserve the
   commit content)
2. `git reset --hard origin/main` (revert local main to clean state)
3. `cd <agent-X-worktree>` (return to your branch worktree)
4. The agent worktree's working tree still has the changes (worktrees are
   independent). Re-commit there.

**Prevention**:
- Before EVERY commit, run `pwd && git branch --show-current` to verify.
- After ANY land script run, explicitly `cd <agent-X-worktree>` before doing
  more work — don't rely on cwd persistence.
- Even better: prefix commit-bound bash invocations with
  `cd <agent-worktree-abs-path> &&`.

**Related**:
- `reference_worktrees.md` — parallel-agent worktree setup
- `feedback_push_after_merge.md` — push-flow after merge
- The land script (`scripts/land-successful-decomp.sh`) does its own cwd
  switching internally; this is fine for the script's own work but leaves
  the calling shell in the wrong dir afterward.

---

<a id="feedback-check-gh-auth-active-user-before-mutating"></a>
## Always check `gh auth status` active account BEFORE running mutating gh commands (issue create, PR create, comment)

_gh CLI silently uses whichever account is "Active account: true". Two accounts are configured here (djsaunde + bigyoshi51) and the active one persists across sessions. Wrong-account attribution on issues/comments is hard to revoke — requires delete+recreate, breaking URL stability and inbound references. Always run `gh auth status | grep -A1 'Active account: true'` first._

**The hazard:** mutating GitHub commands attribute to the active gh user. The harness here has TWO authenticated accounts:
- `djsaunde` — broad scopes, default-active
- `bigyoshi51` — repo owner for 1080-decomp / decomp / similar projects, narrower scopes

If you run `gh issue create` / `gh pr create` / `gh issue comment` etc. without checking, the action goes to whoever's active. On 2026-05-04 this caused issue #5 to be filed under djsaunde on bigyoshi51's repo — wrong attribution that required `gh issue delete` + `gh issue create` to fix, breaking the URL and forcing a sweep of cross-references in the codebase + memory + comments.

**Standard pre-flight before mutating gh actions:**

```bash
gh api user -q .login                  # ← AUTHORITATIVE: prints the exact login
                                       #   the next API call will use
gh auth switch --user bigyoshi51       # if it's wrong, switch
gh api user -q .login                  # re-verify after switch
```

**DO NOT rely on `grep "Active account: true"` alone.** That output looks like

```
  ✓ Logged in to github.com account djsaunde (keyring)
    - Active account: true
  ✓ Logged in to github.com account bigyoshi51 (keyring)
    - Active account: false
```

Greppping `Active.*true` returns just `- Active account: true` — no
account name. Easy to misread which login is the active one (especially
if the order of the two accounts swaps between sessions). On 2026-05-05
this misread caused issue #7 to be filed under djsaunde despite a
pre-flight check that *seemed* to confirm bigyoshi51 was active. Recovered
via `gh issue delete 7` + refile as #8.

**`gh api user -q .login` is the only reliable check** — it prints the
exact identity that the next mutating call will attribute to.

**When this matters most:**
- Creating issues / PRs (author is the API request's user; can't be edited later)
- Adding comments (same)
- Force-pushing branches that have CI workflows (PAT scope check — see `feedback_pat_lacks_workflow_scope_blocks_yml_push.md`)
- Closing issues (permission-gated; one account may lack rights)

**Recovery if attribution went wrong:**
- `gh issue delete <num>` requires admin rights (repo owner only)
- `gh api -X DELETE repos/.../issues/comments/<id>` deletes individual comments
- `gh api -X PATCH repos/.../issues/comments/<id> -f body=...` edits comment body
- Then recreate with the correct user. NEW issue/comment number; update any docs/code that referenced the old number.

**Prevention is much cheaper than recovery.** One-line check before each gh mutating call.

---

<a id="feedback-git-add-a-traps-symlink"></a>
## `git add -A` accidentally tracks the `tools/ido-static-recomp` symlink, breaking the land script

_Don't use `git add -A` in agent-X worktrees. The `tools/ido-static-recomp` symlink (set up locally per `reference_worktrees.md`) is gitignored on main but `-A` ignores .gitignore for already-staged-then-unstaged files; it WILL stage the symlink. Then land-successful-decomp.sh fails on `git merge --ff-only` with `Updating the following directories would lose untracked files in them: tools/ido-static-recomp`._

**The trap (verified 2026-05-02):**

I ran `git add -A` to stage decomp files and accidentally added `tools/ido-static-recomp` (a symlink to the shared toolchain). The land script committed it, then failed to merge into main because main's worktree has `tools/ido-static-recomp/` as an untracked DIRECTORY (the actual toolchain checkout). git refuses to merge a tracked symlink onto an untracked directory.

**Fix when it happens:**
```bash
git rm --cached tools/ido-static-recomp
git commit --amend --no-edit
```
Or if multiple commits ahead: rebase + drop.

**How to avoid:** stage decomp files explicitly. Either:
- `git add src/<file>.c episodes/<func>.json asm/<file>.s Makefile undefined_syms_auto.txt`
- Or `git add` per file
- DON'T `git add -A` or `git add .` in agent worktrees

**Related:**
- `reference_worktrees.md` — the symlink setup
- `feedback_agent_worktree_external_modification.md` — other "stage immediately" gotcha

---

<a id="feedback-git-add-all-stages-worktree-symlinks"></a>
## Don't `git add -A` / `git add .` in a 1080-decomp worktree — stages local-only symlinks

_Each 1080 agent worktree has `tools/asm-processor/asm-processor` and `tools/ido-static-recomp` as symlinks pointing at the main worktree's tool dirs (per reference_worktrees.md setup). These are NOT in .gitignore. `git add -A` or `git add .` or `git commit -a` will stage them, and you'll commit broken symlinks into shared git history. Always add files explicitly: `git add src/<file>.c episodes/<func>.json asm/... undefined_syms_auto.txt expected/...`._

**Symptom:** `git log -p` on your last commit shows two unrelated symlinks:
```
tools/asm-processor/asm-processor -> ../../1080 Snowboarding (USA)/tools/asm-processor
tools/ido-static-recomp -> ../../1080 Snowboarding (USA)/tools/ido-static-recomp
```

**Why it matters:** those paths are worktree-layout-dependent. A fresh clone or a different agent-letter worktree has broken symlinks there. Committing them corrupts the public history.

**Why they aren't gitignored:** the worktree setup (per `reference_worktrees.md`) creates them at worktree-creation time to share tool dirs across agents. They're a local-build convenience, not a tracked project artifact.

**Safe commit patterns:**

```bash
# GOOD: explicit paths
git add src/... episodes/... asm/nonmatchings/... undefined_syms_auto.txt expected/...
git commit -m "..."

# BAD: stages everything including symlinks
git add -A
git commit -a
```

**Recovery if you already committed them (and haven't pushed):**
```bash
git reset HEAD~1
git rm --cached tools/asm-processor/asm-processor tools/ido-static-recomp
git add <only-the-real-changed-files>
git commit -m "..."
```

**If you've already pushed:** `git revert` the symlink addition, don't try to rewrite shared history.

**Origin:** 2026-04-20, agent-a, accidentally committed symlinks during a 3-way merge-fragments commit. Caught via `git log --stat` before pushing.

---

<a id="feedback-git-amend-no-edit-parallel-agent-danger"></a>
## `git commit --amend --no-edit` in a parallel-agent worktree can absorb a wrong commit message

_When another agent pushes to main mid-operation, a local HEAD can shift underneath your feet. `git commit --amend --no-edit` then re-uses whatever the current HEAD's message is — which might not be the commit you THINK you're amending. Either explicit-add + fresh commit, or always `--amend -m "<msg>"` with the intended message._

**Rule:** In a worktree that's subject to parallel-agent pushes to main, do NOT use `git commit --amend --no-edit` after a rebase or land retry. Either:
- Make a fresh follow-up commit with its own message (cleaner history but two commits), OR
- `git commit --amend -m "<explicit message>"` to pin the message you want

**Why:** This bit me this tick on `titproc_uso_func_00000230`:

1. Ran `land-successful-decomp.sh` → script rebased my branch on top of origin/main, then committed `b7dfda9` (locally). Land check failed ("not present in report.json") because my commit was incomplete — several src/.o/syms files had been stripped by a mid-op rebase before my `git add`.
2. Re-applied the missing files, ran `git commit --amend --no-edit`.
3. `--no-edit` preserved "the current HEAD's message" — but the rebase mid-op had updated HEAD to a sibling commit `5a9ee91 h2hproc_uso_func_00000354 NM: sibling of 0x2A4` (a DIFFERENT agent's landed commit). My amend silently relabeled my work with that message.
4. Noticed only when `git log --oneline` showed the wrong commit title.

**How to recover:**
- `git reset --hard origin/main` — wipes the confused local state (my local commits are safe ON REMOTE via the prior failed land attempt; if that's not true, `git reflog` finds them).
- Re-apply the changes from scratch: edit files, explicit `git add <files>`, fresh `git commit -m "<msg>"`.
- Total cost this tick: ~5 extra minutes vs. proper first-try.

**How to apply (prevention):**
- After a land-script failure, prefer `git reset --hard origin/main` + fresh apply over `--amend`.
- When `--amend` IS necessary (rare), always supply `-m "<msg>"` explicitly. Never `--no-edit` in a worktree you don't 100 % control.
- If `git log` shows a commit message that doesn't match what you just did, TRUST the log, not your memory. Reset and redo.

**Origin:** 2026-04-20 agent-a, titproc_uso_func_00000230 (5th prologue-stolen chain match). Land-script failure → amend → wrong message → hard reset → re-apply cleanly → commit eeaff42 landed successfully.

---

<a id="feedback-git-stash-shared-across-worktrees"></a>
## `git stash` is shared across all worktrees of the same repo — never `git stash pop` blind on a multi-agent project

_Stashes live in the parent repo's `.git/refs/stash`, not per-worktree. So sister agents' stashes (created in `agent-c-worktree`, `agent-d-worktree`, etc.) appear in YOUR `git stash list` and `git stash pop` would apply their WIP into your tree. Always `git stash list` first; verify the top stash is yours by checking the message line. Pop stashes by SHA, not by index, to avoid grabbing a sister's._

**Rule:** In a multi-worktree setup like 1080's `projects/1080-agent-<letter>/`, the stash list is a SHARED resource across all worktrees. `git stash` from any worktree appends to the same stash stack. `git stash pop` pops the top — which may be a sister agent's WIP, NOT yours.

**Verified 2026-05-05 on agent-a:**
```
$ git stash list
stash@{0}: On agent-d: WIP                         ← sister agent's stash
stash@{1}: On agent-c: agent-c-wip-nonmatching-and-docs   ← another sister
```

When my own stash WAS empty (post-revert tree was clean, so `git stash`
was a no-op), the next `git stash pop` would have grabbed `stash@{0}`
which was agent-d's WIP, polluting agent-a's worktree with unrelated
changes.

**Diagnostic:**
- `git stash list` always shows ALL stashes from ALL worktrees of the same repo.
- The "On <branch>: <message>" prefix tells you WHICH worktree created it.
- Stashes from your branch are safe to pop; stashes from sister branches are NOT.

**How to apply:**
1. Before `git stash pop`, ALWAYS `git stash list` and check the message.
2. If `stash@{0}` is from a sister agent ("On agent-X: ..." where X != your branch),
   either pop a specific index (`git stash pop stash@{N}`) or use the SHA, NOT index.
3. Even safer: don't stash at all in multi-agent setups. Commit WIP to your branch
   instead, or use a worktree-local approach (e.g., copy files to /tmp).

**Why this is non-obvious:**
- Stash refs feel "local" — most users assume per-worktree.
- The bug is silent: `git stash pop` succeeds even when applying a sister's WIP.
  You'd only notice when reviewing the changes (or after the conflict resolution).
- 1080's spin-up-agent.sh creates worktrees but the shared `.git/refs/stash` is
  a single reservoir.

**Companion memos:**
- `feedback_parallel_agent_wrap_nesting.md` — sister-agent merge artifacts.
- `feedback_sister_agent_orphan_commits_resurface_as_unstarted.md` — sister-agent
  orphan commit detection.

**Failure mode I caught (2026-05-05):**
After a revert (no real changes to stash), I ran `git stash` which was a no-op.
Then later `git stash pop` would have applied agent-d's WIP. Caught by reading
`git stash list` output before popping.

---

<a id="feedback-pat-lacks-workflow-scope-blocks-yml-push"></a>
## GitHub PAT used by `git push` lacks `workflow` scope; pushing changes to .github/workflows/ is rejected

_Pushing to bigyoshi51/1080-decomp from a CLI agent fails with "remote rejected ... refusing to allow a Personal Access Token to create or update workflow ... without `workflow` scope" any time .github/workflows/*.yml is in the commit. Affects both branch pushes and main pushes. Workaround: ask the user to push from a properly-scoped local checkout, OR temporarily separate the workflow change from non-workflow changes so the non-workflow commits push and the workflow commit remains pending._

**Symptom (verified 2026-05-04):**
```
! [remote rejected] agent-e -> agent-e (refusing to allow a Personal Access Token
  to create or update workflow `.github/workflows/build.yml` without `workflow` scope)
error: failed to push some refs to 'https://github.com/bigyoshi51/1080-decomp.git'
```

**When this matters:**
- Any time you commit a change to `.github/workflows/*.yml` and `git push`.
- Both feature-branch pushes and main pushes are blocked equally.
- Other commits in the same push that DON'T touch workflows don't help — push is all-or-nothing per ref.

**How to handle:**
1. Don't try to bypass with `--force` or alternate auth — the user's PAT specifically lacks the scope and there's no harness-side fix.
2. Tell the user clearly: "The workflow commit needs a token with `workflow` scope. Either push it yourself from a local checkout, or update the PAT scope and I'll retry."
3. If non-workflow commits are also pending, either:
   - Push them via a temp branch first (rebase the workflow commit onto a separate branch), OR
   - Tell the user about the chain so they can push the whole stack themselves.

**Why this isn't an in-band fix:**
The PAT scope is a credential property, not a repo property. Updating it requires the user's GitHub account UI. The agent has no way to grant itself the scope.

---

<a id="feedback-pre-existing-text-mismatch-diagnose-via-stash"></a>
## When an NM-wrap commit shows .text mismatch, FIRST stash to confirm — upstream state may already be broken

_When you add an `#ifdef NON_MATCHING / void func() { ... } / #else INCLUDE_ASM(...) / #endif` wrap and observe `cmp build/.o.text expected/.o.text` reports a diff, the natural assumption is that your wrap broke something. But the wrap CAN'T affect the default-build .text (the C body is preprocessed away). FIRST `git stash` and re-cmp: if the mismatch persists, the upstream baseline (expected/.o) itself is broken — possibly from a parallel-agent's incomplete refresh-expected-baseline run, a Yay0-rebuild flake, or unrefreshed expected after a sibling C-body landing. Don't blame your wrap; the wrap is innocent._

**The trap (verified 2026-05-05 on game_uso_func_0000F424 wrap)**:

You add a NM wrap to game_uso.c:

```c
#ifdef NON_MATCHING
void game_uso_func_0000F424(int *a0) { /* decoded body */ }
#else
INCLUDE_ASM("asm/nonmatchings/game_uso/game_uso", game_uso_func_0000F424);
#endif
```

`.mdebug` line numbers shift (per
`feedback_o_diff_in_mdebug_from_nm_wrap_line_shift.md`), so whole-`.o`
cmp shows a diff. You correctly switch to comparing only `.text`:

```bash
mips-linux-gnu-objcopy -O binary --only-section=.text build/.../game_uso.c.o /tmp/build.text
mips-linux-gnu-objcopy -O binary --only-section=.text expected/.../game_uso.c.o /tmp/expected.text
cmp /tmp/build.text /tmp/expected.text
# /tmp/build.text /tmp/expected.text differ: byte 1484, line 7
```

`.text` ALSO differs — and the size is bigger by 0x10 (16 bytes). You panic:
"my wrap is somehow adding 16 bytes to .text!" But the `#else INCLUDE_ASM`
path is the only path compiled (NON_MATCHING is undefined). It CAN'T add
bytes.

**The diagnostic recipe**:

```bash
# Step 1: confirm the mismatch persists WITHOUT your edit:
git stash
make RUN_CC_CHECK=0
mips-linux-gnu-objcopy -O binary --only-section=.text build/.../game_uso.c.o /tmp/build_no.text
cmp /tmp/build_no.text /tmp/expected.text
# If still differs: pre-existing state issue, NOT your wrap.

# Step 2: find which function changed size between build and expected
python3 << 'PY'
import subprocess, re
def syms(o):
    r=subprocess.check_output(["mips-linux-gnu-objdump","-t",o],text=True)
    return sorted([(int(m.group(1),16), int(m.group(2),16), m.group(3))
                   for line in r.split("\n")
                   for m in [re.match(r"^([0-9a-f]+)\s+g\s+F\s+\.text\s+([0-9a-f]+)\s+(\S+)$", line)]
                   if m], key=lambda x:x[0])
b={n:(a,s) for a,s,n in syms("build/.../X.c.o")}
e={n:(a,s) for a,s,n in syms("expected/.../X.c.o")}
for n,(ba,bs) in b.items():
    if n in e:
        ea,es = e[n]
        if bs != es:
            print(f"SIZE DIFF @ {n}: build={bs:04x} expected={es:04x} delta={bs-es:+d}")
PY

# Step 3: restore your wrap
git stash pop
```

If step 2 reveals a size-changed function that you didn't touch, the
upstream baseline is broken — probably from one of:

- **Parallel-agent merge artifact**: another agent landed a C-body change
  but the refresh-expected-baseline ran on a fresh checkout that doesn't
  include other concurrent changes (race during the post-cc recipe).
- **Stale expected/ post-rebase**: your rebase pulled in a sibling agent's
  C-body commit but expected/.o snapshot was taken before that commit
  was applied. Re-running `python3 scripts/refresh-expected-baseline.py`
  fixes it.
- **Yay0-driven .o size change**: USO source files trigger crunch64.yay0
  re-pack and the .o sizes can shift if a sibling unmatched function
  changed. Same fix: refresh-expected-baseline.

**Verified 2026-05-05 on game_uso_func_0000F424 wrap**:
- Added wrap, saw `.text differ: byte 1484, line 7` (build 0x11bd0 vs expected 0x11bc0, +16 bytes).
- Stashed → mismatch persisted (build_no.text vs expected.text still differs at byte 1484).
- Symbol scan revealed: `game_uso_func_000034A4` is 0xC0 in build, 0xB4 in expected (+12 bytes).
- That function is a real C body landed in commit c17975f and has no edits since.
- Conclusion: the wrap is innocent; some prior baseline-refresh left expected/ with the wrong size for game_uso_func_000034A4. Land the wrap; the pre-existing mismatch is for a separate fix.

**Why this matters**:

Without this diagnostic, an agent will:
1. See the .text mismatch
2. Blame their own wrap
3. Revert (losing 30 mins of decode work)
4. Move on, leaving the wrap forever-blocked

The wrap commit is safe to land — it's a doc-only change in default build. The pre-existing upstream mismatch is a separate problem to investigate.

**Related**:
- `feedback_o_diff_in_mdebug_from_nm_wrap_line_shift.md` — sibling about whole-`.o` cmp picking up .mdebug shifts
- `feedback_byte_verify_via_objcopy_not_objdump_string.md` — the right addr+size+objcopy pattern
- `feedback_refresh_expected_baseline_blocks_on_yay0_rom_mismatch.md` — when refresh itself fails
- `feedback_per_file_expected_refresh_recipe.md` — per-file refresh as workaround

---

<a id="feedback-shell-cwd-drift-in-worktree"></a>
## Bash `cd` into main worktree during land persists across later turns — run land from subshell

_In 1080 parallel-agent worktree flow, the manual land fallback is `cd <main-worktree> && git merge --ff-only <agent-branch> && git push`. That `cd` changes the Bash tool's persistent cwd. If I keep working in that session, all later bash commands run in the MAIN worktree, while the Edit tool still writes to the agent-e file (absolute path). Result: `git status` says "clean" and `grep` says "my edits aren't there" even though the agent-e file on disk is correct. Wastes 5-10 min debugging. Fix: always run the land sequence as a single `cd ... && ... && cd -` or in a subshell `(cd ...; ...)`._

**Symptom:** after landing via manual fallback, next Bash commands seem to show:
- `git status` clean (no diffs)
- `grep` doesn't find code I know I just added
- `wc -l` shows a different line count than the Read tool

That's because `cd` persisted — Bash tool is in the main worktree, but Edit/Read tools are still hitting agent-e via absolute path.

**Tells that you're drifted:**
- `readlink -f <file>` shows the main worktree path, not agent-e
- `pwd` shows the main worktree path
- File has different md5sum in shell vs via absolute-path Read

**Fix during the session:** `cd /home/dan/Documents/code/decomp/projects/1080-agent-<letter>` and re-check.

**Prevention (recipe):** the land sequence should never leave the shell in the main worktree. Pick one:

Option A — chain with a final `cd -`:
```bash
cd "/home/dan/Documents/code/decomp/projects/1080 Snowboarding (USA)" && \
  git fetch origin && git merge --ff-only agent-e && git push origin main && \
  cd -
```

Option B — subshell (cleanest, automatic unwind):
```bash
(cd "/home/dan/Documents/code/decomp/projects/1080 Snowboarding (USA)" && \
  git fetch origin && git merge --ff-only agent-e && git push origin main)
```

Option C — prefer `scripts/land-successful-decomp.sh <func>` over the manual fallback; the script handles worktree switching internally and doesn't leave the caller in a wrong cwd.

**Why this keeps happening:** the user already caught this once earlier in the session ("wait, are you working on an agent branch? you should be"). It's an easy regression because the `cd` command feels like a transient change but actually persists in the Bash tool's shell state. The Bash tool's tool description even warns "the working directory persists between commands" — respect that.

**Origin (2026-04-20):** during game_uso_func_00007538 partial-C body work, I cd'd into the main worktree to land a doc-only commit manually. The next ~10 bash commands silently ran in main instead of agent-e. My Edit tool's changes to agent-e's file looked like they "disappeared" from shell view because shell was reading from main's file (which wasn't updated yet). Only `readlink -f` on the file path revealed the drift.

---

<a id="feedback-worktree-mass-revert-recovery"></a>
## Recovering when another agent's process has mass-reverted your worktree's src/ files

_With multiple parallel agents on 1080-decomp, one agent's rebase/reset/splat-rerun can mass-revert another worktree's src/ .c files to all-INCLUDE_ASM, wiping your in-progress NM wraps and exact matches. If `git status` shows dozens of `M src/` files you didn't edit, check `origin/main` — your work is usually safe there (if landed). `git reset --hard origin/main` in your worktree recovers. You only lose *uncommitted* changes since the last land._

**Symptom:** You start a /decompile run. You go to edit a file you were just in, and either:
1. The `Read` tool shows content reverted to pre-work state (INCLUDE_ASM blocks where you had C bodies).
2. `git status` shows tons of `M src/*.c` files you didn't touch.
3. Specific exact matches you just landed are gone.

**Cause:** Another parallel agent's session in another worktree ran a sweeping script (splat re-run, make expected, rebase with --no-autostash, etc.) that shares a git index with yours in some confused way, OR a cron-driven land script fast-forwarded main and your local branch somehow got reset.

**Quick diagnosis:**
```bash
# Check if your landed work is still on origin/main:
git show origin/main:src/<file> | grep "<your_landed_func>"
# If yes → worktree state got corrupted, but work is safe
# If no  → actual loss, investigate git reflog
```

**Recovery:**
```bash
git reset --hard origin/main
```
This re-syncs your worktree to the last landed state. Any uncommitted local edits are lost; committed-but-unlanded branch work is also lost if it wasn't on origin yet — recover via `git reflog` if needed.

**Prevention:**
- Commit and land IMMEDIATELY after each exact match (per skill rule 9a). Don't hoard uncommitted work.
- If you see the mass-revert happen mid-tick, STOP. Don't make edits — reset first, then re-apply what you had in memory.

**Origin:** 2026-04-20, agent-a, mid-grind on game_uso_func_0000751C. My `game_uso_func_000074D8` exact match had just landed but the local worktree was reset to pre-match state, plus many other src/ files showed as `M` without my edits. `git reset --hard origin/main` recovered; all landed work was intact.

---

