from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

from .audit import (
    AuditStateError,
    merge_audits,
    ordered_results,
    prepare_resume,
    select_shard,
)
from .episodes import load_episode
from .fixtures import FixtureBuilder, FixtureError
from .manifest import (
    discover_tasks,
    read_manifest,
    summarize_tasks,
    write_manifest,
)
from .models import TaskStatus
from .profile import load_project_profile
from .provenance import ProvenanceResolver
from .source import empty_function_body
from .verifier import (
    CompilerVerifier,
    ReusableCheckoutCompilerVerifier,
    missing_commands,
)


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
    audit.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="atomically checkpoint after this many newly audited rows",
    )
    audit.add_argument(
        "--resume",
        action="store_true",
        help="resume from valid rows already present in --output",
    )
    audit.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output instead of requiring --resume",
    )
    audit.add_argument(
        "--retry-status",
        action="append",
        choices=tuple(status.value for status in TaskStatus),
        default=[],
        help="with --resume, re-audit checkpoint rows having this status",
    )
    audit.add_argument("--shard-count", type=int, default=1)
    audit.add_argument("--shard-index", type=int, default=0)

    merge = subparsers.add_parser(
        "merge-audits",
        help="merge audit shards and prove complete expected-manifest coverage",
    )
    merge.add_argument("--expected", type=Path, required=True)
    merge.add_argument("--input", type=Path, action="append", required=True)
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()
    if args.command == "merge-audits":
        if args.output.exists() and not args.overwrite:
            parser.error(f"output exists; pass --overwrite: {args.output}")
        try:
            expected = read_manifest(args.expected)
            groups = [read_manifest(path) for path in args.input]
            merged_tasks = merge_audits(expected, groups)
        except (AuditStateError, OSError, ValueError) as exc:
            parser.error(str(exc))
        write_manifest(merged_tasks, args.output)
        print(json.dumps(summarize_tasks(merged_tasks).to_dict(), indent=2))
        return

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
        if args.output.exists() and not (args.resume or args.overwrite):
            parser.error(f"output exists; pass --resume or --overwrite: {args.output}")
        if args.resume and args.overwrite:
            parser.error("--resume and --overwrite are mutually exclusive")
        if args.workers < 1:
            parser.error("--workers must be at least 1")
        if args.checkpoint_every < 1:
            parser.error("--checkpoint-every must be at least 1")
        try:
            tasks = select_shard(
                tasks,
                shard_count=args.shard_count,
                shard_index=args.shard_index,
            )
            existing = (
                read_manifest(args.output)
                if args.resume and args.output.exists()
                else []
            )
            audited_by_id, pending = prepare_resume(
                tasks,
                existing,
                retry_statuses=frozenset(
                    TaskStatus(value) for value in args.retry_status
                ),
            )
        except (AuditStateError, OSError, ValueError) as exc:
            parser.error(str(exc))

        verifier_kwargs = {
            "objdiff_command": args.objdiff_command,
            "timeout_seconds": args.timeout,
            "toolchain_source": args.toolchain_source,
        }
        audit_verifiers = []
        if args.workers == 1:
            verifier = ReusableCheckoutCompilerVerifier(
                root, profile, **verifier_kwargs
            )
            audit_verifiers.append(verifier)
            results = map(lambda task: _audit_task(task, verifier), pending)
            executor = None
        else:
            worker_state = threading.local()
            verifier_lock = threading.Lock()

            def audit_in_worker(task):
                verifier = getattr(worker_state, "verifier", None)
                if verifier is None:
                    verifier = ReusableCheckoutCompilerVerifier(
                        root, profile, **verifier_kwargs
                    )
                    worker_state.verifier = verifier
                    with verifier_lock:
                        audit_verifiers.append(verifier)
                return _audit_task(task, verifier)

            executor = concurrent.futures.ThreadPoolExecutor(max_workers=args.workers)
            futures = [executor.submit(audit_in_worker, task) for task in pending]
            results = (
                future.result()
                for future in concurrent.futures.as_completed(futures)
            )
        resumed = len(tasks) - len(pending)
        newly_audited = 0
        try:
            for task in results:
                audited_by_id[task.task_id] = task
                newly_audited += 1
                completed = resumed + newly_audited
                if newly_audited % args.checkpoint_every == 0:
                    write_manifest(
                        ordered_results(tasks, audited_by_id),
                        args.output,
                        include_gold=False,
                    )
                if args.progress_every and (
                    completed % args.progress_every == 0 or completed == len(tasks)
                ):
                    print(
                        f"audited {completed}/{len(tasks)} tasks ({resumed} resumed)",
                        file=sys.stderr,
                        flush=True,
                    )
        finally:
            if executor is not None:
                executor.shutdown(cancel_futures=True)
            for verifier in audit_verifiers:
                verifier.close()
            write_manifest(
                ordered_results(tasks, audited_by_id),
                args.output,
                include_gold=False,
            )
        audited = ordered_results(tasks, audited_by_id)
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
    try:
        task_verifier = verifier.prepare(task)
    except (FixtureError, OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"verifier infrastructure failed for {task.task_id}: {exc}"
        ) from exc
    gold = task_verifier.verify(task, task.gold_source)
    if gold.failure_kind == "infrastructure":
        raise RuntimeError(
            f"verifier infrastructure failed for {task.task_id}: {gold.compile_stderr}"
        )
    if not gold.exact and verifier.profile.metadata.get(
        "recover_gold_after_failed_audit"
    ):
        recovered_gold = verifier.fixtures.source_candidate(task)
        if recovered_gold and not same_function(recovered_gold, task.gold_source):
            recovered = task_verifier.verify(task, recovered_gold)
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
    starter = task_verifier.verify(task, starter_source)
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
            fallback = task_verifier.verify(task, fallback_source)
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
