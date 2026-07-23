from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ENVIRONMENT_ROOT = Path(__file__).parents[1] / "environments" / "n64_decomp_v1"
sys.path.insert(0, str(ENVIRONMENT_ROOT))
try:
    import n64_decomp_v1 as environment
except ModuleNotFoundError as exc:
    if exc.name != "verifiers":
        raise
    environment = None
finally:
    sys.path.remove(str(ENVIRONMENT_ROOT))


@unittest.skipIf(environment is None, "the optional Verifiers environment is absent")
class SubmitCandidateToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_bare_tool_name_and_dictionary_result_state(self) -> None:
        assert environment is not None
        tool = environment.SubmitCandidateTools(
            environment.SubmitCandidateConfig(verifier_image="test-image")
        )
        self.assertEqual(tool.server_name, "")
        tool.task_data = environment.N64DecompTaskData(
            manifest_row={
                "schema_version": 1,
                "task_id": "fixture/target",
                "project": "fixture",
                "function_name": "target",
                "episode_path": "episodes/target.json",
                "episode_schema": "canonical_v2",
                "status": "ready",
                "split": "test",
                "assembly_fingerprint": "fixture",
                "instruction_count": 1,
                "provenance": {},
            },
            profile_data={
                "project_id": "fixture",
                "repo_url": "https://example.invalid/fixture.git",
                "default_revision": "0" * 40,
            },
            project_root="/tmp/fixture",
            mode="submit_candidate",
        )
        tool.bundle = object()
        results = [
            {
                "compiled": True,
                "exact": False,
                "match_percent": 7.0,
                "reward": 0.0,
                "failure_kind": None,
                "diagnostic": "",
            },
            {
                "compiled": True,
                "exact": False,
                "match_percent": 5.0,
                "reward": 0.0,
                "failure_kind": None,
                "diagnostic": "",
            },
            {
                "compiled": True,
                "exact": True,
                "match_percent": 100.0,
                "reward": 1.0,
                "failure_kind": None,
                "diagnostic": "",
            },
        ]
        verifier = AsyncMock(side_effect=results)
        with patch.object(environment, "_verify_in_trusted_container", verifier):
            first = await tool.submit_candidate("void target(void) {}")
            second = await tool.submit_candidate("void target(void) {}")
            exact = await tool.submit_candidate("void target(void) {}")

        self.assertEqual(first["best_match_percent"], 7.0)
        self.assertEqual(second["best_match_percent"], 7.0)
        self.assertEqual(exact["best_match_percent"], 100.0)
        self.assertEqual(exact["best_reward"], 1.0)
        self.assertEqual(tool.state.attempts, 3)
        self.assertTrue(tool.state.best_exact)
