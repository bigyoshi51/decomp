# N64 single-function verifier RL environment

## Status and scope

`n64-decomp-v1` turns exact-match episode logs into historical,
single-function decompilation tasks. The reusable implementation lives in
`decomp/rl/`; the Verifiers v1 adapter lives in
`environments/n64_decomp_v1/`. `project_profiles/1080.yaml` is the first
project profile, not hard-coded environment logic.

The environment has two modes over the same task manifest and scorer:

- **`coding_agent` (primary):** Verifiers' `default` harness receives a
  redacted historical project tree with bash and edit tools. The final source
  is copied into a second trusted fixture and scored after the harness exits.
- **`submit_candidate` (secondary):** Verifiers' `null` harness receives only
  a stateful `submit_candidate(source)` tool. Each call compiles in a new
  trusted verifier container and returns the current and best match percentage.

Both modes compile the historical object target and compare it with its
tracked historical `expected/*.o` using `objdiff-cli`. They do not need a ROM
in the rollout loop.

## Trust boundary

The model may see the target assembly, starter C, public headers, neighboring
source, compiler label/flags, and build output. It does not receive:

- `.git` or repository history;
- `episodes/` or canonical `final_source`;
- `expected/` or the private reference object;
- `report.json` from the solved checkout.

Historical snapshots are produced with `git archive`, the target function is
replaced with its predecessor/episode starter, every duplicate target
definition and target-specific comment is redacted, and hidden paths are
removed.
Final coding-agent scoring extracts only the target function from the model's
workspace and sends it to a fresh sibling verifier container that is never
exposed to the model. Changes to Makefiles,
headers, scripts, neighboring functions, or generated objects therefore
cannot affect reward. Candidate policy also rejects `INCLUDE_ASM`,
`GLOBAL_ASM`, inline assembly, raw byte directives, and post-compile patch
markers.

The constrained MCP server runs outside the agent runtime and sends candidates
to the same fresh sibling verifier. Private references therefore never enter
either mode's agent runtime, including during post-rollout scoring.

## Dataset preparation

Generate the gold-free provenance manifest from the repository root:

```bash
uv run decomp-rl manifest \
  --project-root projects/1080-decomp \
  --profile project_profiles/1080.yaml \
  --output exports/1080-v1/tasks.jsonl
```

Discovery recognizes canonical and legacy exact episodes. It searches the
pinned repository history for the exact function body, then resolves a
compatible objdiff unit and expected object. The editable source and compiled
unit are intentionally separate: this supports donor-object splices such as
1080's `REPLACE_FUNC_BODY` recipes. Episodes that cannot be reproduced are
retained with a quarantine status and reason instead of being silently
dropped.

At the pinned 1080 revision, the provenance pass covers all 2,239 episode
files: 2,238 are ready and one is `needs_provenance`. The remaining provenance
row, `func_800081D0`, is a linker-defined alternate entry in the middle of
`func_8000817C`, not an independent C definition; it is intentionally outside
the current single-function task model. This is the discovery denominator, not
the release denominator; the full compile audit below is still required before
training.

Profiles may set `metadata.history_search_limit` to bound the expensive
fallback walk through history reachable from the pinned revision after the
direct episode-revision check. A row outside that bound remains in the
manifest as `needs_provenance`; increasing the limit is a deliberate cleanup
pass, not a silent dataset change.

The 1080 profile also enables two conservative cleanup fallbacks for legacy
data. Malformed gold is recovered from an unambiguous target definition in the
pinned source tree, and a bounded pinned-revision replay can supply a compatible
build context when the episode-era split no longer exists. These rows retain
recovery evidence and lower provenance confidence until the build audit proves
the recovered C exact.

Splits are deterministic 90/5/5 train/validation/test assignments. The split
key is a normalized assembly-shape fingerprint, so byte/address variants of
the same function shape cannot leak across splits.

Do not publish a manifest generated with `--include-gold`. That switch exists
only for trusted debugging.

### Release build audit

The provenance pass is ROM-free and does not require the compiler. Before a
dataset release, compile both the starter and gold source for every ready row:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/work" -w /work \
  ghcr.io/bigyoshi51/n64-decomp-verifier:1080-v1 \
  decomp-rl build-audit \
    --project-root projects/1080-decomp \
    --profile project_profiles/1080.yaml \
    --toolchain-source /opt/ido-static-recomp \
    --workers 4 \
    --checkpoint-every 10 \
    --resume \
    --output exports/1080-v1/tasks.audited.jsonl
```

`--resume` accepts a missing output on the first run. Thereafter it validates
task identity, retains completed rows, and retries only unfinished rows. Every
checkpoint is an atomic file replacement, so interruption cannot leave a
partially written JSON line. An existing output requires either `--resume` or
the explicit destructive choice `--overwrite`.

For independent workers or machines, add `--shard-count N --shard-index I` and
give each shard a distinct output. Assignment is a stable hash of `task_id`, so
it does not change when manifest order changes. Merge only after every shard
finishes:

```bash
uv run decomp-rl merge-audits \
  --expected exports/1080-v1/tasks.jsonl \
  --input exports/1080-v1/audit-shard-0.jsonl \
  --input exports/1080-v1/audit-shard-1.jsonl \
  --output exports/1080-v1/tasks.audited.jsonl
```

The merge rejects duplicate, stale, unexpected, and missing task IDs. It also
rejects a `ready` row without a measured starter baseline, proving that copying
the discovery manifest cannot masquerade as a completed audit. Re-run a
quarantined class with `--resume --retry-status <status>`.

The audit records the starter's measured `initial_match_percent`, requires the
gold to reach exact, and stops immediately on verifier infrastructure failure.
If a recovered historical starter no longer compiles in the resolved split
unit, it retries a signature-preserving empty scaffold; the audited row records
whichever starter was actually measured. Already-exact or still-noncompiling
starters are quarantined. If episode gold itself fails, profiles may allow one
retry using the pinned source definition; that replacement is retained only
when the compiler and exact-byte gate pass, and its provenance confidence is
promoted to `verified`. Duplicate definitions use a relocation-bearing redacted
scaffold so donor-object splice recipes remain runnable without exposing gold
C. Use the audited manifest in release/training configs.
During quarantine cleanup, pass one or more repeatable
`--episode episodes/<name>.json` arguments to audit only selected rows.

The July 2026 cleanup audit of the original 65 `needs_provenance` rows produced
63 compiler-confirmed ready tasks. `func_800081D0` remains excluded as the
mid-function linker entry described above, and `gl_func_00006F60` is excluded
because its signature-preserving starter is already byte-exact. No unresolved
ordinary function remains in that quarantine set.

## Verifier image

Build the pinned IDO 5.3/7.1, MIPS binutils, objdiff, and Python environment:

```bash
docker build \
  -f containers/n64-decomp-verifier.Dockerfile \
  -t ghcr.io/bigyoshi51/n64-decomp-verifier:1080-v1 .
```

Build from a checkout that already has `projects/1080-decomp`; the image copies
that revision's vendored asm-processor while `.dockerignore` excludes the rest
of the nested project and all Git metadata.

The profile's `toolchain_image` selects this image per task. A different
project can use another image while retaining the taskset/scorer.

## Evaluation

Create the image and audited manifest first, then run either mode from this
repository root:

```bash
uv run --project environments/n64_decomp_v1 eval \
  @ configs/eval/n64-decomp-coding-agent.toml \
  --model <openai-compatible-model>

uv run --project environments/n64_decomp_v1 eval \
  @ configs/eval/n64-decomp-submit-candidate.toml \
  --model <openai-compatible-model>
```

The checked-in eval configs select the held-out test split. Start with a few
tasks and one rollout, inspect traces and compile diagnostics, and only then
increase concurrency.

## Prime-RL training

Clone and install current Prime-RL, then install this repository and taskset in
its virtual environment:

```bash
git clone https://github.com/PrimeIntellect-ai/prime-rl.git /path/to/prime-rl
cd /path/to/prime-rl
git submodule update --init
uv sync --all-extras
uv pip install --python .venv/bin/python -e /path/to/decomp
uv pip install --python .venv/bin/python -e /path/to/decomp/environments/n64_decomp_v1
```

Launch from the decomp repository root so the relative project/profile paths
in the configs resolve correctly:

```bash
uv run --project /path/to/prime-rl rl \
  @ configs/rl/n64-decomp-coding-agent.toml

uv run --project /path/to/prime-rl rl \
  @ configs/rl/n64-decomp-submit-candidate.toml
```

Environment-server workers need access to a Docker daemon. The agent runtime
and the trusted verifier are separate containers; constrained-mode submissions
start a fresh verifier container for each candidate to prevent cross-attempt
state from affecting reward.

The configs use eight rollouts per example for group-relative advantages and
run online validation every 20 steps. The coding-agent config allocates a
larger sequence/completion budget because terminal trajectories are longer.
Tune batch size, model parallelism, and deployment for the available GPUs.

Reward is `1.0` only when objdiff reaches 100% and raw ELF bytes outside
relocation-covered words are identical. (Relocation addends may differ in
relocatable objects while linking identically; objdiff checks those semantics.)
A compiled non-exact candidate earns up to `0.9` according to verified
progress over its measured starter:

```text
0.9 * clamp((candidate_percent - starter_percent)
            / (100 - starter_percent), 0, 1)
```

Compile or policy failure earns zero. The task trace records compile status,
exactness, match percentage, attempts (constrained mode), and a bounded
diagnostic.

## Adapting another decomp project

Add a YAML profile with its repository URL/revision, episode/source/assembly
roots, objdiff config, object-target template, make arguments, hidden paths,
and verifier image. The project must provide tracked exact reference objects
or an equivalent profile adapter; no ROM should be required for the selected
object target.

Run provenance discovery, inspect every quarantine category, add resolver
support for any project-specific unit indirection, then run the release build
audit. Do not mark a project supported merely because its current HEAD builds:
the gold-era source split, optimization level, compiler version, and
post-processing recipe must reproduce independently.

For a public project, also apply an egress policy that prevents a coding agent
from downloading the solved repository or published episode corpus. The
constrained mode has no shell or network tool, but a full coding harness is
only leakage-resistant when private source history remains inaccessible or
its sandbox egress is restricted.
