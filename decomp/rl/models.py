from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class TaskStatus(StrEnum):
    READY = "ready"
    NEEDS_PROVENANCE = "needs_provenance"
    MISSING_BUILD_INPUTS = "missing_build_inputs"
    AMBIGUOUS_SYMBOL = "ambiguous_symbol"
    STARTER_ALREADY_EXACT = "starter_already_exact"
    GOLD_NOT_REPRODUCIBLE = "gold_not_reproducible"
    UNSUPPORTED_BUILD_RECIPE = "unsupported_build_recipe"
    INVALID_EPISODE = "invalid_episode"


@dataclass(frozen=True)
class BuildProfile:
    unit_name: str
    source_path: str
    target_object: str
    base_object: str
    compiler: str | None = None
    compiler_flags: str | None = None
    object_target: str | None = None


@dataclass(frozen=True)
class Provenance:
    episode_commit: str | None = None
    solve_commit: str | None = None
    reference_commit: str | None = None
    base_commit: str | None = None
    source_path: str | None = None
    confidence: str = "none"
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectProfile:
    project_id: str
    repo_url: str
    default_revision: str
    episode_dir: str = "episodes"
    source_roots: tuple[str, ...] = ("src",)
    asm_roots: tuple[str, ...] = ("asm/nonmatchings",)
    objdiff_config: str = "objdiff.json"
    expected_root: str = "expected"
    build_root: str = "build/non_matching"
    object_target_template: str = "build/non_matching/{source_path}.o"
    make_args: tuple[str, ...] = ("RUN_CC_CHECK=0",)
    immutable_paths: tuple[str, ...] = (
        "expected",
        "tools",
        "Makefile",
        "scripts",
    )
    hidden_paths: tuple[str, ...] = (
        ".git",
        "episodes",
        "report.json",
    )
    allowed_source_suffixes: tuple[str, ...] = (".c", ".h")
    toolchain_image: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def resolve(self, root: Path, value: str) -> Path:
        return root / value


@dataclass(frozen=True)
class TaskSpec:
    schema_version: int
    task_id: str
    project: str
    function_name: str
    episode_path: str
    episode_schema: str
    status: TaskStatus
    split: str
    assembly_fingerprint: str
    instruction_count: int
    provenance: Provenance
    build: BuildProfile | None = None
    asm_path: str | None = None
    starter_source: str | None = None
    gold_source: str | None = None
    initial_match_percent: float | None = None
    reason: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_gold: bool = False) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        if not include_gold:
            value.pop("gold_source", None)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskSpec":
        data = dict(value)
        data["status"] = TaskStatus(data["status"])
        provenance = dict(data["provenance"])
        provenance["evidence"] = tuple(provenance.get("evidence") or ())
        data["provenance"] = Provenance(**provenance)
        if data.get("build") is not None:
            build = dict(data["build"])
            # Historical objdiff base_path is the authoritative make target.
            build["object_target"] = build["base_object"]
            data["build"] = BuildProfile(**build)
        data["tags"] = tuple(data.get("tags") or ())
        return cls(**data)


@dataclass(frozen=True)
class PolicyViolation:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    compiled: bool
    exact: bool
    match_percent: float
    baseline_percent: float
    reward: float
    compile_stdout: str = ""
    compile_stderr: str = ""
    diff_summary: str = ""
    collateral_regressions: tuple[str, ...] = ()
    policy_violations: tuple[PolicyViolation, ...] = ()
    elapsed_ms: int = 0
    failure_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
