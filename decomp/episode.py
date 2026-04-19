"""Legacy exact-match episode logging retained for historical datasets.

New episode logs should use ``decomp.logging.episode.log_exact_match`` so all
new data follows the canonical Episode/Step schema used by the agent loop.
"""

from __future__ import annotations

import json
import re
import subprocess
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
    compiler_flags: str = "-O2 -g2"

    # Context fields
    nearby_decompiled: list[str] = field(default_factory=list)
    called_functions: list[str] = field(default_factory=list)
    referenced_data: list[str] = field(default_factory=list)
    segment: str = ""

    def add_attempt(
        self,
        c_code: str,
        matched: bool,
        diff_count: int = 0,
        diff_details: list[str] | None = None,
        notes: str = "",
    ) -> None:
        self.attempts.append(
            DecompAttempt(
                c_code=c_code,
                matched=matched,
                diff_count=diff_count,
                diff_details=diff_details or [],
                notes=notes,
            )
        )
        if matched:
            self.final_c = c_code
            self.matched = True

    def save(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{self.function_name}.json"
        path.write_text(json.dumps(asdict(self), indent=2))
        return path


def _extract_context(
    func_name: str, asm_text: str, segment: str, project_dir: Path
) -> tuple[list[str], list[str], list[str]]:
    """Extract context from assembly and source files."""
    # Called functions (jal targets)
    called = []
    for line in asm_text.splitlines():
        m = re.search(r"jal\s+(func_[0-9A-Fa-f]+|[A-Za-z_]\w*)", line)
        if m:
            called.append(m.group(1))
    called = list(dict.fromkeys(called))  # dedupe preserving order

    # Referenced data symbols (%hi/%lo patterns)
    data_refs = []
    for line in asm_text.splitlines():
        for m in re.finditer(r"%(hi|lo)\(([A-Za-z_]\w*)\)", line):
            sym = m.group(2)
            if sym.startswith("D_") or sym.startswith("D_80"):
                data_refs.append(sym)
    data_refs = list(dict.fromkeys(data_refs))

    # Nearby decompiled functions (from the same source file)
    nearby = []
    src_path = project_dir / "src" / f"{segment}.c"
    if src_path.exists():
        src_text = src_path.read_text()
        # Find C function definitions (not INCLUDE_ASM, not forward decls)
        for m in re.finditer(
            r"^(?:s32|void|u32|f32)\s+(func_[0-9A-Fa-f]+)\s*\([^)]*\)\s*\{",
            src_text,
            re.MULTILINE,
        ):
            name = m.group(1)
            if name != func_name:
                nearby.append(name)

    return called, data_refs, nearby


def log_success(
    func_name: str,
    asm_path: Path,
    c_code: str,
    m2c_output: str = "",
    compiler_flags: str = "-O2 -g2",
    output_dir: Path | None = None,
) -> Path:
    """Log a successful decompilation with the legacy exact-match schema.

    New callers should use ``decomp.logging.episode.log_exact_match`` instead.
    """
    if output_dir is None:
        output_dir = Path("episodes")

    asm_text = asm_path.read_text()
    instrs = [line for line in asm_text.splitlines() if "/*" in line and "*/" in line]

    # Determine segment from path
    segment = asm_path.parent.name  # e.g., "D910" or "18020"
    project_dir = (
        asm_path.parent.parent.parent.parent
    )  # up from asm/nonmatchings/<seg>/<func>.s

    # Get m2c output if not provided
    if not m2c_output:
        r = subprocess.run(
            ["uv", "run", "m2c", "--target", "mips-ido-c", str(asm_path)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            m2c_output = r.stdout

    # Extract context
    called, data_refs, nearby = _extract_context(
        func_name, asm_text, segment, project_dir
    )

    ep = DecompEpisode(
        function_name=func_name,
        asm_text=asm_text,
        m2c_output=m2c_output,
        instruction_count=len(instrs),
        has_branches=any(".L" in line for line in instrs),
        has_calls=any("jal" in line for line in instrs),
        compiler_flags=compiler_flags,
        segment=segment,
        called_functions=called,
        referenced_data=data_refs,
        nearby_decompiled=nearby,
    )
    ep.add_attempt(c_code, matched=True, notes=f"flags: {compiler_flags}")
    return ep.save(output_dir)
