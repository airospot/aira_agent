"""Model contract and visible error recovery for document analysis."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.domain.agents.flow.execution.decision.validate_model_decision import (
    decision_schema,
    validate_model_decision,
)
from app.domain.agents.flow.execution.llm.client import FlowLlmClient
from app.domain.agents.flow.execution.run_agent_loop import run_agent_loop
from app.domain.agents.flow.memory.bridge import persist_turn


def test_native_transport_enforces_current_decision_schema():
    client = FlowLlmClient(
        base_url="http://localhost:11434/v1", model="qwen3.5:9b",
        api_key="ollama", timeout_seconds=30,
        context_tokens=65536, max_output_tokens=2048, think=False,
    )
    for terminal in (False, True):
        schema = decision_schema(terminal_only=terminal)
        with patch.object(client, "_post_json", return_value=(
            {"message": {"content": '{"action":"ANSWER","answer":"ok"}'},
             "done_reason": "stop"}, None,
        )) as post:
            client.complete_json("system", {"decision_schema": schema})
        assert post.call_args.args[1]["format"] == schema


def test_invalid_decision_is_coded_incomplete_not_invisible_error():
    out = run_agent_loop(
        "review", {}, lambda *args, **kwargs: {"action": "ANSWER"},
        validate_model_decision, max_steps=8,
    )
    assert out["status"] == "STOP_INCOMPLETE"
    assert out["decision"]["code"] == "invalid_model_decision"
    assert out["decision"]["reason"]


def test_error_notice_is_saved_as_assistant_turn():
    with patch("app.domain.agents.flow.memory.bridge.memory_service.save_message",
               side_effect=[SimpleNamespace(id=1), SimpleNamespace(id=2)]) as save:
        result = persist_turn(
            session_id="test-session", customer_id=1, user_id=1,
            user_text="review", flow_status="ERROR",
            assistant_text="İnceleme tamamlanamadı.", metadata={},
        )
    assert result["complete"] is True
    assert result["assistant_memory_id"] == 2
    assert save.call_args_list[1].kwargs["message_type"] == "assistant"
    assert save.call_args_list[1].kwargs["create_embedding"] is False


def _render_with_turns(turns):
    templates = Path(__file__).resolve().parents[1] / "app/interfaces/web/templates"
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(str(templates)),
    ]), autoescape=True)
    env.globals["url_for"] = lambda *args, **kwargs: "/test"
    env.filters["assistant_markdown"] = lambda value: value
    return env.get_template("assistant.html").render(
        conversation_turns=turns, agent_notice="İnceleme tamamlanamadı.",
        past_conversations=[], submission_id="test-id",
    )


def test_recovery_notice_visible_with_existing_user_transcript():
    rendered = _render_with_turns([{"role": "user", "content": "review"}])
    assert "İnceleme tamamlanamadı." in rendered


def test_saved_notice_not_duplicated_by_recovery():
    rendered = _render_with_turns([
        {"role": "user", "content": "review"},
        {"role": "assistant", "content": "İnceleme tamamlanamadı."},
    ])
    assert rendered.count("İnceleme tamamlanamadı.") == 1
