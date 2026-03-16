from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DecompConfig
from .function import DecompFunction


@dataclass
class BuildResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int


class DecompProject:
    """Represents an existing N64 decomp project on disk."""

    def __init__(self, config: DecompConfig) -> None:
        self.config = config
        self.root = config.project_root

        if not self.root.exists():
            raise FileNotFoundError(f"Project root does not exist: {self.root}")

    def discover_functions(self) -> list[DecompFunction]:
        """Find unmatched functions by scanning asm/non_matchings/."""
        functions: list[DecompFunction] = []
        asm_dir = self.config.asm_dir

        if not asm_dir.exists():
            return functions

        for asm_file in sorted(asm_dir.rglob("*.s")):
            func_name = asm_file.stem
            # Try to find a corresponding source file
            src_path = self._find_source_for_asm(asm_file)
            functions.append(
                DecompFunction(
                    name=func_name,
                    asm_path=asm_file,
                    src_path=src_path,
                    is_matched=False,
                )
            )

        return functions

    def get_matched_functions(self) -> list[DecompFunction]:
        """Find matched functions by scanning source files for GLOBAL_ASM absence."""
        # This is a heuristic — in practice, matched functions are those in src/
        # that compile and match. For now, return functions that have source but
        # no corresponding non_matchings asm.
        matched: list[DecompFunction] = []

        for src_file in sorted(self.config.src_dir.rglob("*.c")):
            # Parse function names from source — simplified heuristic
            text = src_file.read_text()
            for line in text.splitlines():
                # Look for function definitions (very rough heuristic)
                if (
                    "(" in line
                    and ")" in line
                    and not line.strip().startswith("//")
                    and not line.strip().startswith("#")
                    and not line.strip().startswith("*")
                    and "{" not in line  # declaration line, body on next line
                ):
                    # This is intentionally rough — will be refined
                    pass

        return matched

    def build(self, jobs: int = 4) -> BuildResult:
        """Run make in the project root."""
        result = subprocess.run(
            ["make", f"-j{jobs}"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        return BuildResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    def _find_source_for_asm(self, asm_path: Path) -> Path | None:
        """Given an asm file, try to find the corresponding .c source file.

        Convention: asm/non_matchings/<path>/<func>.s -> src/<path>.c
        """
        # Get relative path from asm_dir: e.g., "audio/synthesis/func.s"
        try:
            rel = asm_path.relative_to(self.config.asm_dir)
        except ValueError:
            return None

        # The parent directory name usually maps to the source file
        # e.g., asm/non_matchings/audio/synthesis/func.s -> src/audio/synthesis.c
        if rel.parent != Path("."):
            candidate = self.config.src_dir / rel.parent.with_suffix(".c")
            if candidate.exists():
                return candidate

            # Also try: src/<full_parent_path>.c flattened
            # e.g., audio/synthesis -> src/audio/synthesis.c
            candidate = self.config.src_dir / rel.parent / (rel.parent.name + ".c")
            if candidate.exists():
                return candidate

        return None
