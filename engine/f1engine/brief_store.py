"""Brief store — where the race brief lives, OUTSIDE the evidence hash chain.

The evidence ledger (f1engine.evidence) is the demo's proof: append-only,
sha256-chained, tamper-checked. The race brief is advisory narration of a
prediction record, never evidence, so it gets its own plain JSONL file with
no chain hash. The boundary is structural: this module never imports the
ledger, and RaceBrief carries no recordSha256 of its own to chain with — the
record it narrates is identified inside ``digest.recordSha256`` only.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from f1engine.brief import RaceBrief


class BriefStoreInvalid(RuntimeError):
    """A stored line is not parseable into the closed brief schema."""

    code = "BRIEF_STORE_INVALID"


def append_brief(path: Path, brief: RaceBrief) -> None:
    """Append one brief as canonical JSON — the ledger's byte discipline, minus the chaining."""
    line = json.dumps(
        brief.model_dump(by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_briefs(path: Path) -> list[RaceBrief]:
    """Every stored brief in append order; an absent file is an empty store."""
    if not path.exists():
        return []
    briefs: list[RaceBrief] = []
    for index, line in enumerate(_lines(path)):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise BriefStoreInvalid(
                f"brief line {index} is not valid JSON: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise BriefStoreInvalid(f"brief line {index} is not a JSON object")
        try:
            briefs.append(RaceBrief.model_validate(payload))
        except ValidationError as error:
            raise BriefStoreInvalid(
                f"brief line {index} failed the closed brief schema: {error}"
            ) from error
    return briefs


def find_brief(path: Path, prediction_id: str) -> RaceBrief | None:
    """The latest brief for a prediction record, or None."""
    found: RaceBrief | None = None
    for brief in read_briefs(path):
        if brief.prediction_id == prediction_id:
            found = brief
    return found


def _lines(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
