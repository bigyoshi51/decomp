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

    export_parser = subparsers.add_parser(
        "export-episodes",
        help="Export exact-match episodes into normalized SFT/eval JSONL",
    )
    export_parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repo root used to discover project episode directories (default: cwd)",
    )
    export_parser.add_argument(
        "--episodes-dir",
        action="append",
        type=Path,
        default=None,
        help="Specific episode directory to include. May be passed multiple times.",
    )
    export_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("exports"),
        help="Output directory for JSONL files (default: exports)",
    )
    export_parser.add_argument(
        "--eval-ratio",
        type=float,
        default=0.1,
        help="Deterministic eval split ratio in [0, 1] (default: 0.1)",
    )
    export_parser.add_argument(
        "--split-seed",
        default="decomp-export-v1",
        help="Seed string for deterministic train/eval split",
    )

    log_episode_parser = subparsers.add_parser(
        "log-exact-episode",
        help="Log a canonical exact-match episode JSON for one function",
    )
    log_episode_parser.add_argument("function_name", help="Function name")
    log_episode_parser.add_argument(
        "--source-file",
        required=True,
        type=Path,
        help="Source file containing the final exact-match implementation",
    )
    log_episode_parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("episodes"),
        help="Episode directory (default: episodes)",
    )
    log_episode_parser.add_argument(
        "--project",
        default=None,
        help="Project name stored in the episode (default: cwd name)",
    )
    log_episode_parser.add_argument(
        "--asm-file",
        type=Path,
        default=None,
        help="Assembly file used to derive instruction count if needed",
    )
    log_episode_parser.add_argument(
        "--instruction-count",
        type=int,
        default=None,
        help="Instruction count override (default: derive from --asm-file if given)",
    )
    log_episode_parser.add_argument(
        "--m2c-file",
        type=Path,
        default=None,
        help="Path to saved m2c output to store in initial_m2c_source",
    )
    log_episode_parser.add_argument(
        "--m2c-text",
        default=None,
        help="Direct m2c output text to store in initial_m2c_source",
    )
    log_episode_parser.add_argument(
        "--assistant-text",
        default=None,
        help="Short verification/matching note stored on the terminal step",
    )
    log_episode_parser.add_argument(
        "--model",
        default="claude-manual",
        help="Model label stored in the episode (default: claude-manual)",
    )
    log_episode_parser.add_argument(
        "--source-path",
        default=None,
        help=(
            "Relative source path stored in metadata "
            "(default: derived from --source-file)"
        ),
    )
    log_episode_parser.add_argument(
        "--segment",
        default=None,
        help="Segment stored in metadata",
    )
    log_episode_parser.add_argument(
        "--compiler",
        default=None,
        help="Compiler label stored in metadata",
    )
    log_episode_parser.add_argument(
        "--compiler-flags",
        default=None,
        help="Compiler flags stored in metadata",
    )
    log_episode_parser.add_argument(
        "--verification",
        default=None,
        help="Verification summary stored in metadata",
    )
    log_episode_parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        help="Extra metadata as KEY=VALUE. May be passed multiple times.",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Bootstrap doesn't need an existing config
    if args.command == "bootstrap":
        _cmd_bootstrap(args.rom, args.output)
        return
    if args.command == "export-episodes":
        _cmd_export_episodes(args)
        return
    if args.command == "log-exact-episode":
        _cmd_log_exact_episode(args)
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
    print(
        f"Tokens:       {result['input_tokens']:,} in / {result['output_tokens']:,} out"
    )
    print(f"Cost:         ${result['cost_usd']:.2f}")
    print(f"Episode log:  {result['log_path']}")

    if result["outcome"] != "match":
        sys.exit(1)


def _cmd_export_episodes(args: argparse.Namespace) -> None:
    from decomp.training.exporter import main as export_main

    argv: list[str] = []
    argv.extend(["--repo-root", str(args.repo_root)])
    if args.episodes_dir:
        for episode_dir in args.episodes_dir:
            argv.extend(["--episodes-dir", str(episode_dir)])
    argv.extend(["--output-dir", str(args.output_dir)])
    argv.extend(["--eval-ratio", str(args.eval_ratio)])
    argv.extend(["--split-seed", args.split_seed])
    raise SystemExit(export_main(argv))


def _cmd_log_exact_episode(args: argparse.Namespace) -> None:
    from decomp.logging.cli import main as log_main

    argv: list[str] = [args.function_name, "--source-file", str(args.source_file)]
    argv.extend(["--log-dir", str(args.log_dir)])
    if args.project is not None:
        argv.extend(["--project", args.project])
    if args.asm_file is not None:
        argv.extend(["--asm-file", str(args.asm_file)])
    if args.instruction_count is not None:
        argv.extend(["--instruction-count", str(args.instruction_count)])
    if args.m2c_file is not None:
        argv.extend(["--m2c-file", str(args.m2c_file)])
    if args.m2c_text is not None:
        argv.extend(["--m2c-text", args.m2c_text])
    if args.assistant_text is not None:
        argv.extend(["--assistant-text", args.assistant_text])
    if args.model is not None:
        argv.extend(["--model", args.model])
    if args.source_path is not None:
        argv.extend(["--source-path", args.source_path])
    if args.segment is not None:
        argv.extend(["--segment", args.segment])
    if args.compiler is not None:
        argv.extend(["--compiler", args.compiler])
    if args.compiler_flags is not None:
        argv.append(f"--compiler-flags={args.compiler_flags}")
    if args.verification is not None:
        argv.extend(["--verification", args.verification])
    for item in args.metadata:
        argv.extend(["--metadata", item])
    raise SystemExit(log_main(argv))


if __name__ == "__main__":
    main()
