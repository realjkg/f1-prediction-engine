"""Feature tests: the no-lookahead proof and feature values.

The load-bearing proof runs in BOTH directions against the real pinned
snapshot: removing future rounds must change nothing for earlier rounds,
and tampering with a round's own results/qualifying must leave that round's
features untouched while visibly changing the next round's.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from f1engine.features import (
    UNCLASSIFIED_FINISH,
    build_asof_features,
    numeric_finish,
)
from f1engine.ingestion import PinnedDataset, ResultRow, load_snapshot

REPO_SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "snapshot"
TARGET = (2023, 5)  # arbitrary mid-season round for the lookahead proofs


@pytest.fixture(scope="module")
def dataset() -> PinnedDataset:
    return load_snapshot(REPO_SNAPSHOT)


def _rows_through(rows: tuple, target: tuple[int, int]) -> tuple:
    return tuple(row for row in rows if (row.season, row.round) <= target)


def _truncate_after(dataset: PinnedDataset, target: tuple[int, int]) -> PinnedDataset:
    """A dataset truncated AT the target: later rounds fully removed.

    Races stay complete (a future schedule is known in advance); everything
    outcome-bearing — results, qualifying, sprints — is cut after the target.
    """
    return dataclasses.replace(
        dataset,
        results=_rows_through(dataset.results, target),
        qualifying=_rows_through(dataset.qualifying, target),
        sprints=_rows_through(dataset.sprints, target),
    )


def test_no_lookahead_future_rounds_removed(dataset: PinnedDataset) -> None:
    """The load-bearing test: features for rounds <= N are identical with and
    without rounds > N present in the dataset."""
    truncated = _truncate_after(dataset, TARGET)

    full_table = build_asof_features(dataset)
    truncated_table = build_asof_features(truncated)

    expected = tuple(
        row for row in full_table.rows if (row.season, row.round) <= TARGET
    )
    assert truncated_table.rows == expected
    assert len(expected) > 1000  # the comparison covers most of the dataset


def test_no_lookahead_own_round_tampering_immune(dataset: PinnedDataset) -> None:
    """Tampering with round N's own data cannot move round N's features."""

    def tamper_target_round(source: PinnedDataset) -> PinnedDataset:
        results = tuple(
            row.model_copy(
                update={"position": (21 - row.position) if row.position else None}
            )
            if (row.season, row.round) == TARGET
            else row
            for row in source.results
        )
        qualifying = tuple(
            row.model_copy(
                update={
                    "q1_ms": (row.q1_ms + 500) if row.q1_ms else None,
                    "q2_ms": (row.q2_ms + 500) if row.q2_ms else None,
                    "q3_ms": (row.q3_ms + 500) if row.q3_ms else None,
                }
            )
            if (row.season, row.round) == TARGET
            else row
            for row in source.qualifying
        )
        return dataclasses.replace(source, results=results, qualifying=qualifying)

    tampered = tamper_target_round(dataset)
    baseline = build_asof_features(dataset)
    after = build_asof_features(tampered)

    def rows_for(table, key):
        return {
            (row.driver_id, row.constructor_id): row
            for row in table.rows
            if (row.season, row.round) == key
        }

    # Round N: byte-identical despite its own results and qualifying changing.
    assert rows_for(after, TARGET) == rows_for(baseline, TARGET)
    # Round N+1: the tampering flows forward — form and q gaps must move.
    next_round = (TARGET[0], TARGET[1] + 1)
    assert rows_for(after, next_round) != rows_for(baseline, next_round)


def test_build_is_deterministic(dataset: PinnedDataset) -> None:
    assert build_asof_features(dataset) == build_asof_features(dataset)


def test_features_cover_every_result_row(dataset: PinnedDataset) -> None:
    table = build_asof_features(dataset)

    assert len(table.rows) == len(dataset.results) == 2139
    assert table.form_window == 5


def test_first_round_has_no_history(mini_snapshot: Path) -> None:
    dataset = load_snapshot(mini_snapshot)

    table = build_asof_features(dataset)
    first = [
        row for row in table.rows if (row.season, row.round) == (2021, 1)
    ]

    assert len(first) == 3
    for row in first:
        assert row.starts == 0
        assert row.form_finish_mean is None
        assert row.form_finish_mean_all is None
        assert row.q_best_ms is None
        assert row.q_delta_teammate_ms is None
        assert row.q_delta_pole_ms is None
        assert row.team_points_mean is None
        assert row.track_finish_mean is None


def test_window_features_use_prior_rounds(mini_snapshot: Path) -> None:
    """Round-2 features are exactly round-1's outcomes (the fixture mirrors
    round 1's data into round 2)."""
    dataset = load_snapshot(mini_snapshot)

    table = build_asof_features(dataset)
    rows = {
        row.driver_id: row
        for row in table.rows
        if (row.season, row.round) == (2021, 2)
    }

    driver = rows["test-driver"]
    mate = rows["test-mate"]
    third = rows["test-third"]

    assert driver.form_finish_mean == 1.0
    assert mate.form_finish_mean == 2.0
    assert third.form_finish_mean == 3.0

    # Best Q3 times from round 1: 87300 / 87301 / 87302 ms.
    assert driver.q_best_ms == 87_300
    assert mate.q_best_ms == 87_301
    assert third.q_best_ms == 87_302

    # Gaps to the fastest teammate and to pole, in ms.
    assert driver.q_delta_teammate_ms == -1.0
    assert mate.q_delta_teammate_ms == 1.0
    assert third.q_delta_teammate_ms == 2.0
    assert driver.q_delta_pole_ms == 0.0
    assert mate.q_delta_pole_ms == 1.0
    assert third.q_delta_pole_ms == 2.0

    # All three drivers score for test-team in round 1: 25 + 18 + 15.
    assert driver.team_points_mean == 58.0
    assert driver.starts == 1


def test_through_round_bounds_rows_without_changing_values(
    mini_snapshot: Path,
) -> None:
    dataset = load_snapshot(mini_snapshot)

    bounded = build_asof_features(dataset, through_round=2)
    full = build_asof_features(dataset)

    assert bounded.rows == tuple(row for row in full.rows if row.round < 2)


def test_track_history_uses_prior_seasons(mini_snapshot: Path) -> None:
    """A copied 2022 round at the same race_id sees 2021's finishes — and
    only finishes at that race_id, never other rounds."""
    dataset = load_snapshot(mini_snapshot)
    first_race = next(
        race for race in dataset.races if (race.season, race.round) == (2021, 1)
    )

    rolled = dataclasses.replace(
        dataset,
        races=dataset.races + (first_race.model_copy(update={"season": 2022}),),
        results=dataset.results
        + tuple(
            row.model_copy(
                update={
                    "season": 2022,
                    "position": (4 - row.position) if row.position else None,
                    "position_text": "rolled",
                }
            )
            for row in dataset.results
            if (row.season, row.round) == (2021, 1)
        ),
        qualifying=dataset.qualifying
        + tuple(
            row.model_copy(update={"season": 2022, "q1_ms": 90_000})
            for row in dataset.qualifying
            if (row.season, row.round) == (2021, 1)
        ),
    )

    table = build_asof_features(rolled)
    rows_2022 = {
        row.driver_id: row
        for row in table.rows
        if (row.season, row.round) == (2022, 1)
    }

    # 2022 is the same race_id: 2021 finishes at this race roll forward.
    assert rows_2022["test-driver"].track_finish_mean == 1.0
    assert rows_2022["test-mate"].track_finish_mean == 2.0
    assert rows_2022["test-third"].track_finish_mean == 3.0
    # Round 2 of 2021 sits at a different race_id — no track history there.
    rows_2021_r2 = {
        row.driver_id: row
        for row in table.rows
        if (row.season, row.round) == (2021, 2)
    }
    assert rows_2021_r2["test-driver"].track_finish_mean is None


def test_numeric_finish_penalizes_unclassified() -> None:
    classified = ResultRow(
        season=2021,
        round=1,
        race_id="r",
        position=3,
        position_text="3",
        points=15.0,
        driver_id="d",
        constructor_id="c",
        grid=3,
        laps=57,
        status="Finished",
    )
    unclassified = classified.model_copy(
        update={"position": None, "position_text": "DNF", "points": 0.0}
    )

    assert numeric_finish(classified) == 3.0
    assert numeric_finish(unclassified) == UNCLASSIFIED_FINISH == 25.0


def test_form_window_changes_the_computation(dataset: PinnedDataset) -> None:
    wide = build_asof_features(dataset, form_window=10)
    narrow = build_asof_features(dataset, form_window=1)

    assert wide.form_window == 10
    assert narrow.form_window == 1
    assert wide.rows != narrow.rows  # the window genuinely feeds the values


def test_form_window_validated(dataset: PinnedDataset) -> None:
    with pytest.raises(ValueError, match="form_window"):
        build_asof_features(dataset, form_window=0)


def test_qualifying_row_missing_times_is_supported(mini_snapshot: Path) -> None:
    """A qualifying row with no times yields None q-features, never a guess."""
    dataset = load_snapshot(mini_snapshot)
    stripped = tuple(
        row.model_copy(update={"q1_ms": None, "q2_ms": None, "q3_ms": None})
        if (row.season, row.round) == (2021, 1) and row.driver_id == "test-third"
        else row
        for row in dataset.qualifying
    )
    no_times = dataclasses.replace(dataset, qualifying=stripped)

    table = build_asof_features(no_times)
    third = next(
        row
        for row in table.rows
        if (row.season, row.round) == (2021, 2) and row.driver_id == "test-third"
    )

    assert third.q_best_ms is None
    assert third.q_delta_teammate_ms is None
    assert third.q_delta_pole_ms is None
