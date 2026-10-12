"""Live ingest: a synthetic race streamed message by message, no broker, no network."""

from __future__ import annotations

import json
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from f1engine.app import ApiSettings, create_app
from f1engine.live_ingest import LiveIngestor
from f1engine.live_prior import PreRacePrior
from f1engine.openf1_feed import TOKEN_URL, fetch_access_token

SESSION = 55001
LAP_SECONDS = 100
# Anchored to the wall clock so the latest-state API freshness window (120 s)
# sees the fourth lap as current, exactly as it would during a race.
START = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=4 * LAP_SECONDS + 10)


class Stream:
    """Builds OpenF1-shaped MQTT payloads with a rising provider sequence."""

    def __init__(self) -> None:
        self.sequence = 1000

    def message(self, topic: str, body: dict[str, object]) -> tuple[str, bytes]:
        self.sequence += 1
        full = {"session_key": SESSION, "_id": self.sequence,
                "_key": f"{topic}-{self.sequence}", **body}
        return f"v1/{topic}", json.dumps(full).encode()


def prior() -> PreRacePrior:
    return PreRacePrior(
        season=2026, race_id="singapore", session_key=SESSION,
        model_revision="fixed-prospective-challenger-v1",
        model_artifact_sha256="b" * 64, dataset_sha256="c" * 64,
        source_issued_at=START - timedelta(days=1),
        frozen_at=START - timedelta(hours=1),
        race_start_at=START - timedelta(minutes=10),
        driver_win_probabilities={1: .7, 16: .3},
    )


def make_ingestor(tmp_path: Path, *, with_prior: bool = True) -> LiveIngestor:
    return LiveIngestor(
        session_key=SESSION, season=2026, race_id="singapore", total_laps=6,
        entrants=(1, 16), trace_path=tmp_path / "trace.jsonl",
        artifact_root=tmp_path / "artifacts", spool_path=tmp_path / "spool.jsonl",
        rights_evidence="sponsor-account-2026-10", prior=prior() if with_prior else None,
        scenario_weight=.35, trials=300,
    )


def play(ingestor: LiveIngestor, laps: int, stream: Stream | None = None):
    """Feed `laps` completed laps; returns every emission, in order."""
    stream = stream or Stream()
    emissions = []

    def feed(topic: str, body: dict[str, object], at: datetime) -> None:
        name, payload = stream.message(topic, body)
        emission = ingestor.handle(name, payload, at)
        if emission is not None:
            emissions.append(emission)

    feed("race_control", {"date": START.isoformat(), "flag": "GREEN",
                          "scope": "Track", "category": "Flag"}, START + timedelta(seconds=1))
    feed("weather", {"date": START.isoformat(), "rainfall": 0}, START + timedelta(seconds=1))
    for number in range(1, laps + 1):
        end = START + timedelta(seconds=number * LAP_SECONDS)
        for car, position, gap in ((1, 1, 0), (16, 2, 4.2)):
            when = (end - timedelta(seconds=5)).isoformat()
            feed("position", {"driver_number": car, "position": position, "date": when},
                 end - timedelta(seconds=4))
            feed("intervals", {"driver_number": car, "gap_to_leader": gap, "date": when},
                 end - timedelta(seconds=4))
        for offset, car in ((1, 1), (2, 16)):
            feed("laps", {
                "driver_number": car, "lap_number": number,
                "lap_duration": 100.0 - 0.01 * number + car / 100,
                "date_start": (START + timedelta(seconds=(number - 1) * LAP_SECONDS)).isoformat(),
            }, end + timedelta(seconds=offset))
    return emissions


def test_each_new_leader_lap_writes_one_checkpoint_and_the_last_one_fuses(tmp_path: Path):
    ingestor = make_ingestor(tmp_path)
    emissions = play(ingestor, laps=4)
    # Leader completes laps 1..4 -> checkpoints for in-progress laps 2..5, once each.
    assert [e.lap for e in emissions] == [2, 3, 4, 5]
    assert ingestor.last_lap == 5
    last = emissions[-1]
    assert last.scenario_status == "scenario" and last.fused is True
    trace = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert [row["checkpoint"]["lap"] for row in trace] == [2, 3, 4, 5]
    assert all(row["checkpoint"]["sourceType"] == "licensed-live" for row in trace)
    assert all(row["checkpoint"]["rightsEvidence"] == "sponsor-account-2026-10" for row in trace)


def test_existing_read_only_api_serves_the_latest_live_checkpoint(
    predictable_dataset, tmp_path: Path,
):
    ingestor = make_ingestor(tmp_path)
    play(ingestor, laps=4)
    settings = ApiSettings(
        lap_trace_path=tmp_path / "trace.jsonl",
        inrace_artifact_dir=tmp_path / "artifacts",
    )
    client = TestClient(create_app(settings, dataset=predictable_dataset))
    latest = client.get("/api/races/singapore/lap-scenario?season=2026")
    assert latest.status_code == 200
    body = latest.json()
    assert body["lap"] == 5 and body["sourceType"] == "licensed-live"
    assert body["modelReady"] is False
    fusion = client.get("/api/races/singapore/lap-fusion?season=2026")
    assert fusion.status_code == 200
    assert fusion.json()["promoted"] is False
    assert fusion.json()["greenScenarioWeight"] == pytest.approx(.35)
    assert fusion.json()["checkpointSha256"] == body["checkpointSha256"]


def test_without_a_prior_only_the_lap_scenario_is_written(tmp_path: Path):
    emissions = play(make_ingestor(tmp_path, with_prior=False), laps=4)
    assert emissions[-1].scenario_status == "scenario"
    assert all(e.fused is False for e in emissions)
    assert not list((tmp_path / "artifacts").rglob("*.fusion.json"))


def test_duplicate_documents_are_dropped_and_never_counted_twice(tmp_path: Path):
    ingestor = make_ingestor(tmp_path)
    stream = Stream()
    name, payload = stream.message("position", {
        "driver_number": 1, "position": 1, "date": (START + timedelta(seconds=5)).isoformat()})
    at = START + timedelta(seconds=6)
    assert ingestor.handle(name, payload, at) is None
    assert ingestor.handle(name, payload, at) is None
    assert ingestor.stats.received == 1 and ingestor.stats.duplicates == 1
    assert len((tmp_path / "spool.jsonl").read_text().splitlines()) == 1


def test_other_sessions_and_malformed_messages_are_counted_not_ingested(tmp_path: Path):
    ingestor = make_ingestor(tmp_path)
    at = START + timedelta(seconds=10)
    other = json.dumps({"session_key": 999, "_id": 1, "_key": "k", "position": 1}).encode()
    assert ingestor.handle("v1/position", other, at) is None
    assert ingestor.handle("v1/position", b"not json", at) is None
    assert ingestor.handle("v1/car_data", b"{}", at) is None  # topic not allowlisted
    future = json.dumps({"session_key": SESSION, "_id": 2, "_key": "k2",
                         "date": (at + timedelta(minutes=5)).isoformat()}).encode()
    assert ingestor.handle("v1/position", future, at) is None
    stats = ingestor.stats
    assert (stats.other_session, stats.rejected, stats.received) == (1, 3, 0)
    assert stats.last_rejection
    assert not (tmp_path / "spool.jsonl").exists() or (tmp_path / "spool.jsonl").read_text() == ""


def test_incomplete_field_waits_instead_of_inventing_a_checkpoint(tmp_path: Path):
    ingestor = make_ingestor(tmp_path)
    stream = Stream()
    end = START + timedelta(seconds=LAP_SECONDS)
    # Only the leader's position is known; car 16 has never reported.
    for name, body, at in (
        ("position", {"driver_number": 1, "position": 1,
                      "date": (end - timedelta(seconds=5)).isoformat()},
         end - timedelta(seconds=4)),
        ("laps", {"driver_number": 1, "lap_number": 1, "lap_duration": 100.0,
                  "date_start": START.isoformat()}, end + timedelta(seconds=1)),
    ):
        topic, payload = stream.message(name, body)
        assert ingestor.handle(topic, payload, at) is None
    assert ingestor.stats.refusals == 1
    assert "position feed" in (ingestor.stats.last_refusal or "")
    assert ingestor.last_lap == 1
    assert not (tmp_path / "trace.jsonl").exists()


def test_finishing_stops_the_run_without_a_final_checkpoint(tmp_path: Path):
    ingestor = make_ingestor(tmp_path)
    emissions = play(ingestor, laps=6)
    assert ingestor.finished is True
    assert [e.lap for e in emissions] == [2, 3, 4, 5, 6]


def test_spool_replays_offline_into_the_same_checkpoint_inputs(tmp_path: Path):
    """The durable spool must stay usable by the offline bundler."""
    import importlib.util

    ingestor = make_ingestor(tmp_path)
    play(ingestor, laps=4)
    path = Path(__file__).resolve().parents[2] / "scripts" / "bundle-openf1-spool.py"
    spec = importlib.util.spec_from_file_location("bundle_spool", path)
    assert spec and spec.loader
    bundler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundler)
    lines = (tmp_path / "spool.jsonl").read_text().splitlines()
    bundle = bundler.spool_to_bundle(
        lines, session_key=SESSION, cutoff=START + timedelta(seconds=10 * LAP_SECONDS))
    assert sum(len(rows) for rows in bundle["events"].values()) == ingestor.stats.received


def test_rights_reference_and_roster_are_mandatory(tmp_path: Path):
    kwargs = dict(
        session_key=SESSION, season=2026, race_id="x", total_laps=5,
        trace_path=tmp_path / "t", artifact_root=tmp_path / "a", spool_path=tmp_path / "s",
    )
    with pytest.raises(ValueError, match="rights"):
        LiveIngestor(entrants=(1, 16), rights_evidence="  ", **kwargs)
    with pytest.raises(ValueError, match="entrant"):
        LiveIngestor(entrants=(1, 1), rights_evidence="ref", **kwargs)


def test_token_exchange_parses_the_documented_response(monkeypatch: pytest.MonkeyPatch):
    seen = {}

    class Reply:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit: int) -> bytes:
            return self.body

    def fake_urlopen(request, timeout, context):
        seen["url"], seen["data"] = request.full_url, request.data
        seen["tls"] = context
        return Reply(b'{"access_token":"tok","expires_in":"3600","token_type":"bearer"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert fetch_access_token("me@example.com", "pw") == ("tok", 3600)
    assert seen["url"] == TOKEN_URL and TOKEN_URL.startswith("https://")
    assert seen["tls"].minimum_version == ssl.TLSVersion.TLSv1_3
    assert seen["tls"].verify_mode == ssl.CERT_REQUIRED
    assert seen["tls"].check_hostname is True
    assert b"username=me%40example.com" in seen["data"]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Reply(b"{}"))
    with pytest.raises(ValueError, match="malformed"):
        fetch_access_token("me", "pw")
