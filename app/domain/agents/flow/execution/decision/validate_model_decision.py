"""Validate a model decision against aira.knowledge.model_decision.v1."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMA_PATH = Path(__file__).with_name("model_decision_schema.json")
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


def _terminal_decision_schema(full_schema: dict[str, Any]) -> dict[str, Any]:
    """Same decision contract with CALL_TOOL branch removed."""
    schema = copy.deepcopy(full_schema)
    branches = schema.get("oneOf")
    if not isinstance(branches, list):
        return schema
    kept: list[Any] = []
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        props = branch.get("properties") or {}
        action = props.get("action") or {}
        if action.get("const") == "CALL_TOOL":
            continue
        kept.append(branch)
    schema["oneOf"] = kept
    schema["$id"] = "aira.knowledge.model_decision.v1.terminal_only"
    schema["title"] = "Aira Knowledge Model Decision v1 (terminal-only)"
    return schema


_TERMINAL_SCHEMA = _terminal_decision_schema(_SCHEMA)
_TERMINAL_VALIDATOR = Draft202012Validator(_TERMINAL_SCHEMA)


def decision_schema(*, terminal_only: bool = False) -> dict[str, Any]:
    """Expose the schema actually enforced for a decide mode."""
    return _TERMINAL_SCHEMA if terminal_only else _SCHEMA


def validate_model_decision(
    decision: Any,
    *,
    terminal_only: bool = False,
) -> str:
    validator = _TERMINAL_VALIDATOR if terminal_only else _VALIDATOR
    validator.validate(decision)
    return str(decision["action"])
