"""Compact JSON serialization shared by context builder and LLM client.

Byte budgets must measure the same encoding the client puts in message content.
"""

from __future__ import annotations

import json
from typing import Any


def dumps_compact(value: Any) -> str:
    """UTF-8 JSON text with compact separators (no default indent/spaces)."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def utf8_json_bytes(value: Any) -> int:
    return len(dumps_compact(value).encode("utf-8"))


def measure_decision_context_bytes(system_prompt: str, user_payload: Any) -> int:
    """Bytes of system text + compact user JSON (matches client message bodies)."""
    return len(str(system_prompt or "").encode("utf-8")) + utf8_json_bytes(user_payload)
