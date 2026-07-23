# n64-decomp-v1

A Verifiers v1 taskset for exact, single-function N64 decompilation. It supports
two harness modes over the same manifest and trusted object verifier:

- `coding_agent`: the standard Verifiers `bash` harness gets a redacted
  historical project snapshot with bash and edit tools.
- `submit_candidate`: the `null` harness gets only a stateful
  `submit_candidate(source)` tool and iterative compile/diff feedback.

The model never receives the episode gold C, Git history, or `expected/*.o`.
Final coding-agent scoring rebuilds in a fresh sibling verifier container that
the harness never controls. The constrained MCP server runs outside its
tool-less harness and uses the same isolated verifier.

Generate a manifest from the repository root before running an eval:

```bash
uv run decomp-rl manifest \
  --project-root projects/1080-decomp \
  --profile project_profiles/1080.yaml \
  --output exports/1080-v1/tasks.jsonl
```

Then run the documented release build audit and use its
`exports/1080-v1/tasks.audited.jsonl` output for eval or training.

See `docs/RL_ENVIRONMENT.md` for image setup, validation, evaluation, and
Prime-RL commands, including the checked-in one-step single-GPU smoke config.
