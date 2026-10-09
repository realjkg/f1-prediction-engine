"""Race brief contract tests — fixture determinism, digest-pinned live mode.

Spec row "LLM brief": fixture mode deterministic offline; live mode
digest-pinned, temperature 0, JSON-validated; brief kept outside the evidence
hash chain. Live-mode tests run the real HTTP path against a local fake Ollama
(http.server), so the contract under test is the one a real Ollama sees.
"""

from __future__ import annotations

import ast
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from f1engine.brief import (
    DEFAULT_OLLAMA_MODEL,
    FIXTURE_BANNER,
    LIVE_BANNER,
    BriefConfig,
    BriefInvalid,
    BriefRecordUnhashed,
    ModelNotPinned,
    ModelTimeout,
    QualifyingLine,
    RaceDigest,
    brief_config_from_env,
    build_digest,
    generate_brief,
    pin_ollama_model,
    prediction_digest,
    qualifying_snapshot,
    render_fixture_brief,
)
from f1engine.brief_store import (
    BriefStoreInvalid,
    append_brief,
    find_brief,
    read_briefs,
)
from f1engine.ensemble import arbitrate
from f1engine.evidence import (
    PredictionRecord,
    append_record,
    build_prediction_record,
    verify_chain,
)
from f1engine.features import build_asof_features
from f1engine.ingestion import PinnedDataset, load_snapshot
from f1engine.models import create_models

EVIDENCE_BASIS = "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE"
WEIGHTS = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}
OLLAMA_MODEL_NAME = "brief-model:latest"
OLLAMA_MODEL_DIGEST = "sha256:test-model-digest"
TAGS_PAYLOAD: dict[str, object] = {
    "models": [{"name": OLLAMA_MODEL_NAME, "digest": OLLAMA_MODEL_DIGEST}]
}

FIXTURE_CONFIG = BriefConfig(
    mode="fixture", ollama_base_url=None, ollama_model="unused", timeout_seconds=1.0
)


def _record_for(
    dataset: PinnedDataset, season: int, round_number: int
) -> PredictionRecord:
    """One prediction record through the real mini pipeline (as test_evidence does)."""
    table = build_asof_features(dataset)
    predictions = []
    for model in create_models().values():
        model.train(dataset, table, (season, round_number))
        predictions.append(model.predict(season, round_number))
    race = next(
        row
        for row in dataset.races
        if row.season == season and row.round == round_number
    )
    return build_prediction_record(
        predictions, arbitrate(predictions, WEIGHTS), dataset, race, EVIDENCE_BASIS
    )


@pytest.fixture()
def committed_record(predictable_snapshot: Path, tmp_path: Path) -> PredictionRecord:
    """A real prediction record, appended to a ledger, carrying its chain hash."""
    dataset = load_snapshot(predictable_snapshot)
    record = _record_for(dataset, 2021, 5)
    record_hash = append_record(tmp_path / "ledger.jsonl", record)
    return record.model_copy(update={"record_sha256": record_hash})


@pytest.fixture()
def round_qualifying(predictable_snapshot: Path) -> tuple[QualifyingLine, ...]:
    """The target round's pre-race qualifying snapshot from the same pipeline."""
    dataset = load_snapshot(predictable_snapshot)
    return qualifying_snapshot(dataset, 2021, 5)


def _live_config(base_url: str, timeout_seconds: float = 5.0) -> BriefConfig:
    return BriefConfig(
        mode="live",
        ollama_base_url=base_url,
        ollama_model=OLLAMA_MODEL_NAME,
        timeout_seconds=timeout_seconds,
    )


def _valid_brief_json(digest: RaceDigest) -> str:
    """A schema-valid brief JSON — the fixture render, which satisfies the schema."""
    return json.dumps(render_fixture_brief(digest).model_dump(by_alias=True))


@dataclass
class FakeOllama:
    """A local HTTP server speaking just enough of the Ollama API for the tests."""

    base_url: str
    chat_requests: list[dict[str, object]]
    server: ThreadingHTTPServer
    thread: threading.Thread

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@contextmanager
def running_ollama(
    tags_payload: dict[str, object],
    chat_content: str,
    chat_delay: float = 0.0,
) -> Iterator[FakeOllama]:
    chat_requests: list[dict[str, object]] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/api/tags":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(tags_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            chat_requests.append(json.loads(self.rfile.read(length) or b"{}"))
            if chat_delay:
                time.sleep(chat_delay)
            body = json.dumps(
                {"message": {"role": "assistant", "content": chat_content}}
            ).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return  # client gave up (timeout test) — nothing to answer

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake = FakeOllama(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        chat_requests=chat_requests,
        server=server,
        thread=thread,
    )
    try:
        yield fake
    finally:
        fake.close()


def _closed_port_url() -> str:
    """A localhost URL where nothing is listening — connection refused, fast."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


# --- Fixture mode: deterministic, labeled, offline -------------------------


def test_fixture_brief_is_byte_identical_across_runs(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
) -> None:
    first = generate_brief(committed_record, round_qualifying, config=FIXTURE_CONFIG)
    second = generate_brief(committed_record, round_qualifying, config=FIXTURE_CONFIG)

    assert first.model_dump_json(by_alias=True) == second.model_dump_json(
        by_alias=True
    )
    assert first.mode == "fixture"
    assert first.evidence_basis == FIXTURE_BANNER
    assert first.advisory_only is True
    assert first.pins is None
    assert len(first.content.talking_points) >= 3


def test_mode_defaults_to_fixture_without_env(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    brief = generate_brief(committed_record, round_qualifying)

    assert brief.mode == "fixture"
    assert brief.evidence_basis == FIXTURE_BANNER


def test_mode_selection_follows_env() -> None:
    config = brief_config_from_env({})
    assert config.mode == "fixture"
    assert config.ollama_base_url is None

    live = brief_config_from_env({"OLLAMA_BASE_URL": " http://127.0.0.1:11434 "})
    assert live.mode == "live"
    assert live.ollama_base_url == "http://127.0.0.1:11434"
    assert live.ollama_model == DEFAULT_OLLAMA_MODEL

    timed = brief_config_from_env(
        {"OLLAMA_BASE_URL": "http://x", "OLLAMA_TIMEOUT_SECONDS": "7.5"}
    )
    assert timed.timeout_seconds == 7.5


# --- Digest: the brief's only factual input --------------------------------


def test_digest_carries_ensemble_models_and_pre_race_qualifying(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
) -> None:
    digest = build_digest(committed_record, round_qualifying)

    assert digest.prediction_id == committed_record.prediction_id
    assert digest.dataset.sha256 == committed_record.dataset.sha256
    assert digest.record_sha256 == committed_record.record_sha256
    assert digest.consensus == committed_record.ensemble.consensus

    winner_probs = [pick.probability for pick in digest.ensemble_winner_top]
    assert winner_probs == sorted(winner_probs, reverse=True)

    assert [summary.model_id for summary in digest.models] == [
        "m1-gbm",
        "m2-logit",
        "m3-form",
    ]
    for summary in digest.models:
        prediction = committed_record.models[summary.model_id]
        assert summary.prediction_sha256 == prediction_digest(prediction)
        strongest = sorted(
            prediction.winner.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
        assert summary.winner_pick.driver_id == strongest

    # The mini snapshot's qualifying mirrors the finishing order: grid 1-3.
    assert [line.position for line in digest.qualifying] == [1, 2, 3]
    assert digest.qualifying[0].delta_pole_ms == 0


def test_qualifying_line_carries_no_result_fields() -> None:
    # The closed schema is the leakage guard: there is no finish field to leak.
    assert set(QualifyingLine.model_fields) == {
        "driver_id",
        "position",
        "q_best_ms",
        "delta_pole_ms",
    }


def test_brief_module_never_touches_results() -> None:
    # Pre-race invariant, tested not assumed: no attribute access to the
    # results or sprint tables anywhere in the brief module (prose mentions
    # in docstrings are fine — the AST sees code, not comments).
    source = (
        Path(__file__).resolve().parents[1] / "f1engine" / "brief.py"
    ).read_text(encoding="utf-8")
    accessed = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
    }
    assert not accessed & {"results", "sprints"}


def test_digest_refuses_an_unhashed_record(predictable_snapshot: Path) -> None:
    dataset = load_snapshot(predictable_snapshot)
    record = _record_for(dataset, 2021, 5)  # never appended: recordSha256 is ""

    with pytest.raises(BriefRecordUnhashed):
        build_digest(record, ())


# --- Brief store: outside the evidence hash chain ---------------------------


def test_brief_never_enters_the_ledger_chain(
    predictable_snapshot: Path,
    tmp_path: Path,
    round_qualifying: tuple[QualifyingLine, ...],
) -> None:
    dataset = load_snapshot(predictable_snapshot)
    record = _record_for(dataset, 2021, 5)
    ledger = tmp_path / "ledger.jsonl"
    record_hash = append_record(ledger, record)
    committed = record.model_copy(update={"record_sha256": record_hash})
    before = ledger.read_bytes()

    brief = generate_brief(committed, round_qualifying, config=FIXTURE_CONFIG)
    briefs = tmp_path / "briefs.jsonl"
    append_brief(briefs, brief)

    assert ledger.read_bytes() == before  # brief generation/store left the ledger alone
    verify_chain(ledger)  # the chain still verifies end to end

    stored = briefs.read_text(encoding="utf-8").splitlines()
    assert len(stored) == 1
    line = json.loads(stored[0])
    assert "recordSha256" not in line  # no chain hash of its own
    assert "prevRecordSha256" not in line  # and no predecessor to chain to
    assert line["briefType"] == "race-brief"


def test_brief_store_roundtrip_and_lookup(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
    tmp_path: Path,
) -> None:
    path = tmp_path / "briefs.jsonl"
    assert read_briefs(path) == []
    assert find_brief(path, committed_record.prediction_id) is None

    brief = generate_brief(committed_record, round_qualifying, config=FIXTURE_CONFIG)
    append_brief(path, brief)

    assert read_briefs(path) == [brief]
    assert find_brief(path, committed_record.prediction_id) == brief


def test_brief_store_refuses_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "briefs.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(BriefStoreInvalid):
        read_briefs(path)

    path.write_text('{"schemaVersion": 1}\n', encoding="utf-8")
    with pytest.raises(BriefStoreInvalid):
        read_briefs(path)


# --- Live mode: digest-pinned, temperature 0, JSON-validated ----------------


def test_live_brief_contract_with_mocked_ollama(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
) -> None:
    digest = build_digest(committed_record, round_qualifying)
    with running_ollama(
        tags_payload=TAGS_PAYLOAD, chat_content=_valid_brief_json(digest)
    ) as ollama:
        brief = generate_brief(
            committed_record, round_qualifying, config=_live_config(ollama.base_url)
        )

        request = ollama.chat_requests[0]
    assert request["model"] == OLLAMA_MODEL_NAME
    assert request["options"] == {"temperature": 0}
    assert request["format"] == "json"
    assert request["stream"] is False

    system, user = request["messages"]
    assert system["role"] == "system"
    # Digest pins are in the system prompt, verbatim.
    assert committed_record.dataset.sha256 in system["content"]
    assert committed_record.record_sha256 in system["content"]
    for summary in digest.models:
        assert summary.prediction_sha256 in system["content"]
    assert user["role"] == "user"
    assert digest.prediction_id in user["content"]

    assert brief.mode == "live"
    assert brief.evidence_basis == LIVE_BANNER
    assert brief.advisory_only is True
    assert brief.pins is not None
    assert brief.pins.ollama_model == OLLAMA_MODEL_NAME
    assert brief.pins.ollama_model_digest == OLLAMA_MODEL_DIGEST
    assert brief.pins.dataset_digest == committed_record.dataset.sha256
    assert brief.pins.record_sha256 == committed_record.record_sha256
    assert brief.pins.model_digests == {
        summary.model_id: summary.prediction_sha256 for summary in digest.models
    }
    assert brief.content == render_fixture_brief(digest)


@pytest.mark.parametrize(
    "chat_content",
    ["this is not json", '{"headline": "h"}'],
    ids=["not-json", "schema-drift"],
)
def test_live_brief_rejects_invalid_responses(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
    chat_content: str,
) -> None:
    with running_ollama(tags_payload=TAGS_PAYLOAD, chat_content=chat_content) as ollama:
        with pytest.raises(BriefInvalid) as excinfo:
            generate_brief(
                committed_record,
                round_qualifying,
                config=_live_config(ollama.base_url),
            )
    assert excinfo.value.code == "BRIEF_INVALID"


def test_live_brief_rejects_schema_drift_extra_field(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
) -> None:
    drifted = json.dumps(
        {
            "headline": "h",
            "summary": "s",
            "talking_points": ["t"],
            "consensus_note": "c",
            "surprise": True,
        }
    )
    with running_ollama(tags_payload=TAGS_PAYLOAD, chat_content=drifted) as ollama:
        with pytest.raises(BriefInvalid) as excinfo:
            generate_brief(
                committed_record,
                round_qualifying,
                config=_live_config(ollama.base_url),
            )
    assert excinfo.value.code == "BRIEF_INVALID"


def test_live_brief_times_out_with_typed_failure(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
) -> None:
    digest = build_digest(committed_record, round_qualifying)
    with running_ollama(
        tags_payload=TAGS_PAYLOAD,
        chat_content=_valid_brief_json(digest),
        chat_delay=2.0,
    ) as ollama:
        started = time.monotonic()
        with pytest.raises(ModelTimeout) as excinfo:
            generate_brief(
                committed_record,
                round_qualifying,
                config=_live_config(ollama.base_url, timeout_seconds=0.25),
            )
    assert excinfo.value.code == "MODEL_TIMEOUT"
    assert time.monotonic() - started < 1.5  # refused fast, not after the slow handler


def test_live_brief_refused_connection_is_model_timeout(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
) -> None:
    with pytest.raises(ModelTimeout):
        generate_brief(
            committed_record,
            round_qualifying,
            config=_live_config(_closed_port_url(), timeout_seconds=1.0),
        )


def test_live_brief_refuses_when_model_not_in_tags(
    committed_record: PredictionRecord,
    round_qualifying: tuple[QualifyingLine, ...],
) -> None:
    other_model = {"models": [{"name": "other-model:latest", "digest": "sha256:x"}]}
    with running_ollama(tags_payload=other_model, chat_content="{}") as ollama:
        with pytest.raises(ModelNotPinned) as excinfo:
            generate_brief(
                committed_record,
                round_qualifying,
                config=_live_config(ollama.base_url),
            )
    assert excinfo.value.code == "MODEL_NOT_PINNED"


def test_model_pin_matches_full_and_untagged_names() -> None:
    with running_ollama(tags_payload=TAGS_PAYLOAD, chat_content="") as ollama:
        assert (
            pin_ollama_model(ollama.base_url, OLLAMA_MODEL_NAME, 2.0)
            == OLLAMA_MODEL_DIGEST
        )
        assert (
            pin_ollama_model(ollama.base_url, "brief-model", 2.0)
            == OLLAMA_MODEL_DIGEST
        )
