from __future__ import annotations

import functools
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .episodes import EpisodeRecord
from .git import GitRepo
from .models import BuildProfile, ProjectProfile, Provenance, TaskSpec, TaskStatus
from .policy import validate_candidate_source
from .source import (
    SourceIndex,
    empty_function_body,
    find_function_span,
    looks_like_comment_fragment,
    same_function,
)
from .splits import assembly_fingerprint, deterministic_split
from .verifier import extract_function_bytes


class ProvenanceResolver:
    def __init__(self, project_root: Path, profile: ProjectProfile) -> None:
        self.root = project_root.resolve()
        self.profile = profile
        self.git = GitRepo(self.root)
        self.index = SourceIndex.build(self.root, profile.source_roots)
        self.episode_commits = self.git.latest_commits_under(
            profile.episode_dir, profile.default_revision
        )

    def resolve(self, episode: EpisodeRecord) -> TaskSpec:
        fingerprint = assembly_fingerprint(episode.assembly)
        split = deterministic_split(fingerprint)
        task_id = self._task_id(episode)
        episode_path = str(episode.path.relative_to(self.root))
        # The checked-in episode may have been corrected after its introduction.
        # Resolve against the commit that produced the current episode contents.
        episode_commit = self.episode_commits.get(episode_path)
        if episode_commit is None:
            episode_history = self.git.history(
                episode_path, self.profile.default_revision
            )
            episode_commit = episode_history[0] if episode_history else None

        episode, recovery_evidence = self._recover_malformed_gold(episode)

        unsupported_reason = self._unsupported_entry_point_reason(
            episode.function_name
        )
        if unsupported_reason is not None:
            raw_source = episode.metadata.get("source_path")
            source_path = (
                _project_relative(raw_source)
                if isinstance(raw_source, str)
                else None
            )
            return self._unresolved(
                episode,
                task_id=task_id,
                split=split,
                fingerprint=fingerprint,
                episode_commit=episode_commit,
                source_path=source_path,
                status=TaskStatus.UNSUPPORTED_BUILD_RECIPE,
                reason=unsupported_reason,
                evidence=[
                    "profile identifies the episode symbol as a non-standalone "
                    "entry point"
                ],
            )

        candidates = self._source_candidates(episode, episode_commit)
        if not candidates:
            return self._unresolved(
                episode,
                task_id=task_id,
                split=split,
                fingerprint=fingerprint,
                episode_commit=episode_commit,
                status=TaskStatus.NEEDS_PROVENANCE,
                reason="no source file contains the target symbol",
            )
        metadata_path = episode.metadata.get("source_path")
        preferred = (
            _project_relative(metadata_path) if isinstance(metadata_path, str) else None
        )
        resolved = []
        for candidate in candidates:
            solve = self._find_solve_commit(
                episode, candidate, episode_commit, episode.metadata
            )
            if solve[0] is not None:
                resolved.append((candidate, *solve))
                # A valid episode-supplied path is authoritative. Continuing
                # through renamed/split descendants can require thousands of
                # irrelevant revisions and cannot change the selection below.
                if candidate == preferred:
                    break
        if not resolved:
            return self._unresolved(
                episode,
                task_id=task_id,
                split=split,
                fingerprint=fingerprint,
                episode_commit=episode_commit,
                source_path=candidates[0],
                status=TaskStatus.NEEDS_PROVENANCE,
                reason=(
                    "gold function was not found at the episode revision or "
                    "within the configured pinned source-history search"
                ),
            )
        if len(resolved) > 1:
            matching = [item for item in resolved if item[0] == preferred]
            if len(matching) == 1:
                resolved = matching
            else:
                return self._unresolved(
                    episode,
                    task_id=task_id,
                    split=split,
                    fingerprint=fingerprint,
                    episode_commit=episode_commit,
                    status=TaskStatus.AMBIGUOUS_SYMBOL,
                    reason="multiple source histories contain the gold function: "
                    + ", ".join(item[0] for item in resolved),
                )

        source_path, solve_commit, starter_source, confidence, evidence = resolved[0]
        evidence = [*recovery_evidence, *evidence]
        assert solve_commit is not None

        base_commit = self.git.parent(solve_commit)
        build = self._resolve_build(
            solve_commit,
            source_path,
            episode.metadata,
            function_name=episode.function_name,
            prefer_metadata=episode.schema == "canonical_v2",
        )
        if build is None:
            return self._unresolved(
                episode,
                task_id=task_id,
                split=split,
                fingerprint=fingerprint,
                episode_commit=episode_commit,
                solve_commit=solve_commit,
                base_commit=base_commit,
                source_path=source_path,
                status=TaskStatus.UNSUPPORTED_BUILD_RECIPE,
                reason="source file has no objdiff build unit at the solve revision",
                confidence=confidence,
                evidence=evidence,
            )
        reference_commit = self._find_reference_commit(
            episode, source_path, solve_commit, build.target_object
        )
        if reference_commit is None:
            return self._unresolved(
                episode,
                task_id=task_id,
                split=split,
                fingerprint=fingerprint,
                episode_commit=episode_commit,
                solve_commit=solve_commit,
                base_commit=base_commit,
                source_path=source_path,
                status=TaskStatus.MISSING_BUILD_INPUTS,
                reason=f"no compatible historical {build.target_object} was found",
                confidence=confidence,
                evidence=evidence,
            )

        asm_path = self._asm_path(episode)
        tags = self._tags(episode, build)
        starter = self._safe_starter(episode, starter_source)
        provenance = Provenance(
            episode_commit=episode_commit,
            solve_commit=solve_commit,
            reference_commit=reference_commit,
            base_commit=base_commit,
            source_path=source_path,
            confidence=confidence,
            evidence=tuple(evidence),
        )
        return TaskSpec(
            schema_version=1,
            task_id=task_id,
            project=self.profile.project_id,
            function_name=episode.function_name,
            episode_path=episode_path,
            episode_schema=episode.schema,
            status=TaskStatus.READY,
            split=split,
            assembly_fingerprint=fingerprint,
            instruction_count=episode.instruction_count,
            provenance=provenance,
            build=build,
            asm_path=asm_path,
            starter_source=starter,
            gold_source=episode.gold_source,
            tags=tags,
            metadata={
                "episode_project": episode.project,
                "episode_metadata": episode.metadata,
            },
        )

    @staticmethod
    def _safe_starter(episode: EpisodeRecord, historical_starter: str | None) -> str:
        for source in (historical_starter, episode.initial_source):
            if not source:
                continue
            function, violations = validate_candidate_source(
                source, episode.function_name
            )
            if (
                function is not None
                and not violations
                and not same_function(function, episode.gold_source)
            ):
                return function
        return empty_function_body(episode.gold_source, episode.function_name)

    def _recover_malformed_gold(
        self, episode: EpisodeRecord
    ) -> tuple[EpisodeRecord, list[str]]:
        if find_function_span(
            episode.gold_source, episode.function_name
        ) is not None and not looks_like_comment_fragment(episode.gold_source):
            return episode, []
        if not self.profile.metadata.get("recover_malformed_gold_from_pinned"):
            return episode, []

        raw_preferred = episode.metadata.get("source_path")
        preferred = (
            _project_relative(raw_preferred) if isinstance(raw_preferred, str) else None
        )
        indexed = [str(path) for path in self.index.find(episode.function_name)]
        candidates = list(dict.fromkeys(([preferred] if preferred else []) + indexed))
        compatible: list[tuple[str, str]] = []
        for source_path in candidates:
            text = self.git.show_text(self.profile.default_revision, source_path)
            span = (
                find_function_span(text, episode.function_name)
                if text is not None
                else None
            )
            if span is None:
                continue
            build = self._resolve_build(
                self.profile.default_revision,
                source_path,
                episode.metadata,
                function_name=episode.function_name,
                prefer_metadata=episode.schema == "canonical_v2",
            )
            if build is not None:
                compatible.append((source_path, span.text.rstrip() + "\n"))

        preferred_matches = [item for item in compatible if item[0] == preferred]
        if len(preferred_matches) == 1:
            compatible = preferred_matches
        elif len(compatible) > 1:
            bodies = {body for _, body in compatible}
            if len(bodies) != 1:
                return episode, []
            compatible = compatible[:1]
        if len(compatible) != 1:
            return episode, []

        source_path, gold_source = compatible[0]
        metadata = {
            **episode.metadata,
            "gold_recovered_from_pinned_source": source_path,
        }
        return (
            replace(episode, gold_source=gold_source, metadata=metadata),
            [
                "episode gold was malformed; recovered the target definition "
                f"from pinned source {source_path}"
            ],
        )

    def _find_reference_commit(
        self,
        episode: EpisodeRecord,
        source_path: str,
        solve_commit: str,
        target_object: str,
    ) -> str | None:
        if self._reference_target_status(
            solve_commit, target_object, episode.function_name
        ):
            return solve_commit
        history = reversed(
            self.git.history(target_object, self.profile.default_revision)
        )
        for commit in history:
            if not self.git.is_ancestor(solve_commit, commit):
                continue
            text = self.git.show_text(commit, source_path)
            span = (
                find_function_span(text, episode.function_name)
                if text is not None
                else None
            )
            if (
                span is not None
                and same_function(span.text, episode.gold_source)
                and self._reference_target_status(
                    commit, target_object, episode.function_name
                )
            ):
                return commit
        return None

    @functools.lru_cache(maxsize=8192)
    def _reference_target_status(
        self,
        revision: str,
        target_object: str,
        function_name: str,
    ) -> bool | None:
        """Return whether an existing ELF reference contains the target symbol."""
        data = self.git.show_bytes(revision, target_object)
        if data is None:
            return None
        # Other project profiles may use a non-ELF reference format. Its
        # verifier owns validation; the historical N64 objects are ELF.
        if not data.startswith(b"\x7fELF"):
            return True
        return extract_function_bytes(data, function_name) is not None

    def _source_candidates(
        self, episode: EpisodeRecord, episode_commit: str | None
    ) -> list[str]:
        indexed = [str(path) for path in self.index.find(episode.function_name)]
        preferred: list[str] = []
        raw_path = episode.metadata.get("source_path")
        if isinstance(raw_path, str):
            normalized = _project_relative(raw_path)
            revision = episode_commit or self.profile.default_revision
            if normalized and self.git.exists(revision, normalized):
                preferred.append(normalized)

        segment = episode.metadata.get("segment")
        if isinstance(segment, str):
            matching = [path for path in indexed if segment in Path(path).parts]
            if matching:
                indexed = matching
        return list(dict.fromkeys((*preferred, *sorted(indexed))))

    def _unsupported_entry_point_reason(self, function_name: str) -> str | None:
        values = self.profile.metadata.get("unsupported_entry_points", {})
        if not isinstance(values, dict):
            return None
        reason = values.get(function_name)
        return str(reason) if reason else None

    def _find_solve_commit(
        self,
        episode: EpisodeRecord,
        source_path: str,
        episode_commit: str | None,
        metadata: dict[str, Any],
    ) -> tuple[str | None, str | None, str, list[str]]:
        prefer_metadata = episode.schema == "canonical_v2"
        direct_revisions = (episode_commit,) if episode_commit else ()
        invalid_direct_reference = False
        for revision in direct_revisions:
            text = self.git.show_text(revision, source_path)
            span = (
                find_function_span(text, episode.function_name)
                if text is not None
                else None
            )
            if span is None or not same_function(span.text, episode.gold_source):
                continue
            build = self._resolve_build(
                revision,
                source_path,
                metadata,
                function_name=episode.function_name,
                prefer_metadata=prefer_metadata,
            )
            if build is None:
                continue
            reference_status = self._reference_target_status(
                revision, build.target_object, episode.function_name
            )
            if reference_status is False:
                invalid_direct_reference = True
                continue
            starter_source = None
            parent = self.git.parent(revision)
            if parent is not None:
                parent_text = self.git.show_text(parent, source_path)
                parent_span = (
                    find_function_span(parent_text, episode.function_name)
                    if parent_text is not None
                    else None
                )
                if parent_span is not None and not same_function(
                    parent_span.text, episode.gold_source
                ):
                    starter_source = parent_span.text.rstrip() + "\n"
            evidence = ["gold C and build unit match at the episode revision"]
            if starter_source:
                evidence.append("starter C recovered from the preceding revision")
            elif episode.initial_source:
                evidence.append("starter recovered from episode initial source")
            else:
                evidence.append("no prior C body; fixture synthesizes a scaffold")
            return revision, starter_source, "high", evidence

        # Some episode commits precede a follow-up expected-object refresh or
        # non-matching build-recipe fix. If the checked-in reference is an ELF
        # but omits the target entirely, use the pinned compatible project
        # context rather than auditing against that known-broken intermediate.
        if invalid_direct_reference:
            pinned_replay = self._pinned_replay_context(
                episode,
                source_path,
                metadata,
                prefer_metadata=prefer_metadata,
            )
            if pinned_replay is not None:
                revision, starter, confidence, evidence = pinned_replay
                return (
                    revision,
                    starter,
                    confidence,
                    [
                        "episode revision's reference ELF omitted the target "
                        "symbol",
                        *evidence,
                    ],
                )

        # Episodes are sometimes committed before their source/build-unit landing
        # commit. Search the pinned project history, then use exact C equality to
        # identify the compatible solve era.
        revision = self.profile.default_revision
        history = self.git.history(source_path, revision)
        search_limit = int(self.profile.metadata.get("history_search_limit", 512))
        if search_limit > 0:
            history = history[:search_limit]
        if not history:
            return None, None, "none", []

        # Legacy episodes lack a source revision. Most represent the commit
        # that introduced their exact C body, so Git's pickaxe can reduce a
        # multi-thousand-revision monolith to a handful of candidates. Every
        # hit is still checked by full-function equality and build metadata;
        # the exhaustive bounded walk below remains the correctness fallback.
        for probe in _gold_probes(episode.gold_source):
            for commit in self.git.pickaxe(source_path, probe, revision):
                if commit not in history:
                    continue
                text = self.git.show_text(commit, source_path)
                span = (
                    find_function_span(text, episode.function_name)
                    if text is not None
                    else None
                )
                if span is None or not same_function(span.text, episode.gold_source):
                    continue
                if (
                    self._resolve_build(
                        commit,
                        source_path,
                        metadata,
                        function_name=episode.function_name,
                        prefer_metadata=prefer_metadata,
                    )
                    is None
                ):
                    continue
                index = history.index(commit)
                starter_source = None
                if index + 1 < len(history):
                    previous = self.git.show_text(history[index + 1], source_path)
                    previous_span = (
                        find_function_span(previous, episode.function_name)
                        if previous is not None
                        else None
                    )
                    if previous_span is not None and not same_function(
                        previous_span.text, episode.gold_source
                    ):
                        starter_source = previous_span.text.rstrip() + "\n"
                evidence = ["gold C matches a validated source-introduction commit"]
                if starter_source:
                    evidence.append(
                        "starter C recovered from the preceding source revision"
                    )
                elif episode.initial_source:
                    evidence.append("starter recovered from episode initial source")
                else:
                    evidence.append(
                        "no prior C body; fixture must synthesize a scaffold"
                    )
                return commit, starter_source, "medium", evidence

        pinned_replay = self._pinned_replay_context(
            episode,
            source_path,
            metadata,
            prefer_metadata=prefer_metadata,
        )
        scan_history = history
        if pinned_replay is not None:
            pinned_limit = int(
                self.profile.metadata.get("pinned_replay_history_limit", 32)
            )
            if pinned_limit > 0:
                scan_history = history[:pinned_limit]

        solve_commit: str | None = None
        starter_source: str | None = None
        matched_any = False
        evidence: list[str] = []
        for commit in scan_history:
            text = self.git.show_text(commit, source_path)
            span = (
                find_function_span(text, episode.function_name)
                if text is not None
                else None
            )
            is_gold = span is not None and same_function(span.text, episode.gold_source)
            if is_gold:
                matched_any = True
                if (
                    self._resolve_build(
                        commit,
                        source_path,
                        metadata,
                        function_name=episode.function_name,
                        prefer_metadata=prefer_metadata,
                    )
                    is not None
                ):
                    solve_commit = commit
                continue
            if matched_any:
                starter_source = span.text.rstrip() + "\n" if span is not None else None
                break

        if solve_commit is None:
            if pinned_replay is not None:
                return pinned_replay
            return None, None, "none", []
        evidence.append("gold C matches the function at the solve commit")
        if starter_source:
            evidence.append("starter C recovered from the preceding source revision")
        elif episode.initial_source:
            evidence.append("starter recovered from episode initial source")
        else:
            evidence.append("no prior C body; fixture must synthesize a scaffold")
        return solve_commit, starter_source, "medium", evidence

    def _pinned_replay_context(
        self,
        episode: EpisodeRecord,
        source_path: str,
        metadata: dict[str, Any],
        *,
        prefer_metadata: bool,
    ) -> tuple[str, None, str, list[str]] | None:
        if not self.profile.metadata.get("allow_pinned_replay_fallback"):
            return None
        revision = self.profile.default_revision
        pinned_text = self.git.show_text(revision, source_path)
        pinned_span = (
            find_function_span(pinned_text, episode.function_name)
            if pinned_text is not None
            else None
        )
        gold_span = find_function_span(episode.gold_source, episode.function_name)
        build = self._resolve_build(
            revision,
            source_path,
            metadata,
            function_name=episode.function_name,
            prefer_metadata=prefer_metadata,
        )
        if (
            pinned_span is None
            or gold_span is None
            or build is None
            or not self._reference_target_status(
                revision, build.target_object, episode.function_name
            )
        ):
            return None
        evidence = [
            "pinned source provides a compatible replay build context; "
            "gold exactness requires the release build audit"
        ]
        if episode.initial_source:
            evidence.append("starter recovered from episode initial source")
        else:
            evidence.append("no prior C body; fixture must synthesize a scaffold")
        return revision, None, "low", evidence

    def _resolve_build(
        self,
        revision: str,
        source_path: str,
        metadata: dict[str, Any],
        *,
        function_name: str | None = None,
        prefer_metadata: bool = True,
    ) -> BuildProfile | None:
        units = self._objdiff_units(revision)
        matches = [unit for unit in units if unit[0] == source_path]
        if not matches and function_name is not None:
            indexed_paths = {str(path) for path in self.index.find(function_name)}
            matches = [unit for unit in units if unit[0] in indexed_paths]
        if len(matches) != 1:
            return None
        (
            unit_source_path,
            unit_name,
            target_path,
            base_path,
            scratch_compiler,
            scratch_flags,
        ) = matches[0]
        if prefer_metadata:
            compiler_flags = metadata.get("compiler_flags") or scratch_flags
            compiler = metadata.get("compiler") or scratch_compiler
        else:
            compiler_flags = scratch_flags or metadata.get("compiler_flags")
            compiler = scratch_compiler or metadata.get("compiler")
        return BuildProfile(
            unit_name=unit_name,
            source_path=unit_source_path,
            target_object=target_path,
            base_object=base_path,
            compiler=str(compiler) if compiler else None,
            compiler_flags=str(compiler_flags) if compiler_flags else None,
            object_target=base_path,
        )

    def _objdiff_units(
        self, revision: str
    ) -> tuple[tuple[str, str, str, str, str | None, str | None], ...]:
        object_id = self.git.object_id(revision, self.profile.objdiff_config)
        if object_id is None:
            return ()
        return self._objdiff_units_for_object(object_id)

    @functools.lru_cache(maxsize=64)
    def _objdiff_units_for_object(
        self, object_id: str
    ) -> tuple[tuple[str, str, str, str, str | None, str | None], ...]:
        raw = self.git.show_object_text(object_id)
        if raw is None:
            return ()
        try:
            config = json.loads(raw)
        except json.JSONDecodeError:
            return ()
        units = config.get("units", ())
        if not isinstance(units, list):
            return ()
        normalized = []
        for unit in units:
            if not isinstance(unit, dict):
                continue
            metadata = unit.get("metadata", {})
            scratch = unit.get("scratch", {})
            source_path = metadata.get("source_path")
            name = unit.get("name")
            target = unit.get("target_path")
            base = unit.get("base_path")
            if not all(
                isinstance(value, str) for value in (source_path, name, target, base)
            ):
                continue
            compiler = scratch.get("compiler")
            flags = scratch.get("c_flags")
            normalized.append(
                (
                    source_path,
                    name,
                    target,
                    base,
                    str(compiler) if compiler else None,
                    str(flags) if flags else None,
                )
            )
        return tuple(normalized)

    def _asm_path(self, episode: EpisodeRecord) -> str | None:
        raw = episode.metadata.get("asm_path")
        if isinstance(raw, str):
            normalized = _project_relative(raw)
            if normalized and (self.root / normalized).is_file():
                return normalized
        matches: list[Path] = []
        for root in self.profile.asm_roots:
            matches.extend((self.root / root).rglob(f"{episode.function_name}.s"))
        if len(matches) == 1:
            return str(matches[0].relative_to(self.root))
        return None

    def _task_id(self, episode: EpisodeRecord) -> str:
        segment = episode.metadata.get("segment")
        if not isinstance(segment, str) or not segment:
            segment = "unknown"
        return f"{self.profile.project_id}/{segment}/{episode.function_name}"

    @staticmethod
    def _tags(episode: EpisodeRecord, build: BuildProfile) -> tuple[str, ...]:
        values = [episode.schema]
        combined = f"{build.compiler or ''} {build.compiler_flags or ''}".lower()
        for value in ("ido5.3", "ido7.1", "-o0", "-o1", "-o2", "-g3"):
            if value in combined.replace(" ", ""):
                values.append(value.lstrip("-"))
        if episode.instruction_count <= 12:
            values.append("wrapper")
        elif episode.instruction_count >= 150:
            values.append("large")
        return tuple(dict.fromkeys(values))

    def _unresolved(
        self,
        episode: EpisodeRecord,
        *,
        task_id: str,
        split: str,
        fingerprint: str,
        status: TaskStatus,
        reason: str,
        episode_commit: str | None = None,
        solve_commit: str | None = None,
        base_commit: str | None = None,
        source_path: str | None = None,
        confidence: str = "none",
        evidence: list[str] | None = None,
    ) -> TaskSpec:
        return TaskSpec(
            schema_version=1,
            task_id=task_id,
            project=self.profile.project_id,
            function_name=episode.function_name,
            episode_path=str(episode.path.relative_to(self.root)),
            episode_schema=episode.schema,
            status=status,
            split=split,
            assembly_fingerprint=fingerprint,
            instruction_count=episode.instruction_count,
            provenance=Provenance(
                episode_commit=episode_commit,
                solve_commit=solve_commit,
                reference_commit=solve_commit,
                base_commit=base_commit,
                source_path=source_path,
                confidence=confidence,
                evidence=tuple(evidence or ()),
            ),
            asm_path=self._asm_path(episode),
            gold_source=episode.gold_source,
            reason=reason,
            metadata={"episode_metadata": episode.metadata},
        )


def _project_relative(value: str) -> str | None:
    path = Path(value)
    if path.is_absolute():
        return None
    parts = path.parts
    for marker in ("src", "asm", "episodes", "expected"):
        if marker in parts:
            return str(Path(*parts[parts.index(marker) :]))
    if ".." in parts:
        return None
    return str(path)


def _gold_probes(source: str) -> tuple[str, ...]:
    """Choose exact, distinctive C lines for a conservative Git pickaxe."""
    lines = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if (
            len(line) < 12
            or line in {"{", "}"}
            or line.startswith(("//", "/*", "*", "#"))
        ):
            continue
        lines.append(line[:240])
    return tuple(dict.fromkeys(sorted(lines, key=len, reverse=True)[:3]))
