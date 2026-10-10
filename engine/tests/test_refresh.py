"""Refresh-pipeline tests: resumability, rate limiting, budget, backoff.

The acceptance contract for scripts/refresh-data.py: per-round cache makes
re-runs free (resumability), requests are paced at min_interval, the hourly
budget survives re-runs and stops cleanly when spent, and 429s back off
before retrying. Everything runs against the real pipeline with a fake
Jolpica fetch function.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_fake_jolpica

from f1engine.ingestion import load_snapshot

BASE_URL = "https://api.jolpi.ca/ergast/f1"


def _counting_fetch(refresh, calls: list[str]):
    fake = make_fake_jolpica(refresh)

    def fetch_fn(url: str):
        calls.append(url)
        return fake.fetch_fn(url)

    return fetch_fn


def _run(refresh, tmp_path: Path, fetch_fn, budget: int = 500, sleep_fn=None):
    return refresh.run_refresh(
        seasons=[2021],
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        base_url=BASE_URL,
        dataset_id="2026.10.0",
        min_interval=0.0,
        budget=budget,
        fetch_fn=fetch_fn,
        sleep_fn=sleep_fn if sleep_fn is not None else (lambda _seconds: None),
    )


def _dataset_hash(data_dir: Path) -> str:
    provenance = json.loads((data_dir / "provenance.json").read_text("utf-8"))
    return provenance["snapshot"]["sha256"]


def test_refresh_is_cache_first_resumable(refresh, tmp_path: Path) -> None:
    """First run fetches every endpoint once; a re-run makes zero HTTP
    requests and reproduces the identical dataset hash."""
    calls: list[str] = []
    _run(refresh, tmp_path, _counting_fetch(refresh, calls))
    first_hash = _dataset_hash(tmp_path / "data")

    # Mini 2021 season: schedule + r1 (results, qualifying, sprint)
    # + r2 (results, qualifying) = 6 endpoints.
    assert len(calls) == 6

    calls.clear()
    _run(refresh, tmp_path, _counting_fetch(refresh, calls))

    assert calls == []  # a resumed run never touches the network
    assert _dataset_hash(tmp_path / "data") == first_hash


def test_rate_limiter_paces_requests(refresh) -> None:
    """At most one request starts per min_interval window."""
    sleeps: list[float] = []
    clock = {"t": 100.0}
    limiter = refresh.RateLimiter(
        0.25, sleep_fn=sleeps.append, now_fn=lambda: clock["t"]
    )

    limiter.wait()  # the first request never waits
    assert sleeps == []

    limiter.wait()  # immediate second request: sleeps the full interval
    assert sleeps == [0.25]

    clock["t"] += 1.0
    limiter.wait()  # the interval has long passed: no sleep
    assert sleeps == [0.25]


def test_hourly_budget_persists_and_rolls(refresh, tmp_path: Path) -> None:
    """The request log survives re-runs, and entries age out of the window."""
    log_path = tmp_path / "request-log.json"
    clock = {"t": 1_000_000.0}
    budget = refresh.HourlyBudget(log_path, 3, now_fn=lambda: clock["t"])

    budget.record()
    budget.record()
    budget.record()
    assert budget.remaining() == 0
    assert log_path.exists()

    reopened = refresh.HourlyBudget(log_path, 3, now_fn=lambda: clock["t"])
    assert reopened.remaining() == 0  # persistence: a re-run inherits spend

    clock["t"] += 3601  # outside the rolling one-hour window
    assert reopened.remaining() == 3


def test_budget_exhaustion_stops_cleanly_and_resumes(
    refresh, tmp_path: Path
) -> None:
    """A spent budget raises before hammering; a re-run with headroom
    completes from cache + the remaining fetches."""
    calls: list[str] = []

    with pytest.raises(refresh.BudgetExhausted, match="budget"):
        _run(refresh, tmp_path, _counting_fetch(refresh, calls), budget=3)

    assert len(calls) == 3  # stopped before the 4th request, not after hammering
    assert (tmp_path / "cache" / "request-log.json").exists()

    calls.clear()
    _run(refresh, tmp_path, _counting_fetch(refresh, calls), budget=500)

    assert len(calls) == 3  # only the never-fetched endpoints remain
    dataset = load_snapshot(tmp_path / "data")
    assert len(dataset.races) == 2  # the resumed snapshot is complete


def test_429_backoff_honors_retry_after(refresh, tmp_path: Path) -> None:
    """A 429 sleeps the server's Retry-After hint, then the run completes."""
    sleeps: list[float] = []
    fake = make_fake_jolpica(refresh)
    state = {"n": 0}

    def throttled_once(url: str):
        state["n"] += 1
        if state["n"] == 1:
            return refresh.HttpResponse(
                status=429, headers={"Retry-After": "7"}, body=b"{}"
            )
        return fake.fetch_fn(url)

    _run(refresh, tmp_path, throttled_once, sleep_fn=sleeps.append)

    assert sleeps == [7.0]  # the server's hint was honored, once
    assert _dataset_hash(tmp_path / "data")  # the run completed


def test_persistent_429_raises_rate_limited(refresh, tmp_path: Path) -> None:
    """Still rate-limited after MAX_FETCH_ATTEMPTS: raise, never hammer."""
    sleeps: list[float] = []

    def always_429(url: str):
        return refresh.HttpResponse(status=429, headers={}, body=b"{}")

    with pytest.raises(refresh.RateLimited, match="rate-limited"):
        _run(refresh, tmp_path, always_429, sleep_fn=sleeps.append)

    # No Retry-After hint: doubling backoff 2s, 4s across the 3 attempts.
    assert sleeps == [2.0, 4.0]


def test_partial_season_keeps_schedule_without_future_results(
    refresh, tmp_path: Path
) -> None:
    """Cutoff hides future-race outcomes even if the fake API exposes them."""
    from datetime import date

    calls: list[str] = []
    result = refresh.run_refresh(
        seasons=[2021],
        data_dir=tmp_path / "partial",
        cache_dir=tmp_path / "cache",
        base_url=BASE_URL,
        dataset_id="partial.2026.10",
        min_interval=0,
        budget=500,
        as_of=date(2021, 5, 15),
        fetch_fn=_counting_fetch(refresh, calls),
        sleep_fn=lambda _seconds: None,
    )
    dataset = load_snapshot(tmp_path / "partial")
    assert len(dataset.races) == 2  # schedule is retained
    assert len(dataset.results) == 3  # only completed round 1
    assert len(dataset.qualifying) == 3
    assert result["tables"]["races"] == 2
    assert not any("/2021/2/results.json" in url for url in calls)
    assert not any("/2021/2/qualifying.json" in url for url in calls)


def test_partial_season_captures_qualifying_before_upcoming_gp(
    refresh, tmp_path: Path
) -> None:
    """The upcoming race has no outcome but may have a known pre-race grid."""
    from datetime import date

    fake = make_fake_jolpica(refresh)

    def with_qualifying_schedule(url: str):
        response = fake.fetch_fn(url)
        if "/2021.json?" not in url:
            return response
        payload = json.loads(response.body.decode("utf-8"))
        payload["MRData"]["RaceTable"]["Races"][1]["Qualifying"] = {
            "date": "2021-05-14"
        }
        return refresh.HttpResponse(
            status=200, headers={}, body=json.dumps(payload).encode("utf-8")
        )

    refresh.run_refresh(
        seasons=[2021],
        data_dir=tmp_path / "partial",
        cache_dir=tmp_path / "cache",
        base_url=BASE_URL,
        dataset_id="partial.2026.10",
        min_interval=0,
        budget=500,
        as_of=date(2021, 5, 15),
        fetch_fn=with_qualifying_schedule,
        sleep_fn=lambda _seconds: None,
    )
    dataset = load_snapshot(tmp_path / "partial")
    assert {r.round for r in dataset.qualifying} == {1, 2}
    assert {r.round for r in dataset.results} == {1}
