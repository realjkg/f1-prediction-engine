"""LLM race brief — fixture-mode default, digest-pinned Ollama live mode.

Contract (spec, engine/f1engine/brief): the brief narrates a race through the
same local-model seam as the Landing Zone (Ollama /api/chat, temperature 0,
JSON-validated output, digest pinned via /api/tags). Fixture mode is the
default and runs offline-deterministic under a DETERMINISTIC FIXTURE banner.
The brief is advisory and lives OUTSIDE the evidence hash chain.
"""

BRIEF_MODES: tuple[str, ...] = ("fixture", "live")

FIXTURE_BANNER = "DETERMINISTIC FIXTURE — NO LOCAL MODEL INFERENCE"


def generate_brief(race_id: str, mode: str = "fixture") -> dict[str, object]:
    """Generate the race brief; raises ValueError on unknown mode."""
    if mode not in BRIEF_MODES:
        raise ValueError(f"unknown brief mode: {mode!r} (expected one of {BRIEF_MODES})")
    raise NotImplementedError("brief is implemented by the brief task")
