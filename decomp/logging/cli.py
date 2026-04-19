from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .episode import log_exact_match


def _count_instruction_lines(asm_text: str) -> int:
    return sum(1 for line in asm_text.splitlines() if "/*" in line and "*/" in line)


def _read_optional_text(file_path: Path | None, direct_text: str | None) -> str | None:
    if direct_text is not None:
        return direct_text
    if file_path is not None:
        return file_path.read_text()
    return None


def _parse_metadata_items(items: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"metadata item must be KEY=VALUE, got: {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"metadata item must have a non-empty key: {item!r}")
        metadata[key] = value
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Log a canonical exact-match episode JSON for one function."
    )
    parser.add_argument("function_name", help="Function name")
    parser.add_argument(
        "--source-file",
        required=True,
        type=Path,
        help="Source file containing the final exact-match implementation",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("episodes"),
        help="Episode directory (default: episodes)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project name stored in the episode (default: cwd name)",
    )
    parser.add_argument(
        "--asm-file",
        type=Path,
        default=None,
        help="Assembly file used to derive instruction count if needed",
    )
    parser.add_argument(
        "--instruction-count",
        type=int,
        default=None,
        help="Instruction count override (default: derive from --asm-file if given)",
    )
    parser.add_argument(
        "--m2c-file",
        type=Path,
        default=None,
        help="Path to saved m2c output to store in initial_m2c_source",
    )
    parser.add_argument(
        "--m2c-text",
        default=None,
        help="Direct m2c output text to store in initial_m2c_source",
    )
    parser.add_argument(
        "--assistant-text",
        default=None,
        help="Short verification/matching note stored on the terminal step",
    )
    parser.add_argument(
        "--model",
        default="claude-manual",
        help="Model label stored in the episode (default: claude-manual)",
    )
    parser.add_argument(
        "--source-path",
        default=None,
        help=(
            "Relative source path stored in metadata "
            "(default: derived from --source-file)"
        ),
    )
    parser.add_argument(
        "--segment",
        default=None,
        help="Segment stored in metadata",
    )
    parser.add_argument(
        "--compiler",
        default=None,
        help="Compiler label stored in metadata",
    )
    parser.add_argument(
        "--compiler-flags",
        default=None,
        help="Compiler flags stored in metadata",
    )
    parser.add_argument(
        "--verification",
        default=None,
        help="Verification summary stored in metadata",
    )
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        help="Extra metadata as KEY=VALUE. May be passed multiple times.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.m2c_file is not None and args.m2c_text is not None:
        parser.error("pass at most one of --m2c-file and --m2c-text")

    source_file = args.source_file.resolve()
    if not source_file.exists():
        parser.error(f"--source-file does not exist: {source_file}")

    asm_file = args.asm_file.resolve() if args.asm_file is not None else None
    if asm_file is not None and not asm_file.exists():
        parser.error(f"--asm-file does not exist: {asm_file}")

    try:
        metadata = _parse_metadata_items(args.metadata)
    except ValueError as exc:
        parser.error(str(exc))

    cwd = Path.cwd().resolve()
    if args.source_path:
        metadata["source_path"] = args.source_path
    else:
        try:
            metadata["source_path"] = str(source_file.relative_to(cwd))
        except ValueError:
            metadata["source_path"] = str(source_file)

    if asm_file is not None:
        try:
            metadata.setdefault("asm_path", str(asm_file.relative_to(cwd)))
        except ValueError:
            metadata.setdefault("asm_path", str(asm_file))

    if args.segment:
        metadata["segment"] = args.segment
    if args.compiler:
        metadata["compiler"] = args.compiler
    if args.compiler_flags:
        metadata["compiler_flags"] = args.compiler_flags
    if args.verification:
        metadata["verification"] = args.verification

    instruction_count = args.instruction_count
    if instruction_count is None and asm_file is not None:
        instruction_count = _count_instruction_lines(asm_file.read_text())
    if instruction_count is None:
        instruction_count = 0

    path = log_exact_match(
        function_name=args.function_name,
        project=args.project or cwd.name,
        log_dir=args.log_dir,
        final_source=source_file.read_text(),
        initial_m2c_source=_read_optional_text(args.m2c_file, args.m2c_text),
        assistant_text=args.assistant_text,
        instruction_count=instruction_count,
        model=args.model,
        metadata=metadata,
    )

    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
