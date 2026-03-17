"""Tool definitions for the Claude API decompilation agent.

Each tool maps to an existing decomp tool wrapper or filesystem operation.
Tools are defined as Anthropic API tool schemas and have corresponding
execution functions.
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import time
from pathlib import Path

from decomp.core.config import DecompConfig
from decomp.core.project import DecompProject
from decomp.logging.episode import ToolCall

# -- Tool schemas for the Anthropic API --

TOOLS = [
    {
        "name": "read_assembly",
        "description": (
            "Read the MIPS assembly for a function from asm/nonmatchings/. "
            "Returns the raw .s file contents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Name of the function (e.g., func_8010C920).",
                }
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "run_m2c",
        "description": (
            "Run m2c (mips_to_c) on a function's assembly to get initial pseudo-C. "
            "This gives a starting point that usually needs manual adjustment. "
            "m2c often gets types wrong and misses arg passthrough patterns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Name of the function to decompile with m2c.",
                }
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "read_source",
        "description": (
            "Read a C source file from the project. Use this to see the current "
            "state of a file, including INCLUDE_ASM macros and surrounding code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path relative to project root (e.g., 'src/D910.c')."
                    ),
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_function",
        "description": (
            "Replace a single INCLUDE_ASM with decompiled C code in the source file. "
            "This safely replaces only the target function, preserving all other code. "
            "Include forward declarations as part of the replacement text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Name of the function to replace.",
                },
                "c_code": {
                    "type": "string",
                    "description": (
                        "The C code to replace the INCLUDE_ASM with. Include any "
                        "forward declarations needed. Do NOT include the INCLUDE_ASM "
                        "line itself."
                    ),
                },
            },
            "required": ["function_name", "c_code"],
        },
    },
    {
        "name": "compile",
        "description": (
            "Compile the project by running 'make'. Returns stdout/stderr and "
            "whether compilation succeeded. Always use "
            "clean=true after modifying source."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "clean": {
                    "type": "boolean",
                    "description": "If true, run 'rm -rf build/' before compiling.",
                    "default": True,
                },
            },
            "required": [],
        },
    },
    {
        "name": "verify_rom",
        "description": (
            "Compare the built ROM against the base ROM byte-for-byte for a specific "
            "function. Returns match percentage and instruction-level diffs. "
            "This is the definitive matching check."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Name of the function to verify.",
                }
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "diff",
        "description": (
            "Run asm-differ on a function to compare compiled output against the "
            "target ROM assembly. Returns match percentage and instruction-level diff. "
            "Requires diff_settings.py in the project. Use verify_rom if this fails."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Name of the function to diff.",
                }
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "list_functions",
        "description": (
            "List unmatched functions in the project sorted by instruction count. "
            "Use this to pick a good candidate for decompilation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of functions to return (default 20).",
                    "default": 20,
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["size", "name"],
                    "description": "Sort order (default: size, smallest first).",
                    "default": "size",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_header",
        "description": "Read a header file from the project's include/ directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to include/ (e.g., 'common.h').",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_nearby_functions",
        "description": (
            "Read already-decompiled C functions from the same source file. "
            "Use this to understand coding style, types, and patterns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": (
                        "Target function -- returns decompiled functions from its file."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": ("Max nearby functions to return (default 5)."),
                    "default": 5,
                },
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "gfxdis",
        "description": (
            "Disassemble F3DEX2 display list hex data into GBI macro "
            "calls. Use when decompiling functions that construct "
            "display lists (look for 0xDA, 0x06, 0xE7 opcodes). "
            "Input is hex bytes (8 bytes per command)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hex_data": {
                    "type": "string",
                    "description": (
                        "Hex string of F3DEX2 commands (e.g., 'DA38000300000000')."
                    ),
                }
            },
            "required": ["hex_data"],
        },
    },
]


class ToolExecutor:
    """Executes tool calls against a decomp project."""

    def __init__(self, config: DecompConfig, project: DecompProject) -> None:
        self.config = config
        self.project = project
        self._functions = {f.name: f for f in project.discover_functions()}

    def execute(self, tool_name: str, tool_input: dict) -> ToolCall:
        """Execute a tool and return a ToolCall record with timing."""
        start = time.monotonic()
        try:
            result = self._dispatch(tool_name, tool_input)
        except Exception as e:
            result = f"Error: {e}"
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ToolCall(
            name=tool_name,
            input=tool_input,
            output=result,
            duration_ms=elapsed_ms,
        )

    def _dispatch(self, name: str, inp: dict) -> str:
        handlers = {
            "read_assembly": lambda: self._read_assembly(inp["function_name"]),
            "run_m2c": lambda: self._run_m2c(inp["function_name"]),
            "read_source": lambda: self._read_source(inp["path"]),
            "write_function": lambda: self._write_function(
                inp["function_name"], inp["c_code"]
            ),
            "compile": lambda: self._compile(inp.get("clean", True)),
            "verify_rom": lambda: self._verify_rom(inp["function_name"]),
            "diff": lambda: self._diff(inp["function_name"]),
            "list_functions": lambda: self._list_functions(
                inp.get("limit", 20), inp.get("sort_by", "size")
            ),
            "read_header": lambda: self._read_header(inp["path"]),
            "read_nearby_functions": lambda: self._read_nearby(
                inp["function_name"], inp.get("limit", 5)
            ),
            "gfxdis": lambda: self._gfxdis(inp["hex_data"]),
        }
        handler = handlers.get(name)
        if handler is None:
            return f"Unknown tool: {name}"
        return handler()

    def _resolve_path(self, path_str: str) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            return p
        return self.config.project_root / p

    def _read_assembly(self, func_name: str) -> str:
        func = self._functions.get(func_name)
        if not func:
            return f"Function '{func_name}' not found in non_matchings."
        return func.read_assembly()

    def _run_m2c(self, func_name: str) -> str:
        from decomp.tools.m2c import decompile_assembly

        func = self._functions.get(func_name)
        if not func:
            return f"Function '{func_name}' not found in non_matchings."
        return decompile_assembly(self.config, func.asm_path)

    def _read_source(self, path: str) -> str:
        resolved = self._resolve_path(path)
        if not resolved.exists():
            return f"File not found: {resolved}"
        return resolved.read_text()

    def _write_function(self, func_name: str, c_code: str) -> str:
        """Replace INCLUDE_ASM or existing C function with new code."""
        # Find which source file contains this function
        func = self._functions.get(func_name)
        src_path = None
        if func and func.src_path:
            src_path = func.src_path
        else:
            for src in self.config.src_dir.rglob("*.c"):
                text = src.read_text()
                if func_name in text:
                    src_path = src
                    break
        if not src_path:
            return f"Cannot find source file containing {func_name}"

        text = src_path.read_text()

        # Back up the file
        backup = src_path.with_suffix(".c.bak")
        shutil.copy2(src_path, backup)

        # Try 1: replace INCLUDE_ASM
        inc_pat = rf'INCLUDE_ASM\("asm/nonmatchings/[^"]+",\s*{func_name}\);'
        inc_match = re.search(inc_pat, text)
        if inc_match:
            new_text = text[: inc_match.start()] + c_code + text[inc_match.end() :]
            src_path.write_text(new_text)
            return (
                f"Replaced INCLUDE_ASM for {func_name} in"
                f" {src_path.name} (backup: {backup.name})"
            )

        # Try 2: replace existing C function body
        # Match: return_type func_name(args) { ... }
        func_pat = (
            rf"((?:s32|void|u32|f32)\s+{func_name}"
            rf"\s*\([^)]*\)\s*\{{)"
        )
        func_match = re.search(func_pat, text)
        if func_match:
            # Find the matching closing brace
            start = func_match.start()
            brace = 0
            end = start
            for i in range(start, len(text)):
                if text[i] == "{":
                    brace += 1
                elif text[i] == "}":
                    brace -= 1
                    if brace == 0:
                        end = i + 1
                        break
            # Also remove any forward declarations
            # immediately before the function
            pre_start = start
            pre_lines = text[:start].rstrip().splitlines()
            while pre_lines and (
                pre_lines[-1].strip().startswith("extern ")
                or pre_lines[-1].strip().startswith("void func_")
                or pre_lines[-1].strip().startswith("s32 func_")
                or pre_lines[-1].strip().startswith("u32 func_")
            ):
                pre_lines.pop()
            if pre_lines:
                pre_start = len("\n".join(pre_lines)) + 1

            new_text = text[:pre_start] + "\n" + c_code + text[end:]
            src_path.write_text(new_text)
            return (
                f"Replaced existing {func_name} in"
                f" {src_path.name} (backup: {backup.name})"
            )

        return (
            f"Cannot find INCLUDE_ASM or function body"
            f" for {func_name} in {src_path.name}"
        )

    def _compile(self, clean: bool) -> str:
        if clean:
            build_dir = self.config.project_root / "build"
            if build_dir.exists():
                shutil.rmtree(build_dir)

        result = subprocess.run(
            ["make", "RUN_CC_CHECK=0", "-j4"],
            cwd=self.config.project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = ""
        if result.stdout:
            output += result.stdout[-2000:]
        if result.stderr:
            output += "\n--- stderr ---\n" + result.stderr[-2000:]
        rc = result.returncode
        status = "SUCCESS" if rc == 0 else f"FAILED (rc={rc})"
        return f"Compilation {status}\n{output}"

    def _verify_rom(self, func_name: str) -> str:
        """Rebuild from scratch and compare entire ROM byte-for-byte.

        This is the definitive matching check. It:
        1. Does a clean rebuild (rm -rf build/ && make)
        2. Checks ROM size matches exactly
        3. Counts total byte diffs across the entire ROM
        4. Reports per-function diffs if not matching
        """
        # Force clean rebuild to prevent stale objects
        build_dir = self.config.project_root / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir)

        result = subprocess.run(
            ["make", "RUN_CC_CHECK=0", "-j4"],
            cwd=self.config.project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr[-500:] if result.stderr else ""
            return f"Error: build failed.\n{stderr}"

        rom_path = self.config.project_root / "baserom.z64"
        built_path = self.config.project_root / "build" / "glover.z64"

        if not rom_path.exists():
            return "Error: baserom.z64 not found"
        if not built_path.exists():
            return "Error: build/glover.z64 not found"

        rom = rom_path.read_bytes()
        built = built_path.read_bytes()

        # Check TOTAL ROM first — this catches size and shift issues
        if len(rom) != len(built):
            return (
                f"MISMATCH: ROM size differs"
                f" (base={len(rom)}, built={len(built)},"
                f" delta={len(built) - len(rom)})"
            )

        total_diffs = sum(1 for j in range(len(rom)) if rom[j] != built[j])

        # Allow the known 1-byte alabel diff
        if total_diffs <= 1:
            return (
                f"FULL MATCH! Function {func_name} matches"
                f" byte-for-byte.\n"
                f"Total ROM diffs: {total_diffs}"
            )

        # Not matching — show per-function diffs
        func = self._functions.get(func_name)
        if not func:
            return (
                f"MISMATCH: {total_diffs} total ROM byte"
                f" diffs. Function '{func_name}' not found"
                " for detailed diff."
            )

        vram = int(func_name.split("_")[1], 16)
        asm_text = func.read_assembly()
        instrs = [
            line for line in asm_text.splitlines() if "/*" in line and "*/" in line
        ]
        func_size = len(instrs) * 4

        segment = func.asm_path.parent.name
        if segment == "D910":
            rom_off = 0xD910 + (vram - 0x8010C910)
        elif segment == "18020":
            rom_off = 0x18020 + (vram - 0x80118020)
        else:
            return (
                f"MISMATCH: {total_diffs} total byte diffs. Unknown segment: {segment}"
            )

        diffs = []
        for i in range(0, func_size, 4):
            off = rom_off + i
            if off + 4 > len(rom):
                break
            b = struct.unpack(">I", rom[off : off + 4])[0]
            c = struct.unpack(">I", built[off : off + 4])[0]
            if b != c:
                diffs.append(f"  0x{off:06X}: base=0x{b:08X} built=0x{c:08X}")

        func_pct = (1 - len(diffs) / (func_size // 4)) * 100 if func_size > 0 else 0
        diff_text = "\n".join(diffs[:20])
        if len(diffs) > 20:
            diff_text += f"\n... ({len(diffs)} diffs in function)"
        return (
            f"MISMATCH: {total_diffs} total ROM byte diffs.\n"
            f"Function {func_name}: {func_pct:.1f}%"
            f" ({len(diffs)} instruction diffs)\n"
            f"{diff_text}"
        )

    def _diff(self, func_name: str) -> str:
        from decomp.tools.differ import diff_function

        try:
            result = diff_function(self.config, func_name)
        except Exception as e:
            return f"asm-differ failed: {e}. Try verify_rom instead."

        summary = f"Match: {result.match_percent:.1f}%"
        if result.is_match:
            summary = "FULL MATCH (100%)"
        diff_text = result.diff_text
        if len(diff_text) > 3000:
            diff_text = diff_text[:3000] + "\n... (truncated)"
        return f"{summary}\n\n{diff_text}"

    def _list_functions(self, limit: int, sort_by: str) -> str:
        funcs = list(self._functions.values())
        if sort_by == "size":
            funcs.sort(key=lambda f: f.instruction_count)
        else:
            funcs.sort(key=lambda f: f.name)

        funcs = funcs[:limit]
        total = len(self._functions)
        lines = [f"Found {total} unmatched functions (showing {len(funcs)}):\n"]
        for f in funcs:
            src = f" -> {f.src_path.name}" if f.src_path else ""
            lines.append(f"  {f.name:<40} {f.instruction_count:>4} instr{src}")
        return "\n".join(lines)

    def _read_header(self, path: str) -> str:
        resolved = self.config.include_dir / path
        if not resolved.exists():
            resolved = self._resolve_path(path)
        if not resolved.exists():
            return f"Header not found: {path}"
        return resolved.read_text()

    def _gfxdis(self, hex_data: str) -> str:
        from decomp.tools.gfxdis import disassemble_hex

        return disassemble_hex(hex_data)

    def _read_nearby(self, func_name: str, limit: int) -> str:
        """Read already-decompiled functions from the same source file."""
        func = self._functions.get(func_name)
        if not func or not func.src_path:
            return f"Cannot find source file for {func_name}"

        src_text = func.src_path.read_text()

        # Find C function bodies (not INCLUDE_ASM)
        nearby = []
        for m in re.finditer(
            r"^((?:s32|void|u32|f32)\s+func_[0-9A-Fa-f]+\s*\([^)]*\)\s*\{)",
            src_text,
            re.MULTILINE,
        ):
            # Extract full function body
            start = m.start()
            brace = 0
            end = start
            for i in range(start, len(src_text)):
                if src_text[i] == "{":
                    brace += 1
                elif src_text[i] == "}":
                    brace -= 1
                    if brace == 0:
                        end = i + 1
                        break

            body = src_text[start:end].strip()
            # Skip empty functions
            inner = body[body.index("{") + 1 : body.rindex("}")].strip()
            if inner and func_name not in m.group(1):
                nearby.append(body)

        if not nearby:
            return "No decompiled functions found in this source file."

        nearby = nearby[:limit]
        return f"Found {len(nearby)} decompiled functions nearby:\n\n" + "\n\n".join(
            nearby
        )
