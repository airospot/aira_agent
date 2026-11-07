"""Synthetic same-session document reference continuity (fake model; no live LLM)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.domain.agents.flow.execution.decision.agent_system_prompt import (
    AGENT_SYSTEM_PROMPT,
)
from app.domain.agents.flow.execution.decision.request_model_decision import (
    request_model_decision,
)
from app.domain.agents.flow.execution.run_knowledge_agent import run_knowledge_agent


class CaptureClient:
    def __init__(self, script: list[dict[str, Any]]):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, system_prompt: str, user_payload: dict[str, Any]):
        self.calls.append(
            {"system_prompt": system_prompt, "user_payload": dict(user_payload)}
        )
        if not self.script:
            return {"action": "STOP_INCOMPLETE", "reason": "exhausted"}
        return self.script.pop(0)


def test_system_prompt_states_document_reference_priority():
    text = AGENT_SYSTEM_PROMPT
    assert "Document follow-up references" in text
    assert "explicit corpus-relative path" in text
    assert "historical_tool_references" in text
    assert "CLARIFY once" in text
    assert "another session" in text.lower() or "other session" in text.lower()


def test_a_then_b_then_this_document_prefers_latest_opened(tmp_path: Path):
    """A read → B read → vague follow-up: fake model must see B path in history.

    Capture client proves prompt carriage + conversation order; does not prove
    live model quality.
    """
    corpus = tmp_path / "corpus"
    (corpus / "extracted_data" / "doc_a").mkdir(parents=True)
    (corpus / "extracted_data" / "doc_b").mkdir(parents=True)
    (corpus / "extracted_data" / "doc_a" / "content.md").write_text(
        "Doc A summary\n", encoding="utf-8"
    )
    (corpus / "extracted_data" / "doc_b" / "content.md").write_text(
        "Doc B table here\n| x | y |\n| --- | --- |\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    (corpus / "extracted_data" / "doc_b" / "images").mkdir()
    png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (corpus / "extracted_data" / "doc_b" / "images" / "img_001.png").write_bytes(png)
    config = {"AGENT_CORPUS_DIR": str(corpus)}

    # Turn 1: open A
    client1 = CaptureClient(
        [
            {
                "action": "CALL_TOOL",
                "tool": "file_read",
                "arguments": {"path": "extracted_data/doc_a/content.md"},
            },
            {"action": "ANSWER", "answer": "A ozeti: Doc A summary"},
        ]
    )
    with patch(
        "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
        return_value=client1,
    ):
        r1 = run_knowledge_agent(
            "extracted_data/doc_a/content.md ozetle",
            conversation={"turns": [], "active_conversation": {"turns": []}},
            config=config,
        )
    assert r1["status"] == "ANSWER"
    assert client1.calls[0]["user_payload"]["request_text"].endswith("ozetle")

    conv_after_a = {
        "turns": [
            {"role": "user", "content": "extracted_data/doc_a/content.md ozetle"},
            {"role": "assistant", "content": r1["decision"]["answer"]},
        ],
        "active_conversation": {
            "turns": [
                {"role": "user", "content": "extracted_data/doc_a/content.md ozetle"},
                {"role": "assistant", "content": r1["decision"]["answer"]},
            ]
        },
        "historical_tool_references": [
            {"tool": "file_read", "path": "extracted_data/doc_a/content.md"}
        ],
    }

    # Turn 2: open B
    client2 = CaptureClient(
        [
            {
                "action": "CALL_TOOL",
                "tool": "file_read",
                "arguments": {"path": "extracted_data/doc_b/content.md"},
            },
            {"action": "ANSWER", "answer": "B ozeti: Doc B table"},
        ]
    )
    with patch(
        "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
        return_value=client2,
    ):
        r2 = run_knowledge_agent(
            "extracted_data/doc_b/content.md ozetle",
            conversation=conv_after_a,
            config=config,
        )
    assert r2["status"] == "ANSWER"
    # Prior turns present; current request unchanged
    assert (
        client2.calls[0]["user_payload"]["request_text"]
        == "extracted_data/doc_b/content.md ozetle"
    )
    hist = client2.calls[0]["user_payload"]["conversation"]["turns"]
    assert any("doc_a" in str(t.get("content")) for t in hist)

    conv_after_b = {
        "turns": conv_after_a["turns"]
        + [
            {"role": "user", "content": "extracted_data/doc_b/content.md ozetle"},
            {"role": "assistant", "content": r2["decision"]["answer"]},
        ],
        "active_conversation": {
            "turns": conv_after_a["active_conversation"]["turns"]
            + [
                {"role": "user", "content": "extracted_data/doc_b/content.md ozetle"},
                {"role": "assistant", "content": r2["decision"]["answer"]},
            ]
        },
        "historical_tool_references": [
            {"tool": "file_read", "path": "extracted_data/doc_a/content.md"},
            {"tool": "file_read", "path": "extracted_data/doc_b/content.md"},
        ],
        "context_policy": {
            "document_reference_priority": (
                "current_request_explicit_path_then_latest_opened_in_session_then_clarify"
            )
        },
    }

    # Turn 3: vague "this document" → scripted to use B image (latest opened)
    client3 = CaptureClient(
        [
            {
                "action": "CALL_TOOL",
                "tool": "show_image",
                "arguments": {
                    "path": "extracted_data/doc_b/images/img_001.png",
                },
            },
            {
                "action": "ANSWER",
                "answer": (
                    "B belgesindeki gorsel:\n\n"
                    "![img](/agent/corpus/extracted_data/doc_b/images/img_001.png)"
                ),
            },
        ]
    )
    with patch(
        "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
        return_value=client3,
    ):
        r3 = run_knowledge_agent(
            "bu belgedeki gorseli goster",
            conversation=conv_after_b,
            config=config,
        )
    assert r3["status"] == "ANSWER"
    payload3 = client3.calls[0]["user_payload"]
    assert payload3["request_text"] == "bu belgedeki gorseli goster"
    # Persist window: both prior docs visible; B is latest assistant topic
    turns = payload3["conversation"]["turns"]
    assert turns[-1]["content"] == r2["decision"]["answer"]
    assert "Document follow-up references" in client3.calls[0]["system_prompt"]
    # Tool actually hit B image, not A
    trace = r3.get("decision_trace") or []
    show = next(t for t in trace if t.get("tool") == "show_image")
    assert "doc_b" in str((show.get("observation") or {}).get("path") or "")


def test_explicit_path_after_clarify_uses_named_doc(tmp_path: Path):
    corpus = tmp_path / "corpus"
    (corpus / "extracted_data" / "doc_a").mkdir(parents=True)
    (corpus / "extracted_data" / "doc_a" / "content.md").write_text("A\n", encoding="utf-8")
    config = {"AGENT_CORPUS_DIR": str(corpus)}

    prior = {
        "turns": [
            {"role": "user", "content": "bu belgeyi ozetle"},
            {
                "role": "assistant",
                "content": "Hangi belgeden bahsediyorsunuz?",
            },
        ],
        "active_conversation": {
            "turns": [
                {"role": "user", "content": "bu belgeyi ozetle"},
                {
                    "role": "assistant",
                    "content": "Hangi belgeden bahsediyorsunuz?",
                },
            ]
        },
    }
    client = CaptureClient(
        [
            {
                "action": "CALL_TOOL",
                "tool": "file_read",
                "arguments": {"path": "extracted_data/doc_a/content.md"},
            },
            {"action": "ANSWER", "answer": "A ozeti"},
        ]
    )
    with patch(
        "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
        return_value=client,
    ):
        out = run_knowledge_agent(
            "extracted_data/doc_a/content.md",
            conversation=prior,
            config=config,
        )
    assert out["status"] == "ANSWER"
    assert client.calls[0]["user_payload"]["request_text"] == (
        "extracted_data/doc_a/content.md"
    )
    # Must not re-issue CLARIFY when path is now explicit (scripted recovery).
    assert all(c["user_payload"].get("request_text") for c in client.calls)
    actions = [
        (out.get("decision") or {}).get("action"),
    ]
    assert "CLARIFY" not in actions


def test_new_session_empty_turns_no_foreign_doc_auto_bind():
    client = CaptureClient(
        [{"action": "CLARIFY", "question": "Hangi belge?"}]
    )
    payload_conv = {
        "turns": [],
        "active_conversation": {"turns": [], "is_empty": True},
        "long_term_memory": "other session mentioned doc_z",
    }
    decision = request_model_decision(
        "bu belge",
        payload_conv,
        observations=[],
        client=client,
        permitted_tools=["file_read"],
    )
    assert decision["action"] == "CLARIFY"
    assert client.calls[0]["user_payload"]["conversation"]["turns"] == []
    assert "Document follow-up references" in client.calls[0]["system_prompt"]
