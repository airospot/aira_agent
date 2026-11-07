"""A01: runner uses registry/executor; fifth test tool; events/trace preserved."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from app.domain.agents.flow.execution.run_knowledge_agent import run_knowledge_agent
from app.domain.agents.flow.tooling import (
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    build_native_tool_registry,
)
from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES


def _scripted_decisions(sequence: list[dict[str, Any]]):
    calls = {"i": 0}

    def _decide(*_a, **_k):
        idx = calls["i"]
        calls["i"] = idx + 1
        if idx >= len(sequence):
            return {
                "action": "STOP_INCOMPLETE",
                "reason": "script exhausted",
            }
        return sequence[idx]

    return _decide, calls


def test_runner_scripted_file_read_preserves_events_and_trace(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "note.md").write_text("Merhaba corpus\n", encoding="utf-8")
    config = {"AGENT_CORPUS_DIR": str(corpus)}

    decide_fn, _calls = _scripted_decisions(
        [
            {
                "action": "CALL_TOOL",
                "tool": "file_read",
                "arguments": {"path": "note.md"},
            },
            {
                "action": "ANSWER",
                "answer": "Dosyada Merhaba corpus yazıyor.",
            },
        ]
    )
    events: list[dict[str, Any]] = []

    with (
        patch(
            "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
            return_value=MagicMock(),
        ),
        patch(
            "app.domain.agents.flow.execution.run_knowledge_agent.request_model_decision",
            side_effect=lambda *a, **k: decide_fn(),
        ),
    ):
        result = run_knowledge_agent(
            "note.md ne diyor?",
            conversation=[],
            config=config,
            on_event=events.append,
        )

    assert result["status"] == "ANSWER"
    assert result["decision"]["answer"].startswith("Dosyada")
    assert any(e.get("event") == "tool_started" for e in events)
    assert any(
        e.get("event") == "tool_finished" and e.get("tool") == "file_read"
        for e in events
    )
    assert any(e.get("event") == "flow_completed" for e in events)
    trace = result.get("decision_trace") or []
    assert trace
    tool_step = next(t for t in trace if t.get("tool") == "file_read")
    obs = tool_step.get("observation") or {}
    assert obs.get("status") == "ok"
    assert obs.get("path") == "note.md"
    assert obs.get("content_chars", 0) > 0


def test_fifth_test_tool_dispatch_without_production_registration(
    tmp_path: Path,
) -> None:
    """Extra tool works via same executor path; not in production bootstrap."""
    args = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["value"],
        "properties": {"value": {"type": "integer"}},
    }
    result_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "doubled", "error"],
        "properties": {
            "status": {"type": "string", "enum": ["ok"]},
            "doubled": {"type": "integer"},
            "error": {"type": ["string", "null"]},
        },
    }

    def double_handler(arguments, *, config=None):
        return {
            "status": "ok",
            "doubled": int(arguments["value"]) * 2,
            "error": None,
        }

    registry = build_native_tool_registry()
    assert "test_double" not in registry.names()
    registry.register(
        ToolSpec(
            name="test_double",
            version="v1",
            description="test-only double",
            input_schema=args,
            output_schema=result_schema,
            handler=double_handler,
            catalog_document={
                "name": "test_double",
                "description": "test-only double",
                "arguments": args,
            },
        )
    )
    # Production bootstrap remains four tools.
    assert set(build_native_tool_registry().names()) == set(NATIVE_TOOL_NAMES)

    permitted = set(NATIVE_TOOL_NAMES) | {"test_double"}
    executor = ToolExecutor(registry, permitted_names=permitted)
    decide_fn, _ = _scripted_decisions(
        [
            {
                "action": "CALL_TOOL",
                "tool": "test_double",
                "arguments": {"value": 21},
            },
            {"action": "ANSWER", "answer": "42"},
        ]
    )
    events: list[dict[str, Any]] = []
    with (
        patch(
            "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
            return_value=MagicMock(),
        ),
        patch(
            "app.domain.agents.flow.execution.run_knowledge_agent.request_model_decision",
            side_effect=lambda *a, **k: decide_fn(),
        ),
    ):
        result = run_knowledge_agent(
            "iki katı",
            conversation=[],
            config={"AGENT_CORPUS_DIR": str(tmp_path)},
            on_event=events.append,
            tool_registry=registry,
            tool_executor=executor,
            permitted_tool_names=permitted,
        )
    assert result["status"] == "ANSWER"
    assert any(e.get("tool") == "test_double" for e in events)
    obs = result["observations"][0]
    assert obs["status"] == "ok"
    assert obs["doubled"] == 42
