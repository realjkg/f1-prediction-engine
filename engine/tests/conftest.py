"""Shared test fixtures: a deterministic mini snapshot built by the real pipeline.

The ingestion tests need a snapshot they can tamper with in isolation; the
refresh tests need to drive the fetch pipeline with mocked HTTP. Both reuse
scripts/refresh-data.py through a fake fetch function so writer and verifier
are exercised against each other, never against a hand-rolled fixture writer.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "refresh-data.py"


def _load_refresh_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_data", SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("refresh_data", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def refresh() -> ModuleType:
    return _load_refresh_module()


@dataclass(frozen=True)
class FakeJolpica:
    """Deterministic Jolpica responses for a tiny two-round 2021 season."""

    fetch_fn: Callable[[str], object]
    request_urls: list[str]


def make_fake_jolpica(refresh_module: ModuleType) -> FakeJolpica:
    """Build a fake fetch function shaped like the real Jolpica API."""
    driver = {
        "driverId": "test-driver",
        "givenName": "Test",
        "familyName": "Driver",
        "code": "TST",
        "nationality": "Testland",
    }
    teammate = {
        "driverId": "test-mate",
        "givenName": "Test",
        "familyName": "Mate",
        "code": "MAT",
        "nationality": "Testland",
    }
    constructor = {
        "constructorId": "test-team",
        "name": "Test Team",
        "nationality": "Testland",
    }
    races = [
        {
            "season": "2021",
            "round": "1",
            "raceName": "Test Grand Prix",
            "date": "2021-05-02",
            "Sprint": {"date": "2021-05-01"},
            "Circuit": {
                "circuitId": "test_circuit",
                "circuitName": "Test Circuit",
                "Location": {"country": "Testland", "locality": "Testville"},
            },
        },
        {
            "season": "2021",
            "round": "2",
            "raceName": "Second Grand Prix",
            "date": "2021-05-30",
            "Circuit": {
                "circuitId": "second_circuit",
                "circuitName": "Second Circuit",
                "Location": {"country": "Testland", "locality": "Secondville"},
            },
        },
    ]
    people = [driver, teammate, driver]

    def race_with(key: str, entries: list[dict]) -> dict:
        return {"season": "2021", "round": "1", key: entries}

    results = [
        {
            "position": str(index + 1),
            "positionText": str(index + 1),
            "points": ["25", "18", "15"][index],
            "Driver": person,
            "Constructor": constructor,
            "grid": str(index + 1),
            "laps": "57",
            "status": "Finished",
            "Time": {"millis": str(5_000_000 + index * 1000)},
        }
        for index, person in enumerate(people)
    ]
    qualifying = [
        {
            "position": str(index + 1),
            "Driver": person,
            "Constructor": constructor,
            "Q1": f"1:29.{100 + index}",
            "Q2": f"1:28.{200 + index}",
            "Q3": f"1:27.{300 + index}",
        }
        for index, person in enumerate(people)
    ]
    sprint = [
        {
            "position": str(index + 1),
            "positionText": str(index + 1),
            "points": ["3", "2", "1"][index],
            "Driver": person,
            "Constructor": constructor,
            "status": "Finished",
        }
        for index, person in enumerate(people)
    ]

    def mrdata(total: int, races_block: list[dict]) -> dict:
        return {"MRData": {"total": str(total), "RaceTable": {"Races": races_block}}}

    responses: dict[str, dict] = {
        "2021.json?limit=100&offset=0": mrdata(2, races),
        "2021/1/results.json?limit=100&offset=0": mrdata(
            3, [race_with("Results", results)]
        ),
        "2021/1/qualifying.json?limit=100&offset=0": mrdata(
            3, [race_with("QualifyingResults", qualifying)]
        ),
        "2021/1/sprint.json?limit=100&offset=0": mrdata(
            3, [race_with("SprintResults", sprint)]
        ),
        "2021/2/results.json?limit=100&offset=0": mrdata(
            3, [race_with("Results", results)]
        ),
        "2021/2/qualifying.json?limit=100&offset=0": mrdata(
            3, [race_with("QualifyingResults", qualifying)]
        ),
    }

    requested: list[str] = []

    def fetch_fn(url: str) -> object:
        suffix = url.split("ergast/f1/")[1]
        requested.append(url)
        if suffix not in responses:
            raise AssertionError(f"unexpected URL in test: {url}")
        return refresh_module.HttpResponse(
            status=200,
            headers={},
            body=json.dumps(responses[suffix]).encode("utf-8"),
        )

    return FakeJolpica(fetch_fn=fetch_fn, request_urls=requested)


@pytest.fixture()
def mini_snapshot_factory(
    refresh: ModuleType,
) -> Callable[..., Path]:
    """Build a valid mini snapshot in a dir; returns the snapshot path."""

    def build(data_dir: Path, cache_dir: Path, **overrides: object) -> Path:
        fake = make_fake_jolpica(refresh)
        run_kwargs: dict[str, object] = {
            "seasons": [2021],
            "data_dir": data_dir,
            "cache_dir": cache_dir,
            "base_url": "https://api.jolpi.ca/ergast/f1",
            "dataset_id": "2026.10.0",
            "min_interval": 0.0,
            "budget": 500,
            "fetch_fn": fake.fetch_fn,
            "sleep_fn": lambda _seconds: None,
        }
        run_kwargs.update(overrides)
        refresh.run_refresh(**run_kwargs)
        return data_dir

    return build


@pytest.fixture()
def mini_snapshot(
    mini_snapshot_factory: Callable[..., Path], tmp_path: Path
) -> Path:
    """A ready-made valid mini snapshot in this test's tmp dir."""
    return mini_snapshot_factory(tmp_path / "snapshot", tmp_path / "cache")
