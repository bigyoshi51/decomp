from __future__ import annotations

import asyncio
import json
import shlex
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import verifiers.v1 as vf
from verifiers.v1.runtimes import make_runtime

from decomp.rl.fixtures import (
    FixtureBuilder,
    FixtureBundle,
    build_verification_archive,
)
from decomp.rl.manifest import read_manifest
from decomp.rl.models import ProjectProfile, TaskSpec, TaskStatus
from decomp.rl.policy import validate_candidate_source
from decomp.rl.profile import load_project_profile
from decomp.rl.reward import improvement_reward
from decomp.rl.source import find_function_span
from decomp.rl.verifier import find_report_function, function_bytes_equal

Mode = Literal["coding_agent", "submit_candidate"]
__all__ = ["N64DecompTaskset"]


class N64DecompTasksetConfig(vf.TasksetConfig):
    project_root: str
    profile: str
    manifest: str
    split: Literal["train", "validation", "test"] = "train"
    mode: Mode = "coding_agent"
    max_tasks: int | None = None
    use_toolchain_image: bool = True
    timeout_seconds: int = 180
    objdiff_command: str = "objdiff-cli"
    toolchain_source: str = "/opt/ido-static-recomp"


class N64DecompTaskData(vf.TaskData):
    manifest_row: dict
    profile_data: dict
    project_root: str
    mode: Mode


class N64DecompState(vf.State):
    best_reward: float = 0.0
    best_match_percent: float = 0.0
    best_exact: bool = False
    attempts: int = 0


class SubmitCandidateConfig(vf.ToolsetConfig):
    timeout_seconds: int = 180
    objdiff_command: str = "objdiff-cli"
    toolchain_source: str = "/opt/ido-static-recomp"
    verifier_image: str


class N64DecompTaskConfig(vf.TaskConfig):
    project_root: str = ""
    profile_path: str = ""
    mode: Mode = "coding_agent"
    submit: SubmitCandidateConfig


class SubmitCandidateTools(vf.Toolset[SubmitCandidateConfig, N64DecompState]):
    # This task exposes one purpose-built API, and its prompts name that public
    # API directly.  Avoid Verifiers' default class-name prefix so providers see
    # `submit_candidate`, not `submit_candidate_tools_submit_candidate`.
    TOOL_PREFIX = None

    def __init__(self, config: SubmitCandidateConfig) -> None:
        super().__init__(config)
        self.task_data: N64DecompTaskData | None = None
        self.bundle: FixtureBundle | None = None

    async def setup_task(self, task: N64DecompTaskData) -> None:
        self.task_data = task
        spec = TaskSpec.from_dict(task.manifest_row)
        profile = _profile_from_dict(task.profile_data)
        self.bundle = await asyncio.to_thread(
            FixtureBuilder(Path(task.project_root), profile).build, spec
        )

    @vf.tool
    async def submit_candidate(self, source: str) -> dict:
        """Compile and score a complete C definition for the target function."""
        if self.task_data is None or self.bundle is None:
            raise RuntimeError("submit_candidate was not initialized for a task")
        task = TaskSpec.from_dict(self.task_data.manifest_row)
        profile = _profile_from_dict(self.task_data.profile_data)
        result = await _verify_in_trusted_container(
            task,
            profile,
            self.bundle,
            source,
            image=self.config.verifier_image,
            objdiff_command=self.config.objdiff_command,
            toolchain_source=self.config.toolchain_source,
        )
        reward = float(result["reward"])
        match_percent = float(result["match_percent"])
        exact = bool(result["exact"])
        self.state.attempts += 1
        if match_percent > self.state.best_match_percent or exact:
            self.state.best_match_percent = match_percent
        if reward > self.state.best_reward or exact:
            self.state.best_reward = reward
        if exact:
            self.state.best_exact = exact
        return {
            "compiled": bool(result["compiled"]),
            "exact": exact,
            "match_percent": match_percent,
            "reward": reward,
            "best_match_percent": self.state.best_match_percent,
            "best_reward": self.state.best_reward,
            "failure_kind": result["failure_kind"],
            "diagnostic": str(result["diagnostic"])[-4000:],
        }


class BaseN64DecompTask(
    vf.Task[N64DecompTaskData, N64DecompState, N64DecompTaskConfig]
):
    def __init__(self, data: N64DecompTaskData, config: N64DecompTaskConfig) -> None:
        super().__init__(data, config)
        self._bundle_lock = threading.Lock()
        self._bundle_value: FixtureBundle | None = None

    @property
    def spec(self) -> TaskSpec:
        return TaskSpec.from_dict(self.data.manifest_row)

    @property
    def profile(self) -> ProjectProfile:
        return _profile_from_dict(self.data.profile_data)

    def _bundle(self) -> FixtureBundle:
        with self._bundle_lock:
            if self._bundle_value is None:
                self._bundle_value = FixtureBuilder(
                    Path(self.config.project_root), self.profile
                ).build(self.spec)
            return self._bundle_value

    async def setup(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        bundle = await asyncio.to_thread(self._bundle)
        await runtime.write(".decomp-fixture.tar.gz", bundle.archive)
        result = await runtime.run(
            [
                "sh",
                "-c",
                "tar -xzf .decomp-fixture.tar.gz && rm .decomp-fixture.tar.gz",
            ],
            {},
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "failed to extract task fixture")
        linked = await runtime.run(
            [
                "sh",
                "-c",
                (
                    "if [ -d /opt/ido-static-recomp ]; then "
                    'for d in tools ../../tools; do mkdir -p "$d"; '
                    '[ -e "$d/ido-static-recomp" ] || '
                    'ln -s /opt/ido-static-recomp "$d/ido-static-recomp"; '
                    "[ ! -d /opt/asm-processor ] || "
                    '[ -e "$d/asm-processor" ] || '
                    'ln -s /opt/asm-processor "$d/asm-processor"; done; '
                    "fi"
                ),
            ],
            {},
        )
        if linked.exit_code != 0:
            raise RuntimeError(linked.stderr or "failed to attach historical tools")

    @vf.reward(weight=1.0)
    async def decomp_reward(self, trace: vf.Trace, runtime: vf.Runtime) -> float:
        if self.config.mode == "submit_candidate":
            trace.record_metrics(
                {
                    "match_percent": trace.state.best_match_percent,
                    "attempts": float(trace.state.attempts),
                    "exact": float(trace.state.best_exact),
                }
            )
            return trace.state.best_reward
        result = await self._score_workspace(trace, runtime)
        trace.info["verification"] = result
        trace.record_metrics(
            {
                "match_percent": float(result["match_percent"]),
                "compiled": float(result["compiled"]),
                "exact": float(result["exact"]),
            }
        )
        return float(result["reward"])

    async def _score_workspace(
        self, trace: vf.Trace, runtime: vf.Runtime
    ) -> dict[str, object]:
        task = self.spec
        if task.provenance.source_path is None or task.build is None:
            return _failure("infrastructure", "task has no source/build mapping")
        try:
            source = (await runtime.read(task.provenance.source_path)).decode(
                errors="replace"
            )
        except Exception as exc:
            return _failure("candidate", str(exc))
        span = find_function_span(source, task.function_name)
        if span is None:
            return _failure(
                "policy", f"function definition not found: {task.function_name}"
            )
        candidate, violations = validate_candidate_source(span.text, task.function_name)
        if candidate is None or violations:
            return _failure("policy", "; ".join(item.message for item in violations))

        return await _verify_in_trusted_container(
            task,
            self.profile,
            self._bundle(),
            candidate,
            image=self.config.submit.verifier_image,
            objdiff_command=self.config.submit.objdiff_command,
            toolchain_source=self.config.submit.toolchain_source,
        )


class CodingAgentTask(BaseN64DecompTask):
    pass


class SubmitCandidateTask(BaseN64DecompTask):
    tools = (SubmitCandidateTools,)


class N64DecompTaskset(vf.Taskset[BaseN64DecompTask, N64DecompTasksetConfig]):
    def load(self) -> list[BaseN64DecompTask]:
        project_root = Path(self.config.project_root).resolve()
        profile_path = Path(self.config.profile).resolve()
        manifest_path = Path(self.config.manifest).resolve()
        profile = load_project_profile(profile_path)
        tasks = [
            task
            for task in read_manifest(manifest_path)
            if task.status == TaskStatus.READY and task.split == self.config.split
        ]
        if self.config.max_tasks is not None:
            tasks = tasks[: self.config.max_tasks]
        task_config = N64DecompTaskConfig(
            project_root=str(project_root),
            profile_path=str(profile_path),
            mode=self.config.mode,
            submit=SubmitCandidateConfig(
                colocated=False,
                timeout_seconds=self.config.timeout_seconds,
                objdiff_command=self.config.objdiff_command,
                toolchain_source=self.config.toolchain_source,
                verifier_image=profile.toolchain_image or "",
            ),
        )
        task_class = (
            CodingAgentTask
            if self.config.mode == "coding_agent"
            else SubmitCandidateTask
        )
        profile_data = asdict(profile)
        loaded: list[BaseN64DecompTask] = []
        for idx, task in enumerate(tasks):
            prompt = _prompt(project_root, task, self.config.mode)
            image = profile.toolchain_image if self.config.use_toolchain_image else None
            data = N64DecompTaskData(
                idx=idx,
                name=task.task_id,
                description=f"Decompile {task.function_name} to an exact object match",
                prompt=prompt,
                system_prompt=_system_prompt(self.config.mode),
                image=image,
                workdir=f"/workspace/projects/{profile.project_id}",
                manifest_row=task.to_dict(include_gold=False),
                profile_data=profile_data,
                project_root=str(project_root),
                mode=self.config.mode,
            )
            loaded.append(task_class(data, task_config))
        return loaded


def load_taskset(config: N64DecompTasksetConfig) -> N64DecompTaskset:
    return N64DecompTaskset(config)


def load_environment(config: vf.EnvConfig) -> vf.Environment:
    return vf.Environment(config)


def _prompt(project_root: Path, task: TaskSpec, mode: Mode) -> str:
    asm = ""
    if task.asm_path:
        path = project_root / task.asm_path
        if path.is_file():
            asm = path.read_text(errors="replace")
    build = task.build
    context = (
        f"Target function: {task.function_name}\n"
        f"Editable source: {task.provenance.source_path}\n"
        f"Compiler: {build.compiler if build else 'unknown'}\n"
        f"Flags: {build.compiler_flags if build else 'unknown'}\n"
        f"Instruction count: {task.instruction_count}\n"
    )
    if mode == "coding_agent":
        return (
            context
            + "\nWork in the provided historical project snapshot. Edit only the "
            "target function in the editable source file. You may compile and "
            "inspect objects. "
            "Leave your best candidate in that source file when finished.\n\n"
            + "Target assembly:\n```asm\n"
            + asm
            + "\n```"
        )
    return (
        context
        + "\nIteratively call submit_candidate with a complete C function definition. "
        "Use the returned compile diagnostics and match percentage to improve it.\n\n"
        + "Starter function:\n```c\n"
        + (task.starter_source or "")
        + "\n```\n\nTarget assembly:\n```asm\n"
        + asm
        + "\n```"
    )


def _system_prompt(mode: Mode) -> str:
    common = (
        "You are decompiling one N64 MIPS function. Produce maintainable C whose "
        "compiled function matches the target exactly. Raw assembly inclusion, inline "
        "assembly, injected instruction bytes, and build-script changes are forbidden."
    )
    if mode == "coding_agent":
        return common + " Use the terminal and file-editing tools to iterate."
    return common + " Use submit_candidate for every compile-and-diff iteration."


def _profile_from_dict(value: dict) -> ProjectProfile:
    tuple_fields = {
        "source_roots",
        "asm_roots",
        "make_args",
        "immutable_paths",
        "hidden_paths",
        "allowed_source_suffixes",
    }
    data = dict(value)
    for field in tuple_fields:
        data[field] = tuple(data.get(field) or ())
    return ProjectProfile(**data)


def _failure(kind: str, diagnostic: str) -> dict[str, object]:
    return {
        "compiled": False,
        "exact": False,
        "match_percent": 0.0,
        "reward": 0.0,
        "failure_kind": kind,
        "diagnostic": diagnostic[-8000:],
    }


async def _verify_in_trusted_container(
    task: TaskSpec,
    profile: ProjectProfile,
    bundle: FixtureBundle,
    candidate_source: str,
    *,
    image: str,
    objdiff_command: str,
    toolchain_source: str,
) -> dict[str, object]:
    """Compile private inputs in a fresh runtime the model never controls."""
    candidate, violations = validate_candidate_source(
        candidate_source, task.function_name
    )
    if candidate is None or violations:
        return _failure("policy", "; ".join(item.message for item in violations))
    if not image:
        return _failure("infrastructure", "project profile has no verifier image")
    if task.build is None:
        return _failure("infrastructure", "task has no build profile")
    try:
        archive = await asyncio.to_thread(
            build_verification_archive,
            bundle,
            profile,
            task,
            candidate,
        )
    except Exception as exc:
        return _failure("infrastructure", str(exc))

    trusted = make_runtime(
        vf.DockerConfig(
            image=image,
            workdir=f"/workspace/projects/{profile.project_id}",
        )
    )
    try:
        await trusted.start()
        await trusted.write("fixture.tar.gz", archive)
        extracted = await trusted.run(
            ["sh", "-c", "tar -xzf fixture.tar.gz && rm fixture.tar.gz"], {}
        )
        if extracted.exit_code != 0:
            return _failure("infrastructure", extracted.stderr)
        linked = await trusted.run(
            [
                "sh",
                "-c",
                (
                    f"if [ -d {shlex.quote(toolchain_source)} ]; then "
                    'for d in tools ../../tools; do mkdir -p "$d"; '
                    '[ -e "$d/ido-static-recomp" ] || '
                    f"ln -s {shlex.quote(toolchain_source)} "
                    '"$d/ido-static-recomp"; '
                    "[ ! -d /opt/asm-processor ] || "
                    '[ -e "$d/asm-processor" ] || '
                    'ln -s /opt/asm-processor "$d/asm-processor"; done; fi'
                ),
            ],
            {},
        )
        if linked.exit_code != 0:
            return _failure("infrastructure", linked.stderr)
        compiled = await trusted.run(
            [
                "make",
                task.build.object_target or "",
                *profile.make_args,
            ],
            {"LC_ALL": "C"},
        )
        if compiled.exit_code != 0:
            return _failure("compile", (compiled.stderr or compiled.stdout)[-8000:])
        # Preserve untouched candidate bytes for the exact gate before clipping
        # stale symbol sizes in disposable objdiff scoring copies.
        candidate_object = await trusted.read(task.build.base_object)
        normalized = await trusted.run(
            [
                "python3",
                "-c",
                (
                    "import sys; from pathlib import Path; "
                    "from decomp.rl.verifier import clip_elf_symbol_ranges; "
                    "[clip_elf_symbol_ranges(Path(value)) for value in sys.argv[1:]]"
                ),
                task.build.target_object,
                task.build.base_object,
            ],
            {},
        )
        if normalized.exit_code != 0:
            return _failure(
                "infrastructure",
                (normalized.stderr or normalized.stdout)[-8000:],
            )
        scored = await trusted.run(
            [
                objdiff_command,
                "report",
                "generate",
                "--output",
                ".decomp-report.json",
            ],
            {},
        )
        if scored.exit_code != 0:
            return _failure("infrastructure", scored.stderr[-8000:])
        report = json.loads((await trusted.read(".decomp-report.json")).decode())
        function = find_report_function(report, task.function_name)
        raw_match = function.get("fuzzy_match_percent", 0.0)
        match = float(raw_match) if raw_match is not None else 0.0
        byte_exact = function_bytes_equal(
            bundle.reference_object, candidate_object, task.function_name
        )
        if byte_exact is None:
            return _failure(
                "infrastructure",
                f"cannot locate ELF function bytes for {task.function_name}",
            )
        exact = match >= 99.999_999 and byte_exact
        return {
            "compiled": True,
            "exact": exact,
            "match_percent": match,
            "reward": improvement_reward(
                match,
                task.initial_match_percent or 0.0,
                exact=exact,
            ),
            "failure_kind": None,
            "diagnostic": (
                "" if byte_exact or match < 99.999_999 else "raw ELF bytes differ"
            ),
        }
    except Exception as exc:
        return _failure("infrastructure", str(exc))
    finally:
        await trusted.stop()


if __name__ == "__main__":
    SubmitCandidateTools.run()
