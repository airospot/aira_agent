"""ToolSpec and ToolResult contracts (A01)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping


ToolHandler = Callable[..., Mapping[str, Any]]

_SUPPORTED_RETRY_POLICIES = frozenset({None, "none", "transient"})
_SUPPORTED_CACHE_POLICIES = frozenset({None, "none", "read_through"})
_SUPPORTED_SIDE_EFFECTS = frozenset({"read", "write"})


@dataclass(frozen=True)
class ToolSpec:
    """One callable tool: identity, schemas, handler, and A03 control metadata."""

    name: str
    version: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    handler: ToolHandler
    # Catalog fragment matching legacy tool.json shape (name/description/arguments/…).
    catalog_document: Mapping[str, Any]
    side_effect_class: str = "read"
    retry_policy: str | None = None
    cache_policy: str | None = None
    timeout_seconds: float | None = None
    extra_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        side = str(self.side_effect_class or "read").strip().lower()
        if side not in _SUPPORTED_SIDE_EFFECTS:
            raise ValueError(f"unsupported side_effect_class: {self.side_effect_class!r}")
        object.__setattr__(self, "side_effect_class", side)
        retry = self.retry_policy
        if retry is not None:
            retry_norm = str(retry).strip().lower()
            if retry_norm not in _SUPPORTED_RETRY_POLICIES - {None}:
                raise ValueError(f"unsupported retry_policy: {self.retry_policy!r}")
            object.__setattr__(self, "retry_policy", retry_norm)
        cache = self.cache_policy
        if cache is not None:
            cache_norm = str(cache).strip().lower()
            if cache_norm not in _SUPPORTED_CACHE_POLICIES - {None}:
                raise ValueError(f"unsupported cache_policy: {self.cache_policy!r}")
            object.__setattr__(self, "cache_policy", cache_norm)
        if self.timeout_seconds is not None:
            try:
                timeout = float(self.timeout_seconds)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"timeout_seconds must be float|None, got {self.timeout_seconds!r}"
                ) from exc
            if timeout <= 0:
                raise ValueError("timeout_seconds must be > 0 when set")
            object.__setattr__(self, "timeout_seconds", timeout)

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
