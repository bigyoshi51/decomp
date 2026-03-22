"""Milestone 2: Claude API agent loop for iterative N64 decompilation.

The agent reads assembly, generates C via m2c, compiles with KMC GCC 2.7.2,
diffs against the ROM, and iterates until byte-match or max attempts.
Each successful episode is logged as structured JSON for training.

Each agent run uses a git worktree for isolation, enabling parallel runs.
On success, the worktree branch is merged back to main.
On failure, the worktree is discarded with no changes to main.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from decomp.core.config import DecompConfig
from decomp.core.project import DecompProject
from decomp.logging.episode import EpisodeLogger, ToolCall

from .tools import TOOLS, ToolExecutor


def _create_worktree(project_root: Path, func_name: str) -> tuple[Path, str]:
    """Create an isolated git worktree for the agent to work in."""
    branch = f"agent/{func_name}-{uuid.uuid4().hex[:8]}"
    wt_path = Path(tempfile.mkdtemp(prefix="decomp-agent-"))

    subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch],
        cwd=project_root,
        capture_output=True,
        check=True,
    )

    # Symlink gitignored files that the agent needs
    # (NOT build/ — each worktree needs its own)
    for name in ["baserom.z64", "tools"]:
        src = project_root / name
        dst = wt_path / name
        if src.exists() and not dst.exists():
            dst.symlink_to(src)

    return wt_path, branch


def _merge_worktree(
    project_root: Path,
    wt_path: Path,
    branch: str,
    func_name: str,
) -> str | None:
    """Push the worktree branch and open a PR.

    Returns the PR URL on success, None on failure.
    """
    # Clean up backup files before committing
    for bak in wt_path.rglob("*.bak"):
        bak.unlink()

    # Commit in the worktree
    subprocess.run(
        ["git", "add", "-A"],
        cwd=wt_path,
        capture_output=True,
    )
    commit_result = subprocess.run(
        ["git", "commit", "-m", f"Decompile {func_name} (agent)"],
        cwd=wt_path,
        capture_output=True,
        text=True,
    )
    if commit_result.returncode != 0:
        import sys

        print(
            f"[merge] git commit rc={commit_result.returncode}",
            file=sys.stderr,
        )
        print(
            f"[merge] stdout: {commit_result.stdout}",
            file=sys.stderr,
        )
        print(
            f"[merge] stderr: {commit_result.stderr}",
            file=sys.stderr,
        )
        # List what git sees
        st = subprocess.run(
            ["git", "status", "--short"],
            cwd=wt_path,
            capture_output=True,
            text=True,
        )
        print(
            f"[merge] git status: {st.stdout}",
            file=sys.stderr,
        )
        return None

    # Push the branch
    result = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=wt_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        import sys

        print(
            f"[merge] git push failed: {result.stderr}",
            file=sys.stderr,
        )
        return None

    # Open a PR
    result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            f"Decompile {func_name}",
            "--body",
            f"Agent-decompiled {func_name}. Verified byte-matching in worktree.",
            "--head",
            branch,
        ],
        cwd=wt_path,
        capture_output=True,
        text=True,
    )
    pr_url = result.stdout.strip() if result.returncode == 0 else None

    # Clean up worktree (but keep the remote branch for the PR)
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt_path)],
        cwd=project_root,
        capture_output=True,
    )

    return pr_url


def _cleanup_worktree(project_root: Path, wt_path: Path, branch: str) -> None:
    """Remove a worktree and its branch."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt_path)],
        cwd=project_root,
        capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=project_root,
        capture_output=True,
    )


SYSTEM_PROMPT = """\
You are an expert N64 decompilation agent. Your goal is to produce byte-matching \
C code for MIPS assembly functions compiled with KMC GCC 2.7.2.

## Workflow

1. Read the target function's assembly with `read_assembly`.
2. Run `run_m2c` to get initial pseudo-C as a starting point.
3. Use `read_nearby_functions` to see how already-decompiled functions in the same \
file look (for style, types, patterns).
4. Read the source file with `read_source` to see the INCLUDE_ASM line and context.
5. Replace the INCLUDE_ASM line with your decompiled C code using `write_function`. \
This safely replaces just the target function, preserving everything else.
6. Compile with `compile` (use clean=true on first attempt).
7. Run `verify_rom` to check if the function matches byte-for-byte.
8. If not matching, analyze the diffs and iterate on the C code.

## Compiler: KMC GCC 2.7.2

Our compiler reconstruction is validated as byte-identical to the original KMC CC1. \
All matching issues are source code problems, never compiler differences.

- Default flags: `-G0 -mips3 -mgp32 -mfp32 -Wa,--vr4300mul-off -O2 -g2`
- The `-g2` flag is passed to the assembler, which DISABLES delay slot reordering. \
Most Glover functions have unfilled delay slots (`addiu $sp; jr $ra; nop`).
- ~160 game segment functions have filled delay slots (compiled WITHOUT `-g`).
- Check the epilogue pattern to determine which flag the original used:
  - `addiu $sp; jr $ra; nop` = compiled with `-g2` (default)
  - `jr $ra; addiu $sp` = compiled WITHOUT `-g`
  - Frame pointer (`$fp`/`$s8`) in prologue = `-O0`

## Matching Tips

### Register Allocation
- GCC 2.7.2 assigns $s0-$s7 by priority: \
`floor_log2(n_refs) * n_refs / live_length`. Higher priority → lower register.
- Tiebreaker: first-encountered pseudo-register wins (gets lower $s number).
- To change allocation: modify args in-place (`arg0 &= -4`) to increase refs; \
use separate temp variables for values that don't survive calls (keeps them in $a/$v); \
combine expressions inline to reduce ref counts of intermediates.
- Splitting `val = *ptr + 1` into `val = *ptr; val++;` can change which $a register \
is used in leaf functions.

### Branch-Likely (beql/bnel)
- GCC emits `beql`/`bnel` when the delay slot can be filled with a store from \
the taken path AND the branch target is the function epilogue.
- Use `goto label` to a shared store+return point — this produces `beql` where \
separate `if/return` blocks produce plain `beq`.
- Wrapping code in `if (cond) { ... } label: *arg0 = val; return val;` with \
gotos inside produces the right beql pattern.
- `return val` inside a loop skips cleanup calls (produces beql to epilogue). \
`break` goes to after the loop where cleanup still runs.

### Unsigned Comparison
- `(u32)arg > 0x8000U` produces `sltu`. Signed `arg > 0x8000` produces `slt`.

### Other Tips
- `-2` vs `~1` vs `0xFFFFFFFE` produce different instructions.
- When assigning 0xFF to s8, GCC sign-extends to -1. Use u8 type instead.
- `register` keyword with `asm()` does NOT work in GCC 2.7.2.
- m2c often misses arg passthrough: if asm saves `$a1`/`$a2` but not `$a0`, \
the function likely has an extra first parameter that passes through unchanged \
to the callee. Check which register the callee's first arg loads into.
- In C89, `void func()` means unspecified args. Use this when the same function \
is called with different arg counts (passthrough pattern).
- INCLUDE_ASM boundary effects: functions may have prologue scheduling differences \
when surrounded by INCLUDE_ASM blocks. Decompiling adjacent functions helps.
- Stack frame padding: some functions have 8 extra bytes in the original \
(vars=8 vs vars=0). This comes from the original source having local variables \
that our GCC optimizes away. Try adding used locals to match the frame size.

### DO NOT GIVE UP
Try at least 8-10 structurally different C variations before giving up. \
Techniques to try: goto-based control flow, split expressions (`val = *ptr; val++`), \
swap if/else arms, inline vs separate variables, different types (s32/u32), \
wrapping vs flat if chains, modifying args in-place vs separate locals.

## D910.c Context

D910.c is Glover's debug/RAMROM communication module:
- `0xA4600010` = PI_STATUS_REG (DMA readiness). \
Pattern: `while (*(volatile u32*)0xA4600010 & 3) {}`
- `0xB1FFFFxx` = RAMROM development hardware registers
- `func_8010C988` writes to a PI address, `func_8010C9C0` reads from one
- `func_8010D9B4`/`func_8010D9C0` are COP0 Status register read/write (handwritten asm)

## Important Rules

- STRICT C89: ALL variable declarations MUST be at the top of a scope \
(before any statements). `s32 x = 1; x++; s32 y = 2;` is ILLEGAL. \
Declare all variables first, then use them.
- Do NOT use unicode/emoji in C -- assembler uses EUC-JP encoding.
- Empty functions (`void f(void) {}`) should stay as INCLUDE_ASM -- \
GCC omits the delay slot nop.
- Functions that are fragments (no prologue, `lw $ra` as first instruction, m2c shows \
"unset register" errors) should be skipped.
- The existing 1-byte diff at ROM 0x0C4B2C is a known \
forward-reference issue, not a regression.
- Always use clean builds (clean=true) to avoid stale objects.
- Try at least 5-6 variations before giving up.
"""


def run_agent(
    config: DecompConfig,
    func_name: str | None = None,
    *,
    max_attempts: int | None = None,
    model: str | None = None,
    log_dir: Path | None = None,
    verbose: bool = True,
) -> dict:
    """Run the decompilation agent on a single function.

    Args:
        config: Project configuration.
        func_name: Function to decompile. If None, agent picks one.
        max_attempts: Max loop iterations (default: config.max_attempts).
        model: Claude model to use (default: config.model).
        log_dir: Directory for episode logs (default: <project>/logs/agent/).
        verbose: Print progress to stderr.

    Returns:
        dict with keys: outcome, function_name, match_percent, steps, log_path
    """
    # Load API key from .env (searches up from project root, then CWD)
    for candidate in [config.project_root, Path.cwd()]:
        env_file = candidate / ".env"
        while not env_file.exists() and env_file.parent != env_file.parent.parent:
            env_file = env_file.parent.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            break

    model = model or config.model
    max_attempts = max_attempts or config.max_attempts

    # Create isolated worktree
    if verbose:
        _log("Creating worktree...")
    wt_path, branch = _create_worktree(config.project_root, func_name or "auto")
    if verbose:
        _log(f"Worktree: {wt_path} (branch: {branch})")

    # Create a config pointing to the worktree (re-rooting all paths)
    wt_config = config.for_worktree(wt_path)
    log_dir = log_dir or (config.project_root / "episodes")

    project = DecompProject(wt_config)
    executor = ToolExecutor(wt_config, project)
    client = anthropic.Anthropic()

    # Build initial user message
    if func_name:
        user_msg = (
            f"Decompile the function `{func_name}`. "
            f"Read its assembly, generate C code, and iterate until it matches."
        )
    else:
        user_msg = (
            "Pick a good candidate function to decompile (small, 8-20 instructions, "
            "self-contained). Use `list_functions` to see what's available, then "
            "decompile it."
        )

    # Set up episode logger
    logger = EpisodeLogger(
        function_name=func_name or "auto",
        project=config.project_root.name,
        model=model,
    )

    # Find instruction count if function specified
    if func_name:
        funcs = project.discover_functions()
        matching = [f for f in funcs if f.name == func_name]
        if matching:
            logger.episode.instruction_count = matching[0].instruction_count

    messages: list[dict] = [{"role": "user", "content": user_msg}]
    outcome = "failed"
    best_match = 0.0
    total_input_tokens = 0
    total_output_tokens = 0

    if verbose:
        _log(f"Starting agent: model={model}, max_attempts={max_attempts}")
        if func_name:
            _log(f"Target function: {func_name}")
        else:
            _log("No function specified -- agent will pick one")

    for attempt in range(max_attempts):
        step_num = logger.begin_step()

        if verbose:
            _log(f"--- Step {step_num}/{max_attempts} ---")

        # Call Claude
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APIError as e:
            _log(f"API error: {e}")
            break

        # Extract usage
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Process response content
        assistant_text = ""
        tool_calls: list[ToolCall] = []
        tool_results = []

        for block in response.content:
            if block.type == "text":
                assistant_text += block.text
                if verbose and block.text.strip():
                    _log(f"Agent: {block.text[:200]}")

            elif block.type == "tool_use":
                if verbose:
                    _log(f"  -> {block.name}({_summarize_input(block.input)})")

                # Execute the tool
                tc = executor.execute(block.name, block.input)
                tool_calls.append(tc)

                if verbose:
                    preview = tc.output[:150].replace("\n", " ")
                    _log(f"     = {preview}")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tc.output,
                    }
                )

        # Track match percent from verify_rom or diff tool calls
        step_match = None
        step_compiled = None
        for tc in tool_calls:
            if tc.name in ("verify_rom", "diff"):
                if "FULL MATCH" in tc.output:
                    step_match = 100.0
                elif "MISMATCH" in tc.output or "Match:" in tc.output:
                    import re

                    # verify_rom: "Function NAME: 72.0% (N instruction diffs)"
                    # diff:       "Match: 72.0%"
                    m = re.search(r"(\d+(?:\.\d+)?)%", tc.output)
                    if m:
                        step_match = float(m.group(1))
            if tc.name == "compile":
                step_compiled = "SUCCESS" in tc.output

            # Track the actual function name if auto-selected
            if tc.name == "read_assembly" and logger.episode.function_name == "auto":
                logger.episode.function_name = tc.input.get("function_name", "auto")

            # Capture m2c output as initial source
            if tc.name == "run_m2c" and logger.episode.initial_m2c_source is None:
                logger.episode.initial_m2c_source = tc.output

        if step_match is not None and step_match > best_match:
            best_match = step_match
            if verbose:
                _log(f"  New best match: {best_match:.1f}%")

        logger.record_step(
            step_num,
            assistant_text=assistant_text or None,
            tool_calls=tool_calls,
            match_percent=step_match,
            compiled=step_compiled,
            token_usage=usage,
        )

        # Append assistant message to conversation
        messages.append({"role": "assistant", "content": response.content})

        # If there were tool calls, append tool results
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        # Check for match
        if step_match == 100.0:
            outcome = "match"
            if verbose:
                _log("MATCH! Function decompiled successfully.")
            break

        # Check stop reason
        if response.stop_reason == "end_turn" and not tool_results:
            # Agent decided to stop without tool calls
            if verbose:
                _log("Agent stopped (no more tool calls).")
            outcome = "partial" if best_match > 0 else "failed"
            break

    else:
        # Exhausted max_attempts
        outcome = "partial" if best_match > 0 else "failed"
        if verbose:
            _log(f"Max attempts ({max_attempts}) reached. Best: {best_match:.1f}%")

    # Capture final source if we can
    if logger.episode.function_name != "auto":
        fn = logger.episode.function_name
        funcs = {f.name: f for f in project.discover_functions()}
        if fn in funcs and funcs[fn].src_path:
            try:
                logger.episode.final_source = funcs[fn].src_path.read_text()
            except OSError:
                pass

    # Handle worktree: merge on success, discard on failure
    n_steps = len(logger.episode.steps)
    log_path = None

    if outcome == "match":
        fn = logger.episode.function_name

        # Push branch and open PR
        if verbose:
            _log("Pushing branch and opening PR...")
        pr_url = _merge_worktree(config.project_root, wt_path, branch, fn)
        if pr_url:
            if verbose:
                _log(f"PR opened: {pr_url}")
        else:
            if verbose:
                _log("Warning: failed to open PR. Branch may still exist.")

        # Save episode
        log_path = logger.finish(outcome, log_dir)
        if verbose:
            _log(f"Episode saved: {log_path}")
    else:
        # Discard worktree — no changes to main
        if verbose:
            _log("Discarding worktree (no match).")
        _cleanup_worktree(config.project_root, wt_path, branch)

    if verbose:
        _log(f"Outcome: {outcome}, Best: {best_match:.1f}%, Steps: {n_steps}")

    # Estimate cost based on model pricing
    cost = _estimate_cost(model, total_input_tokens, total_output_tokens)

    return {
        "outcome": outcome,
        "function_name": logger.episode.function_name,
        "match_percent": best_match,
        "steps": len(logger.episode.steps),
        "log_path": str(log_path) if log_path else None,
        "total_tokens": logger.episode.total_tokens,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": cost,
    }


_MODEL_PRICING = {
    # (input $/M tokens, output $/M tokens)
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-haiku-4-5": (0.80, 4.0),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost from token counts and model name."""
    for prefix, (inp_rate, out_rate) in _MODEL_PRICING.items():
        if prefix in model:
            return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000
    # Unknown model — use Sonnet pricing as default
    return (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _summarize_input(inp: dict) -> str:
    """Short summary of tool input for logging."""
    parts = []
    for k, v in inp.items():
        if k == "content":
            parts.append(f"content=<{len(str(v))} chars>")
        elif isinstance(v, str) and len(v) > 50:
            parts.append(f"{k}={v[:50]}...")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)
