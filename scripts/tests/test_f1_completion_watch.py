"""Offline tests: no secret, network, or live subscription is needed."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "f1-completion-watch.py"
SPEC = importlib.util.spec_from_file_location("f1_completion_watch", MODULE)
assert SPEC is not None and SPEC.loader is not None
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
SHA = "a" * 64
ACCURACY = "b" * 64


def ready_sample():
    recent = (NOW - timedelta(seconds=12)).isoformat()
    status = {
        "season": 2026,
        "raceId": "singapore",
        "feedState": "connected",
        "mqttTlsVersion": "TLSv1.3",
        "evidenceState": "fresh-checkpoint",
        "sourceType": "licensed-live",
        "inferenceState": "production-qualified",
        "qualifiedForProduction": True,
        "modelPromoted": True,
        "lastMessageAt": recent,
        "lastCheckpointAt": recent,
        "lap": 25,
        "totalLaps": 62,
        "checkpointSha256": SHA,
    }
    trace = {
        "recordSha256": SHA,
        "checkpoint": {
            "sourceType": "licensed-live",
            "provider": "openf1",
            "season": 2026,
            "raceId": "singapore",
            "lap": 25,
            "totalLaps": 62,
            "rightsEvidence": "approved-external-reference",
            "observedAt": recent,
        },
    }
    scenario = {
        "checkpointSha256": SHA,
        "sourceType": "licensed-live",
        "status": "scenario",
        "modelReady": True,
        "scenario": {"drivers": [{"driverNumber": 16}]},
    }
    accuracy = {
        "researchOnly": False,
        "modelPromotionAllowed": True,
        "reportSha256": ACCURACY,
    }
    return status, trace, scenario, accuracy


class CompletionCriteria(unittest.TestCase):
    def check(self, status, trace, scenario, accuracy):
        return watch.verify_qualified_live(
            status, trace, scenario, accuracy, year=2026, race="singapore", now=NOW
        )

    def test_accepts_only_a_fully_qualified_evidence_bound_live_checkpoint(self):
        self.assertIsNone(self.check(*ready_sample()))

    def test_refuses_mqtt_disconnect(self):
        status, trace, scenario, accuracy = ready_sample()
        status["feedState"] = "not-configured"
        with self.assertRaisesRegex(watch.NotReady, "not reporting a connected"):
            self.check(status, trace, scenario, accuracy)

    def test_refuses_unverified_tls(self):
        status, trace, scenario, accuracy = ready_sample()
        status["mqttTlsVersion"] = "TLSv1.2"
        with self.assertRaisesRegex(watch.NotReady, "TLS 1.3"):
            self.check(status, trace, scenario, accuracy)

    def test_refuses_replay_despite_connected_heartbeat(self):
        status, trace, scenario, accuracy = ready_sample()
        status["sourceType"] = "historical-archive"
        with self.assertRaisesRegex(watch.NotReady, "licensed-live"):
            self.check(status, trace, scenario, accuracy)

    def test_refuses_research_simulation_as_production_inference(self):
        status, trace, scenario, accuracy = ready_sample()
        status["inferenceState"] = "conditional-research"
        status["modelPromoted"] = False
        with self.assertRaisesRegex(watch.NotReady, "experimental"):
            self.check(status, trace, scenario, accuracy)

    def test_refuses_stale_checkpoint(self):
        status, trace, scenario, accuracy = ready_sample()
        status["lastCheckpointAt"] = (NOW - timedelta(minutes=5)).isoformat()
        with self.assertRaisesRegex(watch.NotReady, "stale"):
            self.check(status, trace, scenario, accuracy)

    def test_refuses_unbound_scenario(self):
        status, trace, scenario, accuracy = ready_sample()
        scenario["checkpointSha256"] = "f" * 64
        with self.assertRaisesRegex(watch.NotReady, "not bound"):
            self.check(status, trace, scenario, accuracy)

    def test_refuses_unqualified_accuracy(self):
        status, trace, scenario, accuracy = ready_sample()
        accuracy["modelPromotionAllowed"] = False
        with self.assertRaisesRegex(watch.NotReady, "calibration"):
            self.check(status, trace, scenario, accuracy)

    def test_refuses_no_rights_reference(self):
        status, trace, scenario, accuracy = ready_sample()
        trace["checkpoint"]["rightsEvidence"] = None
        with self.assertRaisesRegex(watch.NotReady, "identity"):
            self.check(status, trace, scenario, accuracy)

    def test_refuses_wrong_race(self):
        status, trace, scenario, accuracy = ready_sample()
        trace["checkpoint"]["raceId"] = "monaco"
        with self.assertRaisesRegex(watch.NotReady, "identity"):
            self.check(status, trace, scenario, accuracy)

    def test_parses_production_js_asset(self):
        parser = watch.AssetScripts()
        parser.feed('<div id="root"></div><script type="module" src="/assets/index-Ab123.js"></script>')
        self.assertEqual(parser.js_paths, ["/assets/index-Ab123.js"])

    def test_does_not_accept_external_js_asset(self):
        parser = watch.AssetScripts()
        parser.feed('<script src="https://example.com/asset.js"></script>')
        self.assertEqual(parser.js_paths, [])


if __name__ == "__main__":
    unittest.main()
