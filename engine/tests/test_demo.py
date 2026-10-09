"""Demo orchestration tests — determinism gate, record order, typed failures.

Spec row "Demo scenario": two full demo runs produce identical prediction +
backtest records. The gate runs the pipeline twice in-process against the
predictable fixture and compares ledger bytes — no wall-clock enters the
stored records (generation timestamps are the dataset's pinned provenance
values), so byte equality is the honest form of the test. The narrate stage
is exercised on both sides of its typed degrade path via a patched brief
generator, and a tampered snapshot must refuse the run through the
ingestion layer's own typed error family.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from f1engine.brief import FIXTURE_BANNER, BriefConfig, BriefError
from f1engine.evidence import verify_chain
from f1engine.ingestion import DataSnapshotMismatch, PinnedDataset, load_snapshot
from f1engine.observability import events as bus_events


def _records(ledger_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in ledger_path.read_text().splitlines()]


@pytest.fixture()
def fixture_dataset(predictable_snapshot: Path) -> PinnedDataset:
    return load_snapshot(predictable_snapshot)


class TestDeterminismGate:
    def test_two_runs_produce_byte_identical_ledgers(
        self,
        demo: ModuleType,
        predictable_snapshot: Path,
        tmp_path: Path,
    ) -> None:
        first = tmp_path / "first.jsonl"
        second = tmp_path / "second.jsonl"
        demo.run_demo(predictable_snapshot, first, 2021, brief=False)
        demo.run_demo(predictable_snapshot, second, 2021, brief=False)
        assert first.read_bytes() == second.read_bytes()
        verify_chain(first)  # identical AND internally consistent

    def test_second_run_into_the_same_path_reproduces_the_first(
        self,
        demo: ModuleType,
        predictable_snapshot: Path,
        tmp_path: Path,
    ) -> None:
        # The demo regenerates its evidence: run N's ledger is a pure
        # function of the snapshot, so re-running the demo at the same path
        # yields the same bytes as the first run — not an accretion.
        ledger = tmp_path / "ledger.jsonl"
        demo.run_demo(predictable_snapshot, ledger, 2021, brief=False)
        first_pass = ledger.read_bytes()
        demo.run_demo(predictable_snapshot, ledger, 2021, brief=False)
        assert ledger.read_bytes() == first_pass
        verify_chain(ledger)

    def test_stored_records_carry_no_wall_clock(
        self,
        demo: ModuleType,
        predictable_snapshot: Path,
        tmp_path: Path,
        fixture_dataset: PinnedDataset,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        demo.run_demo(predictable_snapshot, ledger, 2021, brief=False)
        for record in _records(ledger):
            if "generatedAt" in record:
                # The only timestamp in evidence is the dataset's pinned
                # provenance value — identical for every run of this snapshot.
                assert record["generatedAt"] == fixture_dataset.provenance.generatedAt
            assert "durationMs" not in json.dumps(record)


class TestDemoRecordSequence:
    def test_predictions_then_backtest_chain_verifies(
        self,
        demo: ModuleType,
        predictable_snapshot: Path,
        tmp_path: Path,
    ) -> None:
        ledger = tmp_path / "ledger.jsonl"
        result = demo.run_demo(predictable_snapshot, ledger, 2021, brief=False)
        records = _records(ledger)
        assert [record["recordType"] for record in records] == [
            "prediction",
            "prediction",
            "backtest",
        ]
        assert records[-1]["season"] == 2021
        assert records[-1]["roundsScored"] == len(result.rounds)
        verify_chain(ledger)

    def test_cli_no_serve_smoke(
        self,
        demo: ModuleType,
        predictable_snapshot: Path,
        tmp_path: Path,
    ) -> None:
        # main() with --no-serve runs the full pipeline and exits 0.
        ledger = tmp_path / "cli-ledger.jsonl"
        code = demo.main(
            [
                "--data-dir",
                str(predictable_snapshot),
                "--ledger",
                str(ledger),
                "--season",
                "2021",
                "--no-serve",
                "--no-brief",
            ]
        )
        assert code == 0
        assert len(_records(ledger)) == 3


class _FakeBrief:
    """Duck-typed stand-in for RaceBrief — narrate reads basis, mode, headline."""

    def __init__(self, mode: str, evidence_basis: str) -> None:
        self.mode = mode
        self.evidence_basis = evidence_basis
        self.content = SimpleNamespace(headline="Test headline")


def _record_stub() -> SimpleNamespace:
    return SimpleNamespace(
        prediction_id="2021-r4-test", race=SimpleNamespace(race_id="test")
    )


class TestNarrateDegradePath:
    def test_live_failure_degrades_to_fixture_banner(
        self, demo: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        def live_fails(record: object, qualifying: object = (), config=None) -> _FakeBrief:
            calls.append(config.mode)
            if config.mode == "live":
                raise BriefError("connection refused")
            return _FakeBrief("fixture", FIXTURE_BANNER)

        monkeypatch.setattr(
            demo,
            "brief_config_from_env",
            lambda: BriefConfig(
                mode="live",
                ollama_base_url="http://localhost:11434",
                ollama_model="test-model",
                timeout_seconds=1.0,
            ),
        )
        monkeypatch.setattr(demo, "generate_brief", live_fails)
        demo.clear_events()

        demo.narrate([_record_stub()])

        assert calls == ["live", "fixture"]  # degraded once, then fixture retry
        brief_events = [
            event for event in bus_events() if event.signal == "brief-generation"
        ]
        assert [event.status for event in brief_events] == ["degraded", "ok"]
        assert brief_events[0].detail == {"raceId": "test", "reason": "BriefError"}
        assert brief_events[1].detail == {"raceId": "test", "mode": "fixture"}

    def test_fixture_brief_emits_ok(
        self, demo: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def working(record: object, qualifying: object = (), config=None) -> _FakeBrief:
            assert config is not None and config.mode == "fixture"
            return _FakeBrief("fixture", FIXTURE_BANNER)

        monkeypatch.setattr(demo, "brief_config_from_env", demo._fixture_config)
        monkeypatch.setattr(demo, "generate_brief", working)
        demo.clear_events()

        demo.narrate([_record_stub(), _record_stub()])

        brief_events = [
            event for event in bus_events() if event.signal == "brief-generation"
        ]
        assert [event.status for event in brief_events] == ["ok", "ok"]
        assert all(event.detail["mode"] == "fixture" for event in brief_events)

    def test_fixture_brief_failure_is_never_swallowed(
        self, demo: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(record: object, qualifying: object = (), config=None) -> _FakeBrief:
            raise BriefError("record is unhashable")

        monkeypatch.setattr(demo, "brief_config_from_env", demo._fixture_config)
        monkeypatch.setattr(demo, "generate_brief", broken)
        demo.clear_events()

        with pytest.raises(BriefError):
            demo.narrate([_record_stub()])  # only live mode degrades


class TestTypedFailureStates:
    def test_tampered_snapshot_refuses_the_run_typed(
        self,
        demo: ModuleType,
        predictable_snapshot: Path,
        tmp_path: Path,
    ) -> None:
        tampered = tmp_path / "tampered"
        shutil.copytree(predictable_snapshot, tampered)
        table = tampered / "results.parquet"
        data = bytearray(table.read_bytes())
        data[-5] ^= 0xFF  # flip one byte — the hash must catch it
        table.write_bytes(bytes(data))

        ledger = tmp_path / "ledger.jsonl"
        with pytest.raises(DataSnapshotMismatch):
            demo.run_demo(tampered, ledger, 2021, brief=False)
        assert not ledger.exists()  # nothing was predicted, nothing was written
