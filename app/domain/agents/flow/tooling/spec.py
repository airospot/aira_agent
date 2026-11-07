"""ToolSpec and ToolResult contracts (A01)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping


ToolHandler = Callable[..., Mapping[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    """One callable tool: identity, schemas, handler, and future metadata."""

    name: str
    version: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    handler: ToolHandler
    # Catalog fragment matching legacy tool.json shape (name/description/arguments/…).
    catalog_document: Mapping[str, Any]
    side_effect_class: str = "read"
    # Future A03 controls — metadata only in A01; not enforced here.
    retry_policy: str | None = None
    cache_policy: str | None = None
    timeout_seconds: float | None = None
    extra_metadata: Mapping[str, Any] = field(default_factory=dict)

    def catalog_entry(self) -> dict[str, Any]:
        """Deep copy so callers cannot mutate registered schemas."""
        return deepcopy(dict(self.catalog_document))


@dataclass(frozen=True)
class ToolResult:
    """Thin adapter over the existing tool result dict (no field loss)."""

    data: Mapping[str, Any]

    @property
    def status(self) -> str | None:
        raw = self.data.get("status")
        return str(raw) if raw is not None else None

    @property
    def error(self) -> str | None:
        raw = self.data.get("error")
        return str(raw) if raw is not None else None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.data)

    def to_mutable(self) -> MutableMapping[str, Any]:
        return dict(self.data)
