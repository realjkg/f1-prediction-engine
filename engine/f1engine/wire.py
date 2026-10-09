"""Wire-facing schema conventions — camelCase JSON, snake_case Python.

The evidence ledger and the API speak the spec's record shape
(``schemaVersion``, ``recordSha256``, ``dataLimitations``), while the engine
keeps snake_case fields. One alias base keeps every wire-facing model
consistent so serialized records never drift per module.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


def to_camel(name: str) -> str:
    """snake_case field name -> camelCase alias."""
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


class WireModel(BaseModel):
    """Base for schemas that cross the engine boundary (ledger, API)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )
