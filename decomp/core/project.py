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

            src_path, include_asm_present = self._find_source_with_include_asm(
                asm_file, func_name, src_cache
            )

            # Skip functions already decompiled (no INCLUDE_ASM anywhere for them)
            if src_path is not None and not include_asm_present:
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

    def _find_source_with_include_asm(
        self,
        asm_path: Path,
        func_name: str,
        src_cache: dict[Path, str],
    ) -> tuple[Path | None, bool]:
        """Locate the .c file that contains INCLUDE_ASM for this function.

        Searches src/<segment>/**/*.c for an INCLUDE_ASM line naming the
        function. Returns (file, True) if found. Falls back to the old
        asm_dir → src_dir convention when no INCLUDE_ASM exists anywhere
        (returning (candidate_file, False) so discover can skip it as
        decompiled), or (None, True) if we can't determine the layout.
        """
        try:
            rel = asm_path.relative_to(self.config.asm_dir)
        except ValueError:
            return None, True

        # Candidate single-file source (legacy convention).
        single_file: Path | None = None
        if rel.parent != Path("."):
            c = self.config.src_dir / rel.parent.with_suffix(".c")
            if c.exists():
                single_file = c

        # Determine the segment dir under src/ (e.g. src/kernel/).
        segment_dir = (
            self.config.src_dir / rel.parent
            if rel.parent != Path(".")
            else self.config.src_dir
        )

        # Collect all .c files that could contain this function:
        # the single-file candidate plus any .c under the segment dir.
        candidates: list[Path] = []
        if single_file is not None:
            candidates.append(single_file)
        if segment_dir.exists() and segment_dir.is_dir():
            candidates.extend(sorted(segment_dir.rglob("*.c")))

        include_token = f", {func_name})"
        for path in candidates:
            if path not in src_cache:
                try:
                    src_cache[path] = path.read_text()
                except OSError:
                    src_cache[path] = ""
            text = src_cache[path]
            if include_token in text and "INCLUDE_ASM(" in text:
                # Confirm the token appears on an INCLUDE_ASM line (avoid
                # false positives from e.g. comments).
                for line in text.splitlines():
                    if "INCLUDE_ASM(" in line and include_token in line:
                        return path, True

        # No INCLUDE_ASM found anywhere. If we have any candidate, treat
        # this function as already decompiled.
        if candidates:
            return candidates[0], False
        return None, True
