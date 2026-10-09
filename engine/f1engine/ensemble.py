"""Weighted ensemble arbiter with numeric consensus flag.

Contract (spec, engine/f1engine/ensemble): a weighted blend of per-model
winner/podium distributions; consensus.podiumSpread = max pairwise JS
divergence across model podium vectors; flag = OK when spread <=
PODIUM_SPREAD_OK_THRESHOLD, else LOW_CONSENSUS. The flag is advisory —
low-consensus predictions are flagged, never suppressed. This implements the
Landing Zone's unused DISAGREEMENT_THRESHOLD as a real number (LZ research
§4c, recommendation 2).
"""

from typing import Literal

PODIUM_SPREAD_OK_THRESHOLD = 0.15

ConsensusFlag = Literal["OK", "LOW_CONSENSUS"]


def arbitrate(
    predictions: list[dict[str, object]], weights: dict[str, float]
) -> dict[str, object]:
    """Blend per-model distributions into the ensemble verdict + consensus flag."""
    raise NotImplementedError("ensemble is implemented by the ensemble task")
