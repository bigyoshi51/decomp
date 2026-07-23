from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .git import GitRepo
from .models import ProjectProfile, TaskSpec, TaskStatus
from .policy import validate_candidate_source
from .source import (
    canonicalize_c,
    empty_function_body,
    find_function_spans,
    nonexact_function_body,
    relocation_scaffold_function_body,
    replace_function,
)


class FixtureError(RuntimeError):
    pass


@dataclass(frozen=True)
class FixtureBundle:
    task_id: str
    archive: bytes
    reference_object: bytes
    reference_sha256: str


class FixtureBuilder:
    """Build a redacted historical project snapshot plus a private reference."""

    def __init__(self, project_root: Path, profile: ProjectProfile) -> None:
        self.root = project_root.resolve()
        self.profile = profile
        self.git = GitRepo(self.root)

    def build(self, task: TaskSpec) -> FixtureBundle:
        if task.status != TaskStatus.READY:
            raise FixtureError(f"task is not ready: {task.status.value}")
        if task.build is None or task.provenance.solve_commit is None:
            raise FixtureError("task has no build profile or solve revision")
        if task.provenance.source_path is None:
            raise FixtureError("task has no source path")

        revision = task.provenance.solve_commit
        reference_revision = task.provenance.reference_commit or revision
        reference = self.git.show_bytes(reference_revision, task.build.target_object)
        if reference is None:
            raise FixtureError(
                f"reference object is absent at {reference_revision}: "
                f"{task.build.target_object}"
            )

        archive = self.git.archive(
            revision,
            exclude=tuple(dict.fromkeys((*self.profile.hidden_paths, "expected"))),
        )
        with tempfile.TemporaryDirectory(prefix="decomp-fixture-") as raw_tmp:
            root = Path(raw_tmp)
            _extract_tar(archive, root)
            self._redact_target(root, task)
            self._remove_hidden_paths(root)
            self._write_task_info(root, task)
            output = _pack_tar(root)

        return FixtureBundle(
            task_id=task.task_id,
            archive=output,
            reference_object=reference,
            reference_sha256=hashlib.sha256(reference).hexdigest(),
        )

    def materialize(self, task: TaskSpec, destination: Path) -> FixtureBundle:
        if destination.exists() and any(destination.iterdir()):
            raise FixtureError(f"destination is not empty: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        bundle = self.build(task)
        materialize_archive(bundle.archive, destination)
        return bundle

    def build_verification_archive(
        self, task: TaskSpec, candidate_source: str
    ) -> bytes:
        """Return a private fixture containing the candidate and reference object."""
        return build_verification_archive(
            self.build(task), self.profile, task, candidate_source
        )

    @staticmethod
    def starter_candidate(task: TaskSpec) -> str:
        """Return a compilable best-effort starter with the historical signature."""
        if task.starter_source:
            starter, violations = validate_candidate_source(
                task.starter_source, task.function_name
            )
            if (
                starter is not None
                and not violations
                and (
                    not task.gold_source
                    or canonicalize_c(starter) != canonicalize_c(task.gold_source)
                )
            ):
                return starter
        if task.gold_source:
            try:
                starter = empty_function_body(task.gold_source, task.function_name)
                if canonicalize_c(starter) == canonicalize_c(task.gold_source):
                    return nonexact_function_body(task.gold_source, task.function_name)
                return starter
            except ValueError:
                pass
        return _starter_scaffold(task.function_name)

    def source_candidate(self, task: TaskSpec) -> str | None:
        """Read the target definition from the task's trusted solve revision."""
        revision = task.provenance.solve_commit
        source_path = task.provenance.source_path
        if revision is None or source_path is None:
            return None
        text = self.git.show_text(revision, source_path)
        if text is None:
            return None
        spans = find_function_spans(text, task.function_name)
        return spans[0].text.rstrip() + "\n" if spans else None

    def _redact_target(self, root: Path, task: TaskSpec) -> None:
        assert task.provenance.source_path is not None
        primary = root / task.provenance.source_path
        if not primary.is_file():
            raise FixtureError(f"historical source is absent: {primary}")
        starter_function = self.starter_candidate(task)
        if task.gold_source and canonicalize_c(starter_function) == canonicalize_c(
            task.gold_source
        ):
            raise FixtureError("starter source already contains the gold function")

        paths = self._target_paths(root, task.function_name, primary)

        primary_redacted = False
        for path in sorted(paths):
            original = path.read_text(errors="replace")
            spans = find_function_spans(original, task.function_name)
            redacted = original
            for index, span in reversed(tuple(enumerate(spans))):
                if path == primary and index == 0:
                    replacement = starter_function
                    primary_redacted = True
                else:
                    replacement = relocation_scaffold_function_body(
                        span.text, task.function_name
                    ).rstrip()
                redacted = redacted[: span.start] + replacement + redacted[span.end :]
            scrubbed = _scrub_target_comments(redacted, task.function_name)
            if scrubbed != original:
                path.write_text(scrubbed)
        if not primary_redacted:
            raise FixtureError(
                f"function definition not found in historical source: {primary}"
            )

    def _target_paths(self, root: Path, function_name: str, primary: Path) -> set[Path]:
        """Find only files that can leak the target, with a portable fallback."""
        directories = [
            root / value
            for value in self.profile.source_roots
            if (root / value).is_dir()
        ]
        if shutil.which("rg") and directories:
            command = ["rg", "--files-with-matches", "--fixed-strings"]
            for suffix in self.profile.allowed_source_suffixes:
                command.extend(("--glob", f"*{suffix}"))
            command.extend((function_name, *(str(path) for path in directories)))
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            if result.returncode in {0, 1}:
                return {
                    primary,
                    *(
                        Path(line) if Path(line).is_absolute() else root / line
                        for line in result.stdout.splitlines()
                        if line
                    ),
                }

        paths = {primary}
        for directory in directories:
            for suffix in self.profile.allowed_source_suffixes:
                for path in directory.rglob(f"*{suffix}"):
                    if function_name in path.read_text(errors="replace"):
                        paths.add(path)
        return paths

    def _remove_hidden_paths(self, root: Path) -> None:
        for value in tuple(dict.fromkeys((*self.profile.hidden_paths, "expected"))):
            target = root / value
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()

    @staticmethod
    def _write_task_info(root: Path, task: TaskSpec) -> None:
        public = {
            "task_id": task.task_id,
            "project": task.project,
            "function_name": task.function_name,
            "source_path": task.provenance.source_path,
            "asm_path": task.asm_path,
            "compiler": task.build.compiler if task.build else None,
            "compiler_flags": task.build.compiler_flags if task.build else None,
            "object_target": task.build.object_target if task.build else None,
        }
        (root / ".decomp-task.json").write_text(
            json.dumps(public, indent=2, sort_keys=True) + "\n"
        )


def apply_candidate(root: Path, task: TaskSpec, candidate_source: str) -> None:
    if task.provenance.source_path is None:
        raise FixtureError("task has no source path")
    function, violations = validate_candidate_source(
        candidate_source, task.function_name
    )
    if function is None or violations:
        detail = "; ".join(item.message for item in violations)
        raise FixtureError(detail or "invalid candidate")
    path = root / task.provenance.source_path
    path.write_text(replace_function(path.read_text(), task.function_name, function))


def isolate_objdiff_config(root: Path, profile: ProjectProfile, task: TaskSpec) -> None:
    if task.build is None:
        raise FixtureError("task has no build profile")
    config_path = root / profile.objdiff_config
    config = json.loads(config_path.read_text())
    units = [
        unit
        for unit in config.get("units", [])
        if unit.get("name") == task.build.unit_name
    ]
    if len(units) != 1:
        raise FixtureError(
            f"objdiff unit is absent or ambiguous: {task.build.unit_name}"
        )
    config["units"] = units
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def materialize_archive(data: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    _extract_tar(data, destination)


def build_verification_archive(
    bundle: FixtureBundle,
    profile: ProjectProfile,
    task: TaskSpec,
    candidate_source: str,
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="decomp-private-fixture-") as raw_tmp:
        root = Path(raw_tmp)
        materialize_archive(bundle.archive, root)
        apply_candidate(root, task, candidate_source)
        if task.build is None:
            raise FixtureError("task has no build profile")
        reference = root / task.build.target_object
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(bundle.reference_object)
        isolate_objdiff_config(root, profile, task)
        return _pack_tar(root)


def _starter_scaffold(function_name: str) -> str:
    return f"void {function_name}(void) {{\n}}\n"


def _scrub_target_comments(source: str, function_name: str) -> str:
    block = re.compile(r"/\*.*?\*/", re.DOTALL)
    line = re.compile(r"//[^\n]*")

    def replace_comment(match: re.Match[str]) -> str:
        text = match.group(0)
        if function_name in text:
            return "/* Target-function notes redacted for RL. */"
        return text

    return line.sub(replace_comment, block.sub(replace_comment, source))


def _extract_tar(data: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        archive.extractall(destination, filter=_safe_member)


def _safe_member(member: tarfile.TarInfo, destination: str) -> tarfile.TarInfo | None:
    try:
        return tarfile.data_filter(member, destination)
    except tarfile.FilterError:
        # Historical worktrees sometimes committed machine-local tool symlinks.
        # A fixture must neither follow nor reproduce those links.
        return None


def _pack_tar(root: Path) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", compresslevel=6) as archive:
        for path in sorted(root.rglob("*")):
            archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
    return output.getvalue()
