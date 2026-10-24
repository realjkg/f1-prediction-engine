"""Offline tests for scripts/check-vercel-deployments.py (no network)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check-vercel-deployments.py"
spec = importlib.util.spec_from_file_location("check_vercel_deployments", SCRIPT)
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check  # dataclasses resolve their module by name
spec.loader.exec_module(check)

EXPECTED = {"f1-pitwall-demo": {"framework": "container"}}


def status(context: str, state: str, url: str = "", description: str = "") -> dict:
    return {"context": context, "state": state, "target_url": url, "description": description}


class LatestStatuses(unittest.TestCase):
    def test_keeps_newest_status_per_project_and_ignores_other_contexts(self) -> None:
        raw = [
            status("Vercel – f1-pitwall-demo", "success"),
            status("Vercel – f1-pitwall-demo", "pending"),
            status("CodeQL", "failure"),
            status("Vercel - f1-prediction-engine-xcif", "failure"),
        ]
        statuses = check.latest_vercel_statuses(raw)
        self.assertEqual([(s.project, s.state) for s in statuses],
                         [("f1-pitwall-demo", "success"), ("f1-prediction-engine-xcif", "failure")])

    def test_deployment_id_from_description_or_target_url(self) -> None:
        from_text = check.Status("p", "failure", "run: npx vercel inspect dpl_ABC123xyz --logs", "")
        from_url = check.Status("p", "failure", "", "https://vercel.com/team/p/BKfyL5uuxfi6MEBHMWGpqrXrnGJg")
        self.assertEqual(check.deployment_id(from_text), "dpl_ABC123xyz")
        self.assertEqual(check.deployment_id(from_url), "dpl_BKfyL5uuxfi6MEBHMWGpqrXrnGJg")


class Classify(unittest.TestCase):
    def statuses(self, *pairs: tuple[str, str]) -> list:
        return [check.Status(project, state, "", f"https://vercel.com/t/{project}/x") for project, state in pairs]

    def test_all_expected_and_green_has_no_findings(self) -> None:
        report = check.classify(self.statuses(("f1-pitwall-demo", "success")), EXPECTED)
        self.assertEqual(report.findings, [])
        self.assertFalse(report.failed)

    def test_failing_unexpected_project_is_an_error_with_explanation(self) -> None:
        report = check.classify(
            self.statuses(("f1-pitwall-demo", "success"), ("f1-prediction-engine-xcif", "failure")),
            EXPECTED,
            {"f1-prediction-engine-xcif": ("FASTAPI_ENTRYPOINT_NOT_FOUND", "No FastAPI entrypoint found.")},
        )
        self.assertTrue(report.failed)
        finding = report.findings[0]
        self.assertEqual(finding.level, "error")
        self.assertIn("unexpected", finding.message)
        self.assertIn("FASTAPI_ENTRYPOINT_NOT_FOUND", finding.detail)
        self.assertIn("Dockerfile.vercel", finding.detail)

    def test_green_unexpected_project_is_only_a_warning(self) -> None:
        report = check.classify(
            self.statuses(("f1-pitwall-demo", "success"), ("f1-prediction-engine-k469", "success")),
            EXPECTED,
        )
        self.assertFalse(report.failed)
        self.assertEqual([f.level for f in report.findings], ["warning"])

    def test_expected_failure_pending_and_missing_are_reported(self) -> None:
        failed = check.classify(self.statuses(("f1-pitwall-demo", "failure")), EXPECTED)
        self.assertEqual(failed.findings[0].message, "expected deployment failed")
        pending = check.classify(self.statuses(("f1-pitwall-demo", "pending")), EXPECTED)
        self.assertTrue(pending.failed)
        missing = check.classify([], EXPECTED)
        self.assertFalse(missing.failed)
        self.assertIn("did not report", missing.findings[0].message)

    def test_rendered_summary_lists_every_project(self) -> None:
        report = check.classify(
            self.statuses(("f1-pitwall-demo", "success"), ("f1-prediction-engine-qriu", "failure")),
            EXPECTED,
        )
        text = check.render(report, "60754b54fc3a")
        self.assertIn("| f1-prediction-engine-qriu | failure |", text)
        self.assertIn("**ERROR**", text)


class Manifest(unittest.TestCase):
    def test_manifest_lists_the_container_demo_and_its_dockerfile_exists(self) -> None:
        import json

        manifest = json.loads(check.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        demo = manifest["projects"]["f1-pitwall-demo"]
        self.assertEqual(demo["framework"], "container")
        self.assertTrue((check.ROOT / demo["dockerfile"]).is_file())


if __name__ == "__main__":
    unittest.main()
