"""Evidence ledger contract tests — advisory records and hash chaining.

Spec row "Ensemble + ledger": schema-valid records; advisoryOnly +
dataLimitations present; sha256 chain verifies; tampering and gaps are
detected. Records are built through the real pipeline (trained models ->
arbitrated verdict -> record) against the predictable mini snapshot, so the
tested records are the ones the engine actually writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from f1engine.ensemble import arbitrate
from f1engine.evidence import (
    EvidenceChainGap,
    EvidenceRecordInvalid,
    EvidenceTampered,
    PredictionRecord,
    append_record,
    build_prediction_record,
    chain_is_valid,
    verify_chain,
)
from f1engine.features import build_asof_features
from f1engine.ingestion import PinnedDataset, load_snapshot
from f1engine.models import create_models

EVIDENCE_BASIS = "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE"
WEIGHTS = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}


def _record_for(
    dataset: PinnedDataset, season: int, round_number: int
) -> PredictionRecord:
    """One prediction record through the real mini pipeline."""
    table = build_asof_features(dataset)
    predictions = []
    for model in create_models().values():
        model.train(dataset, table, (season, round_number))
        predictions.append(model.predict(season, round_number))
    verdict = arbitrate(predictions, WEIGHTS)
    race = next(
        row
        for row in dataset.races
        if row.season == season and row.round == round_number
    )
    return build_prediction_record(
        predictions, verdict, dataset, race, EVIDENCE_BASIS
    )


def _read_lines(ledger_path: Path) -> list[str]:
    return ledger_path.read_text(encoding="utf-8").splitlines()


def test_record_carries_the_advisory_contract(
    predictable_snapshot: Path,
) -> None:
    dataset = load_snapshot(predictable_snapshot)
    record = _record_for(dataset, 2021, 4)

    # The advisory contract is structural, not conventional: the schema's
    # advisoryOnly is a Literal[True] — a record cannot claim authority.
    assert record.advisory_only is True
    assert record.data_limitations == list(dataset.limitations)
    assert len(record.data_limitations) > 0
    assert record.evidence_basis == EVIDENCE_BASIS
    assert record.prediction_id == "2021-r4-fourth-grand-prix"
    assert record.race.season == 2021
    assert record.race.round == 4
    assert record.dataset.id == dataset.dataset_id
    assert record.dataset.sha256 == dataset.dataset_sha256
    assert set(record.models) == {"m1-gbm", "m2-logit", "m3-form"}
    assert record.ensemble.race_id == "fourth-grand-prix"


def test_append_and_verify_a_two_record_chain(
    predictable_snapshot: Path, tmp_path: Path
) -> None:
    dataset = load_snapshot(predictable_snapshot)
    ledger = tmp_path / "ledger.jsonl"

    first_hash = append_record(ledger, _record_for(dataset, 2021, 4))
    second_hash = append_record(ledger, _record_for(dataset, 2021, 5))

    verify_chain(ledger)  # does not raise
    assert chain_is_valid(ledger)
    lines = _read_lines(ledger)
    assert len(lines) == 2
    assert first_hash != second_hash
    assert json.loads(lines[0])["recordSha256"] == first_hash
    chained_to = json.loads(lines[1])["prevRecordSha256"]
    assert chained_to == first_hash


def test_single_field_tamper_is_detected(
    predictable_snapshot: Path, tmp_path: Path
) -> None:
    dataset = load_snapshot(predictable_snapshot)
    ledger = tmp_path / "ledger.jsonl"
    append_record(ledger, _record_for(dataset, 2021, 4))
    append_record(ledger, _record_for(dataset, 2021, 5))

    # Content tamper in the first record.
    lines = _read_lines(ledger)
    tampered = lines[0].replace("REAL MODELS", "FABRICATED MODELS", 1)
    assert tampered != lines[0]
    ledger.write_text(tampered + "\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(EvidenceTampered):
        verify_chain(ledger)

    # Re-hash tamper in the last record: even rewriting the hash field to
    # hide an edit fails, because the hash covers the record itself.
    ledger.unlink()
    append_record(ledger, _record_for(dataset, 2021, 4))
    append_record(ledger, _record_for(dataset, 2021, 5))
    lines = _read_lines(ledger)
    stored = json.loads(lines[1])["recordSha256"]
    rewritten = lines[1].replace(stored, "0" * 64)
    ledger.write_text(lines[0] + "\n" + rewritten + "\n", encoding="utf-8")
    with pytest.raises(EvidenceTampered):
        verify_chain(ledger)


def test_chain_gap_is_detected(predictable_snapshot: Path, tmp_path: Path) -> None:
    dataset = load_snapshot(predictable_snapshot)
    ledger = tmp_path / "ledger.jsonl"
    append_record(ledger, _record_for(dataset, 2021, 4))
    append_record(ledger, _record_for(dataset, 2021, 5))

    lines = _read_lines(ledger)
    ledger.write_text(lines[1] + "\n", encoding="utf-8")  # drop the genesis

    with pytest.raises(EvidenceChainGap):
        verify_chain(ledger)
    assert not chain_is_valid(ledger)


def test_malformed_record_is_refused_before_write(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "recordType": "prediction",
        "predictionId": "2021-r4-fourth-grand-prix",
        # advisoryOnly missing and no dataset/models — refused by schema.
    }

    with pytest.raises(EvidenceRecordInvalid):
        append_record(ledger, payload)

    assert not ledger.exists()  # refused before anything touched the file


def test_verify_tolerates_an_empty_ledger(tmp_path: Path) -> None:
    verify_chain(tmp_path / "absent.jsonl")  # nothing to verify
    assert chain_is_valid(tmp_path / "absent.jsonl")


def test_record_hash_is_stamped_on_append(
    predictable_snapshot: Path, tmp_path: Path
) -> None:
    dataset = load_snapshot(predictable_snapshot)
    record = _record_for(dataset, 2021, 4)
    assert record.record_sha256 == ""  # the record never hashes itself

    digest = append_record(tmp_path / "ledger.jsonl", record)

    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)
