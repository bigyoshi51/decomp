from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _count_instruction_lines(asm_text: str) -> int:
    return sum(1 for line in asm_text.splitlines() if "/*" in line and "*/" in line)


def _hash_to_unit_interval(value: str) -> float:
    digest = hashlib.blake2s(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def _guess_project_root(episode_dir: Path) -> Path:
    return episode_dir.parent


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.rstrip() + "\n" if value else ""


def _build_prompt(
    *,
    project: str,
    function_name: str,
    instruction_count: int,
    assembly: str | None,
    initial_m2c_source: str | None,
    metadata: dict[str, Any],
) -> str:
    lines = [
        "Decompile the following N64 function to exact-match C.",
        f"Project: {project}",
        f"Function: {function_name}",
    ]
    if metadata.get("segment"):
        lines.append(f"Segment: {metadata['segment']}")
    if instruction_count:
        lines.append(f"Instruction count: {instruction_count}")
    if metadata.get("compiler"):
        lines.append(f"Compiler: {metadata['compiler']}")
    if metadata.get("compiler_flags"):
        lines.append(f"Compiler flags: {metadata['compiler_flags']}")

    if assembly:
        lines.extend(["", "Assembly:", assembly.rstrip()])

    if initial_m2c_source:
        lines.extend(["", "Initial m2c output:", initial_m2c_source.rstrip()])

    lines.extend(
        [
            "",
            "Return only the decompiled C for the target function.",
        ]
    )
    return "\n".join(lines) + "\n"


def _make_task_id(project: str, segment: str | None, function_name: str) -> str:
    if segment:
        return f"{project}/{segment}/{function_name}"
    return f"{project}/{function_name}"


def _find_function_definition(source_text: str, function_name: str) -> str | None:
    name_pat = re.compile(rf"\b{re.escape(function_name)}\s*\(")

    for match in name_pat.finditer(source_text):
        open_paren = source_text.find("(", match.start())
        if open_paren == -1:
            continue

        depth = 0
        close_paren = -1
        for idx in range(open_paren, len(source_text)):
            ch = source_text[idx]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    close_paren = idx
                    break
        if close_paren == -1:
            continue

        body_start = close_paren + 1
        while body_start < len(source_text) and source_text[body_start].isspace():
            body_start += 1
        if body_start >= len(source_text) or source_text[body_start] != "{":
            continue

        brace_depth = 0
        body_end = -1
        for idx in range(body_start, len(source_text)):
            ch = source_text[idx]
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    body_end = idx + 1
                    break
        if body_end == -1:
            continue

        start = source_text.rfind("\n", 0, match.start())
        start = 0 if start == -1 else start + 1

        while start > 0:
            prev_end = start - 1
            prev_start = source_text.rfind("\n", 0, prev_end)
            prev_start = 0 if prev_start == -1 else prev_start + 1
            prev_line = source_text[prev_start:prev_end].rstrip()
            stripped = prev_line.strip()
            if not stripped:
                break
            if (
                stripped.endswith(";")
                or stripped.endswith("}")
                or stripped.startswith("#")
            ):
                break
            start = prev_start

        return source_text[start:body_end].strip() + "\n"

    return None


@dataclass
class ProjectIndex:
    project_root: Path
    asm_map: dict[str, list[Path]]

    @classmethod
    def build(cls, project_root: Path) -> "ProjectIndex":
        asm_map: dict[str, list[Path]] = {}
        asm_root = project_root / "asm"
        if asm_root.exists():
            for asm_path in asm_root.rglob("*.s"):
                asm_map.setdefault(asm_path.stem, []).append(asm_path)
        return cls(project_root=project_root, asm_map=asm_map)

    def find_asm(
        self,
        function_name: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Path | None:
        metadata = metadata or {}
        asm_path_value = metadata.get("asm_path")
        if isinstance(asm_path_value, str):
            candidate = self.project_root / asm_path_value
            if candidate.exists():
                return candidate

        candidates = self.asm_map.get(function_name, [])
        if not candidates:
            return None

        segment = metadata.get("segment")
        if isinstance(segment, str):
            for candidate in candidates:
                if segment in candidate.parts:
                    return candidate

        return candidates[0]


def _episode_dirs_from_repo_root(repo_root: Path) -> list[Path]:
    projects_dir = repo_root / "projects"
    if not projects_dir.exists():
        return []
    return sorted(
        path
        for path in projects_dir.iterdir()
        if path.is_dir() and (path / "episodes").is_dir()
        for path in [path / "episodes"]
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _detect_schema(data: dict[str, Any]) -> str:
    if "steps" in data and "outcome" in data and "final_source" in data:
        return "canonical_v2"
    if ("attempts" in data and ("final_c" in data or "asm_text" in data)) or (
        data.get("matched") is True and "final_c" in data
    ):
        return "legacy_v1"
    return "unknown"


def _normalize_legacy_record(
    *,
    data: dict[str, Any],
    episode_path: Path,
    project_root: Path,
    eval_ratio: float,
    split_seed: str,
) -> dict[str, Any] | None:
    if not data.get("matched"):
        return None

    function_name = data.get("function_name")
    if not isinstance(function_name, str) or not function_name:
        return None

    target_c = _normalize_text(data.get("final_c"))
    if not target_c:
        return None

    project = project_root.name
    metadata: dict[str, Any] = {
        "segment": data.get("segment"),
        "compiler": data.get("compiler"),
        "compiler_flags": data.get("compiler_flags"),
        "symbol_name": data.get("symbol_name"),
        "reference": data.get("reference"),
        "called_functions": data.get("called_functions", []),
        "referenced_data": data.get("referenced_data", []),
        "nearby_decompiled": data.get("nearby_decompiled", []),
        "timestamp": data.get("timestamp"),
        "episode_path": str(episode_path.relative_to(project_root)),
    }

    notes = [
        attempt.get("notes")
        for attempt in data.get("attempts", [])
        if isinstance(attempt, dict) and attempt.get("notes")
    ]
    if isinstance(data.get("notes"), list):
        notes.extend(str(note) for note in data["notes"] if note)
    if notes:
        metadata["notes"] = notes

    asm_text = _normalize_text(data.get("asm_text"))
    initial_m2c_source = _normalize_text(data.get("m2c_output"))
    instruction_count = int(data.get("instruction_count") or 0)

    segment = metadata.get("segment")
    task_id = _make_task_id(
        project, segment if isinstance(segment, str) else None, function_name
    )
    split = (
        "eval"
        if _hash_to_unit_interval(f"{split_seed}:{task_id}") < eval_ratio
        else "train"
    )

    prompt = _build_prompt(
        project=project,
        function_name=function_name,
        instruction_count=instruction_count,
        assembly=asm_text,
        initial_m2c_source=initial_m2c_source,
        metadata=metadata,
    )

    return {
        "schema_version": 1,
        "dataset_type": "sft_exact_match",
        "source_schema": "legacy_v1",
        "split": split,
        "task_id": task_id,
        "project": project,
        "function_name": function_name,
        "instruction_count": instruction_count,
        "assembly": asm_text,
        "initial_m2c_source": initial_m2c_source,
        "target_c": target_c,
        "final_source": target_c,
        "prompt": prompt,
        "completion": target_c,
        "metadata": metadata,
    }


def _normalize_canonical_record(
    *,
    data: dict[str, Any],
    episode_path: Path,
    project_root: Path,
    project_index: ProjectIndex,
    eval_ratio: float,
    split_seed: str,
) -> dict[str, Any] | None:
    if data.get("outcome") != "match":
        return None
    if data.get("final_match_percent") != 100.0:
        return None

    function_name = data.get("function_name")
    project = data.get("project") or project_root.name
    final_source = _normalize_text(data.get("final_source"))
    if not isinstance(function_name, str) or not function_name or not final_source:
        return None

    metadata = dict(data.get("metadata") or {})
    metadata["episode_path"] = str(episode_path.relative_to(project_root))
    metadata["model"] = data.get("model")
    metadata["start_time"] = data.get("start_time")
    metadata["end_time"] = data.get("end_time")
    metadata["total_tokens"] = data.get("total_tokens")

    assistant_texts = [
        step.get("assistant_text")
        for step in data.get("steps", [])
        if isinstance(step, dict) and step.get("assistant_text")
    ]
    if assistant_texts:
        metadata["assistant_texts"] = assistant_texts

    asm_text = None
    asm_path = project_index.find_asm(function_name, metadata=metadata)
    if asm_path is not None:
        metadata.setdefault("asm_path", str(asm_path.relative_to(project_root)))
        asm_text = _normalize_text(asm_path.read_text())

    initial_m2c_source = _normalize_text(data.get("initial_m2c_source"))
    instruction_count = int(data.get("instruction_count") or 0)
    if not instruction_count and asm_text:
        instruction_count = _count_instruction_lines(asm_text)

    target_c = _find_function_definition(final_source, function_name) or final_source

    segment = metadata.get("segment")
    task_id = _make_task_id(
        project, segment if isinstance(segment, str) else None, function_name
    )
    split = (
        "eval"
        if _hash_to_unit_interval(f"{split_seed}:{task_id}") < eval_ratio
        else "train"
    )

    prompt = _build_prompt(
        project=project,
        function_name=function_name,
        instruction_count=instruction_count,
        assembly=asm_text,
        initial_m2c_source=initial_m2c_source,
        metadata=metadata,
    )

    return {
        "schema_version": 1,
        "dataset_type": "sft_exact_match",
        "source_schema": "canonical_v2",
        "split": split,
        "task_id": task_id,
        "project": project,
        "function_name": function_name,
        "instruction_count": instruction_count,
        "assembly": asm_text,
        "initial_m2c_source": initial_m2c_source,
        "target_c": target_c,
        "final_source": final_source,
        "prompt": prompt,
        "completion": target_c,
        "metadata": metadata,
    }


def export_episodes(
    *,
    episode_dirs: list[Path],
    output_dir: Path,
    eval_ratio: float = 0.1,
    split_seed: str = "decomp-export-v1",
) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()

    for episode_dir in episode_dirs:
        project_root = _guess_project_root(episode_dir)
        project_index = ProjectIndex.build(project_root)

        for episode_path in sorted(episode_dir.glob("*.json")):
            try:
                data = _load_json(episode_path)
            except json.JSONDecodeError as exc:
                print(
                    f"warning: skipping invalid JSON {episode_path}: {exc}",
                    file=sys.stderr,
                )
                continue

            schema = _detect_schema(data)
            record: dict[str, Any] | None
            if schema == "legacy_v1":
                record = _normalize_legacy_record(
                    data=data,
                    episode_path=episode_path,
                    project_root=project_root,
                    eval_ratio=eval_ratio,
                    split_seed=split_seed,
                )
            elif schema == "canonical_v2":
                record = _normalize_canonical_record(
                    data=data,
                    episode_path=episode_path,
                    project_root=project_root,
                    project_index=project_index,
                    eval_ratio=eval_ratio,
                    split_seed=split_seed,
                )
            else:
                print(
                    f"warning: skipping unknown episode schema {episode_path}",
                    file=sys.stderr,
                )
                continue

            if record is None:
                continue

            task_id = record["task_id"]
            if task_id in seen_task_ids:
                print(
                    f"warning: duplicate task id {task_id}; keeping first record only",
                    file=sys.stderr,
                )
                continue
            seen_task_ids.add(task_id)
            records.append(record)

    records.sort(key=lambda record: record["task_id"])

    train_path = output_dir / "sft_exact_matches.jsonl"
    eval_path = output_dir / "eval_exact_matches.jsonl"
    train_count = 0
    eval_count = 0

    with (
        train_path.open("w", encoding="utf-8") as train_file,
        eval_path.open("w", encoding="utf-8") as eval_file,
    ):
        for record in records:
            line = json.dumps(record, ensure_ascii=True)
            if record["split"] == "eval":
                eval_file.write(line + "\n")
                eval_count += 1
            else:
                train_file.write(line + "\n")
                train_count += 1

    return {
        "records_total": len(records),
        "records_train": train_count,
        "records_eval": eval_count,
        "episode_dirs": len(episode_dirs),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export exact-match episodes into normalized SFT/eval JSONL."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repo root used to discover project episode directories (default: cwd)",
    )
    parser.add_argument(
        "--episodes-dir",
        action="append",
        type=Path,
        default=None,
        help="Specific episode directory to include. May be passed multiple times.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("exports"),
        help="Output directory for JSONL files (default: exports)",
    )
    parser.add_argument(
        "--eval-ratio",
        type=float,
        default=0.1,
        help="Deterministic eval split ratio in [0, 1] (default: 0.1)",
    )
    parser.add_argument(
        "--split-seed",
        default="decomp-export-v1",
        help="Seed string for deterministic train/eval split",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.eval_ratio < 0.0 or args.eval_ratio > 1.0:
        parser.error("--eval-ratio must be between 0 and 1")

    if args.episodes_dir:
        episode_dirs = [path.resolve() for path in args.episodes_dir]
    else:
        episode_dirs = _episode_dirs_from_repo_root(args.repo_root.resolve())

    if not episode_dirs:
        parser.error("no episode directories found")

    summary = export_episodes(
        episode_dirs=episode_dirs,
        output_dir=args.output_dir.resolve(),
        eval_ratio=args.eval_ratio,
        split_seed=args.split_seed,
    )

    print(
        "export-episodes:",
        f"{summary['records_total']} records",
        f"({summary['records_train']} train / {summary['records_eval']} eval)",
        f"from {summary['episode_dirs']} episode directorie(s)",
        f"-> {args.output_dir.resolve()}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
