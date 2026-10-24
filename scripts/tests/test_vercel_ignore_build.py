"""Bounded offline tests for Vercel's ignored-build exit-code contract."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "vercel-ignore-build.sh"


class VercelIgnoredBuildContract(unittest.TestCase):
    def run_guard(self, branch: str | None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("VERCEL_GIT_COMMIT_REF", None)
        if branch is not None:
            env["VERCEL_GIT_COMMIT_REF"] = branch
        return subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, env=env)

    def test_syntax(self) -> None:
        self.assertEqual(
            subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True).returncode,
            0,
        )

    def test_bot_dependency_branches_are_skipped_without_exposing_secrets(self) -> None:
        for name in (
            "dependabot/github_actions/github/codeql-action/init-4.39.1",
            "dependabot/npm_and_yarn/web/react-19.3.1",
            "renovate/patch-updates",
        ):
            with self.subTest(name=name):
                result = self.run_guard(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("GitHub CI", result.stdout)

    def test_reviewed_main_and_feature_branches_continue_to_build(self) -> None:
        for name in ("main", "feat/prerace-prediction-flow", "security/tls13-stack"):
            with self.subTest(name=name):
                self.assertEqual(self.run_guard(name).returncode, 1)

    def test_missing_branch_does_not_accidentally_publish(self) -> None:
        result = self.run_guard(None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("unavailable", result.stdout)


if __name__ == "__main__":
    unittest.main()
