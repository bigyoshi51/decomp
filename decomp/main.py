from __future__ import annotations

import argparse
import sys
from pathlib import Path

from decomp.core.config import DecompConfig
from decomp.core.project import DecompProject


def main() -> None:
    parser = argparse.ArgumentParser(
        description="N64 decompilation agent",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to decomp.yaml/decomp.toml (auto-detected if omitted)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # bootstrap — create a new decomp project from a ROM
    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Create a new decomp project from a ROM"
    )
    bootstrap_parser.add_argument("rom", type=Path, help="Path to the N64 ROM")
    bootstrap_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output directory (default: projects/<rom_name>)",
    )

    # discover — list unmatched functions
    discover_parser = subparsers.add_parser(
        "discover", help="Discover unmatched functions"
    )
    discover_parser.add_argument(
        "--sort-by",
        choices=["name", "size"],
        default="name",
        help="Sort functions by name or instruction count",
    )

    # info — show project info
    subparsers.add_parser("info", help="Show project configuration")

    # m2c — run mips_to_c on a function
    m2c_parser = subparsers.add_parser("m2c", help="Decompile a function with m2c")
    m2c_parser.add_argument("function", help="Function name")

    # diff — diff a function
    diff_parser = subparsers.add_parser("diff", help="Diff a function")
    diff_parser.add_argument("function", help="Function name")

    # agent — run the Claude decompilation agent
    agent_parser = subparsers.add_parser(
        "agent", help="Run the Claude API decompilation agent"
    )
    agent_parser.add_argument(
        "function",
        nargs="?",
        default=None,
        help="Function name (auto-picks if omitted)",
    )
    agent_parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Max agent iterations (default: from config)",
    )
    agent_parser.add_argument(
        "--model",
        default=None,
        help="Claude model to use (default: from config)",
    )
    agent_parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Directory for episode logs",
    )
    agent_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Bootstrap doesn't need an existing config
    if args.command == "bootstrap":
        _cmd_bootstrap(args.rom, args.output)
        return

    # Load config
    try:
        if args.config:
            config = DecompConfig.load(args.config)
        else:
            config = DecompConfig.find_and_load()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    project = DecompProject(config)

    if args.command == "info":
        _cmd_info(config)
    elif args.command == "discover":
        _cmd_discover(project, sort_by=args.sort_by)
    elif args.command == "m2c":
        _cmd_m2c(config, project, args.function)
    elif args.command == "diff":
        _cmd_diff(config, args.function)
    elif args.command == "agent":
        _cmd_agent(
            config,
            args.function,
            max_attempts=args.max_attempts,
            model=args.model,
            log_dir=args.log_dir,
            verbose=not args.quiet,
        )


def _cmd_bootstrap(rom: Path, output: Path | None) -> None:
    from decomp.bootstrap import TOOL_ROOT, bootstrap

    if output is None:
        # Default to projects/<rom_stem> under our tool root
        output = TOOL_ROOT / "projects" / rom.stem

    bootstrap(rom, output)


def _cmd_info(config: DecompConfig) -> None:
    print(f"Project root:   {config.project_root}")
    print(f"Base ROM:       {config.base_rom}")
    print(f"ASM dir:        {config.asm_dir}")
    print(f"Source dir:     {config.src_dir}")
    print(f"Include dir:    {config.include_dir}")
    print(f"IDO recomp:     {config.ido_recomp}")
    print(f"Model:          {config.model}")
    print(f"Max attempts:   {config.max_attempts}")


def _cmd_discover(project: DecompProject, *, sort_by: str) -> None:
    functions = project.discover_functions()
    if not functions:
        print("No unmatched functions found.")
        return

    if sort_by == "size":
        functions.sort(key=lambda f: f.instruction_count)
    else:
        functions.sort(key=lambda f: f.name)

    print(f"Found {len(functions)} unmatched function(s):\n")
    for func in functions:
        count = func.instruction_count
        src_marker = " [has source]" if func.src_path else ""
        print(f"  {func.name:<40} {count:>4} instructions{src_marker}")


def _cmd_m2c(config: DecompConfig, project: DecompProject, func_name: str) -> None:
    from decomp.tools.m2c import decompile_assembly

    # Find the function
    functions = project.discover_functions()
    matches = [f for f in functions if f.name == func_name]
    if not matches:
        print(f"Function '{func_name}' not found in non_matchings.", file=sys.stderr)
        sys.exit(1)

    func = matches[0]
    result = decompile_assembly(config, func.asm_path)
    print(result)


def _cmd_diff(config: DecompConfig, func_name: str) -> None:
    from decomp.tools.differ import diff_function

    result = diff_function(config, func_name)
    print(result.diff_text)
    if result.is_match:
        print("\nFULL MATCH!")
    else:
        print(f"\nMatch: {result.match_percent:.1f}%")


def _cmd_agent(
    config: DecompConfig,
    func_name: str | None,
    *,
    max_attempts: int | None,
    model: str | None,
    log_dir: Path | None,
    verbose: bool,
) -> None:
    from decomp.agent.loop import run_agent

    result = run_agent(
        config,
        func_name,
        max_attempts=max_attempts,
        model=model,
        log_dir=log_dir,
        verbose=verbose,
    )

    # Print summary to stdout
    print(f"\nOutcome:      {result['outcome']}")
    print(f"Function:     {result['function_name']}")
    print(f"Match:        {result['match_percent']:.1f}%")
    print(f"Steps:        {result['steps']}")
    print(f"Tokens used:  {result['total_tokens']}")
    print(f"Episode log:  {result['log_path']}")

    if result["outcome"] != "match":
        sys.exit(1)


if __name__ == "__main__":
    main()
