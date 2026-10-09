"""Model registry — one interface, three models, fixed seeds.

Contract (spec, engine/f1engine/models): m1-gbm (HistGradientBoostingClassifier),
m2-logit (LogisticRegression), and m3-form (rolling-form heuristic) behind the
PredictionModel protocol. Training sees only rounds < through_round; fixed
seeds make retraining byte-identical — a property that is tested.
"""

from typing import Protocol

MODEL_IDS: tuple[str, ...] = ("m1-gbm", "m2-logit", "m3-form")


class PredictionModel(Protocol):
    """The single interface every model implements."""

    model_id: str

    def train(self, table: dict[str, object], through_round: int) -> None:
        """Fit on rounds < through_round only; byte-identical on retrain."""
        ...

    def predict(self, race_id: str) -> dict[str, object]:
        """Return winner/podium distributions plus diagnostics for one race."""
        ...
