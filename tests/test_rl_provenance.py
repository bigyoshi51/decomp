from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from decomp.rl.episodes import load_episode
from decomp.rl.fixtures import FixtureBuilder, apply_candidate
from decomp.rl.models import ProjectProfile, TaskStatus
from decomp.rl.provenance import ProvenanceResolver


class ProvenanceFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._git("init", "-q")
        self._git("config", "user.email", "rl-tests@example.invalid")
        self._git("config", "user.name", "RL Tests")
        for directory in (
            "src",
            "asm/nonmatchings/unit",
            "episodes",
            "expected/src",
            "scripts",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "scripts/build-helper.py").write_text("historical helper\n")
        (self.root / "Makefile").write_text("all:\n\t@true\n")
        (self.root / "objdiff.json").write_text(
            json.dumps(
                {
                    "units": [
                        {
                            "name": "src/unit",
                            "target_path": "expected/src/unit.c.o",
                            "base_path": "build/non_matching/src/unit.c.o",
                            "metadata": {"source_path": "src/unit.c"},
                            "scratch": {
                                "compiler": "ido7.1",
                                "c_flags": "-O2",
                            },
                        }
                    ]
                }
            )
        )
        (self.root / "src/unit.c").write_text("void target(int x) {\n    (void)x;\n}\n")
        (self.root / "asm/nonmatchings/unit/target.s").write_text(
            "glabel target\n/* 0 */ jr $ra\n/* 4 */ nop\n"
        )
        (self.root / "expected/src/unit.c.o").write_bytes(b"reference-object")
        self._commit("base")
        self.base = self._git("rev-parse", "HEAD").strip()

        gold = "void target(int x) {\n    if (x) return;\n}\n"
        (self.root / "src/unit.c").write_text(
            "/* target solved with a branch */\n" + gold
        )
        (self.root / "src/duplicate.c").write_text(
            "/* target exact duplicate */\n" + gold
        )
        (self.root / "episodes/target.json").write_text(
            json.dumps(
                {
                    "function_name": "target",
                    "project": "fixture",
                    "steps": [],
                    "outcome": "match",
                    "final_match_percent": 100.0,
                    "final_source": gold,
                    "instruction_count": 2,
                    "metadata": {
                        "source_path": "src/unit.c",
                        "asm_path": "asm/nonmatchings/unit/target.s",
                        "segment": "unit",
                    },
                }
            )
        )
        self._commit("solve target")
        self.solve = self._git("rev-parse", "HEAD").strip()
        (self.root / "scripts/build-helper.py").write_text("pinned verifier helper\n")
        self._commit("harden verifier helper")
        self.head = self._git("rev-parse", "HEAD").strip()
        self.profile = ProjectProfile(
            project_id="fixture",
            repo_url="https://example.invalid/fixture.git",
            default_revision=self.head,
            metadata={"fixture_support_files": ["scripts/build-helper.py"]},
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_resolves_solve_and_redacts_fixture(self) -> None:
        episode = load_episode(
            self.root / "episodes/target.json", project_root=self.root
        )
        task = ProvenanceResolver(self.root, self.profile).resolve(episode)
        self.assertEqual(task.status, TaskStatus.READY)
        self.assertEqual(task.provenance.solve_commit, self.solve)
        self.assertEqual(task.provenance.base_commit, self.base)
        self.assertIn("(void)x", task.starter_source or "")

        destination = self.root / "prepared"
        bundle = FixtureBuilder(self.root, self.profile).materialize(task, destination)
        prepared = (destination / "src/unit.c").read_text()
        self.assertIn("(void)x", prepared)
        self.assertNotIn("if (x)", prepared)
        self.assertNotIn("target solved", prepared)
        self.assertIn("Target-function notes redacted", prepared)
        duplicate = (destination / "src/duplicate.c").read_text()
        self.assertNotIn("if (x)", duplicate)
        self.assertNotIn("target exact duplicate", duplicate)
        self.assertIn("void target(int x)", duplicate)
        self.assertIn("decomp_rl_relocation_probe();", duplicate)
        apply_candidate(
            destination,
            task,
            task.gold_source or "",
            profile=self.profile,
        )
        self.assertIn(
            "if (x) return;",
            (destination / "src/unit.c").read_text(),
        )
        self.assertIn(
            "if (x) return;",
            (destination / "src/duplicate.c").read_text(),
        )
        self.assertFalse((destination / ".git").exists())
        self.assertFalse((destination / "episodes").exists())
        self.assertFalse((destination / "expected").exists())
        self.assertEqual(
            (destination / "scripts/build-helper.py").read_text(),
            "pinned verifier helper\n",
        )
        self.assertEqual(bundle.reference_object, b"reference-object")

    def _commit(self, message: str) -> None:
        self._git("add", ".")
        self._git("commit", "-qm", message)

    def _git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)


if __name__ == "__main__":
    unittest.main()
