"""A04: in-flight submission must not show another turn's inspector trace."""

from __future__ import annotations

from app.interfaces.web.agent_routes.submission_display import (
    submission_display_if_session_matches,
)


def test_processing_submission_has_no_assistant_memory_id() -> None:
    row = {
        "status": "processing",
        "session_id": "sess-a",
        "result_json": None,
    }
    display = submission_display_if_session_matches(row, selected_session_id="sess-a")
    assert display.get("assistant_memory_id") is None
    assert "işleniyor" in (display.get("agent_notice") or "")


def test_completed_submission_exposes_bound_assistant_id() -> None:
    row = {
        "status": "completed",
        "session_id": "sess-a",
        "result_json": {
            "session_id": "sess-a",
            "flow_status": "ANSWER",
            "agent_reply": "ok",
            "assistant_memory_id": 142,
        },
    }
    display = submission_display_if_session_matches(row, selected_session_id="sess-a")
    assert display.get("assistant_memory_id") == 142
    assert display.get("agent_reply") == "ok"


def test_other_session_submission_not_overlaid() -> None:
    row = {
        "status": "completed",
        "session_id": "sess-b",
        "result_json": {"session_id": "sess-b", "assistant_memory_id": 99},
    }
    assert (
        submission_display_if_session_matches(row, selected_session_id="sess-a") == {}
    )
