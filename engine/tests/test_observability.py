"""Observability contract tests — closed signals, redaction, metrics, alerts.

Spec row "Observability": closed signal enum; redact-at-creation events; a
Prometheus-format /metrics render; alert-rules.yaml where every rule
references a defined signal and every signal is either covered or explicitly
uncovered-by-design — the accelerator's own invariant (LZ §4e), enforced by
test here.
"""

from __future__ import annotations

import pytest

from f1engine.observability import (
    MAX_EVENTS,
    REDACTED,
    AlertRule,
    Event,
    EventStatus,
    Signal,
    clear_events,
    emit,
    events,
    load_alert_rules,
    observe_prediction_duration,
    render_metrics,
)

ALL_SIGNALS = {
    "data-ingest",
    "prediction-latency",
    "prediction-disagreement",
    "backtest-accuracy",
    "brief-generation",
    "evidence-lifecycle",
}


@pytest.fixture(autouse=True)
def clean_bus():
    clear_events()
    yield
    clear_events()


def test_signal_enum_is_closed() -> None:
    assert {signal.value for signal in Signal} == ALL_SIGNALS


def test_emit_keeps_events_bounded_and_sequenced() -> None:
    for _ in range(MAX_EVENTS + 50):
        emit(Signal.DATA_INGEST, EventStatus.OK, {"round": 1})
    log = events()
    assert len(log) == MAX_EVENTS  # bounded bus, oldest dropped
    seqs = [event.seq for event in log]
    assert seqs == sorted(seqs)
    assert seqs[-1] - seqs[0] == MAX_EVENTS - 1


def test_credential_named_keys_redact_at_creation() -> None:
    emit(
        Signal.DATA_INGEST,
        EventStatus.OK,
        {"api_key": "sk-live-abc123", "nested": {"authToken": "abc.def"}, "round": 4},
    )
    stored = events()[-1]
    assert stored.detail["api_key"] == REDACTED
    assert stored.detail["nested"] == {"authToken": REDACTED}
    assert stored.detail["round"] == 4  # ordinary fields pass untouched
    assert "sk-live-abc123" not in str(stored.detail)


def test_credential_shaped_string_values_redact() -> None:
    event = emit(
        Signal.BRIEF_GENERATION,
        EventStatus.DEGRADED,
        {
            "note": "request failed with token=abcdef123456; retrying",
            "auth": "Bearer eyJhbGciOiJIUzI1Ncw",
            "endpoint": "http://localhost:11434/api/chat",  # benign URL passes
        },
    )
    assert event.detail["note"] == "request failed with [REDACTED]; retrying"
    assert event.detail["auth"] == REDACTED
    assert event.detail["endpoint"] == "http://localhost:11434/api/chat"
    assert "abcdef123456" not in str(event.detail)


def test_render_metrics_is_prometheus_format() -> None:
    emit(Signal.DATA_INGEST, EventStatus.OK, {"dataset": "2026.10.0"})
    observe_prediction_duration("m1-gbm", 0.012)
    body, content_type = render_metrics()
    text = body.decode("utf-8")
    assert content_type.startswith("text/plain")
    assert "# TYPE f1engine_events_total counter" in text
    assert 'f1engine_events_total{signal="data-ingest",status="ok"}' in text
    assert "# TYPE f1engine_prediction_duration_seconds histogram" in text
    assert 'f1engine_prediction_duration_seconds_count{model="m1-gbm"}' in text


class TestAlertRuleCoverage:
    @pytest.fixture()
    def loaded(self):
        return load_alert_rules()

    def test_every_rule_references_a_defined_signal_and_statuses(self, loaded) -> None:
        rules, _ = loaded
        assert rules, "alert-rules.yaml must declare at least one rule"
        for rule in rules:
            assert isinstance(rule, AlertRule)
            assert rule.signal in Signal  # closed enum membership
            assert rule.statuses  # a rule that fires on nothing is broken
            assert all(status in EventStatus for status in rule.statuses)
            assert rule.severity in {"info", "warning", "critical"}

    def test_every_signal_covered_or_explicitly_uncovered(self, loaded) -> None:
        rules, uncovered = loaded
        covered = {rule.signal for rule in rules}
        uncovered_signals = {entry.signal for entry in uncovered}
        assert covered | uncovered_signals == set(Signal)
        assert not covered & uncovered_signals  # a signal is one or the other

    def test_uncovered_signals_carry_a_reason(self, loaded) -> None:
        _, uncovered = loaded
        assert uncovered, "the explicit-uncovered escape hatch must be exercised"
        assert all(entry.reason.strip() for entry in uncovered)

    def test_rule_names_are_unique(self, loaded) -> None:
        rules, _ = loaded
        names = [rule.name for rule in rules]
        assert len(names) == len(set(names))

    def test_unknown_signal_in_rules_is_refused(self, tmp_path) -> None:
        bad = tmp_path / "bad-rules.yaml"
        bad.write_text(
            "rules:\n  - name: typo-rule\n    signal: data-ingestt\n"
            "    statuses: [blocked]\n    severity: critical\n"
            '    description: "typoed signal"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="closed"):
            load_alert_rules(bad)

    def test_event_model_serializes_camel_case(self) -> None:
        event = Event.model_validate(
            {"seq": 1, "signal": "data-ingest", "status": "ok", "detail": {}}
        )
        assert event.model_dump(by_alias=True)["signal"] == "data-ingest"
