"""Explicit Python registration of the four native corpus tools (A01)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from app.domain.agents.flow.tools import file_name_search as file_name_search_mod
from app.domain.agents.flow.tools import file_read as file_read_mod
from app.domain.agents.flow.tools import file_search as file_search_mod
from app.domain.agents.flow.tools import show_image as show_image_mod
from app.domain.agents.flow.tooling.registry import ToolRegistry
from app.domain.agents.flow.tooling.spec import ToolSpec

_NATIVE_TOOL_MODULES = (
    file_name_search_mod,
    file_search_mod,
    file_read_mod,
    show_image_mod,
)

_HANDLERS: dict[str, Callable[..., Mapping[str, Any]]] = {
    "file_name_search": file_name_search_mod.execute_file_name_search,
    "file_search": file_search_mod.execute_file_search,
    "file_read": file_read_mod.execute_file_read,
    "show_image": show_image_mod.execute_show_image,
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _version_from_schema_id(schema_id: str | None, *, fallback: str) -> str:
    raw = str(schema_id or "").strip()
    if not raw:
        return fallback
    # e.g. native.flow.tool.file_read.v1 → v1
    tail = raw.rsplit(".", 1)[-1]
    return tail or fallback


def build_native_tool_registry() -> ToolRegistry:
    """Register only the four production native tools (no directory plugin scan)."""
    registry = ToolRegistry()
    for module in _NATIVE_TOOL_MODULES:
        tool_dir = Path(module.__file__).resolve().parent
        tool_doc = _load_json(tool_dir / "tool.json")
        result_doc = _load_json(tool_dir / "result.json")
        name = str(tool_doc.get("name") or "").strip()
        if name not in _HANDLERS:
            raise RuntimeError(f"native bootstrap missing handler for {name!r}")
        arguments = tool_doc.get("arguments")
        if not isinstance(arguments, dict):
            raise RuntimeError(f"native tool {name!r} missing arguments schema")
        registry.register(
            ToolSpec(
                name=name,
                version=_version_from_schema_id(
                    tool_doc.get("$id"), fallback="v1"
                ),
                description=str(tool_doc.get("description") or ""),
                input_schema=arguments,
                output_schema=result_doc,
                handler=_HANDLERS[name],
                catalog_document=tool_doc,
                side_effect_class="read",
                retry_policy="transient",
                cache_policy="none",
                timeout_seconds=None,
            )
        )
    return registry


NATIVE_TOOL_NAMES: tuple[str, ...] = (
    "file_name_search",
    "file_search",
    "file_read",
    "show_image",
)
