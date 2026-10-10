"""Scoring tests — the Pit Wall call-sheet math and its two read endpoints.

Spec row "Game scoring" (engine side): the scoring math table (exact /
near-miss / winner bonus / zero / the 18-point max), streak extension and the
flame threshold, coin-flip doubling on LOW_CONSENSUS only, endpoint-output
parity with the module math, and the typed refusals — 404 for unknown or
unresulted races, 422 for malformed calls. Module tests are pure tables (no
dataset); endpoint tests run against real pipeline records on the predictable
mini snapshot. The mini grid is only three drivers, so P4 near misses are
exercised in the pure tables, never against fixture data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from f1engine.app import ApiSettings, LedgerStore, create_app
from f1engine.backtest import ClassifiedResult, classify_round
from f1engine.ensemble import ConsensusFlag, arbitrate
from f1engine.evidence import append_record, build_prediction_record
from f1engine.features import build_asof_features
from f1engine.ingestion import PinnedDataset
from f1engine.models import ModelPrediction, create_models
from f1engine.scoring import (
    EXACT_HIT_POINTS,
    FLAME_STREAK,
    NEAR_MISS_POINTS,
    ROUND_MAX_POINTS,
    WINNER_BONUS_POINTS,
    PitCall,
    RoundCallScore,
    next_streak,
    score_call,
    score_call_sheet,
    streak_delta,
)

EVIDENCE_BASIS = "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE"
EQUAL_WEIGHTS: dict[str, float] = {"m1-gbm": 1.0, "m2-logit": 1.0, "m3-form": 1.0}

# The predictable snapshot's three-driver grid, in its usual finishing order.
DRIVER, MATE, THIRD = "test-driver", "test-mate", "test-third"


# ---------------------------------------------------------------------------
# Helpers — pure tables through the shared classifier.
# ---------------------------------------------------------------------------


def _classified(*order: str) -> ClassifiedResult:
    """A classified result from a full finishing order, via the shared classifier."""
    result = classify_round(list(enumerate(order, start=1)))
    assert result is not None  # a fully classified order always has a winner
    return result


def _score(
    picks: tuple[str, str, str],
    classified: tuple[str, ...],
    flag: ConsensusFlag | None = None,
) -> RoundCallScore:
    call = PitCall(p1=picks[0], p2=picks[1], p3=picks[2])
    return score_call(call, _classified(*classified), flag)


# ---------------------------------------------------------------------------
# The scoring math table (spec row "Game scoring").
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("picks", "classified", "flag", "base", "total", "coin_flip"),
    [
        # Exact podium, position by position, plus the winner bonus — the max.
        ((DRIVER, MATE, THIRD), (DRIVER, MATE, THIRD, "d"), None, 18, 18, False),
        # Exact is position-exact, not set-equal: only the P3 slot hits.
        ((MATE, DRIVER, THIRD), (DRIVER, MATE, THIRD), None, 5, 5, False),
        # The P3 pick finished P4 — a near miss on an otherwise exact card.
        ((DRIVER, MATE, "d"), (DRIVER, MATE, THIRD, "d"), None, 14, 14, False),
        # A P1-slot pick that finished P4 scores the near miss alone.
        (("d", "e", "f"), (DRIVER, MATE, THIRD, "d"), None, 1, 1, False),
        # Nothing the machine can honour — zero.
        (("x", "y", "z"), (DRIVER, MATE, THIRD), None, 0, 0, False),
        # OK and absent flags never double.
        ((DRIVER, MATE, THIRD), (DRIVER, MATE, THIRD, "d"), "OK", 18, 18, False),
        # LOW_CONSENSUS doubles everything — the coin-flip round.
        (
            (DRIVER, MATE, THIRD),
            (DRIVER, MATE, THIRD, "d"),
            "LOW_CONSENSUS",
            18,
            36,
            True,
        ),
        (("d", "e", "f"), (DRIVER, MATE, THIRD, "d"), "LOW_CONSENSUS", 1, 2, True),
        (("x", "y", "z"), (DRIVER, MATE, THIRD), "LOW_CONSENSUS", 0, 0, True),
    ],
)
def test_scoring_math_table(
    picks: tuple[str, str, str],
    classified: tuple[str, ...],
    flag: ConsensusFlag | None,
    base: int,
    total: int,
    coin_flip: bool,
) -> None:
    score = _score(picks, classified, flag)
    assert score.base_points == base
    assert score.total_points == total
    assert score.coin_flip is coin_flip
    assert score.consensus_flag == flag


def test_round_max_is_eighteen() -> None:
    assert ROUND_MAX_POINTS == 18
    assert _score((DRIVER, MATE, THIRD), (DRIVER, MATE, THIRD, "d")).base_points == (
        ROUND_MAX_POINTS
    )


def test_pick_outcomes_carry_slot_position_and_points() -> None:
    score = _score((MATE, DRIVER, "d"), (DRIVER, MATE, THIRD, "d"))

    p1, p2, p3 = score.picks
    assert (p1.slot, p1.driver_id, p1.actual_position, p1.outcome, p1.points) == (
        "p1",
        MATE,
        2,
        "MISS",
        0,
    )
    assert (p2.slot, p2.driver_id, p2.actual_position, p2.outcome, p2.points) == (
        "p2",
        DRIVER,
        1,
        "MISS",
        0,
    )
    assert (p3.slot, p3.driver_id, p3.actual_position, p3.outcome, p3.points) == (
        "p3",
        "d",
        4,
        "NEAR_MISS",
        NEAR_MISS_POINTS,
    )


def test_winner_bonus_applies_once_beside_the_exact_hit() -> None:
    score = _score((DRIVER, MATE, THIRD), (DRIVER, MATE, THIRD, "d"))

    assert score.picks[0].points == EXACT_HIT_POINTS  # the bonus never stacks in
    assert score.base_points == 3 * EXACT_HIT_POINTS + WINNER_BONUS_POINTS


def test_unclassified_picks_are_misses_with_no_position() -> None:
    score = _score(("z", DRIVER, MATE), (DRIVER, MATE, THIRD))

    p1 = score.picks[0]
    assert p1.actual_position is None
    assert p1.outcome == "MISS"


def test_a_call_must_name_three_distinct_drivers() -> None:
    with pytest.raises(ValidationError):
        PitCall(p1=DRIVER, p2=DRIVER, p3=MATE)


# ---------------------------------------------------------------------------
# Streak — extension on any exact hit, flame at 3.
# ---------------------------------------------------------------------------


def test_streak_extends_on_any_exact_hit_and_never_resets() -> None:
    exact = _score((DRIVER, MATE, THIRD), (DRIVER, MATE, THIRD, "d"))
    near_miss_only = _score(("d", "e", "f"), (DRIVER, MATE, THIRD, "d"))

    assert streak_delta(exact) == 1
    assert streak_delta(near_miss_only) == 0  # a near miss does not extend
    # The approved design defines extension only: a miss neither resets nor
    # shrinks the streak — a reset would be new design, not this math.
    held = next_streak(2, near_miss_only)
    assert (held.before, held.after, held.delta) == (2, 2, 0)


def test_flame_appears_at_three() -> None:
    exact = _score((DRIVER, MATE, THIRD), (DRIVER, MATE, THIRD, "d"))

    ignited = next_streak(2, exact)
    assert (ignited.before, ignited.after, ignited.delta) == (2, 3, 1)
    assert ignited.flame is True
    assert next_streak(1, exact).flame is False  # 2 is not yet the flame
    assert next_streak(FLAME_STREAK, exact).flame is True  # stays lit


# ---------------------------------------------------------------------------
# The shared classifier — what "actual" means everywhere.
# ---------------------------------------------------------------------------


def test_classify_round_excludes_unclassified_and_orders_the_podium() -> None:
    result = classify_round([(2, MATE), (None, "dnf"), (1, DRIVER), (3, THIRD)])

    assert result is not None
    assert result.winner == DRIVER
    assert result.podium == (DRIVER, MATE, THIRD)
    assert result.classified == (DRIVER, MATE, THIRD)  # the DNF never ranks


def test_classify_round_refuses_without_a_classified_winner() -> None:
    assert classify_round([(2, MATE), (3, THIRD)]) is None
    assert classify_round([]) is None


# ---------------------------------------------------------------------------
# Endpoints — the served JSON is the module math, byte for byte.
# ---------------------------------------------------------------------------


def _client(dataset: PinnedDataset, ledger: Path | None = None) -> TestClient:
    resolved = replace(ApiSettings(), ledger_path=ledger) if ledger else ApiSettings()
    return TestClient(create_app(resolved, dataset=dataset))


def _divergent_ledger(dataset: PinnedDataset, ledger_path: Path) -> Path:
    """A real pipeline ledger whose round-4 verdict is LOW_CONSENSUS.

    Real trained predictions with each model's podium vector re-pointed at a
    different driver — maximally divergent, so the arbitrated consensus flag
    is LOW_CONSENSUS and the score endpoint must double on it.
    """
    table = build_asof_features(dataset)
    orders = (
        (DRIVER, MATE, THIRD),
        (THIRD, MATE, DRIVER),
        (MATE, DRIVER, THIRD),
    )
    predictions: list[ModelPrediction] = []
    for model in create_models().values():
        model.train(dataset, table, (2021, 4))
        predictions.append(model.predict(2021, 4))
    diverged = tuple(
        prediction.model_copy(
            update={
                "winner": {order[0]: 1.0},
                "podium": {
                    driver: 0.9 if slot == 0 else 0.05
                    for slot, driver in enumerate(order)
                },
            }
        )
        for prediction, order in zip(predictions, orders, strict=True)
    )
    verdict = arbitrate(diverged, EQUAL_WEIGHTS)
    assert verdict.consensus.flag == "LOW_CONSENSUS"
    race = next(row for row in dataset.races if row.season == 2021 and row.round == 4)
    append_record(
        ledger_path,
        build_prediction_record(list(diverged), verdict, dataset, race, EVIDENCE_BASIS),
    )
    return ledger_path


def test_result_serves_the_classified_result(predictable_dataset: PinnedDataset) -> None:
    body = _client(predictable_dataset).get("/api/races/fourth-grand-prix/result").json()

    assert body["raceId"] == "fourth-grand-prix"
    assert (body["season"], body["round"]) == (2021, 4)
    assert body["name"] == "Fourth Grand Prix"
    assert body["winner"] == DRIVER
    assert body["podium"] == [DRIVER, MATE, THIRD]
    assert [(entry["position"], entry["driverId"]) for entry in body["classified"]] == [
        (1, DRIVER),
        (2, MATE),
        (3, THIRD),
    ]


def test_result_serves_short_podiums_when_drivers_dnf(
    predictable_dataset: PinnedDataset,
) -> None:
    # Round 3: test-third retired — two classified finishers, a two-car podium.
    body = _client(predictable_dataset).get("/api/races/third-grand-prix/result").json()

    assert body["podium"] == [MATE, DRIVER]
    assert len(body["classified"]) == 2


def test_score_matches_the_module_math(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    ledger = ledger_factory(4, 5)
    client = _client(predictable_dataset, ledger)

    response = client.get(
        "/api/races/fourth-grand-prix/score",
        params={"call": f"{DRIVER},{MATE},{THIRD}", "streak_before": 2},
    )
    assert response.status_code == 200
    classified = classify_round(
        [
            (row.position, row.driver_id)
            for row in predictable_dataset.results
            if row.race_id == "fourth-grand-prix"
        ]
    )
    assert classified is not None
    records = LedgerStore(ledger).records_for_race("fourth-grand-prix")
    flag = records[-1].ensemble.consensus.flag
    expected = score_call_sheet(PitCall(p1=DRIVER, p2=MATE, p3=THIRD), classified, flag, 2)
    assert response.json() == expected.model_dump(mode="json", by_alias=True)


def test_score_doubles_on_the_ledgers_low_consensus_flag(
    predictable_dataset: PinnedDataset, tmp_path: Path
) -> None:
    ledger = _divergent_ledger(predictable_dataset, tmp_path / "coin-flip.jsonl")
    client = _client(predictable_dataset, ledger)

    body = client.get(
        "/api/races/fourth-grand-prix/score",
        params={"call": f"{DRIVER},{MATE},{THIRD}"},
    ).json()

    assert body["round"]["consensusFlag"] == "LOW_CONSENSUS"  # from the ledger
    assert body["round"]["coinFlip"] is True
    assert body["round"]["basePoints"] == 18
    assert body["round"]["totalPoints"] == 36


def test_score_folds_the_callers_prior_streak(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    body = client.get(
        "/api/races/fourth-grand-prix/score",
        params={"call": f"{DRIVER},{MATE},{THIRD}", "streak_before": 2},
    ).json()

    assert body["streak"] == {"before": 2, "after": 3, "delta": 1, "flame": True}


def test_a_reversed_call_scores_zero_but_still_scores(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    body = client.get(
        "/api/races/fourth-grand-prix/score",
        params={"call": f"{THIRD},{DRIVER},{MATE}"},
    ).json()

    assert body["round"]["basePoints"] == 0  # position-exact, not set-equal
    assert body["round"]["totalPoints"] == 0
    assert body["streak"]["delta"] == 0


def test_unknown_races_404_on_both_endpoints(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    result = client.get("/api/races/no-such-grand-prix/result")
    assert result.status_code == 404
    assert result.json()["detail"]["code"] == "RACE_UNKNOWN"

    score = client.get(
        "/api/races/no-such-grand-prix/score", params={"call": f"{DRIVER},{MATE},{THIRD}"}
    )
    assert score.status_code == 404
    assert score.json()["detail"]["code"] == "RACE_UNKNOWN"


def test_unresulted_races_404_on_both_endpoints(
    predictable_dataset: PinnedDataset, ledger_factory: Callable[..., Path]
) -> None:
    client = _client(replace(predictable_dataset, results=()), ledger_factory(4))

    result = client.get("/api/races/fourth-grand-prix/result")
    assert result.status_code == 404
    assert result.json()["detail"]["code"] == "RESULT_NOT_FOUND"

    score = client.get(
        "/api/races/fourth-grand-prix/score", params={"call": f"{DRIVER},{MATE},{THIRD}"}
    )
    assert score.status_code == 404
    assert score.json()["detail"]["code"] == "RESULT_NOT_FOUND"


def test_score_refuses_a_round_without_a_prediction_record(
    predictable_dataset: PinnedDataset,
) -> None:
    client = _client(predictable_dataset)  # no ledger — no ensemble verdict

    response = client.get(
        "/api/races/fourth-grand-prix/score", params={"call": f"{DRIVER},{MATE},{THIRD}"}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PREDICTIONS_NOT_FOUND"


@pytest.mark.parametrize(
    ("call", "why"),
    [
        (None, "missing call"),
        ("", "empty call"),
        (f"{DRIVER},{MATE}", "fewer than three picks"),
        (f"{DRIVER},{MATE},{THIRD},{MATE}", "more than three picks"),
        (f"{DRIVER}, {DRIVER}, {MATE}", "duplicate drivers"),
        ("max-verstappen,test-mate,test-third", "unknown driver ids"),
        (f"{DRIVER},,{THIRD}", "blank pick"),
    ],
)
def test_malformed_calls_422_with_a_typed_code(
    predictable_dataset: PinnedDataset,
    ledger_factory: Callable[..., Path],
    call: str | None,
    why: str,
) -> None:
    client = _client(predictable_dataset, ledger_factory(4))

    params = {"call": call} if call is not None else {}
    response = client.get("/api/races/fourth-grand-prix/score", params=params)

    assert response.status_code == 422, why
    assert response.json()["detail"]["code"] == "CALL_MALFORMED"
