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

from f1engine.ensemble import arbitrate
from f1engine.evidence import append_record, build_prediction_record
from f1engine.features import build_asof_features
from f1engine.ingestion import PinnedDataset, load_snapshot
from f1engine.models import create_models

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "refresh-data.py"
DEMO_SCRIPT_PATH = REPO_ROOT / "scripts" / "demo.py"
REPO_SNAPSHOT = REPO_ROOT / "data" / "snapshot"

EVIDENCE_BASIS = "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE"
WEIGHTS: dict[str, float] = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}


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


def _load_demo_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo", DEMO_SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {DEMO_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("demo", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def demo() -> ModuleType:
    """The demo runner module (scripts/demo.py), loaded once per session."""
    return _load_demo_module()


@dataclass(frozen=True)
class FakeJolpica:
    """Deterministic Jolpica responses for a tiny two-round 2021 season."""

    fetch_fn: Callable[[str], object]
    request_urls: list[str]


def make_fake_jolpica(refresh_module: ModuleType, rounds: int = 2) -> FakeJolpica:
    """Build a fake fetch function shaped like the real Jolpica API.

    rounds=2 (default) is the ingestion/features fixture: two identical
    rounds, byte-for-byte the historical shape. rounds=4 adds two more
    decided rounds — round 3 hands the win to test-mate and retires
    test-third with a DNF, so a window covering rounds 1-3 carries both
    winner classes and a podium-negative label — and a fourth round to
    predict, for the model/ensemble/ledger tests.
    """
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
    third = {
        "driverId": "test-third",
        "givenName": "Test",
        "familyName": "Third",
        "code": "THR",
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
    people = [driver, teammate, third]
    people_by_id = {
        "test-driver": driver,
        "test-mate": teammate,
        "test-third": third,
    }

    # Finishing order per round (qualifying mirrors it). Defaults keep the
    # historical two-round shape byte-for-byte.
    finish_orders: dict[int, list[str]] = {
        1: ["test-driver", "test-mate", "test-third"],
        2: ["test-driver", "test-mate", "test-third"],
        3: ["test-mate", "test-driver", "test-third"],
        4: ["test-driver", "test-mate", "test-third"],
        5: ["test-driver", "test-mate", "test-third"],
    }

    def results_for(round_number: int) -> list[dict]:
        dnf = "test-third" if round_number == 3 else None
        place = 0
        rows = []
        for driver_id in finish_orders[round_number]:
            if driver_id == dnf:
                rows.append(
                    {
                        "positionText": "DNF",
                        "points": "0",
                        "Driver": people_by_id[driver_id],
                        "Constructor": constructor,
                        "grid": "3",
                        "laps": "5",
                        "status": "Engine",
                    }
                )
                continue
            place += 1
            rows.append(
                {
                    "position": str(place),
                    "positionText": str(place),
                    "points": ["25", "18", "15"][place - 1],
                    "Driver": people_by_id[driver_id],
                    "Constructor": constructor,
                    "grid": str(place),
                    "laps": "57",
                    "status": "Finished",
                    "Time": {"millis": str(5_000_000 + place * 1000)},
                }
            )
        return rows

    def qualifying_for(round_number: int) -> list[dict]:
        return [
            {
                "position": str(index + 1),
                "Driver": people_by_id[driver_id],
                "Constructor": constructor,
                "Q1": f"1:29.{100 + index}",
                "Q2": f"1:28.{200 + index}",
                "Q3": f"1:27.{300 + index}",
            }
            for index, driver_id in enumerate(finish_orders[round_number])
        ]

    def race_with(key: str, entries: list[dict]) -> dict:
        return {"season": "2021", "round": "1", key: entries}
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

    later_races = [
        {
            "season": "2021",
            "round": "3",
            "raceName": "Third Grand Prix",
            "date": "2021-06-06",
            "Circuit": {
                "circuitId": "third_circuit",
                "circuitName": "Third Circuit",
                "Location": {"country": "Testland", "locality": "Thirdville"},
            },
        },
        {
            "season": "2021",
            "round": "4",
            "raceName": "Fourth Grand Prix",
            "date": "2021-06-27",
            "Circuit": {
                "circuitId": "fourth_circuit",
                "circuitName": "Fourth Circuit",
                "Location": {"country": "Testland", "locality": "Fourthville"},
            },
        },
        {
            "season": "2021",
            "round": "5",
            "raceName": "Fifth Grand Prix",
            "date": "2021-07-04",
            "Circuit": {
                "circuitId": "fifth_circuit",
                "circuitName": "Fifth Circuit",
                "Location": {"country": "Testland", "locality": "Fifthville"},
            },
        },
    ]
    all_races = races + later_races if rounds > 2 else races

    def mrdata(total: int, races_block: list[dict]) -> dict:
        return {"MRData": {"total": str(total), "RaceTable": {"Races": races_block}}}

    responses: dict[str, dict] = {
        "2021.json?limit=100&offset=0": mrdata(len(all_races), all_races),
        "2021/1/sprint.json?limit=100&offset=0": mrdata(
            3, [race_with("SprintResults", sprint)]
        ),
    }
    for round_number in range(1, rounds + 1):
        responses[f"2021/{round_number}/results.json?limit=100&offset=0"] = mrdata(
            3, [race_with("Results", results_for(round_number))]
        )
        responses[
            f"2021/{round_number}/qualifying.json?limit=100&offset=0"
        ] = mrdata(
            3, [race_with("QualifyingResults", qualifying_for(round_number))]
        )

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

    def build(
        data_dir: Path, cache_dir: Path, rounds: int = 2, **overrides: object
    ) -> Path:
        fake = make_fake_jolpica(refresh, rounds=rounds)
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


@pytest.fixture()
def predictable_snapshot(
    mini_snapshot_factory: Callable[..., Path], tmp_path: Path
) -> Path:
    """A mini snapshot with four decided rounds and a fifth to predict.

    Rounds 1-4 are the training window (round 3 carries a DNF, giving the
    podium labels a second class); round 5 is the prediction target. The
    ledger tests chain two real records: rounds 4 and 5, each trained on a
    window that includes the round-3 DNF.
    """
    return mini_snapshot_factory(
        tmp_path / "predictable", tmp_path / "cache", rounds=5
    )


@pytest.fixture()
def predictable_dataset(predictable_snapshot: Path) -> PinnedDataset:
    return load_snapshot(predictable_snapshot)


@pytest.fixture()
def ledger_factory(
    predictable_dataset: PinnedDataset, tmp_path: Path
) -> Callable[..., Path]:
    """Build a real ledger by appending pipeline records for the given rounds."""

    def build(*rounds: int) -> Path:
        ledger_path = tmp_path / "ledger.jsonl"
        table = build_asof_features(predictable_dataset)
        models = create_models()
        for round_number in rounds:
            predictions = []
            for model in models.values():
                model.train(predictable_dataset, table, (2021, round_number))
                predictions.append(model.predict(2021, round_number))
            verdict = arbitrate(predictions, WEIGHTS)
            race = next(
                row
                for row in predictable_dataset.races
                if row.season == 2021 and row.round == round_number
            )
            append_record(
                ledger_path,
                build_prediction_record(
                    predictions, verdict, predictable_dataset, race, EVIDENCE_BASIS
                ),
            )
        return ledger_path

    return build


@pytest.fixture(scope="session")
def real_snapshot() -> PinnedDataset:
    """The committed 2020-2024 snapshot, hash-verified once per session."""
    return load_snapshot(REPO_SNAPSHOT)
