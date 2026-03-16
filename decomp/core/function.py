from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DecompFunction:
    """Represents a single function in a decomp project."""

    name: str
    asm_path: Path  # Path to the assembly file
    src_path: Path | None = None  # Path to C source (if it exists)
    is_matched: bool = False

    @property
    def instruction_count(self) -> int:
        """Count MIPS instructions in the assembly file (for difficulty estimation)."""
        if not self.asm_path.exists():
            return 0
        count = 0
        for line in self.asm_path.read_text().splitlines():
            stripped = line.strip()
            # Skip labels, directives, comments, blank lines
            if (
                stripped
                and not stripped.startswith(".")
                and not stripped.startswith("#")
                and not stripped.endswith(":")
                and not stripped.startswith("glabel")
            ):
                count += 1
        return count

    def read_assembly(self) -> str:
        """Read the assembly source."""
        return self.asm_path.read_text()

    def read_source(self) -> str | None:
        """Read the C source if it exists."""
        if self.src_path and self.src_path.exists():
            return self.src_path.read_text()
        return None
