from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from elftools.elf.sections import SymbolTableSection

from .fixtures import (
    FixtureBuilder,
    FixtureBundle,
    FixtureError,
    apply_candidate,
    isolate_objdiff_config,
    materialize_archive,
)
from .models import ProjectProfile, TaskSpec, VerificationResult
from .policy import validate_candidate_source
from .reward import improvement_reward


class CompilerVerifier:
    """Compile and score a candidate in a freshly redacted trusted fixture."""

    def __init__(
        self,
        project_root: Path,
        profile: ProjectProfile,
        *,
        objdiff_command: str = "objdiff-cli",
        timeout_seconds: int = 180,
        toolchain_source: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.profile = profile
        self.fixtures = FixtureBuilder(self.project_root, profile)
        self.objdiff_command = objdiff_command
        self.timeout_seconds = timeout_seconds
        self.toolchain_source = toolchain_source

    def verify(self, task: TaskSpec, candidate_source: str) -> VerificationResult:
        try:
            verifier = self.prepare(task)
        except (FixtureError, OSError, subprocess.SubprocessError) as exc:
            return _infrastructure_failure(task, str(exc))
        return verifier.verify(task, candidate_source)

    def prepare(self, task: TaskSpec) -> PrebuiltVerifier:
        """Build one immutable fixture bundle for repeated candidate checks."""
        bundle = self.fixtures.build(task)
        toolchain = self.toolchain_source
        if toolchain is None:
            candidates = (
                self.project_root / "tools" / "ido-static-recomp",
                self.project_root.parent.parent / "tools" / "ido-static-recomp",
            )
            toolchain = next((path for path in candidates if path.exists()), None)
        return PrebuiltVerifier(
            self.profile,
            bundle,
            objdiff_command=self.objdiff_command,
            timeout_seconds=self.timeout_seconds,
            toolchain_source=toolchain,
        )


class PrebuiltVerifier:
    """Verify from a redacted archive and private object, without Git access."""

    def __init__(
        self,
        profile: ProjectProfile,
        bundle: FixtureBundle,
        *,
        objdiff_command: str = "objdiff-cli",
        timeout_seconds: int = 180,
        toolchain_source: Path | None = None,
    ) -> None:
        self.profile = profile
        self.bundle = bundle
        self.objdiff_command = objdiff_command
        self.timeout_seconds = timeout_seconds
        self.toolchain_source = toolchain_source

    def verify(self, task: TaskSpec, candidate_source: str) -> VerificationResult:
        started = time.monotonic()
        candidate, violations = validate_candidate_source(
            candidate_source, task.function_name
        )
        if candidate is None or violations:
            return VerificationResult(
                compiled=False,
                exact=False,
                match_percent=0.0,
                baseline_percent=task.initial_match_percent or 0.0,
                reward=0.0,
                policy_violations=violations,
                elapsed_ms=_elapsed_ms(started),
                failure_kind="policy",
            )

        try:
            with tempfile.TemporaryDirectory(prefix="decomp-verify-") as raw_tmp:
                root = Path(raw_tmp) / "projects" / self.profile.project_id
                root.mkdir(parents=True)
                materialize_archive(self.bundle.archive, root)
                apply_candidate(root, task, candidate)
                self._attach_toolchain(root)
                assert task.build is not None
                reference_path = root / task.build.target_object
                reference_path.parent.mkdir(parents=True, exist_ok=True)
                reference_path.write_bytes(self.bundle.reference_object)
                self._write_objdiff_config(root, task)
                result = self._compile(root, task)
                if result.returncode != 0:
                    return VerificationResult(
                        compiled=False,
                        exact=False,
                        match_percent=0.0,
                        baseline_percent=task.initial_match_percent or 0.0,
                        reward=0.0,
                        compile_stdout=result.stdout[-12_000:],
                        compile_stderr=result.stderr[-12_000:],
                        elapsed_ms=_elapsed_ms(started),
                        failure_kind="compile",
                    )
                match, summary = self._score(root, task)
                compiled_object = root / task.build.base_object
                byte_exact = function_bytes_equal(
                    self.bundle.reference_object,
                    compiled_object.read_bytes(),
                    task.function_name,
                )
                if byte_exact is None:
                    raise FixtureError(
                        f"cannot locate ELF function bytes for {task.function_name}"
                    )
        except (FixtureError, OSError, subprocess.SubprocessError) as exc:
            return VerificationResult(
                compiled=False,
                exact=False,
                match_percent=0.0,
                baseline_percent=task.initial_match_percent or 0.0,
                reward=0.0,
                compile_stderr=str(exc),
                elapsed_ms=_elapsed_ms(started),
                failure_kind="infrastructure",
            )

        baseline = task.initial_match_percent or 0.0
        exact = match >= 99.999_999 and byte_exact
        if match >= 99.999_999 and not byte_exact:
            summary += "; raw ELF function bytes differ"
        reward = improvement_reward(
            match,
            baseline,
            exact=exact,
            compiled=True,
            policy_ok=True,
        )
        return VerificationResult(
            compiled=True,
            exact=exact,
            match_percent=match,
            baseline_percent=baseline,
            reward=reward,
            compile_stdout=result.stdout[-12_000:],
            compile_stderr=result.stderr[-12_000:],
            diff_summary=summary,
            elapsed_ms=_elapsed_ms(started),
        )

    def _attach_toolchain(self, root: Path) -> None:
        source = self.toolchain_source
        if source is None:
            return
        sources = {
            "ido-static-recomp": source,
            "asm-processor": source.parent / "asm-processor",
        }
        tool_roots = (root / "tools", root.parent.parent / "tools")
        for name, support_source in sources.items():
            if not support_source.exists():
                continue
            for tool_root in tool_roots:
                destination = tool_root / name
                if destination.exists() or destination.is_symlink():
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(
                    support_source.resolve(), target_is_directory=True
                )

    def _compile(self, root: Path, task: TaskSpec) -> subprocess.CompletedProcess[str]:
        assert task.build is not None
        output = root / task.build.object_target
        if output.exists():
            output.unlink()
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        return subprocess.run(
            ["make", task.build.object_target, *self.profile.make_args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )

    def _write_objdiff_config(self, root: Path, task: TaskSpec) -> None:
        isolate_objdiff_config(root, self.profile, task)

    def _score(self, root: Path, task: TaskSpec) -> tuple[float, str]:
        report_path = root / ".decomp-report.json"
        result = subprocess.run(
            [
                self.objdiff_command,
                "report",
                "generate",
                "--output",
                str(report_path),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        if result.returncode != 0:
            raise FixtureError(result.stderr.strip()[-4000:] or "objdiff report failed")
        report = json.loads(report_path.read_text())
        function = find_report_function(report, task.function_name)
        raw_match = function.get("fuzzy_match_percent", 0.0)
        match = float(raw_match) if raw_match is not None else 0.0
        summary = json.dumps(
            {
                "function": task.function_name,
                "match_percent": match,
                "size": function.get("size"),
                "address": function.get("address"),
            },
            sort_keys=True,
        )
        return match, summary


def find_report_function(report: dict[str, Any], function_name: str) -> dict[str, Any]:
    matches = [
        function
        for unit in report.get("units", [])
        for function in unit.get("functions", [])
        if function.get("name") == function_name
    ]
    if len(matches) != 1:
        raise FixtureError(
            f"objdiff reported {len(matches)} entries for {function_name}"
        )
    return matches[0]


def function_bytes_equal(
    reference_object: bytes, candidate_object: bytes, function_name: str
) -> bool | None:
    reference = _extract_function_data(reference_object, function_name)
    candidate = _extract_function_data(candidate_object, function_name)
    if reference is None or candidate is None:
        return None
    reference_bytes, reference_relocations = reference
    candidate_bytes, candidate_relocations = candidate
    if len(reference_bytes) != len(candidate_bytes):
        return False
    ignored: set[int] = set()
    for offset in reference_relocations | candidate_relocations:
        ignored.update(range(offset, min(offset + 4, len(reference_bytes))))
    return all(
        left == right
        for index, (left, right) in enumerate(
            zip(reference_bytes, candidate_bytes, strict=True)
        )
        if index not in ignored
    )


def extract_function_bytes(object_data: bytes, function_name: str) -> bytes | None:
    """Extract one ELF function symbol's raw section bytes."""
    result = _extract_function_data(object_data, function_name)
    return result[0] if result is not None else None


def _extract_function_data(
    object_data: bytes, function_name: str
) -> tuple[bytes, frozenset[int]] | None:
    try:
        elf = ELFFile(io.BytesIO(object_data))
        matches: list[tuple[bytes, frozenset[int]]] = []
        for symbol_table in elf.iter_sections():
            if not isinstance(symbol_table, SymbolTableSection):
                continue
            for symbol in symbol_table.iter_symbols():
                if symbol.name != function_name:
                    continue
                section_index = symbol["st_shndx"]
                size = int(symbol["st_size"])
                if not isinstance(section_index, int) or size <= 0:
                    continue
                section = elf.get_section(section_index)
                start = int(symbol["st_value"]) - int(section["sh_addr"])
                end = start + size
                data = section.data()
                if start < 0 or end > len(data):
                    continue
                relocation_offsets: set[int] = set()
                for relocation_section in elf.iter_sections():
                    if not isinstance(relocation_section, RelocationSection):
                        continue
                    if int(relocation_section["sh_info"]) != section_index:
                        continue
                    for relocation in relocation_section.iter_relocations():
                        offset = (
                            int(relocation["r_offset"])
                            - int(section["sh_addr"])
                            - start
                        )
                        if 0 <= offset < size:
                            relocation_offsets.add(offset)
                matches.append((data[start:end], frozenset(relocation_offsets)))
        unique = set(matches)
        return unique.pop() if len(unique) == 1 else None
    except Exception:
        return None


def required_commands(profile: ProjectProfile) -> tuple[str, ...]:
    configured = profile.metadata.get("required_host_commands", ())
    return tuple(str(value) for value in configured)


def missing_commands(profile: ProjectProfile) -> tuple[str, ...]:
    return tuple(
        command for command in required_commands(profile) if not shutil.which(command)
    )


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _infrastructure_failure(task: TaskSpec, detail: str) -> VerificationResult:
    return VerificationResult(
        compiled=False,
        exact=False,
        match_percent=0.0,
        baseline_percent=task.initial_match_percent or 0.0,
        reward=0.0,
        compile_stderr=detail,
        failure_kind="infrastructure",
    )
