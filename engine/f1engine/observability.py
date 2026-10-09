"""Typed observability — closed signal enum, redact-at-creation events.

Contract (spec, engine/f1engine/observability, mirroring LZ §4e): a closed
signal enum, events redacted before any consumer sees them, a Prometheus
/metrics render, and alert rules where every signal keeps at least one rule
(enforced by test in the observability task).
"""

from enum import StrEnum


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


def emit(signal: Signal, status: EventStatus, detail: dict[str, object]) -> None:
    """Emit one redact-at-creation event on the observability bus."""
    raise NotImplementedError("event bus is implemented by the observability task")
