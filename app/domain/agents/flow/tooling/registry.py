"""ToolRegistry — name lookup and model catalog (A01)."""

from __future__ import annotations

from copy import deepcopy
from typing import Iterable

from jsonschema import Draft202012Validator

from app.domain.agents.flow.tooling.errors import (
    ToolNotRegisteredError,
    ToolRegistrationError,
)
from app.domain.agents.flow.tooling.spec import ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        name = str(spec.name or "").strip()
        if not name:
            raise ToolRegistrationError("tool name is required")
        if name in self._tools:
            raise ToolRegistrationError(f"duplicate tool registration: {name}")
        # Validate schemas are well-formed JSON Schema documents at load time.
        try:
            Draft202012Validator.check_schema(dict(spec.input_schema))
            Draft202012Validator.check_schema(dict(spec.output_schema))
        except Exception as exc:  # noqa: BLE001
            raise ToolRegistrationError(
                f"invalid schema for tool {name}: {exc}"
            ) from exc
        # Freeze deep copies so later mutation of caller objects is ignored.
        frozen = ToolSpec(
            name=name,
            version=str(spec.version or ""),
            description=str(spec.description or ""),
            input_schema=deepcopy(dict(spec.input_schema)),
            output_schema=deepcopy(dict(spec.output_schema)),
            handler=spec.handler,
            catalog_document=deepcopy(dict(spec.catalog_document)),
            side_effect_class=str(spec.side_effect_class or "read"),
            retry_policy=spec.retry_policy,
            cache_policy=spec.cache_policy,
            timeout_seconds=spec.timeout_seconds,
            extra_metadata=deepcopy(dict(spec.extra_metadata or {})),
        )
        self._tools[name] = frozen

    def _public_view(self, stored: ToolSpec) -> ToolSpec:
        """Handler identity preserved; schemas/catalog/metadata are independent copies."""
        return ToolSpec(
            name=stored.name,
            version=stored.version,
            description=stored.description,
            input_schema=deepcopy(dict(stored.input_schema)),
            output_schema=deepcopy(dict(stored.output_schema)),
            handler=stored.handler,
            catalog_document=deepcopy(dict(stored.catalog_document)),
            side_effect_class=stored.side_effect_class,
            retry_policy=stored.retry_policy,
            cache_policy=stored.cache_policy,
            timeout_seconds=stored.timeout_seconds,
            extra_metadata=deepcopy(dict(stored.extra_metadata or {})),
        )

    def get(self, name: str) -> ToolSpec | None:
        stored = self._tools.get(str(name or "").strip())
        if stored is None:
            return None
        return self._public_view(stored)

    def require(self, name: str) -> ToolSpec:
        stored = self._tools.get(str(name or "").strip())
        if stored is None:
            raise ToolNotRegisteredError(f"unknown tool: {name}")
        return self._public_view(stored)

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def catalog(self, *, names: Iterable[str] | None = None) -> list[dict]:
        """Model-facing tool list (deep copies). Registry membership ≠ permission."""
        if names is None:
            selected = sorted(self._tools)
        else:
            wanted = {str(n).strip() for n in names if str(n).strip()}
            selected = sorted(n for n in wanted if n in self._tools)
        return [self._tools[n].catalog_entry() for n in selected]
