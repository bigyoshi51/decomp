from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from dataclasses import replace
from pathlib import Path

from .episodes import load_episode
from .fixtures import FixtureBuilder
from .manifest import discover_tasks, summarize_tasks, write_manifest
from .profile import load_project_profile
from .provenance import ProvenanceResolver
from .source import empty_function_body
from .verifier import CompilerVerifier, missing_commands


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare and audit historical decompilation RL tasks"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest", help="discover episode provenance")
    _common_project_args(manifest)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--limit", type=int)
    manifest.add_argument("--ready-only", action="store_true")
    manifest.add_argument("--include-gold", action="store_true")
    manifest.add_argument("--progress-every", type=int, default=100)

    prepare = subparsers.add_parser("prepare", help="materialize one redacted task")
    _common_project_args(prepare)
    prepare.add_argument("episode", type=Path)
    prepare.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify", help="verify a candidate source file")
    _common_project_args(verify)
    verify.add_argument("episode", type=Path)
    verify.add_argument("candidate", type=Path)
    verify.add_argument("--objdiff-command", default="objdiff-cli")
    verify.add_argument("--timeout", type=int, default=180)

    audit = subparsers.add_parser(
        "build-audit", help="compile starter and gold candidates for release gating"
    )
    _common_project_args(audit)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--limit", type=int)
    audit.add_argument(
        "--episode",
        type=Path,
        action="append",
        help="audit only this project-relative episode (repeatable)",
    )
    audit.add_argument("--objdiff-command", default="objdiff-cli")
    audit.add_argument("--toolchain-source", type=Path)
    audit.add_argument("--timeout", type=int, default=180)
    audit.add_argument("--progress-every", type=int, default=25)
    audit.add_argument("--workers", type=int, default=1)

    args = parser.parse_args()
    profile = load_project_profile(args.profile)
    root = args.project_root.resolve()

    if args.command == "manifest":
        tasks = discover_tasks(
            root,
            profile,
            limit=args.limit,
            progress=_progress_callback("discovered", args.progress_every),
        )
        write_manifest(
            tasks,
            args.output,
            include_gold=args.include_gold,
            ready_only=args.ready_only,
        )
        print(json.dumps(summarize_tasks(tasks).to_dict(), indent=2))
        return
    if args.command == "build-audit":
        if args.episode:
            resolver = ProvenanceResolver(root, profile)
            tasks = []
            for raw_path in args.episode:
                path = raw_path if raw_path.is_absolute() else root / raw_path
                tasks.append(resolver.resolve(load_episode(path, project_root=root)))
        else:
            tasks = discover_tasks(
                root,
                profile,
                limit=args.limit,
                progress=_progress_callback("discovered", args.progress_every),
            )
        verifier = CompilerVerifier(
            root,
            profile,
            objdiff_command=args.objdiff_command,
            timeout_seconds=args.timeout,
            toolchain_source=args.toolchain_source,
        )
        if args.workers < 1:
            parser.error("--workers must be at least 1")
        if args.workers == 1:
            results = map(lambda task: _audit_task(task, verifier), tasks)
            executor = None
        else:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=args.workers)
            results = executor.map(lambda task: _audit_task(task, verifier), tasks)
        audited = []
        try:
            for index, task in enumerate(results, 1):
                audited.append(task)
                if args.progress_every and index % args.progress_every == 0:
                    print(
                        f"audited {index}/{len(tasks)} tasks",
                        file=sys.stderr,
                        flush=True,
                    )
        finally:
            if executor is not None:
                executor.shutdown(cancel_futures=True)
        write_manifest(audited, args.output, include_gold=False)
        print(json.dumps(summarize_tasks(audited).to_dict(), indent=2))
        return

    episode_path = args.episode
    if not episode_path.is_absolute():
        episode_path = root / episode_path
    episode = load_episode(episode_path, project_root=root)
    task = ProvenanceResolver(root, profile).resolve(episode)
    if args.command == "prepare":
        FixtureBuilder(root, profile).materialize(task, args.output)
        print(f"Prepared {task.task_id} at {args.output}")
        return

    missing = missing_commands(profile)
    if missing:
        print("Missing verifier commands: " + ", ".join(missing), file=sys.stderr)
    result = CompilerVerifier(
        root,
        profile,
        objdiff_command=args.objdiff_command,
        timeout_seconds=args.timeout,
    ).verify(task, args.candidate.read_text())
    print(json.dumps(result.to_dict(), indent=2))
    raise SystemExit(0 if result.compiled else 2)


def _common_project_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)


def _progress_callback(label: str, every: int):
    def progress(current: int, total: int) -> None:
        if every and (current % every == 0 or current == total):
            print(f"{label} {current}/{total} tasks", file=sys.stderr, flush=True)

    return progress


def _audit_task(task, verifier: CompilerVerifier):
    from .models import Provenance, TaskStatus
    from .source import same_function

    if task.status != TaskStatus.READY:
        return task
    if not task.gold_source:
        return replace(
            task,
            status=TaskStatus.INVALID_EPISODE,
            reason="ready task has no gold source during build audit",
        )
    gold = verifier.verify(task, task.gold_source)
    if gold.failure_kind == "infrastructure":
        raise RuntimeError(
            f"verifier infrastructure failed for {task.task_id}: {gold.compile_stderr}"
        )
    if not gold.exact and verifier.profile.metadata.get(
        "recover_gold_after_failed_audit"
    ):
        recovered_gold = verifier.fixtures.source_candidate(task)
        if recovered_gold and not same_function(recovered_gold, task.gold_source):
            recovered = verifier.verify(task, recovered_gold)
            if recovered.failure_kind == "infrastructure":
                raise RuntimeError(
                    f"verifier infrastructure failed for {task.task_id}: "
                    f"{recovered.compile_stderr}"
                )
            if recovered.exact:
                episode_metadata = dict(task.metadata.get("episode_metadata") or {})
                episode_metadata["gold_recovered_after_failed_audit"] = (
                    task.provenance.source_path
                )
                task = replace(
                    task,
                    gold_source=recovered_gold,
                    provenance=Provenance(
                        episode_commit=task.provenance.episode_commit,
                        solve_commit=task.provenance.solve_commit,
                        reference_commit=task.provenance.reference_commit,
                        base_commit=task.provenance.base_commit,
                        source_path=task.provenance.source_path,
                        confidence="verified",
                        evidence=(
                            *task.provenance.evidence,
                            "episode gold failed the build audit; pinned source "
                            "definition was recovered and verified exact",
                        ),
                    ),
                    metadata={
                        **task.metadata,
                        "episode_metadata": episode_metadata,
                    },
                )
                gold = recovered
    if not gold.exact:
        detail = (gold.compile_stderr or gold.compile_stdout)[-1000:].strip()
        return replace(
            task,
            status=TaskStatus.GOLD_NOT_REPRODUCIBLE,
            reason=(
                f"gold verification failed ({gold.failure_kind or 'mismatch'}; "
                f"{gold.match_percent:.4f}%)" + (f": {detail}" if detail else "")
            ),
        )
    starter_source = verifier.fixtures.starter_candidate(task)
    starter = verifier.verify(task, starter_source)
    if starter.failure_kind == "infrastructure":
        raise RuntimeError(
            f"verifier infrastructure failed for {task.task_id}: "
            f"{starter.compile_stderr}"
        )
    if not starter.compiled:
        try:
            fallback_source = empty_function_body(task.gold_source, task.function_name)
        except ValueError:
            fallback_source = starter_source
        if fallback_source != starter_source:
            fallback = verifier.verify(task, fallback_source)
            if fallback.failure_kind == "infrastructure":
                raise RuntimeError(
                    f"verifier infrastructure failed for {task.task_id}: "
                    f"{fallback.compile_stderr}"
                )
            if fallback.compiled:
                starter = fallback
                starter_source = fallback_source
        if not starter.compiled:
            return replace(
                task,
                status=TaskStatus.MISSING_BUILD_INPUTS,
                reason=f"starter does not compile: {starter.compile_stderr[-1000:]}",
            )
    task = replace(task, starter_source=starter_source)
    if starter.exact:
        return replace(
            task,
            status=TaskStatus.STARTER_ALREADY_EXACT,
            initial_match_percent=100.0,
            reason="starter function is already exact",
        )
    return replace(task, initial_match_percent=starter.match_percent)


if __name__ == "__main__":
    main()
