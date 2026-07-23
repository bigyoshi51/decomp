from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .episodes import EpisodeError, load_episode
from .models import ProjectProfile, Provenance, TaskSpec, TaskStatus
from .provenance import ProvenanceResolver


@dataclass(frozen=True)
class ManifestSummary:
    total: int
    statuses: dict[str, int]
    schemas: dict[str, int]
    splits: dict[str, int]

    @property
    def ready(self) -> int:
        return self.statuses.get(TaskStatus.READY.value, 0)

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "ready": self.ready,
            "statuses": self.statuses,
            "schemas": self.schemas,
            "splits": self.splits,
        }


def discover_tasks(
    project_root: Path,
    profile: ProjectProfile,
    *,
    limit: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[TaskSpec]:
    resolver = ProvenanceResolver(project_root, profile)
    episode_paths = sorted((project_root / profile.episode_dir).glob("*.json"))
    if limit is not None:
        episode_paths = episode_paths[:limit]
    tasks: list[TaskSpec] = []
    for path in episode_paths:
        try:
            episode = load_episode(path, project_root=project_root)
        except EpisodeError as exc:
            tasks.append(
                TaskSpec(
                    schema_version=1,
                    task_id=f"{profile.project_id}/invalid/{path.stem}",
                    project=profile.project_id,
                    function_name=path.stem,
                    episode_path=str(path.relative_to(project_root)),
                    episode_schema="unknown",
                    status=TaskStatus.INVALID_EPISODE,
                    split="train",
                    assembly_fingerprint="missing",
                    instruction_count=0,
                    provenance=Provenance(),
                    reason=str(exc),
                )
            )
            if progress:
                progress(len(tasks), len(episode_paths))
            continue
        tasks.append(resolver.resolve(episode))
        if progress:
            progress(len(tasks), len(episode_paths))
    return tasks


def summarize_tasks(tasks: list[TaskSpec]) -> ManifestSummary:
    return ManifestSummary(
        total=len(tasks),
        statuses=dict(sorted(Counter(task.status.value for task in tasks).items())),
        schemas=dict(sorted(Counter(task.episode_schema for task in tasks).items())),
        splits=dict(sorted(Counter(task.split for task in tasks).items())),
    )


def write_manifest(
    tasks: list[TaskSpec],
    output: Path,
    *,
    include_gold: bool = False,
    ready_only: bool = False,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            for task in tasks:
                if ready_only and task.status != TaskStatus.READY:
                    continue
                handle.write(
                    json.dumps(task.to_dict(include_gold=include_gold), sort_keys=True)
                    + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_manifest(path: Path) -> list[TaskSpec]:
    tasks: list[TaskSpec] = []
    with path.open() as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                tasks.append(TaskSpec.from_dict(json.loads(line)))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid manifest row {line_number} in {path}: {exc}"
                ) from exc
    return tasks
