"""LLM race brief — fixture-mode default, digest-pinned Ollama live mode.

Contract (spec, engine/f1engine/brief): the brief narrates a race through the
same local-model seam as the Landing Zone (Ollama /api/chat, temperature 0,
JSON-validated output, model identity pinned via /api/tags). Fixture mode is
the default and runs offline-deterministic under a DETERMINISTIC FIXTURE
banner. The brief is advisory and lives OUTSIDE the evidence hash chain
(brief_store.py gives it its own file, with no chain hash to verify).

Three identities pin every live brief to its data: the pinned dataset's
sha256, the narrated record's own chain hash, and a digest of each model's
prediction (prediction_digest) — all restated verbatim in the system prompt,
so a brief can only be about the exact data it names. The Ollama model's
server-side identity is pinned via /api/tags before inference.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, ValidationError

from f1engine.dataset import sha256_hex
from f1engine.ensemble import PODIUM_SPREAD_OK_THRESHOLD, Consensus
from f1engine.evidence import DatasetIdentity, PredictionRecord, RaceIdentity
from f1engine.features import best_qualifying_ms
from f1engine.ingestion import PinnedDataset
from f1engine.models import ModelId, ModelPrediction
from f1engine.wire import WireModel

BRIEF_MODES: tuple[str, ...] = ("fixture", "live")
BRIEF_SCHEMA_VERSION = 1

FIXTURE_BANNER = "DETERMINISTIC FIXTURE — NO LOCAL MODEL INFERENCE"
LIVE_BANNER = "LIVE OLLAMA BRIEF — DIGEST-PINNED — TEMPERATURE 0"

OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"
OLLAMA_MODEL_ENV = "OLLAMA_MODEL"
OLLAMA_TIMEOUT_ENV = "OLLAMA_TIMEOUT_SECONDS"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_TIMEOUT_SECONDS = 30.0

# Drivers carried per distribution in the digest — compact by design: the
# prompt narrates the contenders, not the full field.
TOP_PICKS = 5


class BriefError(RuntimeError):
    """Base of the brief refusal family (code BRIEF_INVALID)."""

    code = "BRIEF_INVALID"


class BriefInvalid(BriefError):
    """A live response is not schema-valid brief JSON (code BRIEF_INVALID)."""

    code = "BRIEF_INVALID"


class ModelTimeout(BriefError):
    """Ollama is slow or absent — any transport-level live failure (code MODEL_TIMEOUT)."""

    code = "MODEL_TIMEOUT"


class ModelNotPinned(BriefError):
    """The configured Ollama model is absent from /api/tags — identity cannot be pinned."""

    code = "MODEL_NOT_PINNED"


class BriefRecordUnhashed(BriefError):
    """The narrated record has no chain hash yet — append it to the ledger first."""

    code = "BRIEF_RECORD_UNHASHED"


class DigestPick(WireModel):
    """One driver's probability in a distribution, strongest-first ordered."""

    driver_id: str
    probability: float


class ModelDigestSummary(WireModel):
    """What one model said, plus the digest pinning its exact prediction."""

    model_id: ModelId
    winner_pick: DigestPick
    winner_top: tuple[DigestPick, ...]
    podium_top: tuple[DigestPick, ...]
    prediction_sha256: str
    trained_through_season: int
    trained_through_round: int
    seed: int | None


class QualifyingLine(WireModel):
    """One driver's pre-race qualifying snapshot.

    Closed schema on purpose: qualifying order is known before a race runs,
    so these fields are safe for a PRE-race brief. No result fields exist to
    leak — there is no finish position here, only grid position and times.
    """

    driver_id: str
    position: int | None = None  # qualifying (grid) position, not the finish
    q_best_ms: int | None = None
    delta_pole_ms: int | None = None


class RaceDigest(WireModel):
    """The compact, as-of context a brief narrates — its only factual input."""

    prediction_id: str
    race: RaceIdentity
    dataset: DatasetIdentity
    record_sha256: str
    ensemble_winner_top: tuple[DigestPick, ...]
    ensemble_podium_top: tuple[DigestPick, ...]
    consensus: Consensus
    models: tuple[ModelDigestSummary, ...]  # sorted by model_id
    qualifying: tuple[QualifyingLine, ...]  # grid order, untimed drivers last


class BriefContent(WireModel):
    """The narrated brief — the schema a live response must match exactly."""

    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    talking_points: tuple[str, ...] = Field(min_length=1)
    consensus_note: str = Field(min_length=1)


class BriefPins(WireModel):
    """The data identities a live brief was pinned to, restated for the record."""

    dataset_digest: str
    record_sha256: str
    model_digests: dict[ModelId, str]
    ollama_model: str
    ollama_model_digest: str


class RaceBrief(WireModel):
    """The advisory race brief — stored outside the evidence hash chain.

    No recordSha256 of its own and no predecessor field: a brief cannot chain,
    so it can never masquerade as ledger evidence. The record it narrates is
    identified inside ``digest.recordSha256``.
    """

    schema_version: Literal[1] = BRIEF_SCHEMA_VERSION
    brief_type: Literal["race-brief"]
    prediction_id: str
    mode: Literal["fixture", "live"]
    evidence_basis: str
    race: RaceIdentity
    dataset: DatasetIdentity
    digest: RaceDigest
    content: BriefContent
    pins: BriefPins | None  # live only: what the model call was pinned to
    advisory_only: Literal[True]


@dataclass(frozen=True)
class BriefConfig:
    """Where and how the live brief runs; fixture mode ignores the Ollama fields."""

    mode: Literal["fixture", "live"]
    ollama_base_url: str | None
    ollama_model: str
    timeout_seconds: float


def brief_config_from_env(env: Mapping[str, str] | None = None) -> BriefConfig:
    """Mode selection: OLLAMA_BASE_URL set and non-empty -> live, else fixture."""
    environment: Mapping[str, str] = os.environ if env is None else env
    base_url = (environment.get(OLLAMA_BASE_URL_ENV) or "").strip() or None
    model = (environment.get(OLLAMA_MODEL_ENV) or "").strip() or DEFAULT_OLLAMA_MODEL
    raw_timeout = (environment.get(OLLAMA_TIMEOUT_ENV) or "").strip()
    timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
    return BriefConfig(
        mode="live" if base_url else "fixture",
        ollama_base_url=base_url,
        ollama_model=model,
        timeout_seconds=timeout,
    )


def prediction_digest(prediction: ModelPrediction) -> str:
    """sha256 of a model prediction's canonical JSON — its data identity."""
    payload = prediction.model_dump(by_alias=True)
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return sha256_hex(canonical.encode("utf-8"))


def qualifying_snapshot(
    dataset: PinnedDataset, season: int, round_number: int
) -> tuple[QualifyingLine, ...]:
    """The target round's own qualifying session — pre-race data, never results.

    This function is the brief module's only dataset access, and it reads only
    ``dataset.qualifying``: qualifying order is known before a race runs, so a
    PRE-race brief can cite it, while ``dataset.results`` is unreachable here.
    """
    rows = [
        row
        for row in dataset.qualifying
        if row.season == season and row.round == round_number
    ]
    best_times = [best_qualifying_ms(row) for row in rows]
    pole_ms = min(
        (value for value in best_times if value is not None), default=None
    )
    lines = [
        QualifyingLine(
            driver_id=row.driver_id,
            position=row.position,
            q_best_ms=best_ms,
            delta_pole_ms=(
                best_ms - pole_ms if best_ms is not None and pole_ms is not None else None
            ),
        )
        for row, best_ms in zip(rows, best_times, strict=True)
    ]
    return tuple(sorted(lines, key=_qualifying_sort_key))


def build_digest(
    record: PredictionRecord, qualifying: Sequence[QualifyingLine] = ()
) -> RaceDigest:
    """Compact, as-of digest of one committed prediction record.

    Everything comes from the record — built strictly from rounds before the
    target — plus the pre-race qualifying snapshot, so no race result can
    enter a PRE-race brief's inputs. The record must already be committed to
    the ledger: a brief pins recordSha256, and pinning an empty string would
    tie the narrative to nothing.
    """
    if not record.record_sha256:
        raise BriefRecordUnhashed(
            f"record {record.prediction_id!r} carries no recordSha256 — append it "
            "to the ledger before narrating it"
        )
    return RaceDigest(
        prediction_id=record.prediction_id,
        race=record.race,
        dataset=record.dataset,
        record_sha256=record.record_sha256,
        ensemble_winner_top=_top_picks(record.ensemble.winner, TOP_PICKS),
        ensemble_podium_top=_top_picks(record.ensemble.podium, TOP_PICKS),
        consensus=record.ensemble.consensus,
        models=tuple(
            _model_summary(prediction)
            for _, prediction in sorted(record.models.items())
        ),
        qualifying=tuple(sorted(qualifying, key=_qualifying_sort_key)),
    )


def render_fixture_brief(digest: RaceDigest) -> BriefContent:
    """Deterministic template render — same digest in, byte-identical brief out."""
    race = digest.race
    consensus = digest.consensus
    spread = f"{consensus.podium_spread:.3f}"
    leader = digest.ensemble_winner_top[0]
    return BriefContent(
        headline=(
            f"{race.name} ({race.season} round {race.round}): ensemble favors "
            f"{leader.driver_id} at {_fmt_pct(leader.probability)}"
        ),
        summary=(
            f"Pre-race advisory for the {race.season} {race.name}, round {race.round}: "
            f"{_leaders_clause(digest.ensemble_winner_top)}. Trained only on rounds "
            f"before this one; podium spread {spread} ({consensus.flag})."
        ),
        talking_points=(
            f"Ensemble winner probabilities: {_prob_list(digest.ensemble_winner_top, 3)}.",
            f"Ensemble podium probabilities: {_prob_list(digest.ensemble_podium_top, 3)}.",
            f"Model picks: {_model_picks(digest)}.",
            f"Cross-model agreement: podiumSpread {spread}, flag {consensus.flag}.",
            _qualifying_point(digest.qualifying),
            f"Training windows: {_training_windows(digest)}.",
        ),
        consensus_note=_consensus_note(consensus),
    )


def generate_brief(
    record: PredictionRecord,
    qualifying: Sequence[QualifyingLine] = (),
    config: BriefConfig | None = None,
) -> RaceBrief:
    """Narrate one committed prediction record.

    Mode comes from the config, which by default comes from the environment:
    OLLAMA_BASE_URL set -> live, unset -> deterministic fixture. The fixture
    brief never touches the network; the live brief pins dataset, record, and
    per-model digests in the system prompt and JSON-validates the response.
    """
    resolved = config if config is not None else brief_config_from_env()
    digest = build_digest(record, qualifying)
    if resolved.mode == "fixture":
        return _fixture_brief(digest)
    return _live_brief(digest, resolved)


def _fixture_brief(digest: RaceDigest) -> RaceBrief:
    return RaceBrief(
        brief_type="race-brief",
        prediction_id=digest.prediction_id,
        mode="fixture",
        evidence_basis=FIXTURE_BANNER,
        race=digest.race,
        dataset=digest.dataset,
        digest=digest,
        content=render_fixture_brief(digest),
        pins=None,
        advisory_only=True,
    )


def _live_brief(digest: RaceDigest, config: BriefConfig) -> RaceBrief:
    assert config.ollama_base_url is not None  # mode "live" implies a configured URL
    model_digest = pin_ollama_model(
        config.ollama_base_url, config.ollama_model, config.timeout_seconds
    )
    content = _chat_brief(digest, config)
    return RaceBrief(
        brief_type="race-brief",
        prediction_id=digest.prediction_id,
        mode="live",
        evidence_basis=LIVE_BANNER,
        race=digest.race,
        dataset=digest.dataset,
        digest=digest,
        content=content,
        pins=BriefPins(
            dataset_digest=digest.dataset.sha256,
            record_sha256=digest.record_sha256,
            model_digests={
                summary.model_id: summary.prediction_sha256 for summary in digest.models
            },
            ollama_model=config.ollama_model,
            ollama_model_digest=model_digest,
        ),
        advisory_only=True,
    )


def pin_ollama_model(base_url: str, model: str, timeout_seconds: float) -> str:
    """Pin the model's server-side identity via /api/tags (LZ §4a pattern).

    Returns the server-reported digest for the configured model. A model name
    without a tag also matches its tagged form (``brief-model`` matches
    ``brief-model:latest``); anything else is a refusal, never a guess.
    """
    request = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except OSError as error:  # refused, timed out, HTTP error — one live failure family
        raise ModelTimeout(f"Ollama unreachable at {base_url}: {error}") from error
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ModelNotPinned(f"/api/tags response is not valid JSON: {error}") from error
    entries = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ModelNotPinned("/api/tags response carries no models list")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name, digest_value = entry.get("name"), entry.get("digest")
        if not isinstance(name, str) or not isinstance(digest_value, str):
            continue
        if name == model or (":" not in model and name.split(":", 1)[0] == model):
            return digest_value
    raise ModelNotPinned(
        f"model {model!r} not found in /api/tags — cannot pin its identity"
    )


def _chat_brief(digest: RaceDigest, config: BriefConfig) -> BriefContent:
    """POST the digest to /api/chat and validate the response against the schema."""
    request = urllib.request.Request(
        f"{config.ollama_base_url.rstrip('/')}/api/chat",
        data=json.dumps(
            {
                "model": config.ollama_model,
                "messages": [
                    {"role": "system", "content": _system_prompt(digest)},
                    {"role": "user", "content": _user_prompt(digest)},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read()
    except OSError as error:  # refused, timed out, HTTP error — one live failure family
        raise ModelTimeout(
            f"Ollama unreachable or slow at {config.ollama_base_url}: {error}"
        ) from error
    return _validated_content(_response_content(body))


def _system_prompt(digest: RaceDigest) -> str:
    model_pins = "; ".join(
        f"{summary.model_id}={summary.prediction_sha256}" for summary in digest.models
    )
    return (
        "You are the race-brief narrator for the F1 Prediction Engine, an advisory, "
        "evidence-first demonstrator. Narrate ONLY the structured digest supplied in "
        "the user turn: no outside knowledge, no standings, no weather, no driver "
        "opinions. Every statement must be traceable to the digest. This brief is "
        f"pinned to exact data identities: datasetDigest={digest.dataset.sha256}; "
        f"recordSha256={digest.record_sha256}; modelDigests={model_pins}. Do not "
        "restate the digest identifiers in your output. Respond with ONLY a JSON "
        'object of this exact shape: {"headline": string, "summary": string, '
        '"talking_points": array of strings, "consensus_note": string}'
    )


def _user_prompt(digest: RaceDigest) -> str:
    payload = json.dumps(
        digest.model_dump(by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"Race digest to narrate:\n{payload}"


def _response_content(body: bytes) -> str:
    """Extract the model's content string from Ollama's chat envelope."""
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError as error:
        raise BriefInvalid(f"Ollama response is not valid JSON: {error}") from error
    message = envelope.get("message") if isinstance(envelope, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise BriefInvalid("Ollama response carries no message.content string")
    return content


def _validated_content(content: str) -> BriefContent:
    """Parse and schema-check the brief JSON — drift is refused, never passed through."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise BriefInvalid(f"brief response is not valid JSON: {error}") from error
    try:
        return BriefContent.model_validate(parsed)
    except ValidationError as error:
        raise BriefInvalid(
            f"brief response failed the Brief schema: {error}"
        ) from error


def _top_picks(distribution: dict[str, float], count: int) -> tuple[DigestPick, ...]:
    """Strongest-first picks; ties broken by driver_id so ordering is stable."""
    ordered = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    return tuple(
        DigestPick(driver_id=driver, probability=probability)
        for driver, probability in ordered[:count]
    )


def _model_summary(prediction: ModelPrediction) -> ModelDigestSummary:
    return ModelDigestSummary(
        model_id=prediction.model_id,
        winner_pick=_top_picks(prediction.winner, 1)[0],
        winner_top=_top_picks(prediction.winner, 3),
        podium_top=_top_picks(prediction.podium, 3),
        prediction_sha256=prediction_digest(prediction),
        trained_through_season=prediction.diagnostics.trained_through_season,
        trained_through_round=prediction.diagnostics.trained_through_round,
        seed=prediction.diagnostics.seed,
    )


def _qualifying_sort_key(line: QualifyingLine) -> tuple[bool, int, bool, int, str]:
    """Grid order; untimed, unpositioned drivers last, driver_id as the tiebreak."""
    return (
        line.position is None,
        line.position or 0,
        line.q_best_ms is None,
        line.q_best_ms or 0,
        line.driver_id,
    )


def _fmt_pct(probability: float) -> str:
    return f"{probability * 100:.1f}%"


def _prob_list(picks: Sequence[DigestPick], count: int) -> str:
    return ", ".join(
        f"{pick.driver_id} {_fmt_pct(pick.probability)}" for pick in picks[:count]
    )


def _leaders_clause(winner_top: Sequence[DigestPick]) -> str:
    first = winner_top[0]
    if len(winner_top) >= 3:
        second, third = winner_top[1], winner_top[2]
        return (
            f"the ensemble gives {first.driver_id} the strongest winner probability "
            f"({_fmt_pct(first.probability)}), ahead of {second.driver_id} "
            f"({_fmt_pct(second.probability)}) and {third.driver_id} "
            f"({_fmt_pct(third.probability)})"
        )
    if len(winner_top) == 2:
        second = winner_top[1]
        return (
            f"the ensemble gives {first.driver_id} the strongest winner probability "
            f"({_fmt_pct(first.probability)}), ahead of {second.driver_id} "
            f"({_fmt_pct(second.probability)})"
        )
    return (
        f"the ensemble gives {first.driver_id} the strongest winner probability "
        f"({_fmt_pct(first.probability)})"
    )


def _model_picks(digest: RaceDigest) -> str:
    return "; ".join(
        f"{summary.model_id} favors {summary.winner_pick.driver_id} "
        f"({_fmt_pct(summary.winner_pick.probability)})"
        for summary in digest.models
    )


def _training_windows(digest: RaceDigest) -> str:
    return "; ".join(
        f"{summary.model_id} through {summary.trained_through_season} "
        f"R{summary.trained_through_round}"
        for summary in digest.models
    )


def _qualifying_point(qualifying: Sequence[QualifyingLine]) -> str:
    if not qualifying:
        return (
            "Qualifying snapshot: unavailable for this round "
            "(declared limitation, no guess)."
        )
    pole = qualifying[0]
    pole_ms = f" at {pole.q_best_ms} ms" if pole.q_best_ms is not None else ""
    grid = ", ".join(
        f"{line.driver_id} P{line.position}"
        if line.position is not None
        else line.driver_id
        for line in qualifying[:TOP_PICKS]
    )
    return f"Qualifying (as-of, pre-race): pole {pole.driver_id}{pole_ms}; grid: {grid}."


def _consensus_note(consensus: Consensus) -> str:
    spread = f"{consensus.podium_spread:.3f}"
    threshold = f"{PODIUM_SPREAD_OK_THRESHOLD:.2f}"
    if consensus.flag == "OK":
        return (
            f"Models broadly agree on the podium picture: podium spread {spread} is "
            f"within the OK threshold ({threshold})."
        )
    return (
        f"Models disagree on the podium: podium spread {spread} exceeds the OK "
        f"threshold ({threshold}). The disagreement is flagged, not suppressed — "
        "treat the predicted ordering as uncertain."
    )
