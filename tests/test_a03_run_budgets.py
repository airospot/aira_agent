"""A03: run budgets, bounded context, retries — fake clock/client/handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.domain.agents.flow.execution.decision.context_builder import (
    ContextBuildError,
    build_model_decision_context,
)
from app.domain.agents.flow.execution.run_agent_loop import run_agent_loop
from app.domain.agents.flow.execution.run_knowledge_agent import run_knowledge_agent
from app.domain.agents.flow.execution.run_policy import (
    RunBudget,
    RunPolicyError,
    parse_run_policy,
)
from app.domain.agents.flow.tooling import ToolSpec, build_native_tool_registry
from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES
from app.domain.agents.run.contracts import ExecutionContext
from app.domain.agents.run.service import AgentRunService, pack_decision_trace
from tests.a03_policy_helpers import (
    corpus_config,
    recommended_policy_config,
    recommended_run_policy,
)
from tests.test_a02_agent_run_service import FakeMemory, FakeSubmissions


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


class ScriptClient:
    def __init__(self, script: list[dict[str, Any]], *, configured_timeout: int = 75):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.timeout_seconds = configured_timeout
        self.last_meta: dict[str, Any] = {}

    def complete_json(self, system_prompt, user_payload, *, timeout_seconds=None):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        if not self.script:
            return {"action": "STOP_INCOMPLETE", "reason": "exhausted"}
        item = self.script.pop(0)
        self.last_meta = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
        return item


def test_parse_run_policy_rejects_invalid_and_missing():
    with pytest.raises(RunPolicyError):
        parse_run_policy({})
    with pytest.raises(RunPolicyError):
        parse_run_policy(recommended_policy_config(AGENT_MAX_STEPS=-1))
    with pytest.raises(RunPolicyError):
        parse_run_policy(recommended_policy_config(AGENT_RUN_TIMEOUT_SECONDS="inf"))
    with pytest.raises(RunPolicyError):
        parse_run_policy(recommended_policy_config(AGENT_MAX_CONTEXT_BYTES="NaN"))
    policy = parse_run_policy(recommended_policy_config())
    assert policy.max_steps == 8
    assert policy.run_timeout_seconds == 180


def test_max_steps_one_terminal_only_no_tool(tmp_path: Path):
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_text("hi", encoding="utf-8")
    client = ScriptClient(
        [
            {
                "action": "CALL_TOOL",
                "tool": "file_read",
                "arguments": {"path": "a.md"},
            }
        ]
    )
    with patch(
        "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
        return_value=client,
    ):
        result = run_knowledge_agent(
            "oku",
            conversation=[],
            config=corpus_config(str(corpus), AGENT_MAX_STEPS=1),
            run_policy=recommended_run_policy(AGENT_MAX_STEPS=1),
        )
    assert result["status"] == "STOP_INCOMPLETE"
    assert client.calls  # decide happened
    # Tool must not run on finalization slot.
    assert not result.get("observations")


def test_deadline_blocks_llm_and_tool_handlers():
    clock = FakeClock(0.0)
    budget = RunBudget.start(
        recommended_run_policy(AGENT_RUN_TIMEOUT_SECONDS=5),
        clock=clock,
    )
    clock.advance(6.0)
    decide_calls = {"n": 0}
    tool_calls = {"n": 0}

    def decide(*_a, **_k):
        decide_calls["n"] += 1
        return {"action": "CALL_TOOL", "tool": "file_read", "arguments": {"path": "x"}}

    def validate(decision, terminal_only=False):
        return decision["action"]

    def execute(_decision):
        tool_calls["n"] += 1
        return {"status": "ok"}

    out = run_agent_loop(
        "q",
        {},
        decide,
        validate,
        execute_tool=execute,
        budget=budget,
    )
    assert out["status"] == "STOP_INCOMPLETE"
    assert out["decision"].get("code") == "run_deadline_exceeded"
    assert decide_calls["n"] == 0
    assert tool_calls["n"] == 0


def test_remaining_timeout_passed_to_client_and_late_result_not_success(tmp_path: Path):
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_text("body", encoding="utf-8")
    clock = FakeClock(0.0)
    client = ScriptClient(
        [
            {
                "action": "CALL_TOOL",
                "tool": "file_read",
                "arguments": {"path": "a.md"},
            },
            {"action": "ANSWER", "answer": "should not win"},
        ],
        configured_timeout=75,
    )

    def _advance_during_tool(name, arguments, *, config=None, execution_control=None):
        clock.advance(50)
        # Real file_read via registry after time advances past deadline.
        from app.domain.agents.flow.tools.file_read.execute import execute_file_read

        return execute_file_read(arguments, config=config, execution_control=execution_control)

    with (
        patch(
            "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
            return_value=client,
        ),
        patch(
            "app.domain.agents.flow.tooling.executor.ToolExecutor.execute",
            side_effect=_advance_during_tool,
        ),
    ):
        result = run_knowledge_agent(
            "oku",
            conversation=[],
            config=corpus_config(str(corpus), AGENT_RUN_TIMEOUT_SECONDS=10),
            run_policy=recommended_run_policy(AGENT_RUN_TIMEOUT_SECONDS=10),
            clock=clock,
        )
    assert client.calls
    assert client.calls[0]["timeout_seconds"] == 10
    assert result["status"] == "STOP_INCOMPLETE"
    assert result.get("budget_stop_code") == "run_deadline_exceeded" or (
        isinstance(result.get("decision"), dict)
        and result["decision"].get("code") == "run_deadline_exceeded"
    )


def test_context_budget_mandatory_overflow_skips_model():
    budget = RunBudget.start(
        recommended_run_policy(AGENT_MAX_CONTEXT_BYTES=200)
    )
    huge = "ü" * 5000
    with pytest.raises(ContextBuildError) as exc:
        build_model_decision_context(
            huge,
            {"active_conversation": {"turns": []}},
            [],
            budget=budget,
            permitted_tools=[{"name": "file_read", "description": "x" * 100}],
        )
    assert exc.value.code == "context_budget_exceeded"


def test_observation_projection_keeps_identity_and_byte_limit(tmp_path: Path):
    budget = RunBudget.start(
        recommended_run_policy(AGENT_MAX_OBSERVATION_BYTES=800, AGENT_MAX_CONTEXT_BYTES=20000)
    )
    raw_obs = [
        {
            "status": "ok",
            "path": "extracted_data/doc/content.md",
            "content": "X" * 50000,
            "truncated": True,
            "byte_size": 50000,
            "error": None,
            "source_filename": "Saha İnceleme Formu.docx",
            "display_name": "Saha İnceleme Formu.docx",
            "source_known": True,
            "source_ambiguous": False,
            "display_url": None,
        }
    ]
    built = build_model_decision_context(
        "özetle",
        {"active_conversation": {"turns": []}},
        raw_obs,
        budget=budget,
        permitted_tools=[{"name": "file_read"}],
    )
    obs = built["user_payload"]["observations"]
    assert obs
    assert obs[0]["source_filename"] == "Saha İnceleme Formu.docx"
    assert obs[0]["path"] == "extracted_data/doc/content.md"
    assert obs[0]["status"] == "ok"
    assert len(json.dumps(obs, ensure_ascii=False).encode("utf-8")) <= 800
    assert raw_obs[0]["content"] == "X" * 50000  # inputs not mutated


def test_no_duplicate_turns_in_model_payload():
    budget = RunBudget.start(recommended_run_policy())
    turns = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    conversation = {
        "turns": turns,
        "active_conversation": {"turns": turns, "turn_count": 2},
        "long_term_memory": "bg",
    }
    built = build_model_decision_context(
        "q",
        conversation,
        [],
        budget=budget,
        permitted_tools=[],
    )
    payload = built["user_payload"]["conversation"]
    assert "turns" not in payload or payload.get("turns") is None
    assert isinstance(payload.get("active_conversation"), dict)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # content "a" should appear once in serialized conversation payload
    assert text.count('"content":"a"') == 1


def test_successful_native_duplicate_blocked_and_retry_capped():
    observations_run: list[Any] = []

    def decide(req, conv, observations, decision_constraints=None):
        if decision_constraints and decision_constraints.get("terminal_only"):
            return {"action": "ANSWER", "answer": "done"}
        return {
            "action": "CALL_TOOL",
            "tool": "file_read",
            "arguments": {"path": "a.md"},
        }

    def validate(decision, terminal_only=False):
        return decision["action"]

    calls = {"n": 0}

    def execute(_d):
        calls["n"] += 1
        return {"status": "ok", "path": "a.md"}

    out = run_agent_loop(
        "q",
        {},
        decide,
        validate,
        execute_tool=execute,
        budget=RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=4)),
        tool_meta_lookup=lambda _t: {
            "side_effect_class": "read",
            "retry_policy": "transient",
            "extra_metadata": {},
        },
    )
    assert calls["n"] == 1
    assert out["status"] == "ANSWER"

    # Transient error retries capped by AGENT_MAX_TOOL_RETRIES=1 → 2 executions max.
    err_calls = {"n": 0}

    def decide_err(req, conv, observations, decision_constraints=None):
        if decision_constraints and decision_constraints.get("terminal_only"):
            return {"action": "STOP_INCOMPLETE", "reason": "stop"}
        return {
            "action": "CALL_TOOL",
            "tool": "file_read",
            "arguments": {"path": "a.md"},
        }

    def execute_err(_d):
        err_calls["n"] += 1
        return {"status": "error", "error": "boom"}

    budget = RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=6, AGENT_MAX_TOOL_RETRIES=1))
    out2 = run_agent_loop(
        "q",
        {},
        decide_err,
        validate,
        execute_tool=execute_err,
        budget=budget,
        tool_meta_lookup=lambda _t: {
            "side_effect_class": "read",
            "retry_policy": "transient",
            "extra_metadata": {},
        },
    )
    assert err_calls["n"] == 2  # first + one retry
    assert out2["status"] in {"STOP_INCOMPLETE", "ANSWER"}


def test_write_tool_no_auto_retry_and_unsupported_policy():
    calls = {"n": 0}

    def decide(req, conv, observations, decision_constraints=None):
        if decision_constraints and decision_constraints.get("terminal_only"):
            return {"action": "STOP_INCOMPLETE", "reason": "x"}
        return {
            "action": "CALL_TOOL",
            "tool": "writer",
            "arguments": {"path": "a"},
        }

    def validate(decision, terminal_only=False):
        return decision["action"]

    def execute(_d):
        calls["n"] += 1
        return {"status": "error", "error": "fail"}

    out = run_agent_loop(
        "q",
        {},
        decide,
        validate,
        execute_tool=execute,
        budget=RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=5)),
        tool_meta_lookup=lambda _t: {
            "side_effect_class": "write",
            "retry_policy": "transient",
            "extra_metadata": {},
        },
    )
    assert calls["n"] == 1

    with pytest.raises(ValueError, match="unsupported retry_policy"):
        run_agent_loop(
            "q",
            {},
            decide,
            validate,
            execute_tool=execute,
            budget=RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=3)),
            tool_meta_lookup=lambda _t: {
                "side_effect_class": "read",
                "retry_policy": "exponential",
                "extra_metadata": {},
            },
        )


def test_repeatable_dummy_read_can_rerun():
    calls = {"n": 0}

    def decide(req, conv, observations, decision_constraints=None):
        if calls["n"] >= 2:
            return {"action": "ANSWER", "answer": "ok"}
        return {
            "action": "CALL_TOOL",
            "tool": "dummy_read",
            "arguments": {"path": "x"},
        }

    def validate(decision, terminal_only=False):
        return decision["action"]

    def execute(_d):
        calls["n"] += 1
        return {"status": "ok", "path": "x"}

    out = run_agent_loop(
        "q",
        {},
        decide,
        validate,
        execute_tool=execute,
        budget=RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=5)),
        tool_meta_lookup=lambda _t: {
            "side_effect_class": "read",
            "retry_policy": "none",
            "extra_metadata": {"repeatable": True},
            "repeatable": True,
        },
    )
    assert calls["n"] == 2
    assert out["status"] == "ANSWER"


def test_budget_stop_persists_and_replay_skips_second_run():
    memory = FakeMemory()
    subs = FakeSubmissions()
    runs = {"n": 0}

    def runner(text, **kwargs):
        runs["n"] += 1
        return {
            "status": "STOP_INCOMPLETE",
            "decision": {
                "action": "STOP_INCOMPLETE",
                "reason": "Çalışma süresi doldu; tamamlanamadı.",
                "code": "run_deadline_exceeded",
            },
            "observations": [],
            "decision_trace": [{"step": 1, "action": "STOP_INCOMPLETE"}],
            "decision_trace_final_status": "STOP_INCOMPLETE",
            "decision_trace_final_action": "STOP_INCOMPLETE",
            "run_budget": {
                "run_policy": recommended_run_policy().as_trace_dict(),
                "stop_code": "run_deadline_exceeded",
                "elapsed_seconds": 180.0,
                "remaining_seconds": 0.0,
                "total_tool_retries": 0,
                "last_context_bytes": 100,
                "last_observation_bytes": 0,
                "context_truncated": False,
                "observation_truncated": False,
                "usage_totals": {"known": False},
            },
        }

    svc = AgentRunService(
        memory=memory,
        submissions=subs,
        runner=runner,
        present_timeline=lambda events: events,
        sanitize_event=lambda e: e if isinstance(e, dict) else {},
    )
    ctx = ExecutionContext(
        customer_id=1,
        user_id=2,
        corpus_root="/tmp/corpus",
        permitted_tool_names=frozenset({"file_read"}),
        submission_timeout_seconds=900,
        runner_config=recommended_policy_config(),
    )
    from app.domain.agents.run.contracts import RunRequest

    req = RunRequest(
        request_text="x",
        submission_id="a03budget001",
        new_conversation=True,
    )
    out1 = svc.run(ctx, req)
    assert out1.kind in {"completed", "ok", "done"} or out1.payload.get("replayed") is False
    packed = None
    for row in subs.rows.values():
        if row.get("result_json"):
            packed = row["result_json"]
    assert packed is not None
    # Second propose with same submission should replay without second runner call.
    out2 = svc.run(ctx, req)
    assert runs["n"] == 1
    assert out2.payload.get("replayed") is True or out2.kind in {
        "completed_replay",
        "replay",
        "completed",
    }


def test_pack_decision_trace_keeps_run_budget_metadata():
    packed = pack_decision_trace(
        {
            "decision_trace": [{"step": 1}],
            "decision_trace_final_status": "STOP_INCOMPLETE",
            "decision_trace_final_action": "STOP_INCOMPLETE",
            "run_budget": {
                "run_policy": {"max_steps": 8},
                "stop_code": "context_budget_exceeded",
                "elapsed_seconds": 1.2,
                "secret_doc": "nope",
            },
        }
    )
    assert packed is not None
    assert packed["run_budget"]["stop_code"] == "context_budget_exceeded"
    assert "secret_doc" not in packed["run_budget"]


def test_toolspec_rejects_bad_retry_policy():
    with pytest.raises(ValueError):
        ToolSpec(
            name="x",
            version="v1",
            description="d",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            handler=lambda *_a, **_k: {},
            catalog_document={"name": "x"},
            retry_policy="magic",
        )


def test_growing_catalog_counts_toward_context_budget():
    budget = RunBudget.start(
        recommended_run_policy(AGENT_MAX_CONTEXT_BYTES=2500)
    )
    tools = [
        {
            "name": f"tool_{i}",
            "description": "d" * 80,
            "arguments": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
        for i in range(40)
    ]
    with pytest.raises(ContextBuildError):
        build_model_decision_context(
            "soru",
            {"active_conversation": {"turns": []}},
            [],
            budget=budget,
            permitted_tools=tools,
        )
