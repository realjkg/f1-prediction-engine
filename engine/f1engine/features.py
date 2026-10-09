"""As-of-round feature builder — no-lookahead by construction.

Contract (spec, engine/f1engine/features): rolling driver form, qualifying
deltas, team performance, and track history built strictly from rounds BELOW
the target round. The no-lookahead invariant is tested, not assumed: features
for round N must be identical with and without future rounds present.

Owned by the features task.
"""


def build_asof_features(
    feature_table: dict[str, object], through_round: int
) -> dict[str, object]:
    """Build model features using only rounds < through_round."""
    raise NotImplementedError("features are implemented by the features task")
