"""Typed observability — closed signal enum, redact-at-creation events.

Contract (spec, engine/f1engine/observability, mirroring LZ §4e): a closed
signal enum — every emitted event is one of the enum values, nothing
freeform — events redacted before any consumer sees them (a credential-shaped
field never becomes part of a stored event), an in-process Prometheus
/metrics render, and alert rules over the closed signals where coverage is
enforced by test: every rule references a defined signal, and every signal is
either covered by a rule or explicitly listed as uncovered-by-design with a
reason.

The bus is deliberately in-process and bounded: events are diagnostics for
the demo and the API's events surface, not a durable sink — the durable,
tamper-evident record is the evidence ledger. Events carry a process-local
sequence number, never a wall-clock timestamp, so nothing observability
touches can perturb the determinism gate on stored records.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from itertools import count
from pathlib import Path
from typing import Final

import yaml
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

from f1engine.wire import WireModel

ALERT_RULES_PATH: Final[Path] = Path(__file__).with_name("alert-rules.yaml")

MAX_EVENTS = 1000
REDACTED = "[REDACTED]"


class Signal(StrEnum):
    """Closed set of production signals. Extending this enum is a spec change."""

    DATA_INGEST = "data-ingest"
    PREDICTION_LATENCY = "prediction-latency"
    PREDICTION_DISAGREEMENT = "prediction-disagreement"
    BACKTEST_ACCURACY = "backtest-accuracy"
    BRIEF_GENERATION = "brief-generation"
    EVIDENCE_LIFECYCLE = "evidence-lifecycle"


class EventStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    FAILED = "failed"


# Credential-shaped material — keys and values are scanned at creation so a
# secret never becomes part of a stored event (LZ redact-at-creation).
_CREDENTIAL_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|credential|api[_\-]?key)", re.IGNORECASE
)
_CREDENTIAL_VALUE_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|credential|api[_\-]?key)\s*[:=]\s*[^\s;,]+"
    r"|\bBearer\s+[A-Za-z0-9._\-]+",
)


class Event(WireModel):
    """One redacted observability event, as the events surface shows it."""

    seq: int
    signal: Signal
    status: EventStatus
    detail: dict[str, object]


_events: deque[Event] = deque(maxlen=MAX_EVENTS)
_lock = threading.Lock()
_sequence = count(start=1)

EVENTS_TOTAL = Counter(
    "f1engine_events",
    "Observability events emitted, by signal and status",
    ["signal", "status"],
)
PREDICTION_DURATION = Histogram(
    "f1engine_prediction_duration_seconds",
    "Per-model predict() wall-clock duration",
    ["model"],
)


def _redact_value(value: object) -> object:
    """Redact credential-shaped material inside one value."""
    if isinstance(value, str):
        return _CREDENTIAL_VALUE_PATTERN.sub(REDACTED, value)
    if isinstance(value, dict):
        return {key: _redact_entry(key, item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def _redact_entry(key: object, value: object) -> object:
    """A credential-named key redacts its whole value, whatever it holds."""
    if isinstance(key, str) and _CREDENTIAL_KEY_PATTERN.search(key):
        return REDACTED
    return _redact_value(value)


def emit(signal: Signal, status: EventStatus, detail: dict[str, object]) -> Event:
    """Emit one redact-at-creation event on the observability bus.

    The detail dict is redacted (recursively) before the Event record exists;
    the Prometheus counter is incremented before the bus append returns, so
    the rendered metrics cannot under-report emitted events.
    """
    redacted = _redact_value(detail)
    assert isinstance(redacted, dict)  # dicts redact to dicts by construction
    EVENTS_TOTAL.labels(signal=signal.value, status=status.value).inc()
    with _lock:
        event = Event(
            seq=next(_sequence), signal=signal, status=status, detail=redacted
        )
        _events.append(event)
    return event


def observe_prediction_duration(model_id: str, seconds: float) -> None:
    """Record one per-model predict duration on the Prometheus histogram."""
    PREDICTION_DURATION.labels(model=model_id).observe(seconds)


def events() -> tuple[Event, ...]:
    """The bounded in-process event log, oldest first."""
    with _lock:
        return tuple(_events)


def clear_events() -> None:
    """Drop the in-process event log (tests, and bus resets between runs)."""
    with _lock:
        _events.clear()


def render_metrics() -> tuple[bytes, str]:
    """The Prometheus exposition body and its content type, for /metrics."""
    return generate_latest(), CONTENT_TYPE_LATEST


@dataclass(frozen=True)
class AlertRule:
    """One alert over the closed signals, from alert-rules.yaml."""

    name: str
    signal: Signal
    statuses: tuple[EventStatus, ...]
    severity: str
    description: str


@dataclass(frozen=True)
class UncoveredSignal:
    """A signal deliberately left without a rule — with the reason on record."""

    signal: Signal
    reason: str


def load_alert_rules(
    path: Path = ALERT_RULES_PATH,
) -> tuple[tuple[AlertRule, ...], tuple[UncoveredSignal, ...]]:
    """Parse alert-rules.yaml into typed rules and explicit uncovered signals.

    Raises ValueError on a malformed rule (missing field, unknown signal or
    status, duplicate name) — the coverage test turns that into a red CI run
    rather than a silently uncovered signal.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} must contain a mapping")
    rules: list[AlertRule] = []
    seen_names: set[str] = set()
    for index, entry in enumerate(document.get("rules") or []):
        rule = _alert_rule(entry, index, path.name)
        if rule.name in seen_names:
            raise ValueError(f"{path.name}: duplicate rule name {rule.name!r}")
        seen_names.add(rule.name)
        rules.append(rule)
    uncovered: list[UncoveredSignal] = []
    for entry in document.get("uncoveredByDesign") or []:
        if not isinstance(entry, dict) or "signal" not in entry or "reason" not in entry:
            raise ValueError(
                f"{path.name}: uncoveredByDesign entries need signal + reason"
            )
        uncovered.append(
            UncoveredSignal(signal=_signal(entry["signal"]), reason=str(entry["reason"]))
        )
    return tuple(rules), tuple(uncovered)


def _alert_rule(entry: object, index: int, source: str) -> AlertRule:
    if not isinstance(entry, dict):
        raise ValueError(f"{source}: rule {index} must be a mapping")
    for field in ("name", "signal", "statuses", "severity", "description"):
        if field not in entry:
            raise ValueError(f"{source}: rule {index} is missing {field!r}")
    statuses = tuple(EventStatus(status) for status in entry["statuses"])
    return AlertRule(
        name=str(entry["name"]),
        signal=_signal(entry["signal"]),
        statuses=statuses,
        severity=str(entry["severity"]),
        description=str(entry["description"]),
    )


def _signal(name: object) -> Signal:
    """Signal by value — an unknown name is a broken rule, not a new signal."""
    try:
        return Signal(str(name))
    except ValueError as error:
        raise ValueError(
            f"unknown signal {name!r} — the signal enum is closed"
        ) from error
