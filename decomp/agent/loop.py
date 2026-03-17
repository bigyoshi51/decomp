"""Milestone 2: Claude API agent loop for iterative N64 decompilation.

The agent reads assembly, generates C via m2c, compiles with KMC GCC 2.7.2,
diffs against the ROM, and iterates until byte-match or max attempts.
Each episode is logged as structured JSON for future RL training.
"""

from __future__ import annotations

import sys
from pathlib import Path

import anthropic

from decomp.core.config import DecompConfig
from decomp.core.project import DecompProject
from decomp.logging.episode import EpisodeLogger, ToolCall

from .tools import TOOLS, ToolExecutor

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

- Register allocation is based on variable "weight" (usage frequency), not \
declaration order. Reorder declarations, change types, use in-place modification \
(`arg0 &= -4` instead of new variable).
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

## D910.c Context

D910.c is Glover's debug/RAMROM communication module:
- `0xA4600010` = PI_STATUS_REG (DMA readiness). \
Pattern: `while (*(volatile u32*)0xA4600010 & 3) {}`
- `0xB1FFFFxx` = RAMROM development hardware registers
- `func_8010C988` writes to a PI address, `func_8010C9C0` reads from one
- `func_8010D9B4`/`func_8010D9C0` are COP0 Status register read/write (handwritten asm)

## Important Rules

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
    model = model or config.model
    max_attempts = max_attempts or config.max_attempts
    log_dir = log_dir or (config.project_root / "logs" / "agent")

    project = DecompProject(config)
    executor = ToolExecutor(config, project)
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
                elif "Match:" in tc.output:
                    import re

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

    # Save episode log (detailed trajectory)
    log_path = logger.finish(outcome, log_dir)
    if verbose:
        _log(f"Episode saved: {log_path}")
        n_steps = len(logger.episode.steps)
        _log(f"Outcome: {outcome}, Best: {best_match:.1f}%, Steps: {n_steps}")

    # On success, also save clean training example to episodes/
    if outcome == "match" and logger.episode.function_name != "auto":
        try:
            from decomp.episode import log_success

            fn = logger.episode.function_name
            # Find asm path
            for f in project.discover_functions():
                if f.name == fn:
                    # Extract C code from current source
                    if f.src_path and f.src_path.exists():
                        import re

                        src = f.src_path.read_text()
                        m = re.search(
                            rf"((?:s32|void|u32|f32)\s+{fn}"
                            rf"\s*\([^)]*\)\s*\{{)",
                            src,
                        )
                        if m:
                            start = m.start()
                            brace = 0
                            for idx in range(start, len(src)):
                                if src[idx] == "{":
                                    brace += 1
                                elif src[idx] == "}":
                                    brace -= 1
                                    if brace == 0:
                                        c_code = src[start : idx + 1]
                                        break
                            else:
                                c_code = ""
                            if c_code:
                                ep_dir = config.project_root / "episodes"
                                log_success(
                                    fn,
                                    f.asm_path,
                                    c_code,
                                    output_dir=ep_dir,
                                )
                                if verbose:
                                    _log(f"Training episode: {ep_dir / fn}.json")
                    break
        except Exception as e:
            if verbose:
                _log(f"Warning: failed to save training episode: {e}")

    return {
        "outcome": outcome,
        "function_name": logger.episode.function_name,
        "match_percent": best_match,
        "steps": len(logger.episode.steps),
        "log_path": str(log_path),
        "total_tokens": logger.episode.total_tokens,
    }


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
