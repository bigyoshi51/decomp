"""Log decompilation episodes as structured data for training."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class DecompAttempt:
    """A single attempt at decompiling a function."""

    c_code: str
    matched: bool
    diff_count: int = 0
    diff_details: list[str] = field(default_factory=list)
    compiler_flags: str = ""
    notes: str = ""


@dataclass
class DecompEpisode:
    """A complete decompilation episode for one function."""

    function_name: str
    asm_text: str  # original assembly
    m2c_output: str  # initial m2c pseudo-C
    attempts: list[DecompAttempt] = field(default_factory=list)
    final_c: str | None = None
    matched: bool = False
    instruction_count: int = 0
    has_branches: bool = False
    has_calls: bool = False
    timestamp: float = field(default_factory=time.time)
    game: str = "glover"
    compiler: str = "gcc_2.7.2_kmc"

    def add_attempt(self, c_code: str, matched: bool, diff_count: int = 0,
                    diff_details: list[str] | None = None, notes: str = "") -> None:
        self.attempts.append(DecompAttempt(
            c_code=c_code,
            matched=matched,
            diff_count=diff_count,
            diff_details=diff_details or [],
            notes=notes,
        ))
        if matched:
            self.final_c = c_code
            self.matched = True

    def save(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{self.function_name}.json"
        path.write_text(json.dumps(asdict(self), indent=2))
        return path


def log_success(
    func_name: str,
    asm_path: Path,
    c_code: str,
    m2c_output: str = "",
    compiler_flags: str = "-O2 -g2",
    output_dir: Path | None = None,
) -> Path:
    """Quick helper to log a successful decompilation."""
    if output_dir is None:
        output_dir = Path("episodes")

    asm_text = asm_path.read_text()
    instrs = [l for l in asm_text.splitlines() if "/*" in l and "*/" in l]

    ep = DecompEpisode(
        function_name=func_name,
        asm_text=asm_text,
        m2c_output=m2c_output,
        instruction_count=len(instrs),
        has_branches=any(".L" in l for l in instrs),
        has_calls=any("jal" in l for l in instrs),
    )
    ep.add_attempt(c_code, matched=True, notes=f"flags: {compiler_flags}")
    return ep.save(output_dir)
