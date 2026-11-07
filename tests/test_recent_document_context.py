"""recent_document hint: bridge projection + context carriage (no live LLM)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from app.domain.agents.flow.execution.decision.agent_system_prompt import (
    AGENT_SYSTEM_PROMPT,
)
from app.domain.agents.flow.execution.decision.context_builder import (
    build_model_decision_context,
)
from app.domain.agents.flow.execution.decision.observation_projection import (
    project_observations_for_model,
)
from app.domain.agents.flow.execution.run_policy import RunBudget
from app.domain.agents.flow.memory import bridge as bridge_mod
from tests.a03_policy_helpers import recommended_run_policy


def _assistant(msg_id: int, seq: int, steps: list[dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id,
        sequence_number=seq,
        message_type="assistant",
        message_content="ok",
        meta_data={"decision_trace": {"steps": steps, "final_status": "ANSWER"}},
    )


def _ok_read(path: str, *, source: str, step: int = 1) -> dict[str, Any]:
    return {
        "step": step,
        "tool": "file_read",
        "tool_status": "ok",
        "observation": {
            "status": "ok",
            "path": path,
            "source_filename": source,
            "display_name": source,
        },
    }


def test_system_prompt_mentions_recent_document_hint():
    text = AGENT_SYSTEM_PROMPT
    assert "recent_document" in text
    assert "reference-resolution hint" in text
    assert "user_facing_title" in text


def test_project_recent_document_prefers_latest_verified_open():
    short_term = [
        _assistant(
            1,
            1,
            [_ok_read("extracted_data/doc_a/content.md", source="doc_a.docx", step=1)],
        ),
        _assistant(
            2,
            2,
            [
                {
                    "step": 1,
                    "tool": "file_name_search",
                    "tool_status": "ok",
                    "observation": {
                        "status": "ok",
                        "candidates": [
                            {
                                "path": "extracted_data/doc_c/content.md",
                                "source_filename": "doc_c.docx",
                            }
                        ],
                    },
                },
                _ok_read(
                    "extracted_data/doc_b/content.md", source="doc_b.docx", step=2
                ),
            ],
        ),
    ]
    recent = bridge_mod._project_recent_document(short_term)
    assert recent is not None
    assert recent["path"] == "extracted_data/doc_b/content.md"
    assert recent["source_filename"] == "doc_b.docx"
    assert recent["user_facing_title"] == "doc_b.docx"
    assert recent["content_evidence"] is False
    assert recent["selected_entity"] is False


def test_search_candidates_alone_do_not_become_recent_document():
    short_term = [
        _assistant(
            3,
            3,
            [
                {
                    "step": 1,
                    "tool": "file_name_search",
                    "tool_status": "ok",
                    "observation": {
                        "status": "ok",
                        "candidates": [
                            {
                                "path": "extracted_data/only_search/content.md",
                                "source_filename": "only_search.docx",
                            }
                        ],
                    },
                }
            ],
        )
    ]
    assert bridge_mod._project_recent_document(short_term) is None


def test_failed_read_does_not_become_recent_document():
    short_term = [
        _assistant(
            4,
            4,
            [
                {
                    "step": 1,
                    "tool": "file_read",
                    "tool_status": "not_found",
                    "observation": {
                        "status": "not_found",
                        "path": "extracted_data/missing/content.md",
                    },
                }
            ],
        )
    ]
    assert bridge_mod._project_recent_document(short_term) is None


def test_load_flow_conversation_attaches_recent_document():
    short_term = [
        SimpleNamespace(
            id=10,
            sequence_number=1,
            message_type="user",
            message_content="05_multipage_cross_reference.docx oku",
            meta_data={},
        ),
        _assistant(
            11,
            2,
            [
                _ok_read(
                    "extracted_data/05_multipage_cross_reference/content.md",
                    source="05_multipage_cross_reference.docx",
                )
            ],
        ),
    ]
    with (
        patch.object(bridge_mod.memory_service, "get_short_term_memory", return_value=short_term),
        patch.object(bridge_mod, "_load_long_term_block", return_value=("", "disabled", [])),
        patch.object(
            bridge_mod, "_load_structured_block", return_value=(None, {"enabled": False})
        ),
    ):
        payload = bridge_mod.load_flow_conversation(
            session_id="sess-1", customer_id=1, user_id=1, query="takip"
        )
    assert payload["active_conversation"]["turn_count"] == 2
    recent = payload["recent_document"]
    assert recent["source_filename"] == "05_multipage_cross_reference.docx"
    assert recent["path"].endswith("content.md")
    assert payload["recent_document_policy"]["content_evidence"] is False
    # Order preserved: user then assistant
    roles = [t["role"] for t in payload["active_conversation"]["turns"]]
    assert roles == ["user", "assistant"]


def test_context_builder_keeps_recent_document_when_dropping_background():
    budget = RunBudget(recommended_run_policy())
    conversation = {
        "active_conversation": {
            "turns": [
                {"role": "user", "content": "05_multipage_cross_reference.docx oku"},
                {"role": "assistant", "content": "ozet"},
            ],
            "turn_count": 2,
            "is_empty": False,
        },
        "long_term_memory": "other session noise " * 20,
        "historical_tool_references": [{"tool": "file_read", "path": "x"}],
        "recent_document": {
            "path": "extracted_data/05_multipage_cross_reference/content.md",
            "source_filename": "05_multipage_cross_reference.docx",
            "tool": "file_read",
            "content_evidence": False,
        },
        "recent_document_policy": {"content_evidence": False},
    }
    built = build_model_decision_context(
        "Bu belgedeki müşterinin telefon numarası nedir?",
        conversation,
        observations=[],
        budget=budget,
        permitted_tools=["file_read", "file_name_search"],
    )
    conv = built["user_payload"]["conversation"]
    assert conv["recent_document"]["source_filename"] == (
        "05_multipage_cross_reference.docx"
    )
    assert built["user_payload"]["recent_document"]["source_filename"] == (
        "05_multipage_cross_reference.docx"
    )
    assert built["user_payload"]["request_text"].startswith("Bu belgedeki")
    # Optional historical list may remain until pressure; recent always present.
    assert "recent_document" in conv


def test_observation_projection_adds_user_facing_title():
    projected, _meta = project_observations_for_model(
        [
            {
                "status": "ok",
                "path": "extracted_data/05_multipage_cross_reference/content.md",
                "source_filename": "05_multipage_cross_reference.docx",
                "display_name": "05_multipage_cross_reference.docx",
                "content": "Sevk tarihi 18.11.2026",
            }
        ],
        max_observation_bytes=50_000,
    )
    assert projected[0]["user_facing_title"] == "05_multipage_cross_reference.docx"
    assert projected[0]["path"].endswith("content.md")
