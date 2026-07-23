from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .models import TaskSpec, TaskStatus


class AuditStateError(ValueError):
    pass


def select_shard(
    tasks: Iterable[TaskSpec], *, shard_count: int, shard_index: int
) -> list[TaskSpec]:
    """Select a stable task-ID shard without depending on manifest order."""
    if shard_count < 1:
        raise AuditStateError("shard_count must be at least 1")
    if not 0 <= shard_index < shard_count:
        raise AuditStateError(
            f"shard_index must be in [0, {shard_count - 1}], got {shard_index}"
        )
    if shard_count == 1:
        return list(tasks)
    return [
        task for task in tasks if _shard_for(task.task_id, shard_count) == shard_index
    ]


def prepare_resume(
    tasks: list[TaskSpec],
    existing: Iterable[TaskSpec],
    *,
    retry_statuses: frozenset[TaskStatus] = frozenset(),
) -> tuple[dict[str, TaskSpec], list[TaskSpec]]:
    """Validate a checkpoint and return retained results plus pending tasks."""
    expected = _index_unique(tasks, label="selected task")
    retained: dict[str, TaskSpec] = {}
    for task in existing:
        if task.task_id in retained:
            raise AuditStateError(f"duplicate checkpoint task_id: {task.task_id}")
        source = expected.get(task.task_id)
        if source is None:
            raise AuditStateError(
                f"checkpoint task is outside the selected shard: {task.task_id}"
            )
        _validate_identity(source, task)
        retained[task.task_id] = task
    pending = [
        task
        for task in tasks
        if task.task_id not in retained
        or not _is_audited(retained[task.task_id])
        or retained[task.task_id].status in retry_statuses
    ]
    return retained, pending


def ordered_results(
    task_order: Iterable[TaskSpec], results: dict[str, TaskSpec]
) -> list[TaskSpec]:
    """Return completed results in canonical task order."""
    return [results[task.task_id] for task in task_order if task.task_id in results]


def merge_audits(
    expected: list[TaskSpec], audit_groups: Iterable[Iterable[TaskSpec]]
) -> list[TaskSpec]:
    """Merge non-overlapping audit shards and prove exact manifest coverage."""
    expected_by_id = _index_unique(expected, label="expected")
    merged: dict[str, TaskSpec] = {}
    for group in audit_groups:
        for task in group:
            if task.task_id in merged:
                raise AuditStateError(f"duplicate audited task_id: {task.task_id}")
            source = expected_by_id.get(task.task_id)
            if source is None:
                raise AuditStateError(f"unexpected audited task_id: {task.task_id}")
            _validate_identity(source, task)
            if not _is_audited(task):
                raise AuditStateError(
                    f"ready row has no measured starter baseline: {task.task_id}"
                )
            merged[task.task_id] = task

    missing = [task.task_id for task in expected if task.task_id not in merged]
    if missing:
        preview = ", ".join(missing[:5])
        suffix = "" if len(missing) <= 5 else f", ... ({len(missing)} total)"
        raise AuditStateError(f"audit coverage is incomplete: {preview}{suffix}")
    return [merged[task.task_id] for task in expected]


def _shard_for(task_id: str, shard_count: int) -> int:
    digest = hashlib.sha256(task_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def _index_unique(tasks: Iterable[TaskSpec], *, label: str) -> dict[str, TaskSpec]:
    result: dict[str, TaskSpec] = {}
    for task in tasks:
        if task.task_id in result:
            raise AuditStateError(f"duplicate {label} task_id: {task.task_id}")
        result[task.task_id] = task
    return result


def _validate_identity(expected: TaskSpec, actual: TaskSpec) -> None:
    fields = (
        "project",
        "function_name",
        "episode_path",
        "assembly_fingerprint",
        "split",
    )
    changed = [
        field for field in fields if getattr(expected, field) != getattr(actual, field)
    ]
    if changed:
        raise AuditStateError(
            f"stale audit identity for {expected.task_id}: {', '.join(changed)}"
        )


def _is_audited(task: TaskSpec) -> bool:
    return task.status != TaskStatus.READY or task.initial_match_percent is not None
