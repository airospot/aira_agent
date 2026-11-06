"""A00 review: full answers must not enter the Flask session cookie."""

from __future__ import annotations

from app.interfaces.web.agent_routes.submission_store import (
    _thin_payload,
    remember_submission,
)


def test_thin_payload_strips_assistant_text_and_reply() -> None:
    long_answer = "A" * 8000
    thin = _thin_payload(
        {
            "session_id": "sess-1",
            "submission_id": "sub-1",
            "assistant_text": long_answer,
            "agent_reply": long_answer,
            "agent_notice": "kısa uyarı",
            "memory_error": "bellek hatası",
            "flow_timeline": [{"x": 1}],
            "decision_trace": {"steps": []},
            "flow_status": "ANSWER",
            "assistant_memory_id": "99",
        }
    )
    assert "assistant_text" not in thin
    assert "agent_reply" not in thin
    assert "flow_timeline" not in thin
    assert thin["session_id"] == "sess-1"
    assert thin["submission_id"] == "sub-1"
    assert thin["agent_notice"] == "kısa uyarı"
    assert thin["assistant_memory_id"] == "99"


def test_long_agent_notice_not_stored_in_cookie() -> None:
    thin = _thin_payload(
        {
            "session_id": "s",
            "submission_id": "sub",
            "agent_notice": "N" * 500,
        }
    )
    assert "agent_notice" not in thin


def test_remember_submission_cookie_regression_long_answer() -> None:
    store: dict = {}
    long_answer = "Cevap-" + ("X" * 12000)
    remember_submission(
        store,
        submission_id="a00-cookie-long-1",
        payload={
            "session_id": "sess-cookie",
            "submission_id": "a00-cookie-long-1",
            "assistant_text": long_answer,
            "agent_reply": long_answer,
            "flow_status": "ANSWER",
            "memory_error": "Yanıt üretildi ancak bellek yazılamadı.",
            "assistant_memory_id": None,
        },
    )
    blob = repr(store)
    assert long_answer not in blob
    assert "assistant_text" not in store.get("agent_last_ui", {})
    assert "agent_reply" not in store.get("agent_last_ui", {})
    assert store["agent_last_ui"]["submission_id"] == "a00-cookie-long-1"
    assert "bellek yazılamadı" in store["agent_last_ui"]["memory_error"]
