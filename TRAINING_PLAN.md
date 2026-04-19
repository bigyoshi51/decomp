# Training Plan

This document captures the current plan for turning the repo's decompilation
episodes and scaffolding into useful training assets for:

- supervised fine-tuning (SFT)
- verifier-based reinforcement learning (RL)

The central recommendation is:

- keep improving the decomp project now
- keep logging exact matches in the canonical structured schema
- use the historical episode corpus primarily for SFT, eval, and prompt mining
- defer the actual verifier-RL environment buildout until the task distribution
  and verifier path are more stable

## Goal

Eventually support two training modes:

1. SFT on exact-match decompilation examples
2. fresh-rollout verifier RL where the model generates candidate C online and
   receives reward from project-native verification

This repo does not need to choose one forever. The intended flow is:

- SFT/bootstrap first
- verifier RL later

## Current State

There are currently two episode formats in the repo:

- `decomp/episode.py`
  - legacy exact-match format
  - centered on fields like `asm_text`, `m2c_output`, `attempts`, `final_c`
- `decomp/logging/episode.py`
  - canonical structured `Episode` / `Step` format
  - used by the agent loop and now by the exact-match helper

Operationally:

- new exact-match logs should use `decomp.logging.episode.log_exact_match`
- `decomp.episode.log_success` is legacy-only and should not be used for new
  data
- the 1080 and Glover project hooks validate newly added episode files against
  the canonical schema

Current 1080 corpus characteristics:

- a few hundred solved episodes already exist
- almost all are positive exact matches
- nearly all are single-attempt summaries rather than rich trajectories

That makes the current corpus much better suited to SFT than to tool-trajectory
RL.

## Guiding Principles

- Exact-match solves are always useful.
- Historical data should not be rewritten aggressively while active decomp work
  is ongoing.
- RL should train on fresh generations from a verifier, not on old trajectories,
  unless we explicitly decide to build a multi-step tool-use RL setup.
- The repo state should remain the source of truth for tasks and verification.
  Export formats are derived artifacts.

## What We Need Now

### 1. Logging Hygiene

Keep doing this now:

- log every new exact match in the canonical `Episode` / `Step` schema
- keep landing exact matches with their episode file in the same history
- keep schema checks strict in hooks and landing scripts

This preserves future optionality without forcing an immediate training
pipeline.

### 2. Better Project Progress

Continue decomp work until the solved set is more representative. In practical
terms, that means:

- more medium and large functions
- more non-wrapper game code
- more stable per-project compiler/verification conventions
- fewer moving pieces in source layout and file-split policy

This matters because an RL environment built too early will reflect the current
bootstrap phase, not the eventual task distribution.

## Historical Episodes

Do not mass-migrate or rewrite the historical `episodes/*.json` files right now.

Treat them as `legacy_v1` data:

- keep them in place
- keep using them for SFT, eval, and prompt mining
- do not require them to pass the new canonical validator

Use them for:

- exact-match SFT examples
- evaluation targets
- prompt/context mining
- difficulty estimation
- project history / provenance

Do not treat them as canonical RL trajectories.

## SFT Plan

### Immediate Outcome

Build a derived exporter that reads both episode schemas and emits normalized
training data outside the repo's source-of-truth episode files.

Suggested derived outputs:

- `sft_exact_matches.jsonl`
- `eval_exact_matches.jsonl`

### SFT Unit of Training

The basic SFT example should be one exact-match decompilation problem:

- prompt/context:
  - function name
  - project
  - segment
  - assembly
  - optional m2c seed
  - optional nearby context
  - optional compiler/verifier metadata
- target:
  - exact matching C solution

### What Goes Into the Exporter

For canonical episodes:

- read directly from `Episode` / `Step`
- use `initial_m2c_source`, `final_source`, `instruction_count`, and metadata

For legacy episodes:

- map `m2c_output` -> `initial_m2c_source`
- map `final_c` -> normalized target source
- map legacy metadata fields into exporter-side metadata

### SFT Dataset Policy

Only include exact matches.

Weighting and filtering should likely:

- include solved medium/hard functions with higher value than tiny wrappers
- consider segment-specific balancing
- optionally separate wrapper-heavy subsets from richer control-flow tasks

## Verifier RL Plan

### Core Point

Verifier RL does not require historical trajectories.

It needs:

- a task distribution
- an environment
- a verifier/reward function

The environment should generate fresh rollouts online.

### Recommended First Version

Do not start with multi-step tool-use RL.

Start with single-shot function decompilation:

1. sample a function task
2. provide the model with prompt/context
3. model emits candidate C
4. environment patches the target location
5. build and verify
6. return reward

This is the lowest-complexity path that still captures the real decomp task.

### Verifier Design

Use project-native verification.

For 1080 specifically:

- prefer object-level verification and `objdiff`-style reporting
- use full ROM verification mainly for offline eval / confidence checks

This is cheaper and more aligned with how the project is already verified.

### Reward Shape

The first reward model should stay simple:

- large terminal reward for exact match
- dense reward from match percentage / diff count
- compile failure penalty
- optional penalty for collateral regressions in the same compilation unit

Avoid clever reward shaping early. Keep it interpretable.

## Task Manifest

We do not need a committed `rl_tasks.jsonl` right now.

The recommended internal abstraction is:

- a Python `TaskSpec` or equivalent dataclass
- task discovery from current repo state

Only export a task manifest later if needed for:

- frozen train/eval splits
- distributed workers
- reproducible benchmark snapshots

If that export exists later, it should remain minimal:

- `task_id`
- `project`
- `function_name`
- `asm_path`
- `source_path`
- `verifier_profile`
- `compiler`
- `compiler_flags`
- `instruction_count`
- `split`

Do not bake full prompt context, gold answers, or trajectory data into the task
manifest.

## Why We Are Deferring the RL Environment

We should wait before building the actual verifier environment because:

- the solved set is still skewed toward small exact matches and wrappers
- verification conventions are still somewhat project-specific
- file layout and per-file flag policy are still evolving as part of the decomp
- any environment built now is likely to be redesigned once the task set
  broadens

The delay is strategic, not indefinite.

## Readiness Gates For RL Buildout

Start the verifier environment build when most of these are true:

- the solved set includes a meaningful spread of small, medium, and larger
  functions
- exact-match verification is stable for the main project(s)
- source file layout and compiler-flag policy are mostly settled
- the canonical episode schema is in regular use for new solves
- the exporter for SFT/eval data exists and is working

## Concrete Phases

### Phase 0: Now

- keep decompiling
- keep logging exact matches in canonical schema
- keep historical episodes untouched

### Phase 1: Data Exports

- implement a dual-schema exporter
- produce SFT and eval outputs from both historical and canonical logs

### Phase 2: RL Prep

- define `TaskSpec`
- define verifier profiles per project
- define patch/build/verify loop for one-shot function tasks

### Phase 3: RL Environment

- build the single-shot verifier environment
- train from fresh generations
- keep ROM-wide checks as eval, not the main training inner loop

### Phase 4: Optional Extensions

Only after the single-shot environment is working:

- task manifests for reproducible splits
- richer context builders
- curriculum scheduling
- multi-step tool-use RL

## Near-Term Deliverables

When the repo is ready, the first concrete training-related deliverables should
be:

1. `export_episodes.py`
   - reads legacy and canonical episode files
   - emits normalized SFT/eval JSONL
2. `TaskSpec` discovery
   - repo-derived problem definitions for verifier RL
3. per-project verifier profiles
   - especially for 1080 object-level exactness checks

## Summary

The right plan is:

- preserve and use the historical episodes
- do not force them into being RL trajectories
- use them to bootstrap SFT and eval
- continue the decomp until the task and verifier landscape are more stable
- then build a simple verifier-based single-shot RL environment on top of the
  repo's native verification flow

This keeps current decomp velocity high while still moving toward useful SFT and
verifiable RL training.
