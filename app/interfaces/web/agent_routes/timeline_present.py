"""Present Knowledge Flow events for Agent Timeline UI.

Presentation only. Does not invent Flow events or recompute durations.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_ALLOWED_KEYS = frozenset(
    {"event", "step", "action", "tool", "status", "duration_ms", "elapsed_ms"}
)

_KNOWN_EVENTS = frozenset(
    {
        "decide_started",
        "decide_finished",
        "validate_finished",
        "tool_started",
        "tool_finished",
        "observation_consumed",
        "flow_completed",
        "error",
    }
)

_KNOWN_ACTIONS = frozenset(
    {"CALL_TOOL", "ANSWER", "CLARIFY", "STOP_INCOMPLETE"}
)

_TOOL_STATUSES = frozenset(
    {
        "found",
        "candidates",
        "not_found",
        "source_unavailable",
        "invalid_argument",
    }
)

_FLOW_STATUSES = frozenset(
    {"ANSWER", "CLARIFY", "STOP_INCOMPLETE", "ERROR", "step_limit"}
)

_OBS_STATUSES = frozenset({"ok"})

_ERROR_STATUSES = frozenset(
    {
        "tool_not_permitted",
        "RuntimeError",
        "FlowLlmClientError",
        "ValueError",
        "TypeError",
        "KeyError",
        "TimeoutError",
        "OSError",
        "PermissionError",
        "FileNotFoundError",
        "JSONDecodeError",
    }
)

_TOOL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

_ACTION_LABELS = {
    "CALL_TOOL": "Araç çağrısı",
    "ANSWER": "Yanıt",
    "CLARIFY": "Açıklama isteği",
    "STOP_INCOMPLETE": "Eksik bilgiyle durdu",
}

_TOOL_STATUS_LABELS = {
    "found": "Kaynak bulundu",
    "candidates": "Adaylar bulundu",
    "not_found": "Kayıt bulunamadı",
    "source_unavailable": "Kaynağa erişilemedi",
    "invalid_argument": "Geçersiz parametre",
}

_TOOL_STATUS_TONE = {
    "found": "ok",
    "candidates": "ok",
    "not_found": "warn",
    "source_unavailable": "warn",
    "invalid_argument": "warn",
}

_FLOW_STATUS_LABELS = {
    "ANSWER": "Tamamlandı — yanıt",
    "CLARIFY": "Tamamlandı — açıklama gerekli",
    "STOP_INCOMPLETE": "Tamamlandı — eksik bilgi",
    "ERROR": "Hata ile sonlandı",
    "step_limit": "Adım sınırına ulaşıldı",
}

_ERROR_STATUS_LABELS = {
    "tool_not_permitted": "İzin verilmeyen araç",
    "RuntimeError": "Model veya araç hatası",
    "FlowLlmClientError": "Model veya araç hatası",
    "ValueError": "Doğrulama veya araç hatası",
    "TypeError": "Model veya araç hatası",
    "KeyError": "Model veya araç hatası",
    "TimeoutError": "Model veya araç hatası",
    "OSError": "Model veya araç hatası",
    "PermissionError": "Model veya araç hatası",
    "FileNotFoundError": "Model veya araç hatası",
    "JSONDecodeError": "Model veya araç hatası",
}


def sanitize_flow_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only typed, allowlisted Flow Event contract fields."""
    if not isinstance(payload, Mapping):
        return {}

    event_name = payload.get("event")
    if not isinstance(event_name, str) or event_name not in _KNOWN_EVENTS:
        return {}

    out: dict[str, Any] = {"event": event_name}

    step = _nonneg_int(payload.get("step"))
    if step is not None:
        out["step"] = step

    duration_ms = _nonneg_int(payload.get("duration_ms"))
    if duration_ms is not None:
        out["duration_ms"] = duration_ms

    elapsed_ms = _nonneg_int(payload.get("elapsed_ms"))
    if elapsed_ms is not None:
        out["elapsed_ms"] = elapsed_ms

    action = payload.get("action")
    if isinstance(action, str) and action in _KNOWN_ACTIONS:
        out["action"] = action

    tool = payload.get("tool")
    if isinstance(tool, str) and _TOOL_ID_RE.fullmatch(tool):
        out["tool"] = tool

    status = payload.get("status")
    if isinstance(status, str) and _status_allowed(event_name, status):
        out["status"] = status

    return out


def present_flow_timeline(
    events: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Collapse paired start/finish events into readable stage rows."""
    if not events:
        return []

    rows: list[dict[str, Any]] = []
    pending_decide: dict[str, Any] | None = None
    pending_tool: dict[str, Any] | None = None

    for raw in events:
        ev = sanitize_flow_event(raw)
        name = ev.get("event")
        if not name:
            continue

        if name == "decide_started":
            pending_decide = ev
            continue

        if name == "decide_finished":
            if pending_decide is not None:
                rows.append(
                    _row(
                        "decide",
                        "Agent kararı",
                        tone="neutral",
                        step=ev.get("step", pending_decide.get("step")),
                        duration_ms=ev.get("duration_ms"),
                    )
                )
                pending_decide = None
            continue

        if name == "validate_finished":
            action = ev.get("action")
            label = "Doğrulanmış Agent kararı"
            if isinstance(action, str) and action in _ACTION_LABELS:
                label = f"Doğrulanmış karar — {_ACTION_LABELS[action]}"
            rows.append(
                _row(
                    "validate",
                    label,
                    tone="neutral",
                    step=ev.get("step"),
                    action=action if isinstance(action, str) else None,
                    duration_ms=ev.get("duration_ms"),
                )
            )
            continue

        if name == "tool_started":
            pending_tool = ev
            continue

        if name == "tool_finished":
            if pending_tool is not None:
                status = ev.get("status")
                tool = ev.get("tool") or pending_tool.get("tool")
                status_label = None
                tone = "neutral"
                if isinstance(status, str) and status in _TOOL_STATUS_LABELS:
                    status_label = _TOOL_STATUS_LABELS[status]
                    tone = _TOOL_STATUS_TONE.get(status, "neutral")
                title = "Araç çalıştı"
                if isinstance(tool, str) and tool:
                    title = f"Araç — Çalıştırıldı"
                rows.append(
                    _row(
                        "tool",
                        title,
                        tone=tone,
                        step=ev.get("step", pending_tool.get("step")),
                        tool=tool if isinstance(tool, str) else None,
                        status=status if isinstance(status, str) else None,
                        detail=status_label,
                        duration_ms=ev.get("duration_ms"),
                    )
                )
                pending_tool = None
            continue

        if name == "observation_consumed":
            tool = ev.get("tool")
            title = "Gözlem agenta aktarıldı"
            if isinstance(tool, str) and tool:
                title = f"Gözlem agenta aktarıldı — Araç"
            rows.append(
                _row(
                    "observation",
                    title,
                    tone="neutral",
                    step=ev.get("step"),
                    tool=tool if isinstance(tool, str) else None,
                )
            )
            continue

        if name == "error":
            pending_decide = None
            pending_tool = None
            status = ev.get("status")
            detail = "Akış hatası"
            if isinstance(status, str) and status in _ERROR_STATUS_LABELS:
                detail = _ERROR_STATUS_LABELS[status]
            rows.append(
                _row(
                    "error",
                    "Hata",
                    tone="error",
                    step=ev.get("step"),
                    status=status if isinstance(status, str) else None,
                    detail=detail,
                    duration_ms=ev.get("duration_ms"),
                )
            )
            continue

        if name == "flow_completed":
            pending_decide = None
            pending_tool = None
            status = ev.get("status")
            action = ev.get("action")
            if status == "ANSWER":
                tone = "ok"
            elif status in ("CLARIFY", "STOP_INCOMPLETE"):
                tone = "warn"
            elif status in ("ERROR", "step_limit"):
                tone = "error"
            else:
                tone = "neutral"
            if isinstance(status, str) and status in _FLOW_STATUS_LABELS:
                title = _FLOW_STATUS_LABELS[status]
            else:
                title = "Flow sonlandı"
            rows.append(
                _row(
                    "flow",
                    title,
                    tone=tone,
                    action=action if isinstance(action, str) else None,
                    status=status if isinstance(status, str) else None,
                    duration_ms=ev.get("duration_ms"),
                )
            )
            continue

        pending_decide = None
        pending_tool = None

    return rows


def _status_allowed(event_name: str, status: str) -> bool:
    if event_name == "tool_finished":
        return status in _TOOL_STATUSES
    if event_name == "observation_consumed":
        return status in _OBS_STATUSES
    if event_name == "error":
        return status in _ERROR_STATUSES
    if event_name == "flow_completed":
        return status in _FLOW_STATUSES
    return False


def _nonneg_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def _row(
    kind: str,
    title: str,
    *,
    tone: str,
    step: Any = None,
    action: str | None = None,
    tool: str | None = None,
    status: str | None = None,
    detail: str | None = None,
    duration_ms: Any = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "tone": tone,
    }
    if step is not None:
        row["step"] = step
    if action is not None:
        row["action"] = action
    if tool is not None:
        row["tool"] = tool
    if status is not None:
        row["status"] = status
    if detail is not None:
        row["detail"] = detail
    if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
        row["duration_ms"] = int(duration_ms)
    return row
