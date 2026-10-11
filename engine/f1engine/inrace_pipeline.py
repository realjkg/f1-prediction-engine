"""Immutable artifact loop for source -> checkpoint -> conditional scenario.

Input source bytes remain in a separate retained evidence file. The artifact
records the checkpoint SHA-256, scenario revision, and a digest of its own
canonical content, and can be reverified before being shown in the UI.
This is a bounded experimental scenario, not a calibrated prediction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from f1engine.lap_trace import (
    LapCheckpoint,
    LapTraceError,
    LapTraceRecord,
    append_lap_checkpoint,
    verify_lap_trace,
)
from f1engine.openf1_projection import project_lap_checkpoint
from f1engine.race_simulator import (
    InRaceScenario,
    ScenarioUnavailable,
    simulate_green_pace,
)
from f1engine.wire import WireModel


class ArtifactTampered(LapTraceError):
    code = "ARTIFACT_TAMPERED"


class InRaceRunArtifact(WireModel):
    schema_version: Literal[1] = 1
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: Literal["historical-archive", "licensed-live", "synthetic-fixture"]
    season: int
    race_id: str
    lap: int
    generated_at: datetime
    status: Literal["scenario", "insufficient-evidence"]
    scenario: InRaceScenario | None
    refusal_reason: str | None = None
    model_ready: Literal[False] = False
    advisory_only: Literal[True] = True
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_binding(self) -> InRaceRunArtifact:
        if self.status == "scenario":
            if self.scenario is None or self.refusal_reason is not None:
                raise ValueError("scenario artifact missing or conflicting")
            if (
                self.scenario.checkpoint_record_sha256 != self.checkpoint_sha256
                or self.scenario.checkpoint_lap != self.lap
                or self.scenario.season != self.season
                or self.scenario.race_id != self.race_id
            ):
                raise ValueError("scenario artifact points at different evidence")
        elif self.scenario is not None or not self.refusal_reason:
            raise ValueError("insufficient-evidence artifact must give a reason")
        return self


def artifact_digest(artifact: InRaceRunArtifact | dict[str, object]) -> str:
    if isinstance(artifact, InRaceRunArtifact):
        value = artifact.model_dump(mode="json", by_alias=True)
    else:
        value = artifact
    content = {k: v for k, v in value.items() if k != "artifactSha256"}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_path(root: Path, *, season: int, race_id: str, lap: int, digest: str) -> Path:
    if not race_id or not all(c.isalnum() or c in "-_" for c in race_id):
        raise LapTraceError("invalid event slug")
    return root / f"{season}-{race_id}" / f"lap-{lap:03d}" / f"{digest}.json"


def read_run_artifact(
    root: Path, *, season: int, race_id: str, lap: int,
    checkpoint_sha256: str,
) -> InRaceRunArtifact | None:
    path = _file_path(root, season=season, race_id=race_id, lap=lap, digest=checkpoint_sha256)
    if not path.is_file():
        return None
    try:
        artifact = InRaceRunArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ArtifactTampered("saved simulation artifact cannot be validated") from exc
    if (
        artifact.artifact_sha256 != artifact_digest(artifact)
        or artifact.checkpoint_sha256 != checkpoint_sha256
        or artifact.lap != lap
        or artifact.season != season
        or artifact.race_id != race_id
    ):
        raise ArtifactTampered("saved simulation artifact checksum or identity mismatch")
    return artifact


def build_run_artifact(record: LapTraceRecord, *, trials: int = 2000) -> InRaceRunArtifact:
    scenario = None
    error_reason = None
    try:
        scenario = simulate_green_pace(record, trials=trials)
    except ScenarioUnavailable as exc:
        error_reason = str(exc)
    checkpoint = record.checkpoint
    fields: dict[str, object] = {
        "schemaVersion": 1,
        "checkpointSha256": record.record_sha256,
        "sourceSha256": checkpoint.source_payload_sha256,
        "sourceType": checkpoint.source_type,
        "season": checkpoint.season,
        "raceId": checkpoint.race_id,
        "lap": checkpoint.lap,
        "generatedAt": checkpoint.captured_at.isoformat(),
        "status": "scenario" if scenario is not None else "insufficient-evidence",
        "scenario": scenario.model_dump(mode="json", by_alias=True)
        if scenario is not None else None,
        "refusalReason": error_reason,
        "modelReady": False,
        "advisoryOnly": True,
    }
    fields["artifactSha256"] = artifact_digest(fields)
    return InRaceRunArtifact.model_validate(fields)


def write_run_artifact(root: Path, artifact: InRaceRunArtifact) -> Path:
    if artifact.artifact_sha256 != artifact_digest(artifact):
        raise ArtifactTampered("artifact checksum invalid before write")
    path = _file_path(
        root, season=artifact.season, race_id=artifact.race_id, lap=artifact.lap,
        digest=artifact.checkpoint_sha256,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = artifact.model_dump_json(by_alias=True) + "\n"
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(payload)
    except FileExistsError:
        prior = read_run_artifact(
            root, season=artifact.season, race_id=artifact.race_id,
            lap=artifact.lap, checkpoint_sha256=artifact.checkpoint_sha256,
        )
        if prior != artifact:
            raise ArtifactTampered("immutable artifact identity changed")
    return path


def project_and_record(
    raw_source: bytes, *, trace_path: Path, artifact_root: Path,
    season: int, race_id: str, session_key: int, lap: int,
    total_laps: int, cutoff: datetime, captured_at: datetime,
    entrant_numbers: tuple[int, ...], source_type: str,
    rights_evidence: str | None, trials: int = 2000,
) -> tuple[LapTraceRecord, InRaceRunArtifact]:
    """Execute PLAN -> observed DO -> hash VERIFY -> publish read-only artifact.

    Idempotent when an identical checkpoint already exists at the exact
    same lap/time/source; fail on same-time divergent evidence.
    """
    if source_type not in ("historical-archive", "licensed-live", "synthetic-fixture"):
        raise LapTraceError("unknown source class")
    if source_type == "licensed-live" and not rights_evidence:
        raise LapTraceError("live source license reference is required")
    checkpoint: LapCheckpoint = project_lap_checkpoint(
        raw_source, season=season, race_id=race_id, session_key=session_key,
        lap=lap, total_laps=total_laps, cutoff=cutoff,
        entrant_numbers=entrant_numbers, source_type=source_type,
        rights_evidence=rights_evidence, captured_at=captured_at,
    )
    current = verify_lap_trace(trace_path)
    previous = next((
        r for r in reversed(current)
        if r.checkpoint.lap == checkpoint.lap
        and r.checkpoint.source_payload_sha256 == checkpoint.source_payload_sha256
        and r.checkpoint.observed_at == checkpoint.observed_at
    ), None)
    if previous is not None:
        record = previous
    else:
        record = append_lap_checkpoint(trace_path, checkpoint)
    artifact = build_run_artifact(record, trials=trials)
    write_run_artifact(artifact_root, artifact)
    return record, artifact
