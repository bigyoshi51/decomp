from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from decomp.rl.audit import (
    AuditStateError,
    merge_audits,
    ordered_results,
    prepare_resume,
    select_shard,
)
from decomp.rl.episodes import EpisodeError, load_episode
from decomp.rl.fixtures import FixtureBundle
from decomp.rl.manifest import read_manifest, write_manifest
from decomp.rl.models import ProjectProfile, Provenance, TaskSpec, TaskStatus
from decomp.rl.policy import validate_candidate_source
from decomp.rl.reward import improvement_reward
from decomp.rl.source import (
    empty_function_body,
    find_function_span,
    looks_like_comment_fragment,
    nonexact_function_body,
    relocation_scaffold_function_body,
    replace_function,
    same_function,
)
from decomp.rl.splits import assembly_fingerprint, deterministic_split
from decomp.rl.verifier import (
    PrebuiltVerifier,
    extract_function_bytes,
    function_bytes_equal,
)


class SourceTests(unittest.TestCase):
    def test_function_parser_ignores_comment_pseudocode(self) -> None:
        source = """
/* void target(int x) { fake(); } */
static void helper(void) {}

void target(int x) {
    const char *brace = "}";
    if (x) { helper(); }
}
"""
        span = find_function_span(source, "target")
        self.assertIsNotNone(span)
        assert span is not None
        self.assertTrue(span.text.startswith("void target"))
        self.assertIn("if (x)", span.text)

        multiline = """
/* analysis:
void only_in_comment(void) {
    fake();
}
*/
void real(void) {}
"""
        self.assertIsNone(find_function_span(multiline, "only_in_comment"))

    def test_replace_changes_only_target(self) -> None:
        source = "void a(void) {}\nvoid b(void) { a(); }\n"
        replaced = replace_function(source, "a", "void a(void) { b(); }\n")
        self.assertIn("void a(void) { b(); }", replaced)
        self.assertIn("void b(void) { a(); }", replaced)
        self.assertTrue(same_function("void a(void){b();}", "void a(void) { b(); }"))

    def test_empty_body_preserves_signature(self) -> None:
        source = "static int target(const char *value) { return value != 0; }\n"
        self.assertEqual(
            empty_function_body(source, "target"),
            "static int target(const char *value) {\n}\n",
        )

        nonexact = nonexact_function_body("void target(void) {}", "target")
        self.assertIn("volatile int decomp_rl_probe", nonexact)
        self.assertFalse(same_function(nonexact, "void target(void) {}"))

        relocating = relocation_scaffold_function_body(source, "target")
        self.assertIn("extern void decomp_rl_relocation_probe(void);", relocating)
        self.assertIn("decomp_rl_relocation_probe();", relocating)
        self.assertIn("static int target(const char *value)", relocating)

    def test_parser_supports_implicit_int_and_old_style_parameters(self) -> None:
        source = "func_00000000() {\n}\n"
        span = find_function_span(source, "func_00000000")
        self.assertIsNotNone(span)
        self.assertEqual(span.text if span else None, source.rstrip())

        old_style = "int target(value)\nint value;\n{\n return value;\n}\n"
        span = find_function_span(old_style, "target")
        self.assertIsNotNone(span)
        self.assertIn("return value", span.text if span else "")

    def test_detects_bare_doc_comment_fragment(self) -> None:
        malformed = """void target(void) {
 *       if (ready) return;
 *       return;
 *   }
"""
        self.assertTrue(looks_like_comment_fragment(malformed))
        self.assertFalse(
            looks_like_comment_fragment(
                "void target(void) {\n /*\n  *       if (ready) return;\n  */\n}\n"
            )
        )


class EpisodeTests(unittest.TestCase):
    def test_loads_canonical_and_rejects_non_exact(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            episodes = root / "episodes"
            episodes.mkdir()
            path = episodes / "target.json"
            data = {
                "function_name": "target",
                "project": "fixture",
                "steps": [],
                "outcome": "match",
                "final_match_percent": 100.0,
                "final_source": "void target(void) {}\n",
                "instruction_count": 2,
                "metadata": {"source_path": "src/unit.c"},
            }
            path.write_text(json.dumps(data))
            episode = load_episode(path, project_root=root)
            self.assertEqual(episode.schema, "canonical_v2")
            self.assertEqual(episode.gold_source, "void target(void) {}\n")
            data["final_match_percent"] = 99.0
            path.write_text(json.dumps(data))
            with self.assertRaises(EpisodeError):
                load_episode(path, project_root=root)

    def test_loads_compact_legacy_exact_episode(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            episodes = root / "episodes"
            asm = root / "asm/nonmatchings/unit"
            episodes.mkdir()
            asm.mkdir(parents=True)
            (asm / "target.s").write_text("/* 0 */ jr $ra\n/* 4 */ nop\n")
            path = episodes / "target.json"
            path.write_text(
                json.dumps(
                    {
                        "function_name": "target",
                        "matched": True,
                        "segment": "unit",
                        "final_c": "void target(void) {}\n",
                    }
                )
            )
            episode = load_episode(path, project_root=root)
            self.assertEqual(episode.schema, "legacy_v1")
            self.assertEqual(episode.instruction_count, 2)


class SplitRewardPolicyTests(unittest.TestCase):
    def test_assembly_twins_share_split(self) -> None:
        left = "/* 80000000 */ addiu $sp, $sp, -0x20\n/* x */ jr $ra"
        right = "/* 90000000 */ addiu $sp, $sp, -0x30\n/* y */ jr $ra"
        left_key = assembly_fingerprint(left)
        right_key = assembly_fingerprint(right)
        self.assertEqual(left_key, right_key)
        self.assertEqual(deterministic_split(left_key), deterministic_split(right_key))

    def test_reward_reserves_one_for_exact(self) -> None:
        self.assertEqual(improvement_reward(100, 40, exact=True), 1.0)
        self.assertAlmostEqual(improvement_reward(70, 40), 0.45)
        self.assertEqual(improvement_reward(30, 40), 0.0)
        self.assertEqual(improvement_reward(90, 40, compiled=False), 0.0)

    def test_policy_blocks_assembly_escape_hatches(self) -> None:
        candidate, violations = validate_candidate_source(
            'void target(void) { __asm__("nop"); }', "target"
        )
        self.assertIsNotNone(candidate)
        self.assertIn("inline_asm", {item.code for item in violations})

        _, violations = validate_candidate_source(
            'void target(void) {\n#include "expected/unit.o"\n}', "target"
        )
        self.assertIn("preprocessor", {item.code for item in violations})

    def test_task_round_trip(self) -> None:
        task = TaskSpec(
            schema_version=1,
            task_id="p/s/f",
            project="p",
            function_name="f",
            episode_path="episodes/f.json",
            episode_schema="canonical_v2",
            status=TaskStatus.READY,
            split="train",
            assembly_fingerprint="abc",
            instruction_count=2,
            provenance=Provenance(solve_commit="deadbeef"),
            tags=("small",),
        )
        serialized = json.loads(json.dumps(task.to_dict()))
        self.assertEqual(TaskSpec.from_dict(serialized), task)


class AuditStateTests(unittest.TestCase):
    def test_shards_are_stable_disjoint_and_complete(self) -> None:
        tasks = [_task(index) for index in range(40)]
        shards = [
            select_shard(tasks, shard_count=4, shard_index=index) for index in range(4)
        ]
        task_ids = [task.task_id for shard in shards for task in shard]
        self.assertEqual(len(task_ids), len(set(task_ids)))
        self.assertEqual(set(task_ids), {task.task_id for task in tasks})
        self.assertEqual(
            shards,
            [
                select_shard(tasks, shard_count=4, shard_index=index)
                for index in range(4)
            ],
        )

    def test_resume_retains_checkpoint_and_retries_selected_status(self) -> None:
        tasks = [_task(index) for index in range(3)]
        failed = replace(tasks[0], status=TaskStatus.GOLD_NOT_REPRODUCIBLE)
        ready = replace(tasks[1], initial_match_percent=12.5)
        retained, pending = prepare_resume(
            tasks,
            [failed, ready],
            retry_statuses=frozenset({TaskStatus.GOLD_NOT_REPRODUCIBLE}),
        )
        self.assertEqual(set(retained), {tasks[0].task_id, tasks[1].task_id})
        self.assertEqual(
            [task.task_id for task in pending],
            [tasks[0].task_id, tasks[2].task_id],
        )
        self.assertEqual(
            ordered_results(tasks, retained),
            [failed, ready],
        )

    def test_merge_rejects_missing_duplicate_and_stale_rows(self) -> None:
        tasks = [_task(index) for index in range(4)]
        audited = [
            replace(task, initial_match_percent=float(index))
            for index, task in enumerate(tasks)
        ]
        merged = merge_audits(tasks, (audited[:2], audited[2:]))
        self.assertEqual(merged, audited)
        with self.assertRaisesRegex(AuditStateError, "incomplete"):
            merge_audits(tasks, (audited[:2],))
        with self.assertRaisesRegex(AuditStateError, "duplicate"):
            merge_audits(tasks, (audited, audited[:1]))
        stale = replace(audited[0], episode_path="episodes/stale.json")
        with self.assertRaisesRegex(AuditStateError, "stale audit identity"):
            merge_audits(tasks, ([stale], audited[1:]))
        with self.assertRaisesRegex(AuditStateError, "no measured starter"):
            merge_audits(tasks, (tasks,))

    def test_manifest_write_is_atomic_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            output = root / "tasks.jsonl"
            tasks = [_task(index) for index in range(3)]
            write_manifest(tasks, output)
            self.assertEqual(read_manifest(output), tasks)
            self.assertEqual(list(root.glob(".tasks.jsonl.*.tmp")), [])


class VerifierLayoutTests(unittest.TestCase):
    def test_supports_project_local_and_historical_shared_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            base = Path(raw_tmp)
            source_root = base / "support"
            (source_root / "ido-static-recomp").mkdir(parents=True)
            (source_root / "asm-processor").mkdir()
            project = base / "sandbox" / "projects" / "fixture"
            project.mkdir(parents=True)
            verifier = PrebuiltVerifier(
                ProjectProfile(
                    project_id="fixture",
                    repo_url="https://example.invalid/fixture.git",
                    default_revision="deadbeef",
                ),
                FixtureBundle("task", b"", b"", ""),
                toolchain_source=source_root / "ido-static-recomp",
            )
            verifier._attach_toolchain(project)
            for tool_root in (project / "tools", base / "sandbox" / "tools"):
                self.assertTrue((tool_root / "ido-static-recomp").is_symlink())
                self.assertTrue((tool_root / "asm-processor").is_symlink())

    @unittest.skipUnless(shutil.which("cc"), "host C compiler is unavailable")
    def test_exact_gate_compares_raw_elf_function_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            objects = []
            for index, value in enumerate((1, 2)):
                source = root / f"candidate-{index}.c"
                output = root / f"candidate-{index}.o"
                source.write_text(f"int target(void) {{ return {value}; }}\n")
                subprocess.run(["cc", "-c", str(source), "-o", str(output)], check=True)
                objects.append(output.read_bytes())
            self.assertIsNotNone(extract_function_bytes(objects[0], "target"))
            self.assertTrue(function_bytes_equal(objects[0], objects[0], "target"))
            self.assertFalse(function_bytes_equal(objects[0], objects[1], "target"))


def _task(index: int) -> TaskSpec:
    name = f"func_{index:08X}"
    return TaskSpec(
        schema_version=1,
        task_id=f"fixture/unit/{name}",
        project="fixture",
        function_name=name,
        episode_path=f"episodes/{name}.json",
        episode_schema="canonical_v2",
        status=TaskStatus.READY,
        split="train",
        assembly_fingerprint=f"shape-{index}",
        instruction_count=index + 1,
        provenance=Provenance(solve_commit=f"{index:040x}"),
    )


if __name__ == "__main__":
    unittest.main()
