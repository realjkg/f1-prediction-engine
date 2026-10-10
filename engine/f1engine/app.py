"""FastAPI application factory — the read-only API over the ledger + snapshot.

The engine's HTTP surface is a READ surface (spec: "Two runtimes, one evidence
contract"): every endpoint serves the pinned snapshot or the evidence ledger,
and none of them recompute predictions — training, ensembling, and ledger
writes belong to the engine tasks and the demo scenario. The game-scoring
endpoint computes points, not predictions: the scoring module's pure
arithmetic over the ledger's stored verdict and the snapshot's classified
results — no model inference on the request path. Response schemas
reuse the engine's wire models directly (``PredictionRecord``,
``ModelPrediction``, ``EnsembleVerdict``), so the API cannot drift from the
prediction-record contract the ledger writes: ``advisoryOnly`` and
``dataLimitations`` reach every prediction-bearing response by construction,
not by copy.

Failure discipline at the boundary:

- A snapshot that fails version/hash verification refuses app startup with
  the typed ``DATA_SNAPSHOT_*`` errors — the demo contract's fail-closed
  preflight, applied when the API is built.
- A ledger that fails chain verification is refused per request with a 503
  carrying the typed evidence code (``EVIDENCE_TAMPERED``,
  ``EVIDENCE_CHAIN_GAP``, ``EVIDENCE_SCHEMA_INVALID``) — evidence that cannot
  be verified is evidence that is not served. An absent ledger is not an
  error: the store is simply empty until the demo scenario writes records.
- Unknown races 404 with a typed code: ``RACE_UNKNOWN`` (race not in the
  snapshot) or ``PREDICTIONS_NOT_FOUND`` (race known, no records yet).
- Game-scoring refusals are typed too: a race with no classified result 404s
  with ``RESULT_NOT_FOUND``, and a call that is not three distinct snapshot
  drivers 422s with ``CALL_MALFORMED``.

Observability boundary: ``/api/events`` and ``/metrics`` are READS. The event
bus and the engine's metric series are the observability task's domain; this
surface consumes them through small injectable ports (``EventSource``, plus
the API's own request counters) with safe defaults, and never touches
observability internals.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from f1engine.backtest import ClassifiedResult, classify_round
from f1engine.ensemble import PODIUM_SPREAD_OK_THRESHOLD
from f1engine.evidence import (
    EvidenceError,
    EvidenceSchemaInvalid,
    PredictionRecord,
    verify_chain,
)
from f1engine.ingestion import PinnedDataset, load_snapshot
from f1engine.observability import EventStatus, Signal
from f1engine.scoring import CallScore, PitCall, score_call_sheet
from f1engine.wire import WireModel

APP_TITLE = "F1 Prediction Engine"
APP_VERSION = "0.1.0"

ADVISORY_NOTICE = (
    "All predictions are advisory-only: statistical evidence computed from the "
    "pinned 2020–2024 dataset, never authority over real-world outcomes. Every "
    "record declares its own dataLimitations and dataset hash."
)

DEFAULT_LEDGER_PATH = "data/evidence/ledger.jsonl"
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


def _brief_mode(value: str | None) -> Literal["fixture", "live"]:
    """Parse F1E_BRIEF_MODE; invalid values fail toward the safe default."""
    return value if value in ("fixture", "live") else "fixture"


@dataclass(frozen=True)
class ApiSettings:
    """Engine API configuration — env-driven, loopback-safe defaults."""

    data_dir: Path = Path("data/snapshot")
    ledger_path: Path = Path(DEFAULT_LEDGER_PATH)
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    brief_mode: Literal["fixture", "live"] = "fixture"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ApiSettings:
        """Read the F1E_* variables (see .env.example); bad values fall back."""
        environ = os.environ if env is None else env
        origins_raw = environ.get("F1E_CORS_ORIGINS")
        origins = (
            tuple(o.strip() for o in origins_raw.split(",") if o.strip())
            if origins_raw is not None
            else DEFAULT_CORS_ORIGINS
        )
        return cls(
            data_dir=Path(environ.get("F1E_DATA_DIR", "data/snapshot")),
            ledger_path=Path(environ.get("F1E_LEDGER_PATH", DEFAULT_LEDGER_PATH)),
            cors_origins=origins,
            brief_mode=_brief_mode(environ.get("F1E_BRIEF_MODE")),
        )


# ---------------------------------------------------------------------------
# Response schemas — new envelopes only; record shapes are the engine's own.
# ---------------------------------------------------------------------------


class RaceSummary(WireModel):
    """One race in the pinned snapshot — the Race screen's picker rows."""

    season: int
    round: int
    race_id: str
    name: str
    date: str
    completed: bool  # result rows for this round exist in the snapshot


class RacesView(WireModel):
    races: list[RaceSummary]
    total: int


class ClassifiedFinish(WireModel):
    """One classified finishing position — position-ascending on the result."""

    position: int
    driver_id: str


class RaceResultView(WireModel):
    """A round's classified result — the reveal's actual column.

    ``podium`` is the backtest's podium@3 actual (first three classified;
    shorter when fewer finished) and ``classified`` is the full classified
    order, so the reveal can name the P4 heartbreak.
    """

    race_id: str
    season: int
    round: int
    name: str
    date: str
    winner: str
    podium: list[str]
    classified: list[ClassifiedFinish]


class PredictionsView(WireModel):
    """Every ledger record answering one race — per-model + ensemble evidence."""

    predictions: list[PredictionRecord]
    total: int


class ModelInfo(WireModel):
    """Static roster entry for the Models screen; metrics live on the records."""

    model_id: str
    method: str
    role: str
    consensus_threshold: float | None = None  # the ensemble entry only


class ModelsView(WireModel):
    models: list[ModelInfo]


class EventView(WireModel):
    """One observability event as the API serves it.

    ``signal`` and ``status`` are the closed enums; ``detail`` is already
    redacted at creation by the observability layer, never here.
    """

    signal: Signal
    status: EventStatus
    occurred_at: str
    detail: dict[str, object]


class EventsView(WireModel):
    events: list[EventView]
    total: int


class EvidencePage(WireModel):
    """One page of ledger records plus the verification status it was served under."""

    records: list[PredictionRecord]
    total: int
    offset: int
    limit: int
    chain_valid: bool  # always true in a served page — a failed page is a 503


class ConfigView(WireModel):
    """The Settings screen's operating contract."""

    engine_version: str
    dataset_version: str
    advisory_only: bool
    advisory_notice: str
    consensus_threshold: float
    brief_mode: Literal["fixture", "live"]


_MODEL_INFO: tuple[ModelInfo, ...] = (
    ModelInfo(
        model_id="m1-gbm",
        method=(
            "Gradient-boosted trees on engineered as-of features "
            "(HistGradientBoostingClassifier)"
        ),
        role="The ML voice — strongest expected accuracy, drives the headline numbers",
    ),
    ModelInfo(
        model_id="m2-logit",
        method="Logistic regression on normalized features",
        role="Interpretable counterweight — m1/m2 disagreement is itself informative",
    ),
    ModelInfo(
        model_id="m3-form",
        method="Rolling-form heuristic — weighted recent finishes plus qualifying",
        role="Sanity floor — if m1 cannot beat it in backtest, that is a visible finding",
    ),
    ModelInfo(
        model_id="ensemble",
        method=(
            "Performance-weighted blend with a numeric consensus flag "
            "(max pairwise JS divergence on podium distributions)"
        ),
        role="Arbitrated verdict — cross-model disagreement flagged, never suppressed",
        consensus_threshold=PODIUM_SPREAD_OK_THRESHOLD,
    ),
)


# ---------------------------------------------------------------------------
# Read-side stores and ports.
# ---------------------------------------------------------------------------


class RaceCatalog:
    """Read view over the pinned snapshot's races table."""

    def __init__(self, dataset: PinnedDataset) -> None:
        self._dataset = dataset
        self._completed = {
            (result.season, result.round, result.race_id) for result in dataset.results
        }
        self._races = tuple(
            RaceSummary(
                season=race.season,
                round=race.round,
                race_id=race.race_id,
                name=race.name,
                date=race.date,
                completed=(race.season, race.round, race.race_id) in self._completed,
            )
            for race in sorted(dataset.races, key=lambda row: (row.season, row.round))
        )
        self._known_race_ids = {race.race_id for race in self._races}

    @property
    def dataset(self) -> PinnedDataset:
        """The validated snapshot this catalog was built from."""
        return self._dataset

    def list_races(self) -> RacesView:
        return RacesView(races=list(self._races), total=len(self._races))

    def knows(self, race_id: str) -> bool:
        return race_id in self._known_race_ids

    def race(self, race_id: str) -> RaceSummary | None:
        """One race by id, or None when the snapshot does not know it."""
        return next((race for race in self._races if race.race_id == race_id), None)


class LedgerStore:
    """Read view over the append-only ledger — verified before it is served.

    Every read re-verifies the sha256 chain: the evidence contract's
    verify-on-use means a chain that verified on write may still have been
    edited on disk since. Raises the typed evidence errors on tamper, gap, or
    schema failure; an absent file is an empty ledger, not an error.
    """

    def __init__(self, ledger_path: Path) -> None:
        self._ledger_path = ledger_path

    def read_all(self) -> list[PredictionRecord]:
        verify_chain(self._ledger_path)
        if not self._ledger_path.exists():
            return []
        return [
            self._record(index, line)
            for index, line in enumerate(self._lines())
        ]

    def records_for_race(self, race_id: str) -> list[PredictionRecord]:
        return [
            record for record in self.read_all() if record.race.race_id == race_id
        ]

    def page(self, offset: int, limit: int) -> EvidencePage:
        records = self.read_all()
        return EvidencePage(
            records=records[offset : offset + limit],
            total=len(records),
            offset=offset,
            limit=limit,
            chain_valid=True,
        )

    def _lines(self) -> list[str]:
        return [
            line
            for line in self._ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _record(self, index: int, line: str) -> PredictionRecord:
        try:
            payload = json.loads(line)
            return PredictionRecord.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as error:
            raise EvidenceSchemaInvalid(
                f"ledger line {index} failed the closed record schema: {error}"
            ) from error


class EventSource(Protocol):
    """Read port over the observability event store.

    The observability task owns the event bus (emit, redaction, persistence);
    the API consumes it through this port and never touches its internals.
    The default source is empty until that bus exists.
    """

    def list_events(self) -> Sequence[EventView]: ...


class NullEventSource:
    """The empty event store — the default until the observability task lands."""

    def list_events(self) -> Sequence[EventView]:
        return ()


# ---------------------------------------------------------------------------
# API-serving metrics: a request counter and build info, Prometheus-rendered.
# Deliberately additive — the engine's own metric series belong to the
# observability task's registry, which can own the renderer when it lands.
# ---------------------------------------------------------------------------


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class ApiMetrics:
    """Request counter + latency sum/count + build info for /metrics."""

    def __init__(self, version: str) -> None:
        self._version = version
        self._request_counts: dict[tuple[str, str, int], int] = {}
        self._duration_seconds: dict[tuple[str, str, int], float] = {}

    def observe_request(
        self, method: str, path_template: str, status: int, elapsed_seconds: float
    ) -> None:
        key = (method, path_template, status)
        self._request_counts[key] = self._request_counts.get(key, 0) + 1
        self._duration_seconds[key] = (
            self._duration_seconds.get(key, 0.0) + elapsed_seconds
        )

    def render(self) -> str:
        lines = [
            "# HELP f1engine_build_info Engine build metadata (always 1).",
            "# TYPE f1engine_build_info gauge",
            f'f1engine_build_info{{version="{_escape_label(self._version)}"}} 1',
            "# HELP f1engine_http_requests_total HTTP requests handled by the engine API.",
            "# TYPE f1engine_http_requests_total counter",
        ]
        for (method, path, status), count in sorted(self._request_counts.items()):
            labels = (
                f'method="{_escape_label(method)}",path="{_escape_label(path)}",'
                f'status="{status}"'
            )
            lines.append(f"f1engine_http_requests_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP f1engine_http_request_duration_seconds Cumulative request handling time.",
                "# TYPE f1engine_http_request_duration_seconds summary",
            ]
        )
        for (method, path, status), seconds in sorted(self._duration_seconds.items()):
            labels = (
                f'method="{_escape_label(method)}",path="{_escape_label(path)}",'
                f'status="{status}"'
            )
            count = self._request_counts[(method, path, status)]
            lines.append(f"f1engine_http_request_duration_seconds_count{{{labels}}} {count}")
            lines.append(f"f1engine_http_request_duration_seconds_sum{{{labels}}} {seconds!r}")
        return "\n".join(lines) + "\n"


class RequestMetricsMiddleware:
    """Pure-ASGI request observer — labels are route templates, not raw paths."""

    def __init__(self, app: ASGIApp, metrics: ApiMetrics) -> None:
        self.app = app
        self._metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code: int | None = None

        async def send_observing(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_observing)
        finally:
            template = getattr(scope.get("route"), "path", None)
            self._metrics.observe_request(
                method=scope["method"],
                path_template=template or "unmatched",
                status=status_code if status_code is not None else 500,
                elapsed_seconds=time.perf_counter() - started,
            )


# ---------------------------------------------------------------------------
# Routes — closures over the stores wired in create_app.
# ---------------------------------------------------------------------------


def _error(status_code: int, code: str, message: str) -> HTTPException:
    """A typed API error: {"detail": {"code": ..., "message": ...}}."""
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


def _classified_result(dataset: PinnedDataset, race_id: str) -> ClassifiedResult | None:
    """Classify one race's results with the backtest's shared classifier."""
    entries = [
        (row.position, row.driver_id)
        for row in dataset.results
        if row.race_id == race_id
    ]
    return classify_round(entries)


def _parse_call(raw: str | None, dataset: PinnedDataset) -> PitCall:
    """Parse 'P1,P2,P3' into a PitCall — typed 422 on any malformed call.

    A call must name three distinct drivers from the snapshot's drivers
    table. A known driver who did not race this round is a wrong call —
    scored as a MISS, not refused.
    """
    picks = [part.strip() for part in raw.split(",")] if raw and raw.strip() else []
    if len(picks) != 3 or any(not pick for pick in picks):
        raise _error(
            422,
            "CALL_MALFORMED",
            f"call must be exactly three driver ids 'P1,P2,P3', got {raw!r}",
        )
    if len(set(picks)) != 3:
        raise _error(
            422, "CALL_MALFORMED", f"call must name three distinct drivers, got {raw!r}"
        )
    known = {driver.driver_id for driver in dataset.drivers}
    unknown = sorted(set(picks) - known)
    if unknown:
        raise _error(
            422,
            "CALL_MALFORMED",
            f"call names drivers not in the pinned snapshot: {unknown}",
        )
    return PitCall(p1=picks[0], p2=picks[1], p3=picks[2])


def create_app(
    settings: ApiSettings | None = None,
    *,
    dataset: PinnedDataset | None = None,
    event_source: EventSource | None = None,
) -> FastAPI:
    """Create the engine API app.

    ``dataset`` and ``event_source`` are injection points: tests pass
    fixtures, and the observability task can back the default empty event
    source with the real bus. When no dataset is injected, the pinned
    snapshot is loaded (version + hash verified) at creation — a snapshot
    that fails verification refuses the app, per the demo contract.
    """
    resolved = settings if settings is not None else ApiSettings.from_env()
    loaded = dataset if dataset is not None else load_snapshot(resolved.data_dir)
    catalog = RaceCatalog(loaded)
    ledger = LedgerStore(resolved.ledger_path)
    events = event_source if event_source is not None else NullEventSource()
    metrics = ApiMetrics(APP_VERSION)

    app = FastAPI(title=APP_TITLE, version=APP_VERSION)
    app.state.settings = resolved
    app.state.dataset = loaded
    app.state.race_catalog = catalog
    app.state.ledger_store = ledger
    app.state.event_source = events
    app.state.metrics = metrics

    # CORS first, metrics second: the metrics middleware is outermost, so the
    # counter sees every request the server accepts, including rejected CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_methods=["GET"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.add_middleware(RequestMetricsMiddleware, metrics=metrics)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(
            content=metrics.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/api/races")
    def list_races() -> RacesView:
        """The snapshot's race list — the Race screen's picker."""
        return catalog.list_races()

    @app.get("/api/predictions/{race_id}")
    def race_predictions(race_id: str) -> PredictionsView:
        """The ledger's prediction records for one race, per-model + ensemble."""
        if not catalog.knows(race_id):
            raise _error(
                404, "RACE_UNKNOWN", f"no race {race_id!r} in the pinned snapshot"
            )
        try:
            records = ledger.records_for_race(race_id)
        except EvidenceError as error:
            raise _error(503, error.code, str(error)) from error
        if not records:
            raise _error(
                404,
                "PREDICTIONS_NOT_FOUND",
                f"no prediction records for {race_id!r} in the ledger",
            )
        return PredictionsView(predictions=records, total=len(records))

    @app.get("/api/races/{race_id}/result")
    def race_result(race_id: str) -> RaceResultView:
        """A round's classified result — podium first, full order behind it."""
        race = catalog.race(race_id)
        if race is None:
            raise _error(
                404, "RACE_UNKNOWN", f"no race {race_id!r} in the pinned snapshot"
            )
        result = _classified_result(loaded, race_id)
        if result is None:
            raise _error(
                404,
                "RESULT_NOT_FOUND",
                f"no classified result for {race_id!r} in the snapshot",
            )
        return RaceResultView(
            race_id=race_id,
            season=race.season,
            round=race.round,
            name=race.name,
            date=race.date,
            winner=result.winner,
            podium=list(result.podium),
            classified=[
                ClassifiedFinish(position=position, driver_id=driver_id)
                for position, driver_id in enumerate(result.classified, start=1)
            ],
        )

    @app.get("/api/races/{race_id}/score")
    def race_score(
        race_id: str,
        call: Annotated[str | None, Query()] = None,
        streak_before: Annotated[int, Query(ge=0)] = 0,
    ) -> CallScore:
        """Score one locked call — the client never invents scores.

        Stateless by design: the pit-wall record (prior streak) lives
        client-side, so the caller passes ``streak_before`` and the engine
        folds it with the pure streak math. The round's consensus flag comes
        from the ledger's latest prediction record — never from the caller,
        never recomputed — so a round with no prediction record has no
        ensemble verdict to double on and is refused (PREDICTIONS_NOT_FOUND).
        """
        race = catalog.race(race_id)
        if race is None:
            raise _error(
                404, "RACE_UNKNOWN", f"no race {race_id!r} in the pinned snapshot"
            )
        result = _classified_result(loaded, race_id)
        if result is None:
            raise _error(
                404,
                "RESULT_NOT_FOUND",
                f"no classified result for {race_id!r} in the snapshot",
            )
        try:
            records = ledger.records_for_race(race_id)
        except EvidenceError as error:
            raise _error(503, error.code, str(error)) from error
        if not records:
            raise _error(
                404,
                "PREDICTIONS_NOT_FOUND",
                f"no prediction record for {race_id!r} — no ensemble verdict, "
                "so no consensus flag to score against",
            )
        flag = records[-1].ensemble.consensus.flag  # latest append; verdicts are deterministic
        return score_call_sheet(_parse_call(call, loaded), result, flag, streak_before)

    @app.get("/api/models")
    def model_metadata() -> ModelsView:
        """The model roster — static method/role copy; per-model metrics live on records."""
        return ModelsView(models=list(_MODEL_INFO))

    @app.get("/api/evidence")
    def evidence_page(
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> EvidencePage:
        """One page of ledger records, served only if the chain verifies."""
        try:
            return ledger.page(offset, limit)
        except EvidenceError as error:
            raise _error(503, error.code, str(error)) from error

    @app.get("/api/events")
    def list_events() -> EventsView:
        """Observability events from the (injected) closed-signal store."""
        served = list(events.list_events())
        return EventsView(events=served, total=len(served))

    @app.get("/api/config")
    def engine_config() -> ConfigView:
        """The Settings screen's operating contract."""
        return ConfigView(
            engine_version=APP_VERSION,
            dataset_version=loaded.dataset_id,
            advisory_only=True,
            advisory_notice=ADVISORY_NOTICE,
            consensus_threshold=PODIUM_SPREAD_OK_THRESHOLD,
            brief_mode=resolved.brief_mode,
        )

    return app
