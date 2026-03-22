from __future__ import annotations

import re
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
        """Find unmatched functions by scanning asm/non_matchings/.

        Only returns functions that still use INCLUDE_ASM in their source file
        (i.e., have not yet been decompiled). Functions without a source file
        or whose source file still contains the INCLUDE_ASM macro are included.
        """
        functions: list[DecompFunction] = []
        asm_dir = self.config.asm_dir

        if not asm_dir.exists():
            return functions

        # Cache source file contents to avoid re-reading per function
        src_cache: dict[Path, str] = {}

        for asm_file in sorted(asm_dir.rglob("*.s")):
            func_name = asm_file.stem

            asm_text = asm_file.read_text()

            # Skip handwritten assembly (cache/COP0 instructions — can't be decompiled)
            if "Handwritten" in asm_text:
                continue

            # Skip empty/stub functions (≤8 bytes) — GCC can't reproduce the
            # trailing nop, so these must stay as INCLUDE_ASM
            size_match = re.search(
                r"nonmatching\s+\S+,\s+(0x[0-9A-Fa-f]+|\d+)", asm_text
            )
            if size_match:
                size = int(size_match.group(1), 0)
                if size <= 8:
                    continue

            # Skip function fragments (no prologue and no jr $ra)
            # These are mid-function code that splat split at internal labels
            instrs = []
            for line in asm_text.splitlines():
                s = line.strip()
                if "/*" in s and "*/" in s and "glabel" not in s:
                    after = s.split("*/")[-1].strip()
                    if after and not after.startswith(
                        (".", "endlabel", "nonmatching", "enddlabel")
                    ):
                        instrs.append(after)
            if instrs:
                first = instrs[0]
                has_prologue = "addiu" in first and "$sp" in first and "-0x" in first
                has_jr_ra = any("jr" in i and "$ra" in i for i in instrs)
                if not has_prologue and not has_jr_ra:
                    continue

            src_path = self._find_source_for_asm(asm_file)

            # Skip functions already decompiled (no INCLUDE_ASM in source)
            if src_path and src_path.exists():
                if src_path not in src_cache:
                    src_cache[src_path] = src_path.read_text()
                if 'INCLUDE_ASM("' not in src_cache[src_path]:
                    # Entire file is decompiled, skip all its functions
                    continue
                if f", {func_name})" not in src_cache[src_path]:
                    # This specific function has been decompiled
                    continue

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
