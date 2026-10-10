"""Engine-owned Pit Wall scoring — the call sheet's math as pure functions.

Contract (Pit Wall design, art_kYADIZWp §3; spec "Game scoring" row): scoring
lives in the engine — the client never invents scores. Exact podium hits are
position-exact (+5 each), the winner bonus adds +3, and a pick that finished
P4 scores a +1 near miss, so a round ranges 0-18. Any exact podium hit
extends the player's streak (flame at 3+), and when the ensemble's consensus
flag is LOW_CONSENSUS every point for that round doubles — a split machine
means the player's gut is the only edge.

Purity and reuse: no I/O here. The classified result comes from the backtest
module's ``classify_round`` — the game scores against exactly the
classification the backtest scores against, one source of truth — and the
consensus flag arrives from the ensemble arbiter's verdict as recorded in the
ledger, passed in and never recomputed or suppressed here.

The approved design defines streak EXTENSION only: a miss neither resets nor
shrinks the streak. Reset mechanics would be new design, so none exists here.

Response schemas (``CallScore`` and friends) are the module's own wire models:
the API serves them verbatim, so the JSON the client reads cannot drift from
this math.
"""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from f1engine.backtest import ClassifiedResult
from f1engine.ensemble import ConsensusFlag
from f1engine.wire import WireModel

EXACT_HIT_POINTS = 5
WINNER_BONUS_POINTS = 3
NEAR_MISS_POINTS = 1
NEAR_MISS_POSITION = 4  # a pick that finished here scores the near-miss point
ROUND_MAX_POINTS = 3 * EXACT_HIT_POINTS + WINNER_BONUS_POINTS  # 18
FLAME_STREAK = 3  # the flame appears at a streak of 3

PickSlot = Literal["p1", "p2", "p3"]
PickOutcome = Literal["EXACT", "NEAR_MISS", "MISS"]

_SLOT_POSITION: dict[PickSlot, int] = {"p1": 1, "p2": 2, "p3": 3}


class PitCall(WireModel):
    """A locked podium call — three distinct drivers in position order."""

    p1: str
    p2: str
    p3: str

    @model_validator(mode="after")
    def _distinct_drivers(self) -> PitCall:
        if len({self.p1, self.p2, self.p3}) != 3:
            raise ValueError("a podium call must name three distinct drivers")
        return self


class PickCallScore(WireModel):
    """One pick's outcome — a slot, the driver, where they finished, the points."""

    slot: PickSlot
    driver_id: str
    actual_position: int | None  # classified position; None = not classified
    outcome: PickOutcome
    points: int


class StreakState(WireModel):
    """The player's streak across this round — extension-only by design."""

    before: int
    after: int
    delta: int  # +1 when any pick hit exactly, else 0
    flame: bool  # after >= FLAME_STREAK


class RoundCallScore(WireModel):
    """One call scored against one classified result — the round's points."""

    picks: list[PickCallScore]  # call order: p1, p2, p3
    base_points: int  # 0-18 before any coin-flip doubling
    consensus_flag: ConsensusFlag | None  # from the ledger — None: no verdict
    coin_flip: bool  # consensus_flag == LOW_CONSENSUS
    total_points: int  # base_points doubled on a coin-flip round


class CallScore(WireModel):
    """The score endpoint's full response: round math plus streak state."""

    round: RoundCallScore
    streak: StreakState


def score_call(
    call: PitCall,
    result: ClassifiedResult,
    consensus_flag: ConsensusFlag | None,
) -> RoundCallScore:
    """Score one locked call against one classified result.

    Per pick: position-exact hit +5, a P4 finish +1 near miss, anything else
    0 — a driver outside the classified order (DNF, not in the race) is a
    MISS, because a wrong call is scored, not refused. The winner bonus +3
    applies when the P1 pick is the classified winner. The classified result
    is the backtest's own classification; the consensus flag is the ledger's
    ensemble verdict, doubled here when LOW_CONSENSUS — never recomputed.
    """
    positions = {
        driver_id: position
        for position, driver_id in enumerate(result.classified, start=1)
    }
    picks: list[PickCallScore] = []
    for slot, driver_id in (
        ("p1", call.p1),
        ("p2", call.p2),
        ("p3", call.p3),
    ):
        actual_position = positions.get(driver_id)
        if actual_position == _SLOT_POSITION[slot]:
            outcome, points = "EXACT", EXACT_HIT_POINTS
        elif actual_position == NEAR_MISS_POSITION:
            outcome, points = "NEAR_MISS", NEAR_MISS_POINTS
        else:
            outcome, points = "MISS", 0
        picks.append(
            PickCallScore(
                slot=slot,
                driver_id=driver_id,
                actual_position=actual_position,
                outcome=outcome,
                points=points,
            )
        )
    base = sum(pick.points for pick in picks)
    if call.p1 == result.winner:
        base += WINNER_BONUS_POINTS
    coin_flip = consensus_flag == "LOW_CONSENSUS"
    return RoundCallScore(
        picks=picks,
        base_points=base,
        consensus_flag=consensus_flag,
        coin_flip=coin_flip,
        total_points=base * 2 if coin_flip else base,
    )


def streak_delta(round_score: RoundCallScore) -> int:
    """+1 when any pick hit exactly, else 0 — a streak only ever extends."""
    return 1 if any(pick.outcome == "EXACT" for pick in round_score.picks) else 0


def next_streak(previous: int, round_score: RoundCallScore) -> StreakState:
    """Fold one round into the streak: extension-only, flame at FLAME_STREAK."""
    delta = streak_delta(round_score)
    after = previous + delta
    return StreakState(before=previous, after=after, delta=delta, flame=after >= FLAME_STREAK)


def score_call_sheet(
    call: PitCall,
    result: ClassifiedResult,
    consensus_flag: ConsensusFlag | None,
    streak_before: int,
) -> CallScore:
    """Compose the full score response: round math plus the streak fold.

    The API's thin wrapper — the endpoint parses inputs, classifies the
    round, reads the consensus flag from the ledger, and hands everything to
    this module so the served JSON is this math, byte for byte.
    """
    round_score = score_call(call, result, consensus_flag)
    return CallScore(round=round_score, streak=next_streak(streak_before, round_score))
