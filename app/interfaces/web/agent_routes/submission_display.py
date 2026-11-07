"""Map agent_submissions rows/payloads to GET assistant render fields."""

from __future__ import annotations

import json
from typing import Any, Mapping


def parse_submission_result(raw: object) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def display_from_submission_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Map server-side submission result to GET render fields (no cookie)."""
    flow_status = payload.get("flow_status")
    agent_reply = payload.get("agent_reply")
    assistant_text = payload.get("assistant_text")
    agent_notice = payload.get("agent_notice")
    if not agent_reply and flow_status == "ANSWER" and assistant_text:
        agent_reply = assistant_text
    if not agent_notice and flow_status not in {"ANSWER", "CLARIFY"} and assistant_text:
        agent_notice = assistant_text
    return {
        "agent_reply": agent_reply,
        "agent_notice": agent_notice,
        "memory_error": payload.get("memory_error"),
        "assistant_memory_id": payload.get("assistant_memory_id"),
        "session_id": payload.get("session_id"),
        "flow_status": flow_status,
    }


def turns_include_assistant_text(turns: list, text: str | None) -> bool:
    needle = str(text or "").strip()
    if not needle:
        return False
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role") or "").lower() != "assistant":
            continue
        if str(turn.get("content") or "").strip() == needle:
            return True
    return False


def overlay_submission_reply(turns: list, *, agent_reply: str | None) -> list:
    """If persist failed, transcript may lack the answer — append for display."""
    reply = str(agent_reply or "").strip()
    if not reply or turns_include_assistant_text(turns, reply):
        return turns
    out = list(turns)
    out.append({"role": "assistant", "content": reply, "from_submission": True})
    return out


def submission_bound_session_id(row: Mapping[str, Any] | None) -> str | None:
    if not row:
        return None
    direct = str(row.get("session_id") or "").strip() or None
    if direct:
        return direct
    payload = parse_submission_result(row.get("result_json"))
    return str(payload.get("session_id") or "").strip() or None


def submission_display_if_session_matches(
    row: Mapping[str, Any] | None, *, selected_session_id: str | None
) -> dict[str, Any]:
    """Overlay submission UI only when it belongs to the selected conversation."""
    if not row or not selected_session_id:
        return {}
    bound = submission_bound_session_id(row)
    if not bound or bound != str(selected_session_id).strip():
        return {}
    status_row = str(row.get("status") or "")
    if status_row == "completed":
        return display_from_submission_payload(
            parse_submission_result(row.get("result_json"))
        )
    if status_row == "processing":
        return {
            "session_id": bound,
            "agent_notice": (
                "Bu gönderim hâlâ işleniyor. Lütfen bekleyin; "
                "otomatik yeniden çalıştırma yapılmaz."
            ),
        }
    if status_row == "failed":
        return {
            "session_id": bound,
            "agent_notice": (
                "Önceki gönderim zaman aşımına uğradı veya başarısız oldu. "
                "Yeniden denemek için yeni bir soru gönderin (yeni submission_id)."
            ),
            "memory_error": row.get("error"),
        }
    return {}
