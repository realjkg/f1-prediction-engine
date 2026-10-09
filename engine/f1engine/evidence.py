"""Append-only prediction ledger — sha256-chained, advisory-only.

Contract (spec, engine/f1engine/evidence): every prediction is a schema-valid
record with advisoryOnly: true, declared dataLimitations, and recordSha256
chained to the previous record's hash. Verification walks the chain and
raises typed errors on tamper or gap — a chain that verifies is the demo's
proof that nothing was edited after the fact. Backtest results join the same
ledger as additional record types in the backtest task.

Record hash discipline: recordSha256 is the sha256 of the record's canonical
JSON (sorted keys, compact separators) with the recordSha256 field itself
excluded, so every line's integrity is recomputable from its own content.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from f1engine.dataset import sha256_hex
from f1engine.ensemble import EnsembleVerdict
from f1engine.ingestion import PinnedDataset, RaceRow
from f1engine.models import ModelId, ModelPrediction
from f1engine.wire import WireModel

LEDGER_SCHEMA_VERSION = 1


class EvidenceError(RuntimeError):
    """Base of the evidence refusal family (code EVIDENCE_INVALID)."""

    code = "EVIDENCE_INVALID"


class EvidenceRecordInvalid(EvidenceError):
    """A record fails the ledger's closed schema or its cross-field invariants."""

    code = "EVIDENCE_RECORD_INVALID"


class EvidenceSchemaInvalid(EvidenceError):
    """A ledger line is not parseable into the closed record schema."""

    code = "EVIDENCE_SCHEMA_INVALID"


class EvidenceTampered(EvidenceError):
    """A record's content no longer matches its own recorded hash."""

    code = "EVIDENCE_TAMPERED"


class EvidenceChainGap(EvidenceError):
    """The chain is broken: a record does not name its true predecessor."""

    code = "EVIDENCE_CHAIN_GAP"


class RaceIdentity(WireModel):
    """The race a record answers — season, round, and the event's name."""

    season: int
    round: int
    race_id: str
    name: str


class DatasetIdentity(WireModel):
    """Which pinned dataset produced the record."""

    id: str
    sha256: str


class PredictionRecord(WireModel):
    """The ledger's prediction record — the spec's shared contract, on disk.

    advisoryOnly is a Literal[True]: the pydantic schema itself refuses any
    record that claims prediction authority the engine does not have.
    """

    schema_version: Literal[1] = LEDGER_SCHEMA_VERSION
    record_type: Literal["prediction"]
    prediction_id: str
    race: RaceIdentity
    generated_at: str
    dataset: DatasetIdentity
    evidence_basis: str
    models: dict[ModelId, ModelPrediction]
    ensemble: EnsembleVerdict
    advisory_only: Literal[True]
    data_limitations: list[str]
    prev_record_sha256: str | None = None
    record_sha256: str = ""  # set by append_record; excluded from the chain hash


def build_prediction_record(
    predictions: Sequence[ModelPrediction],
    verdict: EnsembleVerdict,
    dataset: PinnedDataset,
    race: RaceRow,
    evidence_basis: str,
) -> PredictionRecord:
    """Assemble the ledger's prediction record from arbitrated output.

    advisoryOnly is always true — the engine's predictions never carry
    authority — and dataLimitations are copied from the pinned dataset's own
    provenance, so the record declares exactly what the data cannot say.
    """
    _validate_consistency(predictions, verdict, dataset, race)
    return PredictionRecord(
        record_type="prediction",
        prediction_id=f"{race.season}-r{race.round}-{race.race_id}",
        race=RaceIdentity(
            season=race.season, round=race.round, race_id=race.race_id, name=race.name
        ),
        generated_at=dataset.provenance.generatedAt,
        dataset=DatasetIdentity(id=dataset.dataset_id, sha256=dataset.dataset_sha256),
        evidence_basis=evidence_basis,
        models={prediction.model_id: prediction for prediction in predictions},
        ensemble=verdict,
        advisory_only=True,
        data_limitations=list(dataset.limitations),
    )


def _validate_consistency(
    predictions: Sequence[ModelPrediction],
    verdict: EnsembleVerdict,
    dataset: PinnedDataset,
    race: RaceRow,
) -> None:
    race_ids = {prediction.race_id for prediction in predictions}
    if race_ids != {race.race_id} or verdict.race_id != race.race_id:
        raise EvidenceRecordInvalid(
            f"record race {race.race_id!r} does not match predictions "
            f"{sorted(race_ids)} / verdict {verdict.race_id!r}"
        )
    digests = {prediction.dataset_digest for prediction in predictions}
    if digests != {dataset.dataset_sha256}:
        raise EvidenceRecordInvalid(
            f"predictions carry dataset digest(s) {sorted(digests)}, snapshot is "
            f"{dataset.dataset_sha256}"
        )
    if any(
        prediction.generated_at != dataset.provenance.generatedAt
        for prediction in predictions
    ):
        raise EvidenceRecordInvalid(
            "prediction generatedAt disagrees with the dataset provenance"
        )


def append_record(
    ledger_path: Path, record: PredictionRecord | dict[str, object]
) -> str:
    """Append one hash-chained record; returns the record's sha256.

    Dicts are validated into the closed schema first, so a malformed record
    is refused before anything touches the file. The record is chained to the
    current last line (genesis records name no predecessor) and the file is
    opened in append mode — existing lines are never rewritten.
    """
    validated = (
        record if isinstance(record, PredictionRecord) else _validated_record(record)
    )
    chained = validated.model_copy(
        update={"prev_record_sha256": _last_record_hash(ledger_path)}
    )
    digest = _record_digest(chained)
    line = json.dumps(
        chained.model_dump(by_alias=True) | {"recordSha256": digest},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return digest


def verify_chain(ledger_path: Path) -> None:
    """Walk the whole chain; raise on tamper, gap, or schema failure.

    Every line is re-hashed from its own content (tamper detection) and must
    name the previous line's hash exactly (gap detection). An absent file is
    an empty chain — nothing to verify, nothing to refuse.
    """
    if not ledger_path.exists():
        return
    previous: str | None = None
    for index, line in enumerate(_ledger_lines(ledger_path)):
        record = _parsed_record(index, line)
        if record.record_sha256 != _record_digest(record):
            raise EvidenceTampered(
                f"ledger line {index}: content re-hash does not match its "
                f"recorded recordSha256 {record.record_sha256!r}"
            )
        if record.prev_record_sha256 != previous:
            raise EvidenceChainGap(
                f"ledger line {index} chains to {record.prev_record_sha256!r}, "
                f"expected {previous!r}"
            )
        previous = record.record_sha256


def chain_is_valid(ledger_path: Path) -> bool:
    """verify_chain as a boolean — for preflight checks, not for enforcement."""
    try:
        verify_chain(ledger_path)
    except EvidenceError:
        return False
    return True


def _validated_record(payload: dict[str, object]) -> PredictionRecord:
    try:
        return PredictionRecord.model_validate(payload)
    except ValidationError as error:
        raise EvidenceRecordInvalid(
            f"record failed the closed ledger schema: {error}"
        ) from error


def _parsed_record(index: int, line: str) -> PredictionRecord:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        raise EvidenceSchemaInvalid(
            f"ledger line {index} is not valid JSON: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise EvidenceSchemaInvalid(f"ledger line {index} is not a JSON object")
    return _validated_record(payload)


def _ledger_lines(ledger_path: Path) -> list[str]:
    return [
        line
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _last_record_hash(ledger_path: Path) -> str | None:
    """The last record's hash, or None for a fresh (genesis) chain."""
    if not ledger_path.exists():
        return None
    lines = _ledger_lines(ledger_path)
    if not lines:
        return None
    last = _parsed_record(len(lines) - 1, lines[-1])
    return last.record_sha256


def _record_digest(record: PredictionRecord) -> str:
    """sha256 of the record's canonical JSON, excluding its own hash field."""
    payload = record.model_dump(by_alias=True)
    payload.pop("recordSha256", None)
    return sha256_hex(_canonical(payload).encode("utf-8"))


def _canonical(payload: dict[str, object]) -> str:
    """Canonical JSON: sorted keys, compact separators — stable bytes."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
