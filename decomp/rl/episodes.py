from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .source import find_function_span


@dataclass(frozen=True)
class EpisodeRecord:
    path: Path
    schema: str
    function_name: str
    project: str
    gold_source: str
    final_source: str
    assembly: str | None
    initial_source: str | None
    instruction_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


class EpisodeError(ValueError):
    pass


def detect_episode_schema(data: dict[str, Any]) -> str:
    if "steps" in data and "outcome" in data and "final_source" in data:
        return "canonical_v2"
    if ("attempts" in data and ("final_c" in data or "asm_text" in data)) or (
        data.get("matched") is True and isinstance(data.get("final_c"), str)
    ):
        return "legacy_v1"
    raise EpisodeError("unrecognized episode schema")


def load_episode(path: Path, *, project_root: Path | None = None) -> EpisodeRecord:
    path = path.resolve()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise EpisodeError(f"cannot read episode: {exc}") from exc

    schema = detect_episode_schema(data)
    function_name = data.get("function_name")
    if not isinstance(function_name, str) or not function_name:
        raise EpisodeError("missing function_name")

    root = (project_root or path.parent.parent).resolve()
    if schema == "canonical_v2":
        if data.get("outcome") != "match" or data.get("final_match_percent") != 100.0:
            raise EpisodeError("canonical episode is not an exact match")
        final_source = data.get("final_source")
        if not isinstance(final_source, str) or not final_source.strip():
            raise EpisodeError("canonical episode has no final_source")
        span = find_function_span(final_source, function_name)
        gold_source = span.text if span is not None else final_source
        metadata = dict(data.get("metadata") or {})
        assembly = _read_assembly(root, function_name, metadata)
        project = str(data.get("project") or root.name)
        initial_source = data.get("initial_m2c_source")
        instruction_count = int(data.get("instruction_count") or 0)
    else:
        if data.get("matched") is not True:
            raise EpisodeError("legacy episode is not an exact match")
        final_source = data.get("final_c")
        if not isinstance(final_source, str) or not final_source.strip():
            raise EpisodeError("legacy episode has no final_c")
        span = find_function_span(final_source, function_name)
        gold_source = span.text if span is not None else final_source
        metadata = {
            key: data.get(key)
            for key in (
                "segment",
                "compiler",
                "compiler_flags",
                "timestamp",
                "called_functions",
                "referenced_data",
                "nearby_decompiled",
            )
            if data.get(key) is not None
        }
        assembly = data.get("asm_text") or _read_assembly(root, function_name, metadata)
        project = str(data.get("game") or root.name)
        initial_source = data.get("m2c_output")
        instruction_count = int(data.get("instruction_count") or 0)

    if not instruction_count and assembly:
        instruction_count = sum(
            1 for line in assembly.splitlines() if "/*" in line and "*/" in line
        )

    return EpisodeRecord(
        path=path,
        schema=schema,
        function_name=function_name,
        project=project,
        gold_source=gold_source.rstrip() + "\n",
        final_source=final_source.rstrip() + "\n",
        assembly=assembly.rstrip() + "\n" if assembly else None,
        initial_source=(
            initial_source.rstrip() + "\n"
            if isinstance(initial_source, str) and initial_source
            else None
        ),
        instruction_count=instruction_count,
        metadata=metadata,
    )


def load_episodes(
    episode_dir: Path, *, project_root: Path | None = None
) -> Iterator[EpisodeRecord]:
    for path in sorted(episode_dir.glob("*.json")):
        yield load_episode(path, project_root=project_root)


def _read_assembly(
    root: Path, function_name: str, metadata: dict[str, Any]
) -> str | None:
    raw_path = metadata.get("asm_path")
    if isinstance(raw_path, str):
        normalized = _normalize_metadata_path(raw_path, root)
        if normalized is not None and normalized.is_file():
            return normalized.read_text()

    candidates = sorted((root / "asm").rglob(f"{function_name}.s"))
    segment = metadata.get("segment")
    if isinstance(segment, str):
        for candidate in candidates:
            if segment in candidate.parts:
                return candidate.read_text()
    if len(candidates) == 1:
        return candidates[0].read_text()
    return None


def _normalize_metadata_path(value: str, root: Path) -> Path | None:
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            return None

    parts = path.parts
    for marker in ("asm", "src", "episodes"):
        if marker in parts:
            path = Path(*parts[parts.index(marker) :])
            break
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate
