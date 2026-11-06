"""Minimal Flow Event helpers.

Builds compact stage events and safely delivers them to an optional
callback. No broker, queue, or persistence.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping


def build_flow_event(
    event: str,
    *,
    flow_started_at: float,
    step: int | None = None,
    action: str | None = None,
    tool: str | None = None,
    status: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Build one Flow event payload with only provided fields."""
    payload: dict[str, Any] = {
        "event": event,
        "elapsed_ms": _elapsed_ms(flow_started_at),
    }
    if step is not None:
        payload["step"] = step
    if action is not None:
        payload["action"] = action
    if tool is not None:
        payload["tool"] = tool
    if status is not None:
        payload["status"] = status
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    return payload


def emit_flow_event(
    on_event: Callable[[Mapping[str, Any]], Any] | None,
    payload: Mapping[str, Any],
) -> None:
    """Deliver event to consumer; isolate consumer failures."""
    if on_event is None:
        return
    try:
        on_event(payload)
    except Exception:  # noqa: BLE001 — consumer must not affect Agent outcome
        return


def _elapsed_ms(flow_started_at: float) -> int:
    return max(0, int((time.perf_counter() - flow_started_at) * 1000))
